# ADR 0004: M8.3B — Android Real-Time Coaching WebSocket Client

Status: implemented 2026-09-06, real-device E2E verified (see
"Real-device verification"). Fourth slice of FitQuest SRS §15/§16 "Real-Time
AI Coaching". Makes the Android app a **receive-only** participant in the M8.2
push channel: it connects to the backend WebSocket `/api/v1/ws/coaching`,
ignores the raw `coaching_trigger` frames, converts each `coaching_message`'s
`coach` into the **existing** `CoachResponse` DTO, and surfaces it in the
**existing** Home coaching card. The REST channel (`GET /api/v1/coach` +
`CoachFetcher`/`CoachCache`) is untouched and remains the offline/request path.

    PushCoach (M8.3A, unchanged)  ->  CoachingSessionManager (M8.2, unchanged)
        {"type":"coaching_message", "coach": CoachResponse}
            |
            v  ws://<BACKEND_BASE_URL>/api/v1/ws/coaching   (this slice)
    OkHttpCoachingSocketFactory -> CoachingWsClient -> LiveCoachStore
            |                                              |
            |                              StateFlow<CoachResponse?>  (live slot)
            v                                              v
    CoachingWsMessageParser                          HomeTab CoachCard
    (ignores coaching_trigger / unknown / malformed)   "⚡ Live coaching"

What this slice explicitly does **not** do: TTS (M8.4), modifying any backend
trigger rule or `PushCoach`, changing `GET /api/v1/coach`, adding Redis or
authentication, inventing a second coaching model or schema, or rewriting the
Home/Coach UI. The wire `coach` object is decoded straight into the pull
`CoachResponse` DTO (Gson ignores the unmapped `trigger` envelope), so there
is exactly one coaching representation on the client.

## Context & Problem Statement

The backend (M8.1 → M8.2 → M8.3A) can now push a grounded AI coaching message
the instant a run commits, but the app still only pulls on Home entry. The
spec for this slice:

- Parse the two stable envelope types: `coaching_trigger` (log/ignore) and
  `coaching_message` (surface).
- No hard-coded dev IP: derive `ws://`/`wss://` from the existing
  `BuildConfig.BACKEND_BASE_URL` (same source every REST call uses).
- No auth header: connect with no `?user_id`, so the backend's
  `resolve_user_id(None)` lands on the same fixed dev user the app's
  unauthenticated REST calls act as.
- The live push must not corrupt the pull `CoachCache` (whose "fetch again?"
  decision is keyed on the set of synced run ids).
- Lifecycle: connect at the right time, disconnect cleanly, never leak, never
  open duplicates across recomposition/navigation, and survive
  Home → Profile → Home navigation (process/activity scoping).
- Reconnect: bounded, conservative, capped-exponential backoff — no aggressive
  loops.
- Failure containment: a dead/refused socket must not crash the app, block
  REST, or stop `CoachFetcher` / workout tracking / run sync. The app stays
  fully usable on the pull/offline path.
- Focused JVM tests (no real network) for decoding, mapping, ignoring,
  malformed safety, live-state update, no pull-cache corruption, no duplicate
  connection, disconnect cleanup, reconnect/backoff, and WS-failure isolation.

## Decisions

### 1. Transport seam: `CoachingSocketFactory` (real = OkHttp; fake = tests)

`core/network/OkHttpCoachingSocketFactory.kt` bridges OkHttp's
`newWebSocket` to a tiny 4-callback seam (`CoachingSocketCallbacks`:
`onOpen/onMessage/onClosed/onFailure`) plus an outbound `CoachingSocket`
handle exposing only `close(code, reason)`. `CoachingWsClient` depends only on
the seam, so every unit test drives a scripted in-memory fake — zero network,
deterministic, no `kotlinx-coroutines-test` (the version catalog deliberately
doesn't have it; tests use `runBlocking`/`Dispatchers.Unconfined` + a no-op
backoff `sleeper`).

`coachingWsUrl(baseUrl)` derives the endpoint from the REST base:
`http` → `ws`, `https` → `wss`, preserving host/port/base path and appending
`/api/v1/ws/coaching`. OkHttp's `HttpUrl` only accepts `http(s)` schemes, so
the base URL is parsed with `HttpUrl` purely for validation/normalization and
the `ws`/`wss` URL is assembled by hand (a first draft that called
`.scheme("ws")` on the builder threw `IllegalArgumentException` — caught by the
unit test, fixed).

### 2. Client: receive-only, status + one live message

`core/network/CoachingWsClient.kt` runs a single owner loop per logical
connection:

- `connect()` is **idempotent** (a second call while running is a no-op), so
  recomposition and tab navigation can never open a duplicate socket.
- `runLoop()` opens one socket at a time and **parks at a
  `CompletableDeferred`** while the socket is healthy; the terminal outcome is
  completed by the callbacks from the transport's own threads.
- On an unexpected close/failure it reconnects with **capped exponential
  backoff** (`retryDelayMs`: 1s·2^n, cap 30 s) up to `maxReconnectAttempts`
  (5) consecutive failures, then sets `running = false` and reports
  `DISCONNECTED` — a later `connect()` (next foreground) starts a fresh budget.
  A deliberate `disconnect()` cancels the loop and never reconnects.
- A successful `onOpen`/live `onMessage` resets the failure counter, so a
  healthy socket that later drops gets a fresh retry window.
- Publish/status callbacks go to the client owner; only `LiveCoach` frames are
  published.

The WS-dedicated OkHttp client (in `AppModule`) disables read/write timeouts
(long-lived socket) and sends OkHttp `pingInterval(30s)` keep-alives.

### 3. Parsing: `coaching_trigger` ignored, `coaching_message` mapped, no crash

`CoachingWsMessageParser` models ONLY the stable envelope (`type` + `coach`),
so no second coaching schema is invented. It decodes each frame to a sealed
result:

- `LiveCoach(CoachResponse)` — a `coaching_message` whose `coach` passes the
  **same shape validation as `CoachFetcher`** (message non-blank,
  `recommendation` present).
- `Ignored` — a valid frame that is not publishable content: the raw M8.2
  `coaching_trigger`, an unknown/future type, or a `coaching_message` whose
  `coach` violates the shape.
- `Malformed` — the frame is not valid JSON at all.

Ignored and malformed frames are never published and never crash; the socket
stays alive for the next real frame. The trigger object is deliberately left
unmodeled (Gson ignores it) — the UI has nothing to do with it yet, and M8.4
may decide whether raw triggers get their own presentation.

### 4. Live state vs. pull cache: separate `LiveCoachStore`, never write into `CoachCache`

`core/network/LiveCoachStore.kt` holds the latest LIVE push as
`StateFlow<CoachResponse?>` (thread-safe publish from the socket threads,
process-lifetime like `CoachCache`). The live slot is **deliberately separate**
from `CoachCache`: the pull cache keys its "do I need to fetch again?" decision
on the set of synced run ids and owns the pull-request lifecycle. A pushed
response represents a *different* trigger/context than whatever the last pull
produced, so writing it into `CoachCache` would corrupt that bookkeeping
(a future `ensureLoaded()` would then be comparing against the wrong
signature). Instead, `HomeTab` prefers the live push while one is present:

    pullAiOutcome = CoachCache.state             // existing pull path, unchanged
    livePush      = LiveCoachStore.message       // null until a real push arrives
    aiCoachOutcome = livePush?.let { Success(it) } ?: pullAiOutcome
    aiIsLive = livePush != null                  // heading: "⚡ Live coaching"

The card otherwise renders identically — same `CoachResponse`, same
`CoachCard`. A push replaces the visible card until a newer push or process
death; `LiveCoachStore.clear()` exists for tests/ops only.

### 5. Lifecycle wiring: one connection per process, foreground-bound

`CoachingWsClient` is a Koin **singleton** on a process `AppScope`
(`SupervisorJob + Dispatchers.Default`). `MainActivity` calls
`coachingWsClient.connect()` in `onStart` and `disconnect()` in `onStop`. So:

- Home → Profile → Home navigation inside the activity never connects twice
  or drops the socket (activity is only started/stopped on real backgrounding).
- Going to the background closes the socket and cancels the loop; the next
  foreground reconnects (fresh budget). This is a conservative default — a
  background socket to a dev backend is not something the app should hold.
- A WebSocket never blocks the main thread: OkHttp callbacks arrive on OkHttp
  threads and the state changes go through the thread-safe `StateFlow`.

### 6. Failure containment (proven by tests and on-device)

Every failure path is contained: factory `connect` throws are treated as a
failed attempt (backoff applies); malformed frames are ignored; a give-up only
leaves `LiveCoachStore` empty, so the card falls back to the pull cache or the
existing Retry path. `CoachFetcher`, run sync/reconciliation and workout
tracking share no state with the client and are unaffected by its liveness.

## Files

Android (`apps/app/fitquest/src/main/java/com/example/mobileapp/`):

- `core/network/CoachingWsClient.kt` — new: client, status enum, sealed parse
  result, `CoachingSocket`/`Callbacks`/`Factory` seam, parser.
- `core/network/OkHttpCoachingSocketFactory.kt` — new: OkHttp bridge +
  `coachingWsUrl`.
- `core/network/LiveCoachStore.kt` — new: live push slot.
- `di/AppModule.kt` — new: `AppScope`, `LiveCoachStore` singleton,
  WS `CoachingWsClient` singleton (WS-dedicated OkHttp, ping 30 s).
- `MainActivity.kt` — `connect()` on `onStart`, `disconnect()` on `onStop`.
- `ui/home/HomeTab.kt` — prefer `LiveCoachStore.message` over pull; "⚡ Live
  coaching" heading while live.

Tests (`apps/app/fitquest/src/test/java/com/example/mobileapp/core/network/`):

- `CoachingWsClientTest.kt` — 16 tests: valid decode, existing-field mapping,
  `coaching_trigger`/unknown ignored, malformed never crashes, live-store
  update/replacement, garbage frames never published, duplicate `connect` keeps
  one socket, disconnect closes + stops delivery, reconnect after failed
  connect / after unexpected close, bounded capped backoff + fresh budget after
  give-up, pure `retryDelayMs` cap, WS-dead ⇒ `CoachFetcher` still works, and
  `coachingWsUrl` ws/wss derivation.
- `LiveCoachStoreTest.kt` — 5 tests: empty→latest, replace, clear, and the
  decoupling proof (a push neither overwrites `CoachCache.state` nor triggers a
  refetch).

## Test & build results (2026-09-06)

- Focused M8.3B tests: **21 passed**.
- `CoachFetcherTest` + `CoachCacheTest` regression: **passed**.
- Full Android unit suite (`:app:testDebugUnitTest`): **96 tests, 0 failures**.
- `:app:assembleDebug`: **BUILD SUCCESSFUL**.

## Real-device verification (PASS, 2026-09-06)

The debug APK was installed on the physical device (`RZ8R90661CF`), launched to
Home, and the device's WS client connected (`logcat CoachingWs`:
CONNECTING → CONNECTED, no crash). The end-to-end push was then exercised for
real:

1. A fresh run sync (new `run_id`, 1,500 steps, no hexes) was POSTed to the
   dev user. It committed credit (`already_processed: false`) and fired the
   M8.1 `workout_completed` trigger → M8.3A `PushCoach` → `coaching_message`.
2. The `coaching_message` arrived over the live socket, was decoded by
   `CoachingWsMessageParser` into the existing `CoachResponse`, published to
   `LiveCoachStore`, and the Home CoachCard recomposed to the live push:
   heading changed to **"⚡ Live coaching"** and the body was the freshly
   generated grounded message ("today's run left you at 35% of your step goal…
   aim for one short, comfortable activity each day that earns you a single
   hex…"), i.e. real per-run content, not the pull card that preceded it.
   Screenshot evidence: `docs/docs/ui/evidence-m83b/home_live_push.png`.

One infrastructure note: the backend process originally running on `:8000`
(PID 24672, started 18:40, `python -m uvicorn app.main:app`, no `--reload`)
predated M8.2 — its WS transport landed in commit `61a0e84` at 20:18 — and
returned Starlette's 403 for every WebSocket upgrade (host probes of both the
real and a bogus `/api/v1/ws/*` path 403'd, the signature of an unmatched
WebSocket route). The Android client behaved correctly under that dead socket
(bounded retries → quiet give-up, no crash, REST intact). For the E2E the
server was restarted onto current `main` from the app venv
(`apps/api/.venv/Scripts/python.exe -m uvicorn app.main:app`), after which the
WS route accepted connections and the push flow above succeeded.

## What remains (M8.4 and later)

- **M8.4 — Text-to-speech** of the coaching message (out of scope here; do not
  claim voice coaching yet).
- Decide the eventual UI for raw `coaching_trigger` frames (currently
  intentionally ignored) and whether a no-session pull GET should clear a
  stale live push.
- Production: real auth means the WS URL will carry the user's identity
  (`?user_id=` or a token) exactly as the REST channel will; the seam already
  isolates that change to `coachingWsUrl`/`AppModule`. Release builds use
  `wss://` via the same derivation (cleartext is debug-only).
