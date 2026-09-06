# ADR 0001: M8.1 — Coaching Trigger Engine (backend)

Status: implemented 2026-09-06. First slice of FitQuest SRS §15
"Real-Time AI Coaching". A small backend trigger engine that turns REAL
activity moments (run completion, territory capture, daily-step milestones)
into recorded, deduplicated coaching triggers that a later milestone
(M8.2, WebSocket) consumes. This task adds **no** LLM/RAG call, **no** change
to the existing pull-coach flow (`GET /api/v1/coach`), **no** WebSocket/SSE,
and **no** Redis.

## Context & Problem Statement

SRS §15 real-time coaching is trigger-based:

    real activity event -> trigger evaluation -> AI context ->
    recommendation/RAG -> LLM -> (M8.2+) WebSocket -> Android

Before any transport or LLM work, M8.1 must answer "which backend events can
honestly produce a trigger?" The SRS's six candidate triggers (§15.2) are a
shopping list, not a guarantee that the current code emits them. The task
mandated a focused audit first and to implement **only** from real event
sources — never inventing events that do not exist.

## Audit result — actual event sources found

Audited `apps/api/app/modules/{runs,map,quests,users,coach}` plus the Android
call surface (`FitQuestApi.kt` — the device only ever calls `runs/sync`,
`leaderboard`, `map/viewport`, `recommendations`, `coach`).

| Candidate trigger | Real server-side event source? | M8.1 outcome |
|---|---|---|
| `WORKOUT_COMPLETED` | **Yes** — `runs/service.py::process_run_sync` applies credit for a finished run, guarded by the `runsession` replay ledger | Implemented |
| `TERRITORY_CAPTURED` | **Yes** — inside that same transaction, `HexOwnership` owner changes to the user (fresh claim of empty land, or a steal from a rival) | Implemented |
| `ACTIVITY_MILESTONE` | **Yes** — `UserDailyActivity` rows (Phase 4B.5 telemetry) are upserted on sync with absolute day-to-date steps | Implemented |
| `WORKOUT_STARTED` | **No** — the backend has no start endpoint; runs only ever arrive already finished via `runs/sync` | Not implemented |
| `STREAK_MILESTONE` | **No** — streak columns exist on `User` but are device-computed; nothing writes them server-side | Not implemented |
| `QUEST_PROGRESS` | **No** — the `quests` module has no Android caller and no automatic event-driven progress (only manual PATCH) | Not implemented |

Conclusion: exactly **three** triggers have a real source, all downstream of
the single authoritative run-sync transaction. Everything else was
intentionally NOT built rather than fabricated.

## Decisions

### 1. New module `app/modules/triggers/` — domain + engine, no DB

`engine.py` defines:

- `TriggerType` — only `WORKOUT_COMPLETED`, `TERRITORY_CAPTURED`,
  `ACTIVITY_MILESTONE`. No enum entries for event types the backend does not
  produce.
- `CoachingTrigger` — pydantic model: `trigger_type`, `user_id`,
  `occurred_at` (aware UTC), `dedupe_key`, optional `event_id` (the
  originating run/session), lightweight `payload`. Always JSON-serializable.
- `TriggerDecision` — `ACCEPTED` / `DUPLICATE` / `COOLDOWN`.
- `TriggerEngine` — thread-safe in-process dedupe + cooldown gate with a
  bounded accepted-log and a `subscribe()` seam.
- Pure rules: `canonical_key(*parts)`, `highest_milestone_crossed(prev, cur)`,
  fixed ladder `ACTIVITY_MILESTONE_STEPS = (5_000, 10_000, 15_000, 20_000)`.

No table → no Alembic migration. Mirrors the `coach_cache` precedent:
single-instance dev backend, in-process on purpose, one narrow seam
(`TriggerEngine` / `subscribe()`) that a Redis-backed implementation or the
M8.2 WebSocket bridge attaches to without touching emitters.

### 2. Emission is inside `process_run_sync`, AFTER a successful commit only

`runs/service.py` now collects read-only outcome lists while it processes the
run (which hexes changed owner and how, and the pre-upsert day total) and, on
the **success path only** (never on `already_processed` replays, never on an
`IntegrityError` race), hands them to `_emit_run_triggers(...)`. Authoritative
XP / territory / lifetime math is untouched.

`WORKOUT_COMPLETED` — one per newly-applied run. Dedupe key = run scope.
Payload: `run_id`, `total_session_steps`, `xp_earned`,
`hexes_newly_captured/hexes_stolen/hexes_defended`, `new_total_lifetime_steps`.

`TERRITORY_CAPTURED` — one per hex whose **owner changed to the user**
(`kind: "captured"` for empty-land claim, `kind: "stolen"` for a rival steal).
Reinforcing a hex you already own is not a capture and emits nothing. Dedupe
key = run scope + hex. Payload: `hex_id`, `kind`, `defense_score_steps`,
`run_id`.

`ACTIVITY_MILESTONE` — at most one per sync: the **highest** fixed daily-step
threshold this sync crossed (a 4,999 → 12,000 day yields one 10,000 trigger,
not three — one nudge per day). Dedupe key = activity date + threshold.
Payload: `activity_date`, `daily_steps`, `milestone_steps`.

### 3. Deduplication & cooldown design

- **Deterministic dedupe** (`TriggerEngine`, `OrderedDict` LRU, capacity
  100 000): the same `dedupe_key` is accepted once and reported `DUPLICATE`
  afterwards. Keys are built from stable parts (`canonical_key`), so a
  retried sync cannot double-emit.
- **Layered, persistent idempotency:** the strongest guard is upstream — the
  `runsession` ledger makes a replayed `run_id` return `already_processed`
  before any emission. The engine's dedupe log is the second layer (and
  matters for the rare legacy sync that carries no `run_id`, whose scope is a
  content hash so identical retries collapse).
- **Per-(user, type) cooldown** (`DEFAULT_COOLDOWN_SECONDS`):
  - `WORKOUT_COMPLETED`: 10 s — real runs are minutes long, so a 10 s window
    never drops a genuine completion; it only flattens a pathological burst
    of legacy no-`run_id` syncs whose dedupe is content-derived.
  - `TERRITORY_CAPTURED` / `ACTIVITY_MILESTONE`: 0 s — each distinct capture
    and each threshold crossing is its own meaningful moment; they are
    deduplicated exactly (run+hex / date+threshold) instead of rate-gated.
- `COOLDOWN` is transient (records nothing, so the moment stays retryable);
  `DUPLICATE` persists until LRU eviction. Milestone dedupe also survives
  process restarts because the persisted `UserDailyActivity` row is the
  memory: a fresh run re-reporting the same day total never re-crosses.

### 4. Strictly advisory — can never fail a committed run sync

Trigger emission runs after the commit; the whole block is wrapped and the
engine's subscriber seam swallows subscriber errors, so a bug or a raising
consumer can never turn an already-committed run sync into an error response.

### 5. The M8.2 seam

`TriggerEngine.subscribe(callable)` is invoked (outside the lock) for every
`ACCEPTED` trigger. M8.2 connects WebSocket by subscribing a broadcaster that
serializes `CoachingTrigger` (`model_dump(mode="json")`) to a session
manager — emitters stay untouched. Android then renders triggers that arrive
over that socket; today the app already has the pull-coach card, which this
work leaves exactly as-is.

## What was intentionally NOT implemented

- `WORKOUT_STARTED`, `STREAK_MILESTONE`, `QUEST_PROGRESS` — no real
  server-side event source exists (audit table above). Building them would
  fabricate events.
- No LLM/RAG call, no change to `GET /api/v1/coach`, no WebSocket/SSE, no
  Android handling, no TTS, no Redis — all later/optional per SRS §15/§16/§17.
- No DB table or migration — the engine is in-process state like `coach_cache`.
- No trigger on GPS/step ticks — the only input is an explicit event from
  code that just committed business credit.

## Files changed

- `app/modules/triggers/__init__.py` *(new)* — public re-exports.
- `app/modules/triggers/engine.py` *(new)* — domain types + `TriggerEngine` +
  pure rules + module singleton `trigger_engine`.
- `app/modules/runs/service.py` — read-only outcome collection in
  `process_run_sync`, post-commit `_emit_run_triggers(...)`, legacy content
  scope helper. Business math unchanged.
- `tests/test_triggers.py` *(new)* — 28 tests (pure engine + `process_run_sync`
  integration).
- `tests/conftest.py` — clears `trigger_engine` with the DB in the `client`
  fixture (same pattern as `coach_cache`).

## Tests

`tests/test_triggers.py`: unit tests for every implemented trigger type,
duplicate/dedupe tests, cooldown tests, milestone boundary table, no-trigger
for irrelevant events (defense-only run; sub-milestone day), repeated
processing of the same event → no duplicate triggers, replay → nothing,
legacy content-scope dedupe, subscriber seam, raising-subscriber safety,
unseeded-user emits nothing.

Run: `pytest tests/test_triggers.py`. Full backend suite:
`pytest tests/` → **238 passed** (includes these 28).

## Limitations

- Engine dedupe/cooldown state is in-process: a process restart clears the
  dedupe log (run idempotency survives via `runsession`, milestone
  idempotency via the daily row — the two weaker cases, legacy bursts and
  hex recaptures, are the only ones that could re-emit after a restart).
- One workflow runs inside a single run sync; a future run-start or quest
  event source can be added by emitting from the new business code — no
  engine change needed.
- Milestone ladder is fixed (mirrors the app's default 10 000 goal);
  per-user goals are a later enhancement.
- No transport yet: triggers are recorded and inspectable
  (`trigger_engine.accepted()`) until M8.2 wires the WebSocket broadcaster.

## Next step (M8.2)

WebSocket transport: subscribe a session manager to `trigger_engine`, then a
push-coach pipeline (trigger → FitnessContext → recommendation/RAG → LLM →
socket) — evaluated against the pull-coach endpoint so nothing regresses.
