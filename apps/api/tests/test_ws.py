"""M8.2 WebSocket transport tests (M11: authenticated handshake).

Covers the transport layer of the SRS §15/§16 real-time coaching pipeline:

    TriggerEngine -> CoachingSessionManager -> connected client

Focused tests for connection/disconnection, user-scoped delivery, multiple
sessions per user, unrelated-user isolation, serialization, disconnect
cleanup, a broken socket never breaking trigger processing, and the trigger
engine's subscriber staying safe. Integration tests prove that a real
CoachingTrigger emitted by the existing trigger engine (via a real
``process_run_sync``) reaches a subscribed WebSocket client.

M11 changed HOW a connection proves who it is, so this file now covers both
halves:

* the handshake must present a real ES256 bearer token — the ``?user_id=``
  query parameter is gone and grants nothing, and there is no unauthenticated
  fallback to the dev user (see the section below);
* everything above the identity boundary (fan-out, isolation, teardown,
  failure containment) behaves exactly as it did in M8.2.

Authentication here is real: the handshake token is verified by the same
``decode_supabase_jwt`` REST uses. Nothing is stubbed — see tests/authkit.py.

No LLM/RAG is called anywhere; ``GET /api/v1/coach`` is untouched.
"""
import asyncio
import datetime as dt
import json
import time
import uuid
from concurrent import futures

from sqlmodel import Session
from starlette.datastructures import Headers
from starlette.websockets import WebSocketDisconnect

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
    WS_CLOSE_INTERNAL_ERROR,
    WS_CLOSE_POLICY_VIOLATION,
    authenticate_handshake,
    serialize_trigger,
)
from tests.authkit import install_jwks, jwks_outage, link_identity

USER_ID = DEV_USER_ID
RIVAL_ID = "00000000-0000-0000-0000-000000000099"
BROKEN_USER_ID = "00000000-0000-0000-0000-0000000000bb"
WS_PATH = "/api/v1/ws/coaching"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


class _Connect:
    """``client.websocket_connect`` with a tolerant teardown.

    ``headers`` are merged OVER the client's defaults, so passing a rival's
    Authorization header connects as the rival while omitting it connects as
    whichever account the client is authenticated as (see httpx
    ``_merge_headers``).

    Starlette's TestClient closes a socket by cancel-scoping the app task and
    waiting on it; the wait intermittently re-raises ``CancelledError`` even
    when the endpoint already unwound cleanly — a harness artifact that appears
    on any websocket endpoint, not this transport. The endpoint's try/finally
    removes the session on EITHER path before the portal task finishes, so the
    raise is cosmetic. We suppress it (return True) only when the body did not
    raise; a real body error still propagates.
    """

    def __init__(self, client, headers: dict[str, str] | None = None, path: str = WS_PATH):
        self._inner = client.websocket_connect(path, headers=dict(headers or {}))

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, et, ev, tb):
        try:
            return self._inner.__exit__(et, ev, tb)
        except futures.CancelledError:
            return et is None


def _refusal_code(client, headers=None, path: str = WS_PATH) -> int:
    """Attempt a handshake that must be refused; return the server's close code.

    The endpoint closes BEFORE ``accept()``, so the upgrade never completes and
    the test client raises ``WebSocketDisconnect`` out of ``__enter__`` rather
    than yielding a socket. Reaching the body would mean the connection was
    accepted — which is exactly the failure this asserts against.
    """
    try:
        with client.websocket_connect(path, headers=dict(headers or {})):
            pass
    except WebSocketDisconnect as disconnect:
        return disconnect.code
    raise AssertionError("the handshake was accepted; it should have been refused")


class _FakeHandshake:
    """Just enough of a WebSocket for the pure ``authenticate_handshake`` tests.

    ``headers`` is a real ``starlette.datastructures.Headers``, the same type
    the endpoint reads, so case-insensitive lookup is exercised rather than
    assumed.
    """

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = Headers(headers)


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
# Handshake authentication (M11)
# ─────────────────────────────────────────────────────────────────────────────


def test_handshake_without_a_token_is_refused(anon_client):
    """No credentials => no connection. There is no anonymous coaching session.

    The dev user is seeded in this schema, so this also proves the old
    ``DEV_USER_ID`` fallback is gone: an unauthenticated connection is refused
    even though a default account exists and is reachable.
    """
    code = _refusal_code(anon_client)

    assert code == WS_CLOSE_POLICY_VIOLATION
    assert ws_module.manager.active_sessions(USER_ID) == 0


def test_handshake_with_a_garbage_token_is_refused(anon_client):
    code = _refusal_code(anon_client, {"Authorization": "Bearer not.a.jwt"})
    assert code == WS_CLOSE_POLICY_VIOLATION


def test_handshake_with_a_non_bearer_scheme_is_refused(anon_client):
    """A token under the wrong scheme is not a credential."""
    code = _refusal_code(anon_client, {"Authorization": "Basic dXNlcjpwYXNz"})
    assert code == WS_CLOSE_POLICY_VIOLATION


def test_handshake_signed_by_an_unpublished_key_is_refused(anon_client, jwks):
    """A well-formed token from a key this project does not publish.

    Forging a coaching session must fail at the signature, exactly as forging
    a REST request does.
    """
    forged = jwks.factory.foreign_token(jwks.foreign, RIVAL_ID)
    code = _refusal_code(anon_client, {"Authorization": f"Bearer {forged}"})
    assert code == WS_CLOSE_POLICY_VIOLATION


def test_handshake_with_an_expired_token_is_refused(anon_client, jwks):
    expired = jwks.factory.token(USER_ID, ttl_seconds=-60)
    code = _refusal_code(anon_client, {"Authorization": f"Bearer {expired}"})
    assert code == WS_CLOSE_POLICY_VIOLATION


def test_handshake_minted_for_another_project_is_refused(anon_client, jwks):
    """A valid signature from the wrong issuer still names the wrong project."""
    foreign_issuer = "https://someone-elses-project.supabase.co/auth/v1"
    token = jwks.factory.token(USER_ID, iss=foreign_issuer)
    code = _refusal_code(anon_client, {"Authorization": f"Bearer {token}"})
    assert code == WS_CLOSE_POLICY_VIOLATION


def test_handshake_with_the_old_hs256_shared_secret_is_refused(anon_client, jwks):
    """No HS256 fallback (M11 decision D2).

    The pre-M11 backend verified exactly this token if its secret matched —
    and its default secret was the published string "change-me".
    """
    token = jwks.factory.hs256_token(USER_ID, "change-me")
    code = _refusal_code(anon_client, {"Authorization": f"Bearer {token}"})
    assert code == WS_CLOSE_POLICY_VIOLATION


def test_handshake_with_an_unsigned_token_is_refused(anon_client, jwks):
    token = jwks.factory.unsigned_token(USER_ID)
    code = _refusal_code(anon_client, {"Authorization": f"Bearer {token}"})
    assert code == WS_CLOSE_POLICY_VIOLATION


def test_jwks_outage_refuses_with_an_internal_error_not_a_policy_violation(
    anon_client, jwks, monkeypatch, es256_key
):
    """A valid token that cannot be CHECKED is a 5xx, not bad credentials.

    1008 would tell the client its token is bad and invite it to discard
    credentials it should keep; 1011 tells it to retry.
    """
    install_jwks(monkeypatch, jwks_outage())
    token = jwks.factory.token(USER_ID)
    code = _refusal_code(anon_client, {"Authorization": f"Bearer {token}"})
    assert code == WS_CLOSE_INTERNAL_ERROR


def test_handshake_registers_under_the_token_holder(client, tokens):
    """A valid token connects, and the session belongs to ITS subject."""
    link_identity(RIVAL_ID, "rival")

    with _Connect(client, tokens.headers(RIVAL_ID)):
        assert _wait_until(lambda: ws_module.manager.active_sessions(RIVAL_ID) == 1)
        # The client's own account is NOT the one serving this connection.
        assert ws_module.manager.active_sessions(USER_ID) == 0

    assert _wait_until(lambda: ws_module.manager.active_sessions(RIVAL_ID) == 0)


def test_query_param_cannot_name_an_identity(client, tokens):
    """``?user_id=`` is inert — it is parsed by nothing.

    Kept as an explicit regression guard: this parameter used to BE the
    identity, so a connection could serve any user's events by asking for them.
    A dev-token connection demanding the rival's id must still register as the
    dev user.
    """
    link_identity(RIVAL_ID, "rival")

    with _Connect(client, path=f"{WS_PATH}?user_id={RIVAL_ID}") as ws:
        ws.send_text("ping")
        assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 1)
        assert ws_module.manager.active_sessions(RIVAL_ID) == 0


def test_a_connection_cannot_forge_a_foreign_subject_in_the_query_string(anon_client):
    """The same guard, without a token at all — the parameter grants nothing."""
    code = _refusal_code(anon_client, path=f"{WS_PATH}?user_id={USER_ID}")
    assert code == WS_CLOSE_POLICY_VIOLATION


def test_authenticate_handshake_returns_the_internal_id_and_no_close_code(client, tokens):
    """The pure function: success is ``(id, None)``, refusal ``(None, code)``.

    On success the id is FitQuest's INTERNAL user id — the token's subject is
    resolved through the user table, never used directly as the identity.
    """
    token = tokens.token(USER_ID)
    identity, close_code = authenticate_handshake(
        _FakeHandshake({"authorization": f"Bearer {token}"})
    )
    assert (identity, close_code) == (USER_ID, None)
    # The subject and the identity are different id spaces, deliberately.
    assert identity == USER_ID
    assert tokens.claims(USER_ID)["sub"] == USER_ID  # the subject that was resolved


def test_authenticate_handshake_refuses_missing_and_malformed_credentials():
    assert authenticate_handshake(_FakeHandshake({})) == (
        None,
        WS_CLOSE_POLICY_VIOLATION,
    )
    assert authenticate_handshake(_FakeHandshake({"authorization": "Bearer"})) == (
        None,
        WS_CLOSE_POLICY_VIOLATION,
    )
    assert authenticate_handshake(
        _FakeHandshake({"authorization": "Bearer    "})
    ) == (None, WS_CLOSE_POLICY_VIOLATION)
    assert authenticate_handshake(
        _FakeHandshake({"authorization": "Token abc.def.ghi"})
    ) == (None, WS_CLOSE_POLICY_VIOLATION)


def test_authenticate_handshake_rejects_a_token_without_a_subject(client, jwks):
    """``sub`` is required: a signature alone does not name a user."""
    claims = jwks.factory.claims(USER_ID)
    claims.pop("sub")
    token = jwks.trusted.sign(claims)
    assert authenticate_handshake(
        _FakeHandshake({"authorization": f"Bearer {token}"})
    ) == (None, WS_CLOSE_POLICY_VIOLATION)


# ─────────────────────────────────────────────────────────────────────────────
# Serialization (pure)
# ─────────────────────────────────────────────────────────────────────────────


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
        # The session is registered under the token's user; inbound payloads
        # are ignored (REST stays the request channel) and the socket stays open.
        ws.send_text("hello")
        assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 1)
        assert ws_module.manager.active_sessions(RIVAL_ID) == 0
    assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 0)


# ─────────────────────────────────────────────────────────────────────────────
# Delivery: user-scoping, multi-session, isolation, cleanup
# ─────────────────────────────────────────────────────────────────────────────


def test_trigger_reaches_its_user_and_not_an_unrelated_user(client, tokens):
    """Integration: a real trigger emitted by the engine reaches the socket of
    the owning user only — the unrelated user's FIRST message is their own.

    Both connections are authenticated as different accounts, which is the
    M11 shape of this test: isolation between two REAL identities, not between
    a real one and a query-parameter one.
    """
    link_identity(RIVAL_ID, "rival")

    with _Connect(client) as ws_dev:
        with _Connect(client, tokens.headers(RIVAL_ID)) as ws_rival:
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
    with _Connect(client) as ws_a:
        with _Connect(client) as ws_b:
            assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 2)

            _sync_run_for(USER_ID, "run-multi-1")

            envelope_a = ws_a.receive_json()
            envelope_b = ws_b.receive_json()
            assert envelope_a == envelope_b
            assert envelope_a["trigger"]["event_id"] == "run-multi-1"
            assert ws_module.manager.active_sessions(USER_ID) == 2


def test_disconnected_session_is_removed_and_no_longer_targeted(client):
    # A first session connects and closes immediately.
    with _Connect(client):
        pass
    assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 0)

    # A live session still receives triggers afterwards.
    with _Connect(client) as ws:
        assert _wait_until(lambda: ws_module.manager.active_sessions(USER_ID) == 1)
        _sync_run_for(USER_ID, "run-after-close")
        envelope = ws.receive_json()
        assert envelope["trigger"]["user_id"] == USER_ID
        assert envelope["trigger"]["event_id"] == "run-after-close"
        assert ws_module.manager.active_sessions(USER_ID) == 1


def test_a_refused_handshake_never_registers_a_session(anon_client, jwks):
    """The refusal path must leave no trace in the registry.

    A session registered before the token is checked would receive that user's
    triggers on a socket the client was told was closed.
    """
    for headers in (
        {},
        {"Authorization": "Bearer not.a.jwt"},
        {"Authorization": f"Bearer {jwks.factory.token(USER_ID, ttl_seconds=-60)}"},
    ):
        assert _refusal_code(anon_client, headers) == WS_CLOSE_POLICY_VIOLATION

    assert ws_module.manager.active_sessions(USER_ID) == 0
    assert ws_module.manager.active_sessions(RIVAL_ID) == 0


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
    with _Connect(client):
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
