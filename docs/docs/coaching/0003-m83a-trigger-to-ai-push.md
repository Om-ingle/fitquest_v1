# ADR 0003: M8.3A — Trigger → AI Coaching → WebSocket Push (backend)

Status: implemented 2026-09-06. Third slice of FitQuest SRS §15/§16
"Real-Time AI Coaching". Completes the backend of the real-time pipeline that
M8.1 and M8.2 scaffolded — a real trigger now produces a grounded AI coaching
message and pushes it to the connected user over the existing M8.2 transport:

    TriggerEngine (M8.1, unchanged)
        |  subscribe(...)            [PushCoach, one more subscriber]
        v
    PushCoach                        (this slice)
        |  coalesce + per-user cooldown, then reuse the EXISTING AI stack
        v
    generate_coaching (recommend + RAG + LLM, unchanged) -> CoachResponse
        |  only when the user has a live WebSocket session
        v
    CoachingSessionManager (M8.2, unchanged)  ->  {"type":"coaching_message", ...}

This task adds **no** TTS, **no** Android handling, **no** Redis, **no**
authentication, **no** second recommendation/RAG/LLM implementation, and
**no** replacement of `GET /api/v1/coach`. M8.1 trigger rules and M8.2
transport semantics were NOT changed (the transport gained one additive
method). The producer (run sync) NEVER waits for the LLM. Tests mock/fake the
AI boundary; no test makes a real API call.

Android integration and TTS remain out of scope (M8.3B / M8.4 in the project
tracking) — "real-time AI coaching" is **not** claimed complete for the whole
product.

## Context & Problem Statement

M8.1 ends with real, deduplicated, cooldown-gated `CoachingTrigger`s;
M8.2 delivers them live to a user's socket as raw `coaching_trigger`
envelopes. What a device actually wants is the *coaching content* — a short,
grounded message that explains the moment. The spec for this slice:

- A trigger after a committed run must fire-and-forget: **the producer must
  not block on the LLM**, and no AI failure may roll back the run, change
  XP/territory, break trigger processing, or break other WebSocket sessions.
- AI generation is paid per call, so bursts need **cost/burst control**
  (in-process; Redis explicitly out of scope).
- **Fresh context**: build `FitnessContext` from current DB state at
  generation time, never from a snapshot captured when the trigger fired.
- The generated text must know **why** it fired (a run vs. a capture vs. a
  milestone) without duplicating the prompt system.
- **No-session ⇒ no paid generation**: don't spend an LLM call for a user
  nobody is connected to receive.
- Reuse the existing `CoachCache`/fingerprint rather than creating a second
  cache.

The engineering constraints are: the engine invokes subscribers synchronously
on the emitter thread (a FastAPI threadpool thread); generation is
comparatively slow and must not happen there; and the transport is asyncio on
the event loop, so a producer-side push can only enqueue, never send.

## Decisions

### 1. `PushCoach` — a third engine subscriber, import-wired like the transport

`app/modules/coach/push.py` defines `PushCoach` (module singleton
`push_coach`). It is registered as a trigger-engine subscriber once, at
import, in `app/api/router.py` (importing the module is the wiring), exactly
mirroring how M8.2's WebSocket manager subscribes. The engine remains the
sole producer.

`handle_trigger(trigger)` runs on the emitter thread and does only O(1) work
under a short per-user lock, then hands off via `self.schedule(...)` (a
bounded `ThreadPoolExecutor`, `push_coach_max_workers`). It can never call
the LLM, so a committed run is never delayed by AI. All seams (`schedule`,
`now`, the DB session factory, the embedding/LLM provider factories, the WS
manager, the cache) are injectable instance attributes, which is what makes
the tests deterministic without threads or API keys.

### 2. Coalescing / cooldown policy (in-process, per user)

A run that also captures hexes and crosses a milestone fires three triggers
back-to-back. Paying once per trigger would triple the LLM bill for three
near-duplicate nags. Per user, `PushCoach` keeps one small state
(`armed`, a `reasons` set of folded trigger types, a `cooldown_until`):

- **Armed (a generation is scheduled or running)** → later triggers in the
  same instant **fold** their trigger types into the armed generation (the
  prompt then reflects every folded reason) and return. One push per burst.
- **Nothing armed but inside the cooldown window** (settings
  `push_coach_cooldown_seconds`, default 30 s, from arm-time) → the trigger
  is **suppressed**.
- **Nothing armed and outside cooldown** → a new generation starts.

The cooldown is finite by construction, so it can never suppress genuinely
changed coaching context indefinitely; a real later event (after ~30 s) still
generates. When a job runs it snapshots the folded reasons under the lock at
job start, so a burst is deterministic regardless of scheduling.

### 3. No-session ⇒ no paid generation

Before arming, `handle_trigger` checks the M8.2 manager's new
`has_live_sessions(user_id)`. With no live session the trigger is skipped
entirely — no job is scheduled, no LLM call is paid for. Because the raw M8.2
transport still fans the trigger out (unchanged), a disconnected user loses
only the AI coaching message, exactly as before this slice existed. If the
user disconnects after a job is scheduled but before it runs, the job
re-checks `has_live_sessions` and gives up.

### 4. Fresh context at generation time; reason-aware, fingerprint-consistent

`PushCoach._run` builds a **fresh** `FitnessContext` via
`build_fitness_context(db, user_id)` when the job executes — never a stale
context captured when the trigger fired. The trigger only informs *why*; the
AI grounds in what the server knows *now*.

Why the response exists (the folded trigger types) is threaded into the
existing grounded prompt in the smallest clean way: `generate_coaching` and
`build_coaching_prompt` gained an optional `event_context` string rendered as
one context line — `"- Why this message is being generated: …"`. The pull
path (`GET /api/v1/coach`) omits it, so its prompt is byte-identical and its
behavior is unchanged. It never loosens grounding/safety rules. The prompt
maps each real type to a factual phrase (`completed a run` / `captured new
territory` / `reached a daily step milestone`), so the model distinguishes the
triggers without inventing specifics.

### 5. Cache decision: reuse `CoachCache` under a SEPARATE reason-aware push key

The existing `CoachCache` remains the single response store, but push
generations are keyed by a composite **push key**
(`push_generation_key(user_id, context_fingerprint, folded_reasons)`), never
by the plain `FitnessContext` fingerprint that `GET /coach` uses.

Why not reuse the plain fingerprint for push? A push is worth generating even
when the fitness context is unchanged but the trigger *reason* differs (a
territory capture minutes after a pull on the same context). Conversely a
push should not be suppressed because the pull cache already holds the same
context. The `push:` prefix guarantees a push key can never equal a raw
fingerprint, so push and pull entries coexist in the same `CoachCache`
without interfering, and only one cache exists to maintain. The push stage
calls `generate_coaching(..., cache=None)` so it neither reads nor writes the
pull fingerprint entries; it then stores the validated response under its own
push key in the same cache. Dedupe rule: identical `(fingerprint, reasons)`
⇒ serve the stored push; changed context **or** changed reason ⇒ fresh
generation. A version tag (`m83a-push-v1`) inside the key invalidates old
push entries on the next deploy, mirroring the fingerprint's versioning.

### 6. Wire message: one new stable envelope over real models, via M8.2

Delivered by the new additive `CoachingSessionManager.send_to_user(user_id,
envelope)` (the same fan-out, per-session bounded queue and failure
containment as raw triggers; the raw M8.2 `coaching_trigger` envelope stays
valid and is sent first):

    {"type": "coaching_message",
     "trigger": <the CoachingTrigger that armed this push, model_dump(json)>,
     "coach":   <CoachResponse, model_dump(json)>}

Both halves are the real Pydantic JSON forms — no invented fields. `coach`
carries the existing `CoachResponse` (`generated_at`, `message`, `grounded`,
`context`, `recommendation`, `retrieval`, `context_fingerprint`), so a client
already understands it from the pull API.

### 7. Background generation + strict failure containment

The heavy path runs off the emitter thread, on the shared executor. A DB
session is opened per job. Any failure — DB/context construction, embedding
or RAG retrieval, LLM timeout/error, validation, or WebSocket delivery — is
caught, logged with the user id, and swallowed. Consequences:

- a failed generation delivers **no** `coaching_message` (never a fabricated
  message);
- the run that emitted the trigger is untouched (it committed long before);
- other users and other live WebSocket sessions are unaffected;
- the user's push state is un-armed in a `finally`, so the next real trigger
  after cooldown can generate again (a transient LLM failure does not wedge
  the user).

### 8. Configuration

Three settings bound the stage: `push_coach_enabled` (default True),
`push_coach_cooldown_seconds` (30.0), `push_coach_max_workers` (2). Tests set
`PUSH_COACH_ENABLED=false` in `conftest.py` so no existing test ever trips a
background generation by accident; M8.3A tests re-enable it with fakes.

## Files changed

- `app/modules/coach/push.py` *(new)* — `PushCoach`, the event-phrase mapper,
  the composite push key, the `coaching_message` serializer, the module
  singleton and its single import-time `trigger_engine.subscribe(...)`.
- `app/api/router.py` — imports the push module so the subscription happens
  on app import (mirrors the M8.2 transport wiring).
- `app/modules/triggers/ws.py` — additive: `has_live_sessions(user_id)`
  (gate for paid generation) and `send_to_user(user_id, envelope)` (M8.3A
  delivery over the existing fan-out). M8.2 `coaching_trigger` semantics are
  unchanged.
- `app/modules/coach/service.py` + `coach/prompt.py` — optional
  `event_context` threaded from `generate_coaching` into the prompt; omitted
  by the pull path, so `GET /coach` prompts are unchanged.
- `app/core/config.py` — `push_coach_*` settings.
- `tests/conftest.py` — disables/resets `push_coach` alongside the other
  process-global singletons; `PUSH_COACH_ENABLED=false` default.
- `tests/test_push.py` *(new)* — 15 focused tests, below.
- `docs/docs/coaching/0003-m83a-trigger-to-ai-push.md` *(this ADR)*.

## Testing strategy

`tests/test_push.py` drives `PushCoach` directly with a fake transport (a
"live users" set + delivery recorder), a fake embedding provider, a
prompt-recording (or failing) LLM, a `JobRecorder` `schedule`, and an
injectable monotonic clock — so coalescing/cooldown/dedupe are deterministic
and LLM invocation counts are asserted exactly. The final test runs the REAL
engine path (`process_run_sync` → module `trigger_engine`) into TWO real M8.2
WebSocket sessions over the TestClient and asserts each receives the raw
`coaching_trigger` then the AI `coaching_message`. Zero API calls anywhere.

Focused coverage (15 tests): each real trigger type produces a
`coaching_message` with a reason-aware prompt; the producer returns
immediately and never calls the LLM synchronously; no live session ⇒ no job
is even scheduled; a three-trigger burst coalesces to one generation whose
prompt names all three reasons; a post-push cooldown suppresses an immediate
retry; identical (context, reason) after cooldown is deduped by the push key
(no second LLM call); changed context regenerates fresh; a different reason
on the SAME context regenerates (reason-aware); two users' armed/cooldown
state is isolated; an LLM failure is contained, delivers no fake message and
does not wedge the next trigger; a broken WS delivery never breaks the
generation or later pushes; the pull path's prompt carries no event context;
plus unit checks of the phrase mapper and the composite key.

Run: `pytest tests/test_push.py` → **15 passed**.
Run: `pytest tests/` → **262 passed** (247 pre-existing — including the 28
M8.1 trigger tests and the 9 M8.2 WebSocket tests, all unmodified and green —
plus the 15 above).

## Limitations / honest boundaries

- **Best-effort, in-process, single-instance.** No durable outbox and no
  shared bus: a push generated while the user has no live session is simply
  not generated (deliberate — no paid work for nobody), and multi-instance
  deployments would need the Redis the task keeps out of scope.
- **Coalescing can drop an in-flight push.** Triggers that arrive inside the
  armed window or the cooldown window fold or are suppressed. This is the
  intended cost/burst control: coaching is advisory, and the cooldown is
  finite so a genuinely new moment minutes later still fires.
- **Generation is fire-and-forget from the producer's perspective**, so a
  push can arrive a few seconds after the trigger that caused it; ordering
  relative to a later push is not strictly guaranteed.
- **Identity and security posture are unchanged** (dev-user mechanism; real
  auth is a separate, explicitly-deferred concern). Android rendering of
  `coaching_message` and TTS are **not** implemented here (M8.3B/M8.4).

## Next step (M8.3B)

Android consumes `coaching_message`: parse the new envelope type on the
device's coaching WebSocket client, render the coach `message` (reusing the
same CoachResponse UI as the pull flow), and handle the TTS presentation of
push coaching (device TTS is out of scope here by task). Keep the backend
slice closed: the transport, cache and push policy from this ADR are the
contract a device now integrates against.
