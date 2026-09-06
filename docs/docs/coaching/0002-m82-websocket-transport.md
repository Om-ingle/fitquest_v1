# ADR 0002: M8.2 — WebSocket Transport for Coaching Triggers (backend)

Status: implemented 2026-09-06. Second slice of FitQuest SRS §15/§16
"Real-Time AI Coaching". Adds the WebSocket transport that carries the M8.1
`CoachingTrigger`s (recorded, deduplicated, cooldown-gated) from the trigger
engine to a connected client in real time:

    TriggerEngine (producer, M8.1)  ->  WebSocket session manager  ->
    connected client  ->  serialized CoachingTrigger envelope

This task adds **no** TTS, **no** Android UI/event handling, **no** LLM call,
**no** RAG call, **no** Redis, **no** replacement of any existing REST API,
and **no** fabricated authentication — the current dev-user identity is
reused. The WebSocket is an ADDITIONAL real-time channel (SRS §16); REST
(including `GET /api/v1/coach`) is unchanged. M8.1 trigger rules were NOT
modified.

## Context & Problem Statement

M8.1 ended with triggers recorded and inspectable in-process
(`trigger_engine.accepted()`), but with no transport: "No transport yet …
until M8.2 wires the WebSocket broadcaster." The SRS §16 client contract is
connect → (server) send coaching events → receive → disconnect/reconnect,
with REST explicitly untouched and WebSocket reserved for real-time coaching
only. M8.2 must deliver those accepted triggers to the right user's device
without ever letting a transport failure break run sync or trigger emission.

The hard engineering constraint is concurrency. `process_run_sync` runs on a
FastAPI threadpool thread (sync `def`), while sockets are asyncio on the event
loop. `trigger_engine.subscribe(fn)` invokes subscribers synchronously on the
emitter thread, so the transport's trigger callback runs OFF the event loop
and must not do any socket I/O itself.

## Decisions

### 1. Endpoint: `/api/v1/ws/coaching` — an additive push channel

`app/modules/triggers/ws.py` exposes an `APIRouter` with a single WebSocket
route, mounted in `app/api/router.py`:

    api_router.include_router(coaching_ws_router, prefix="/ws", tags=["Coaching WS"])

Composed with the existing `/api/v1` prefix, the address is
**`/api/v1/ws/coaching`** (the task's preferred path). It is a push-only
channel: the server sends trigger envelopes; inbound client payloads are
ignored (REST stays the request channel). It does not shadow or replace any
REST route.

### 2. Session identity: existing dev-user mechanism — NOT a security boundary

No auth is fabricated. The optional query parameter `?user_id=<uuid>` lets a
dev/test client observe per-user isolation; the resolver mirrors the REST
dev-stub identity in `app/api/dependencies.py`:

- `user_id` missing, empty, or not a valid UUID → the fixed dev user
  `DEV_USER_ID` (00000000-0000-0000-0000-000000000001), logged at warning.
- valid UUID → normalized `str(uuid.UUID(...))`.

Real authentication replaces this wholesale in production (see the existing
TODO in `dependencies.py`); this resolver is a scoping convenience, not a
security control. The same identity mechanism every REST endpoint already uses
is simply reused over the socket.

### 3. Producer/consumer seam: subscribe once, at import

`ws.py` subscribes its session manager to the engine exactly once, at module
import: `trigger_engine.subscribe(manager.handle_trigger)`. The engine remains
the sole producer; the manager is a pure transport consumer. Because M8.1's
engine already swallows subscriber errors and invokes subscribers outside its
lock, even a misbehaving transport callback cannot break emission.

### 4. Connection manager: user-scoped, thread-safe, lazy cleanup

`CoachingSessionManager` is a `threading.RLock`-guarded registry
`user_id -> set[_Session]`:

- `register(user_id, websocket)` — records a just-accepted connection.
- `disconnect(session)` — idempotent removal; pops the user key when empty.
- `clear()` — empties the registry (test isolation / shutdown).
- `active_sessions(user_id)` — introspection for tests/ops.

Each `_Session` owns one bounded `asyncio.Queue` (cap 256). On a trigger, the
manager snapshots the user's sessions under the lock, serializes once, and
schedules each session's own queue put via
`loop.call_soon_threadsafe(...)` — never touching a socket from the producer
thread.

### 5. One connection = two dedicated tasks, joined by FIRST_COMPLETED

Every open connection is driven by `_serve_session`:

- `_sender_loop` — the ONLY task that sends: `await queue.get()` then
  `await websocket.send_text(envelope)`. Sends are therefore serialized per
  connection, and the sender exits (via exception) only on a broken socket.
- `_client_watcher` — the only task that receives; returns on a client
  disconnect (`websocket.disconnect` / `WebSocketDisconnect`) so it never
  consumes app-level messages.
- `_serve_session` joins them with `asyncio.wait(..., FIRST_COMPLETED)`,
  cancels the loser, `gather(..., return_exceptions=True)`, logs a dropped
  session if the sender failed, and unregisters via `manager.disconnect`.

The endpoint wraps this in `try/except Exception ... finally:
manager.disconnect(session)`. The `finally` matters: it makes unregister
survive task cancellation (server shutdown, test-client teardown), so a dead
connection can never linger in the registry and later receive triggers. This
is the one behavioral guard M8.2 added on top of the design in ADR 0001.

### 6. Wire format: stable envelope over the real model

One serialization, defined once in `serialize_trigger`:

    {"type": "coaching_trigger", "trigger": <CoachingTrigger.model_dump(mode="json")>}

`model_dump(mode="json")` yields the schema's actual fields
(`trigger_type`, `user_id`, `occurred_at`, `dedupe_key`, `event_id`,
`payload`) with UUID/date/datetime already stringified. Nothing is invented
and no field is added. `type` distinguishes this push channel's event and is
stable for the client switch. Example:

    {
      "type": "coaching_trigger",
      "trigger": {
        "trigger_type": "workout_completed",
        "user_id": "00000000-0000-0000-0000-000000000001",
        "occurred_at": "2026-09-06T12:34:56.789Z",
        "dedupe_key": "run-1234",
        "event_id": "run-1234",
        "payload": {"run_id": "run-1234", "total_session_steps": 5000}
      }
    }

### 7. Failure safety — a dead client can never break the pipeline

Every failure path is contained and ends in dropping only that session:

- **Broken/stale socket**: the sender's `send_text` raises → sender ends →
  `_serve_session` tears down and unregisters. The producer never awaited the
  transport, so run sync and engine emission are unaffected.
- **Slow client**: the per-session queue is bounded (256); on overflow the
  trigger is dropped with a debug log rather than blocking the producer or
  growing memory. Coaching is advisory, so a lost advisory message is the
  correct failure mode.
- **Loop already closed** (disconnect race between snapshot and enqueue):
  `call_soon_threadsafe` raises `RuntimeError` → the session is unregistered.
- **Cancellation**: the endpoint's `finally` unregisters even when the task is
  cancelled mid-serve.

## Files changed

- `app/modules/triggers/ws.py` *(new)* — transport consumer: serializer,
  identity resolver, `_Session`, `CoachingSessionManager` (module singleton
  `manager`), sender/watcher/`_serve_session`, the `/coaching` WebSocket
  endpoint, and the single import-time `trigger_engine.subscribe(...)`.
- `app/api/router.py` — imports `ws.router` and mounts it under `/ws`.
- `tests/conftest.py` — clears `coaching_ws_manager` with the DB and the other
  process-global singletons in the `client` fixture.
- `tests/test_ws.py` *(new)* — see below.
- `docs/docs/coaching/0002-m82-websocket-transport.md` *(this ADR)*.

## Tests

`tests/test_ws.py` — 9 focused tests:

- identity: missing/invalid `user_id` falls back to the dev user; a valid UUID
  is accepted.
- serialization: the envelope has exactly `{"type","trigger"}` and the
  `trigger` equals `CoachingTrigger.model_dump(mode="json")` field-for-field.
- connection lifecycle: connect registers, close unregisters (registry empty),
  identity query param scopes the session to that user.
- delivery: a REAL engine-emitted trigger (via a real `process_run_sync`
  through the runsession replay ledger) reaches its user's socket and NOT an
  unrelated user's; the unrelated user's first message is their own.
- multi-session: two sockets for one user each receive the same envelope.
- disconnect cleanup: a closed session is removed and no longer targeted.
- broken socket: a send failure tears down only that session and never breaks
  later trigger processing.
- engine-subscriber safety: emission is recorded before AND after a client
  connect/disconnect (proved with a territory capture, a cooldown-0 type), and
  a raising subscriber never breaks `accept()`.

Run: `pytest tests/test_ws.py`. Full backend suite:
`pytest tests/` → **247 passed** (includes the 28 M8.1 trigger tests, all
unmodified and still green).

### Note on TestClient WebSocket teardown

Starlette's `TestClient` closes a socket by cancel-scoping the app task and
blocking on it; that wait intermittently re-raises `CancelledError` even after
the endpoint unwound cleanly — a harness artifact that appears on ANY
websocket endpoint. Tests route connections through a small `_Connect` wrapper
that suppresses that cosmetic raise (the endpoint's `try/finally` guarantees
the session is removed on both the clean-close and the cancel path before the
portal task finishes, so suppression never hides a real leak). The dedicated
disconnect-cleanup assertion is thus deterministic.

## Limitations

- The channel pushes raw `CoachingTrigger` events — the AI coaching content a
  device would speak/display is a later stage (M8.3+). SRS §16's end-to-end
  coaching event still terminates at a structured trigger here.
- Delivery is best-effort and in-process: no durable outbox. A trigger emitted
  while the user has no live session is simply not delivered (it is still
  recorded by the engine's accepted log). The 256-slot per-session queue drops
  newest-first for a slow socket rather than blocking the producer.
- Registry and session state are process-local; multi-instance deployments
  would need a shared bus (Redis is explicitly out of scope per the task).
- Identity is the dev-user mechanism; no authentication, reconnection backoff
  protocol, or heartbeat/ping is implemented yet.

## Next step (M8.3)

Wire a trigger → coaching-message stage that reuses the existing pull-coach
services instead of writing a second AI path: a new engine subscriber builds
`build_fitness_context(db, user_id)` (already in
`app/modules/recommendations/service.py`), runs the existing
`recommend`/`generate_coaching` (RAG + LLM) to produce a short coaching
message, and enqueues it to the SAME transport as a new envelope type — so the
M8.2 fan-out, user scoping and failure containment are reused untouched. The
LLM stage must run as a fire-and-forget task off the emitter thread (never
block run sync) and be gated by the existing coach cache/cooldown so bursty
activity (a run that also captures hexes and crosses a milestone) collapses to
one push. Evaluate it against pull-coach so nothing regresses; defer TTS and
Android handling as before.
