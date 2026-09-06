"""M8.2 — WebSocket transport for coaching triggers.

Role in the SRS §15/§16 architecture:

    TriggerEngine                      (producer — M8.1, unchanged)
        |  subscribe(...)
        v
    CoachingSessionManager             (transport consumer — this module)
        |  per-user fan-out
        v
    connected WebSocket clients
        |
        v
    serialized CoachingTrigger envelope

The trigger engine REMAINS the only producer of triggers; this layer is a
pure transport consumer. WebSocket is an ADDITIONAL real-time channel for
coaching events (SRS §16) — it does not replace REST, does not touch
``GET /api/v1/coach``, and never calls the LLM/RAG. Out of scope here: TTS,
Android handling, Redis, and real authentication (dev identity is reused).

Threading model
---------------
``trigger_engine.subscribe`` callbacks run synchronously on the EMITTER's
thread (a run-sync request threadpool thread), while sockets are asyncio. The
manager therefore never touches a socket from the producer thread: it
snapshots the sessions registered for the trigger's user and schedules each
session's own bounded asyncio queue via ``loop.call_soon_threadsafe``. Every
open connection owns one sender task that awaits that queue and writes to its
socket, so all socket I/O happens on the event loop and sends are serialized
per connection.

Failure safety
--------------
A send failure (broken/stale socket) ends only that session's sender task and
unregisters the session. The producer (run sync / trigger engine) never awaits
the transport, and the engine already swallows subscriber errors (M8.1), so a
failed WebSocket client can never break run sync or trigger emission.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.dependencies import DEV_USER_ID
from app.modules.triggers.engine import CoachingTrigger, trigger_engine

logger = logging.getLogger(__name__)

# Stable wire envelope: {"type": ENVELOPE_TYPE, "trigger": {...}}.
ENVELOPE_TYPE = "coaching_trigger"

# Per-connection outbound queue cap. Coaching is advisory: if a slow socket
# falls this far behind we start dropping rather than blocking the producer
# or growing memory without bound.
SESSION_QUEUE_SIZE = 256


def serialize_trigger(trigger: CoachingTrigger) -> str:
    """Envelope a trigger for the wire using its existing Pydantic form.

    ``model_dump(mode="json")`` yields the schema's real fields (UUID/date/
    datetime as strings). Nothing is invented and no fields are added.
    """
    return json.dumps(
        {"type": ENVELOPE_TYPE, "trigger": trigger.model_dump(mode="json")},
        ensure_ascii=False,
    )


def resolve_user_id(user_id: str | None) -> str:
    """Dev-identity resolution, consistent with ``dependencies.get_current_user``.

    Missing -> the dev user (the same fixed identity every REST endpoint
    uses). Present and a valid UUID -> that user, so a dev/test client can
    observe per-user isolation without inventing an auth system. Anything else
    is logged and falls back to the dev user — never an error, matching the
    no-auth dev posture. Real auth replaces this wholesale in production (see
    the TODO in app/api/dependencies.py); this is NOT a security boundary.
    """
    if user_id:
        try:
            return str(uuid.UUID(user_id))
        except ValueError:
            logger.warning(
                "coaching WS: ignoring non-UUID user_id %r; using dev user",
                user_id,
            )
    return DEV_USER_ID


class _Session:
    """One open connection: its own bounded outbound queue + closed flag."""

    def __init__(
        self,
        user_id: str,
        websocket: WebSocket,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.user_id = user_id
        self.websocket = websocket
        self.loop = loop
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=SESSION_QUEUE_SIZE)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class CoachingSessionManager:
    """User-scoped registry of live coaching WebSocket sessions.

    Thread-safe (the producer thread and the event-loop thread both touch the
    registry). ``register``/``disconnect`` mutate it; the trigger callback only
    snapshots it and enqueues onto per-session loops.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, set[_Session]] = defaultdict(set)

    # ── lifecycle ───────────────────────────────────────────────────────────

    def register(self, user_id: str, websocket: WebSocket) -> _Session:
        """Record a newly-accepted connection for ``user_id``."""
        session = _Session(user_id, websocket, asyncio.get_running_loop())
        with self._lock:
            self._sessions[user_id].add(session)
        return session

    def disconnect(self, session: _Session) -> None:
        """Unregister a session. Idempotent; safe from the sender task."""
        session.close()
        with self._lock:
            sessions = self._sessions.get(session.user_id)
            if sessions is None:
                return
            sessions.discard(session)
            if not sessions:
                self._sessions.pop(session.user_id, None)

    def clear(self) -> None:
        """Drop every session (test isolation / shutdown).

        Sockets are owned by their connection lifecycle; this only empties the
        registry so stale sessions can never receive triggers.
        """
        with self._lock:
            for sessions in self._sessions.values():
                for session in sessions:
                    session.close()
            self._sessions.clear()

    # ── introspection (tests / ops) ─────────────────────────────────────────

    def active_sessions(self, user_id: str) -> int:
        with self._lock:
            return len(self._sessions.get(user_id, ()))

    # ── trigger subscription (producer thread) ──────────────────────────────

    def handle_trigger(self, trigger: CoachingTrigger) -> None:
        """``trigger_engine.subscribe`` target: fan a trigger out to the user's
        live sessions.

        Runs on the producer thread. It only snapshots the registry and
        schedules queue puts (never sends), so it can neither block nor fail
        the run sync; every failure path below is contained.
        """
        with self._lock:
            targets = list(self._sessions.get(str(trigger.user_id), ()))
        if not targets:
            return
        envelope = serialize_trigger(trigger)
        for session in targets:
            self._enqueue(session, envelope)

    def _enqueue(self, session: _Session, envelope: str) -> None:
        if session.closed:
            return

        def _put() -> None:
            try:
                session.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                # Advisory: drop rather than let a slow socket grow unbounded.
                logger.debug(
                    "coaching WS queue full for %s; dropping trigger",
                    session.user_id,
                )

        try:
            session.loop.call_soon_threadsafe(_put)
        except RuntimeError:
            # Loop closed between snapshot and enqueue (disconnect race).
            self.disconnect(session)


# Module singleton shared with the endpoint. Cleared together with the other
# process-global singletons in tests (see tests/conftest.py).
manager = CoachingSessionManager()


# ── per-connection task loops ───────────────────────────────────────────────


async def _sender_loop(session: _Session) -> None:
    """Consume the session's outbound queue and write each envelope.

    Ends (via exception) only on a broken/stale socket; the connection
    teardown then unregisters the session. Sends are serialized because this
    is the ONLY task that ever sends on this socket.
    """
    while True:
        envelope = await session.queue.get()
        await session.websocket.send_text(envelope)


async def _client_watcher(session: _Session) -> None:
    """Watch for client disconnect. Inbound client payloads are ignored —
    REST remains the request channel (SRS §16); this is a push-only channel."""
    try:
        while True:
            message = await session.websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
    except (WebSocketDisconnect, RuntimeError):
        return
    except Exception:
        logger.debug(
            "coaching WS client watcher ended for %s",
            session.user_id,
            exc_info=True,
        )


async def _serve_session(
    session: _Session,
    mgr: CoachingSessionManager = manager,
) -> None:
    """Drive one session until the client disconnects or the socket breaks.

    ``mgr`` defaults to the module singleton (used by the endpoint); tests pass
    their own manager to assert teardown without touching global state.
    """
    sender = asyncio.create_task(_sender_loop(session))
    watcher = asyncio.create_task(_client_watcher(session))
    done, pending = await asyncio.wait(
        {sender, watcher}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    if sender in done:
        try:
            exc = sender.exception()
        except (asyncio.CancelledError, Exception):
            exc = None
        if exc is not None:
            # Broken/stale socket — expected on network loss; drop quietly.
            logger.debug(
                "coaching WS session dropped for %s: %s",
                session.user_id,
                exc,
            )
    mgr.disconnect(session)


# ── endpoint ────────────────────────────────────────────────────────────────

router = APIRouter()


@router.websocket("/coaching")
async def coaching_ws(websocket: WebSocket, user_id: str | None = None) -> None:
    """``/api/v1/ws/coaching`` — push channel for the connecting user's
    CoachingTrigger events. See docs/docs/coaching/0002-m82-websocket-transport.md.
    """
    identity = resolve_user_id(user_id)
    await websocket.accept()
    session = manager.register(identity, websocket)
    try:
        await _serve_session(session)
    except Exception:  # noqa: BLE001 — a broken WS must never crash the app
        logger.info(
            "coaching WS connection error for %s",
            identity,
            exc_info=True,
        )
    finally:
        # Idempotent: _serve_session already unregisters on a clean close or a
        # broken socket. The finally also covers task cancellation (server
        # shutdown, test-client teardown), so a session can never linger in
        # the registry and later receive triggers against a dead socket.
        manager.disconnect(session)


# Subscribe the transport to the trigger engine ONCE, at import. The engine
# stays the producer; this is the M8.1 -> M8.2 seam. The engine swallows
# subscriber errors (M8.1), so even a misbehaving transport cannot break
# emission.
trigger_engine.subscribe(manager.handle_trigger)
