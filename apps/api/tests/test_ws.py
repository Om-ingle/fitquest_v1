"""M8.2 WebSocket transport tests.

Covers the transport layer of the SRS §15/§16 real-time coaching pipeline:

    TriggerEngine -> CoachingSessionManager -> connected client

Focused tests for connection/disconnection, user-scoped delivery, multiple
sessions per user, unrelated-user isolation, serialization, disconnect
cleanup, a broken socket never breaking trigger processing, and the trigger
engine's subscriber staying safe. Integration tests prove that a real
CoachingTrigger emitted by the existing trigger engine (via a real
``process_run_sync``) reaches a subscribed WebSocket client.

No LLM/RAG is called anywhere; ``GET /api/v1/coach`` is untouched.
"""
import asyncio
import datetime as dt
import json
import time
import uuid
from concurrent import futures

from sqlmodel import Session

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.runs.schemas import RunSyncPayload
from app.modules.runs.service import process_run_sync
from app.modules.triggers import ws as ws_module
from app.modules.triggers.engine import (
    CoachingTrigger,
    TriggerDecision,
    TriggerType,
    trigger_engine,
)
from app.modules.triggers.ws import (
    ENVELOPE_TYPE,
    resolve_user_id,
    serialize_trigger,
)
from app.modules.users.models import User

USER_ID = DEV_USER_ID
RIVAL_ID = "00000000-0000-0000-0000-000000000099"
BROKEN_USER_ID = "00000000-0000-0000-0000-0000000000bb"
WS_PATH = "/api/v1/ws/coaching"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _ws_url(user_id: str | None = None) -> str:
    return WS_PATH if user_id is None else f"{WS_PATH}?user_id={user_id}"


class _Connect:
    """``client.websocket_connect`` with a tolerant teardown.

    Starlette's TestClient closes a socket by cancel-scoping the app task and
    waiting on it; the wait intermittently re-raises ``CancelledError`` even
    when the endpoint already unwound cleanly — a harness artifact that appears
    on any websocket endpoint, not this transport. The endpoint's try/finally
    removes the session on EITHER path before the portal task finishes, so the
    raise is cosmetic. We suppress it (return True) only when the body did not
    raise; a real body error still propagates.
    """

    def __init__(self, client, user_id: str | None = None):
        self._inner = client.websocket_connect(_ws_url(user_id))

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, et, ev, tb):
        try:
            return self._inner.__exit__(et, ev, tb)
        except futures.CancelledError:
            return et is None


def _seed_user(user_id: str) -> None:
    with Session(engine) as session:
        session.add(
            User(
                id=uuid.UUID(user_id),
                username=f"user-{user_id[-12:]}",
                total_lifetime_steps=0,
            )
        )
        session.commit()


def _sync_run_for(user_id: str, run_id: str) -> None:
    """Emit a real WORKOUT_COMPLETED trigger through the REAL engine path."""
    with Session(engine) as session:
        summary = process_run_sync(
            session,
            RunSyncPayload(total_session_steps=1000, hexes_to_steps={}, run_id=run_id),
            uuid.UUID(user_id),
        )
        assert summary.already_processed is False


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ─────────────────────────────────────────────────────────────────────────────
# Identity & serialization (pure)
# ─────────────────────────────────────────────────────────────────────────────


def test_resolve_user_id_defaults_to_dev_and_accepts_valid_uuid():
    assert resolve_user_id(None) == DEV_USER_ID
    assert resolve_user_id("") == DEV_USER_ID
    assert resolve_user_id("not-a-uuid") == DEV_USER_ID  # logged, falls back
    assert resolve_user_id(RIVAL_ID) == RIVAL_ID


def test_serialize_trigger_uses_real_model_fields_in_stable_envelope():
    trigger = CoachingTrigger(
        trigger_type=TriggerType.WORKOUT_COMPLETED,
        user_id=uuid.UUID(USER_ID),
        occurred_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        dedupe_key="k",
        event_id="run-1",
        payload={"run_id": "run-1", "total_session_steps": 10},
    )
    envelope = json.loads(serialize_trigger(trigger))

    assert envelope["type"] == ENVELOPE_TYPE == "coaching_trigger"
    assert set(envelope.keys()) == {"type", "trigger"}  # nothing invented
    # The trigger is the model's real Pydantic JSON form — field-for-field.
    assert envelope["trigger"] == trigger.model_dump(mode="json")
    assert envelope["trigger"]["trigger_type"] == "workout_completed"
    assert envelope["trigger"]["user_id"] == USER_ID
    assert envelope["trigger"]["dedupe_key"] == "k"


# ─────────────────────────────────────────────────────────────────────────────
# Connection lifecycle
# ─────────────────────────────────────────────────────────────────────────────


def test_connection_and_disconnection_register_and_cleanup(client):
    assert ws_module.manager.active_sessions(USER_ID) == 0
    with _Connect(client) as ws:
        # Default identity is the dev user; inbound client payloads are
        # ignored (REST stays the request channel) and the socket stays open.
        ws.send_text("hello")
        assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 1)
        assert ws_module.manager.active_sessions(RIVAL_ID) == 0
    assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 0)


def test_identity_from_query_param_scopes_the_session(client):
    with _Connect(client, RIVAL_ID) as ws:
        ws.send_text("ping")
        assert _wait_until(lambda: ws_module.manager.active_sessions(RIVAL_ID) == 1)
        assert ws_module.manager.active_sessions(USER_ID) == 0
    assert _wait_until(lambda: ws_module.manager.active_sessions(RIVAL_ID) == 0)


# ─────────────────────────────────────────────────────────────────────────────
# Delivery: user-scoping, multi-session, isolation, cleanup
# ─────────────────────────────────────────────────────────────────────────────


def test_trigger_reaches_its_user_and_not_an_unrelated_user(client):
    """Integration: a real trigger emitted by the engine reaches the socket of
    the owning user only — the unrelated user's FIRST message is their own."""
    _seed_user(USER_ID)
    _seed_user(RIVAL_ID)

    with _Connect(client, USER_ID) as ws_dev:
        with _Connect(client, RIVAL_ID) as ws_rival:
            # The connect handshake returns on accept, marginally before the
            # endpoint registers the session — wait until both are registered
            # so a run below cannot emit before a socket is targetable.
            assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 1)
            assert _wait_until(lambda: ws_module.manager.active_sessions(RIVAL_ID) == 1)

            # DEV runs -> DEV's socket gets it.
            _sync_run_for(USER_ID, "run-dev-1")
            dev_envelope = ws_dev.receive_json()
            assert dev_envelope["type"] == ENVELOPE_TYPE
            assert dev_envelope["trigger"]["user_id"] == USER_ID
            assert dev_envelope["trigger"]["trigger_type"] == "workout_completed"

            # RIVAL runs -> RIVAL's socket gets THEIR message, and since this
            # is RIVAL's first received message, DEV's earlier trigger never
            # leaked across users.
            _sync_run_for(RIVAL_ID, "run-rival-1")
            rival_envelope = ws_rival.receive_json()
            assert rival_envelope["trigger"]["user_id"] == RIVAL_ID


def test_multiple_sessions_for_one_user_each_receive_the_trigger(client):
    _seed_user(USER_ID)
    with _Connect(client, USER_ID) as ws_a:
        with _Connect(client, USER_ID) as ws_b:
            assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 2)

            _sync_run_for(USER_ID, "run-multi-1")

            envelope_a = ws_a.receive_json()
            envelope_b = ws_b.receive_json()
            assert envelope_a == envelope_b
            assert envelope_a["trigger"]["event_id"] == "run-multi-1"
            assert ws_module.manager.active_sessions(USER_ID) == 2


def test_disconnected_session_is_removed_and_no_longer_targeted(client):
    _seed_user(USER_ID)

    # A first session connects and closes immediately.
    with _Connect(client, USER_ID):
        pass
    assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 0)

    # A live session still receives triggers afterwards.
    with _Connect(client, USER_ID) as ws:
        assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 1)
        _sync_run_for(USER_ID, "run-after-close")
        envelope = ws.receive_json()
        assert envelope["trigger"]["user_id"] == USER_ID
        assert envelope["trigger"]["event_id"] == "run-after-close"
        assert ws_module.manager.active_sessions(USER_ID) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Broken socket / subscriber safety
# ─────────────────────────────────────────────────────────────────────────────


class _BrokenSendSocket:
    """A socket whose writes always fail — models a stale/broken connection."""

    async def send_text(self, _text: str) -> None:
        raise ConnectionError("broken pipe")

    async def receive(self):
        await asyncio.sleep(3600)  # never completes; sender fails first
        return {"type": "websocket.disconnect"}


def test_broken_socket_teardown_never_breaks_trigger_processing():
    """A send failure drops only that session and must never raise into the
    producer (run sync / trigger engine)."""

    async def scenario():
        fresh_manager = ws_module.CoachingSessionManager()
        session = fresh_manager.register(BROKEN_USER_ID, _BrokenSendSocket())
        assert fresh_manager.active_sessions(BROKEN_USER_ID) == 1

        # A producer delivers a trigger to the session exactly like the real
        # engine path does (handle_trigger -> threadsafe queue put).
        trigger = CoachingTrigger(
            trigger_type=TriggerType.WORKOUT_COMPLETED,
            user_id=uuid.UUID(BROKEN_USER_ID),
            dedupe_key="over-broken-socket",
        )
        fresh_manager.handle_trigger(trigger)
        await asyncio.sleep(0)  # let the scheduled queue put land

        # Driving the session: the sender task hits the broken socket, tears
        # the session down and returns without raising.
        await ws_module._serve_session(session, mgr=fresh_manager)
        assert fresh_manager.active_sessions(BROKEN_USER_ID) == 0

        # Subsequent emissions for that user simply no-op (no live sessions).
        fresh_manager.handle_trigger(trigger)  # must not raise

    asyncio.run(scenario())


def test_trigger_engine_subscriber_stays_safe_and_emission_continues(client):
    """Emission works before AND after a client connect/disconnect — the WS
    transport never degrades the engine's own recording."""
    _seed_user(USER_ID)

    def accepted_types():
        return [
            t.trigger_type
            for t in trigger_engine.accepted(user_id=uuid.UUID(USER_ID))
        ]

    # Before any socket: a run still records its WORKOUT_COMPLETED normally.
    with Session(engine) as session:
        process_run_sync(
            session,
            RunSyncPayload(total_session_steps=500, hexes_to_steps={}, run_id="pre-ws"),
            uuid.UUID(USER_ID),
        )
    assert TriggerType.WORKOUT_COMPLETED in accepted_types()

    # Open + close a socket (client churn), then emit again. Two WORKOUT runs
    # inside the 10s M8.1 cooldown would collapse to one, so prove continuity
    # with a territory capture — a cooldown-0 type that must always emit.
    # The endpoint unregisters on close via try/finally, so the registry must
    # be empty again after the client disconnects.
    with _Connect(client, USER_ID):
        pass
    assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 0)

    with Session(engine) as session:
        summary = process_run_sync(
            session,
            RunSyncPayload(
                total_session_steps=500,
                hexes_to_steps={"hexPost": 500},
                run_id="post-ws",
            ),
            uuid.UUID(USER_ID),
        )
        assert summary.already_processed is False
    assert TriggerType.TERRITORY_CAPTURED in accepted_types()

    # A malformed subscriber callback must never break accept (M8.1 contract).
    eng = trigger_engine
    eng.subscribe(lambda _t: (_ for _ in ()).throw(RuntimeError("boom")))
    trigger = CoachingTrigger(
        trigger_type=TriggerType.WORKOUT_COMPLETED,
        user_id=uuid.UUID(BROKEN_USER_ID),
        dedupe_key="subscriber-safe",
    )
    assert eng.accept(trigger) is TriggerDecision.ACCEPTED
