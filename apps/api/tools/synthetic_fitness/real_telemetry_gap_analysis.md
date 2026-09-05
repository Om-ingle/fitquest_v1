# Phase 4B.5 — Real-User Telemetry Gap Analysis & Minimum Schema Design

> This document maps every Phase 4B.2 model feature (and the Phase 4B.3
> target) to what the repository actually stores **today**, then specifies the
> minimum production change needed so real users' historical behavioral data
> can eventually flow through the same feature/target pipeline that Phases
> 4B.1–4B.4 validated on synthetic data. It was written **before** any code
> changes in this phase. No real user data exists yet and nothing here claims
> otherwise.

---

## 1. What the repository stores today (verified by inspection)

### Backend (`apps/api`) — aggregate / current-state only

| Table | Columns | Telemetry value |
| --- | --- | --- |
| `user` | `total_lifetime_steps`, `current_streak`, `longest_streak`, `last_activity_date` | Lifetime **aggregates**. `current_streak`/`last_activity_date` are **never written by run-sync** (`app/modules/runs/service.py` only touches `total_lifetime_steps`) — they are stale snapshots. No daily history. |
| `hexownership` | `hex_id` (PK), `king_id`, `defense_score_steps`, `captured_at`, `times_stolen` | **Mutable current-owner state.** `defense_score_steps` accumulates for the hex's lifetime (never per day); `captured_at` is *reset* on every steal, so capture history is destroyed when a hex changes hands. No per-user, per-day territory history. |
| `runsession` | `id`, `user_id`, `started_at` | **Never written by the API at all** — `process_run_sync` does not insert RunSession rows. Even if it did, there are no steps/minutes columns. |
| `capturedhex` | `id`, `run_id`, `hex_id` | Never written either; and no user/date attribution of its own. |
| `quest` / `userquest` | Quest catalog + per-user progress | No per-user daily step goal exists server-side (Quest is a shared catalog keyed by `active_date`, not a user goal). |

The run-sync request itself (`RunSyncPayload`) carries only
`total_session_steps` + `hexes_to_steps` — **no activity date, no active
minutes, no goal, no session id**. The response (`RunSyncSummary`) has
per-sync capture/steal/defense counts, but nothing persists them per day.

### Android (`apps/app/fitquest`) — the only place daily facts exist, device-local

| Room table / component | Facts | Survives restart / device replacement |
| --- | --- | --- |
| `run_sessions` (`RunSessionEntity`) | per run: `startedAt`, `endedAt`, `durationSeconds`, `totalSteps`, `distanceMeters`, `caloriesBurned`, `capturedHexCount`, `xpEarned`, `isSynced` | survives restart; **lost on uninstall/device replacement** (LOCAL_ONLY) |
| `user_profile` (`UserProfileEntity`) | `dailyStepGoal` (chosen at onboarding, default 6000), `currentStreak`, `lastActiveDate`, lifetime totals | LOCAL_ONLY, mutable current-state |
| `captured_hexes` (`CapturedHexEntity`) | local mirror of owned hexes (`hexId`, `totalSteps`, `lastUpdated`) | LOCAL_ONLY, drifts from server truth |
| `daily_quests` (`DailyQuestEntity`) | quests keyed by `dateString` | LOCAL_ONLY |
| `StepSensorManager` | hardware step counter **during run tracking only** — there is no all-day background step counting | in-memory only |

Key Android facts established by reading `CaptureScreenModel`,
`RunSessionRepository`, `UserProfileRepository`, and `HomeTab`:

- "Steps today" on the device = **sum of run-session `totalSteps` for the
  device-local calendar date** (`HomeTab.kt:118-122`). No background
  all-day pedometer exists.
- "Active minutes" for a day = **sum of run `durationSeconds` / 60** — never
  computed or stored as such anywhere, but derivable from `run_sessions`.
- Streaks are maintained client-side with a 20–48 h "consecutive day" window
  (`UserProfileRepository.isConsecutiveDay`) — device-local semantics, not
  the server's.
- Run sync happens **once, at run end** (`CaptureScreenModel.onToggleTracking`);
  there is no retry, and unsynced runs stay in Room forever.
- Hexes *lost* to rivals are **not observable by the victim's device** — the
  app only learns about rival ownership opportunistically via map-viewport
  fetches. Nobody (client or server) records a loss event.

---

## 2. Feature-by-feature classification (all 21 features + the target)

Legend:

- **READY** — server-persisted historical data exists today.
- **DERIVABLE** — computable from raw daily telemetry once the new snapshot
  table (§3) fills; nothing else needed.
- **PARTIAL** — the raw signal can be *stored* by the new schema, but the
  device cannot observe it reliably yet, so it arrives as `null` initially.
- **LOCAL_ONLY** — exists only on-device today; server has nothing.
- **AGGREGATE_ONLY** — server has only a lifetime/current-state aggregate; no
  per-day history and history cannot be reconstructed.

| # | Feature (from `features.MODEL_FEATURES`) | Raw signal(s) needed | Status **today** | Status **after 4B.5** |
| --- | --- | --- | --- | --- |
| 1 | `steps_today` | daily steps | **LOCAL_ONLY** (Room `run_sessions` summed per date) | **DERIVABLE** (`userdailyactivity.steps`) |
| 2 | `active_minutes_today` | daily active minutes | **LOCAL_ONLY** (Σ `durationSeconds`/60; never materialized anywhere) | **DERIVABLE** (`active_minutes`) |
| 3 | `steps_3d_avg` | steps history | LOCAL_ONLY (no server history at all) | **DERIVABLE** |
| 4 | `steps_7d_avg` | steps history | LOCAL_ONLY | **DERIVABLE** |
| 5 | `active_minutes_3d_avg` | minutes history | LOCAL_ONLY | **DERIVABLE** |
| 6 | `active_minutes_7d_avg` | minutes history | LOCAL_ONLY | **DERIVABLE** |
| 7 | `activity_days_7d` | steps history | LOCAL_ONLY | **DERIVABLE** |
| 8 | `steps_change_vs_7d_avg` | steps history | LOCAL_ONLY | **DERIVABLE** |
| 9 | `current_streak` | steps history (recomputable) | **LOCAL_ONLY** (device `UserProfileEntity.currentStreak`, 20–48 h semantics; server `User.current_streak` never updated by run-sync) | **DERIVABLE** (recomputed from steps history at export — matches the generator's ≥1,000-step definition) |
| 10 | `goal_completion_rate_7d` | goal + steps history | **LOCAL_ONLY** (`dailyStepGoal` lives only in `user_profile`) | **DERIVABLE** (`goal_steps`, `goal_completed` snapshots) |
| 11 | `days_since_active` | steps history | LOCAL_ONLY | **DERIVABLE** |
| 12 | `hexes_owned` | end-of-day owned count | **AGGREGATE_ONLY** (server `hexownership` current state; count computable now, history not) | **DERIVABLE** (daily snapshot from the device's mirror) |
| 13 | `captures_7d` | daily captures | **AGGREGATE_ONLY** (`hexownership.captured_at` is reset on steal → capture history is destroyed when a hex is taken back) | **DERIVABLE** going forward (`hexes_captured` snapshot) |
| 14 | `losses_7d` | daily losses | **MISSING** (no event log anywhere; the victim's device cannot observe steals) | **PARTIAL** — column exists; device sends `null` in v1 (see §6) |
| 15 | `territory_change_7d` | `hexes_owned` history | AGGREGATE_ONLY | **DERIVABLE** |
| 16 | `defense_steps_7d` | daily defense steps | **AGGREGATE_ONLY** (`hexownership.defense_score_steps` accumulates over the hex's lifetime, not per day) | **PARTIAL** — column exists; device sends `null` in v1 (see §6) |
| 17 | `defense_ratio_7d` | defense + steps history | AGGREGATE_ONLY | **PARTIAL** (follows #16) |
| 18 | `goal_steps` | the user's daily goal | **LOCAL_ONLY** (onboarding-selected, `user_profile.dailyStepGoal`; no server concept of a per-user goal) | **DERIVABLE** (snapshotted per day, so goal *changes* are also recorded) |
| 19 | `goal_completed_today` | steps + goal | LOCAL_ONLY | **DERIVABLE** |
| 20 | `active_today` | steps | LOCAL_ONLY | **DERIVABLE** |
| 21 | `goal_progress_ratio` | steps + goal | LOCAL_ONLY | **DERIVABLE** |
| — | **Target `inactive_next_3d`** | future days' steps | LOCAL_ONLY | **DERIVABLE** once ≥3 days of forward history accumulate (labels for day D need days D+1..D+3) |

**Summary:** 18 of 21 features + the target become DERIVABLE purely from the
new daily snapshot; 2 (`losses_7d`, `defense_steps_7d`) + 1 dependent
(`defense_ratio_7d`) are PARTIAL — storable but not yet observable by the
client (§6 explains why and what the honest options are). **Nothing is READY
today** — the backend records no daily history whatsoever.

---

## 3. Minimum telemetry schema (design)

### 3.1 Chosen direction: a daily activity **snapshot** table

The phase brief's preferred direction — *a daily user activity snapshot table
preserving historical per-user observations, rather than reconstructing
history from mutable aggregates* — is also what the inspection demands:

- Reconstructing from `hexownership`/`user` is **impossible**: `captured_at`
  is reset on steal (capture history destroyed), `defense_score_steps` is a
  lifetime accumulator, `total_lifetime_steps` is a single counter, and
  streak fields are never updated.
- Reconstructing from `runsession` is **impossible**: the API never writes
  those rows, and they lack steps/minutes anyway.
- The only source of steps/minutes/goal facts is the **device**, so the
  device must upload them.

### 3.2 Table: `userdailyactivity`

New SQLModel table in the **runs module** (telemetry rides the existing
run-sync path, so it belongs beside it):

```text
userdailyactivity
  user_id        UUID    PK  (FK -> user.id)
  activity_date  DATE    PK
  steps              INTEGER  NOT NULL  -- device-observed steps that local day
  active_minutes     INTEGER  NOT NULL  -- Σ run durations / 60 that day
  goal_steps         INTEGER  NULL      -- daily goal as of that day
  goal_completed     BOOLEAN  NULL      -- steps >= goal_steps that day
  hexes_owned        INTEGER  NULL      -- device-mirror owned count, end of day
  hexes_captured     INTEGER  NULL      -- hexes captured that day (device view)
  hexes_lost         INTEGER  NULL      -- hexes lost that day (unknown in v1)
  defense_steps      INTEGER  NULL      -- steps reinforcing owned hexes that day (unknown in v1)
  updated_at         DATETIME NOT NULL  -- server clock, last upsert
  PRIMARY KEY (user_id, activity_date)
  INDEX (activity_date)                 -- export queries by date range
```

Design properties, each mapping to a phase requirement:

- **Raw, not ML features.** Columns are the same *raw* daily signals the
  synthetic generator emits (`generator.COLUMNS` minus `streak`/`data_source`
  plus provenance handled at export). No rolling averages, no model features
  are stored — features.py stays the single feature definition.
- **Immutable facts, safely upsertable.** The natural key is
  `(user_id, activity_date)`. Repeated syncs **upsert**, they never append or
  duplicate. The row is a snapshot of the day **as last reported by the
  device** — a *late correction* (a re-sync with corrected values) simply
  overwrites, which is deterministic last-write-wins per field.
- **Idempotent.** The device sends **absolute day-to-date values** (never
  deltas), so sending the same snapshot twice yields the identical row.
  Merge rule: a field that is `null` in the incoming snapshot **keeps the
  stored value**; a non-null field **replaces** it. This makes partial
  updates safe and keeps the common case (full snapshot) trivially
  idempotent.
- **Why absolutes, not server-side accumulation:** the server *could* derive
  captures/steals/defenses per sync, but accumulating them per day breaks
  idempotency (a retried sync would double-count) and the existing endpoint
  already has no session-dedup. Client-absolute snapshots keep the write
  path idempotent by construction. The competitive game state (XP, ownership,
  leaderboard) remains 100 % server-authoritative in the existing tables —
  this table is *observational telemetry for ML*, and never feeds game logic.
- **No cross-user leakage.** `user_id` comes **only** from the authenticated
  user (dev stub today), never from the payload; the composite PK makes
  cross-user rows structurally impossible to address from one user's sync.
- **No duplication of immutable data.** Run-session rows (steps per run)
  stay in Room on the device; the server gets the daily aggregate only. The
  never-written `runsession`/`capturedhex` server tables are left untouched.
- **Timezone:** `activity_date` is the **device's local calendar date** (the
  same date the device uses for streaks and HomeTab), sent explicitly by the
  client — not derived from server UTC, which would split days wrongly.

### 3.3 API: extend the existing run-sync request (no new endpoint)

`RunSyncPayload` gains one optional field:

```json
{
  "total_session_steps": 350,
  "hexes_to_steps": {"8a2a1072b59ffff": 300},
  "daily_activity": {
    "activity_date": "2026-09-05",
    "steps": 4210,
    "active_minutes": 38,
    "goal_steps": 6000,
    "goal_completed": false,
    "hexes_owned": 12,
    "hexes_captured": 2,
    "hexes_lost": null,
    "defense_steps": null
  }
}
```

- **Optional & backward-compatible** — old payloads (and all existing tests)
  behave exactly as before; `daily_activity: null` writes nothing.
- **One network path** — the device already syncs at run end; telemetry rides
  the same request, same failure mapping, no new scheduling/retry logic.
- Validation (Pydantic → 422): `activity_date` a real ISO date **at most one
  day ahead of UTC-today** (a device at UTC+14 near midnight is legitimately
  one local day ahead; anything further is future-dated and rejected); `steps`/`active_minutes` required, `0 ≤ steps ≤ 1_000_000`,
  `0 ≤ active_minutes ≤ 1440`; all optional ints `≥ 0` and sane-bounded
  (`≤ 100_000` for counts, `≤ 1_000_000` for defense steps).
- The upsert runs in the **same transaction** as the game-state update, after
  the turf-war loop, before the single `db.commit()`.
- If the `user` row does not exist (only possible in unseeded environments),
  telemetry is skipped — mirroring the existing leniency where
  `total_lifetime_steps` is also skipped; PostgreSQL FKs guarantee this never
  happens in a seeded environment (`seed.py` creates the dev user).
- **No read endpoint** is added: collection only. Export for ML happens
  offline/directly from the DB in a later phase; nothing privileged is
  exposed to the app. No Supabase secrets ever reach Android (unchanged).

### 3.4 Migration: `0002_user_daily_activity.py`

Additive Alembic migration (style follows `0001_initial_schema.py`):
`create_table("userdailyactivity", …)` with the composite PK, the FK to
`user.id`, and `ix_userdailyactivity_activity_date`. **No existing table is
touched; nothing is dropped; downgrade drops only the new table/index.**

### 3.5 Data flow (end to end)

```text
 run ends (device-local date D)
   │  CaptureScreenModel saves RunSessionEntity to Room first (offline-safe, unchanged)
   │  then computes the day-D snapshot from Room:
   │    steps          = Σ totalSteps of run_sessions with startedAt on D
   │    active_minutes = round(Σ durationSeconds / 60) for the same rows
   │    goal_steps     = user_profile.dailyStepGoal   goal_completed = steps ≥ goal
   │    hexes_owned    = captured_hexes count (device mirror)
   │    hexes_captured = Σ capturedHexCount of D's runs
   │    hexes_lost / defense_steps = null (not observable — §6)
   ▼
 POST /api/v1/runs/sync  (existing endpoint, payload + optional daily_activity)
   │  FastAPI validates (422 on bad dates / negative / impossible values)
   │  service: game-state mutations (unchanged) → upsert_daily_activity()
   │  single db.commit()
   ▼
 Supabase PostgreSQL  userdailyactivity  (one row per user per day, upserted)
   ▼
 later ML export (NOT this phase): rows → densify gaps → features.build_features
   with data_source="real" → same Phase 4B.2/4B.3/4B.4 pipeline
```

### 3.6 ML compatibility (verified, not rewritten)

`features._normalize_row` requires exactly `generator.COLUMNS`:
`synthetic_user_id, day, steps, active_minutes, hexes_owned, hexes_captured,
hexes_lost, defense_steps, streak, goal_steps, goal_completed, data_source`.
The new table supplies every column **except `streak`** (deliberately not
stored — it is fully derivable from the steps history, and storing it would
duplicate state) and `data_source` (an export-time label, `"real"`). A small
pure-Python adapter (`tools/synthetic_fitness/real_telemetry_compat.py`,
this phase) converts telemetry rows to that shape:

- `streak` recomputed as consecutive days with `steps ≥ 1000` ending on D
  (the generator's own `STREAK_MIN_STEPS` definition);
- `goal_completed` derived (`steps ≥ goal_steps`) when the device omitted it;
- **gap days densified to zero-step rows** (a day with no run produces no
  sync, hence no row — but rolling windows in `features.py` are index-based,
  so missing days *must* be filled, goal carried forward) — this also makes
  genuinely inactive days first-class rows, which the
  `inactive_next_3d` target needs;
- `hexes_lost`/`defense_steps` nulls → `0` with the caveat that they mean
  "unknown", not "none" (documented; the features remain computable).

`features.py` itself is **not modified** — the adapter feeds it unchanged,
proving the real-telemetry path is schema-compatible with the validated
pipeline.

---

## 4. What remains unavailable after this phase, and why

| Signal | Why unavailable | Honest options (future phases) |
| --- | --- | --- |
| `hexes_lost` (daily) | No steal event exists anywhere. The server knows a steal happened *for the thief's sync*; the victim is never notified, and `hexownership` keeps no history. | Server-side territory event log, or daily server snapshot of `hexownership` counts (a later, server-authoritative enrichment). |
| `defense_steps` (daily) | `defense_score_steps` is a lifetime accumulator per hex. Per-day defense is known only inside a single run-sync call (steps applied to hexes the user already owned) and accumulating it per day would break the idempotent-by-construction design. | Server-side per-sync attribution in a later phase, keyed by a session id with dedup. |
| All-day background steps / minutes | The app counts steps only during tracked runs (hardware step sensor, no background pedometer). "Steps today" = run sessions only. | A foreground-service step counter — an Android architecture change, explicitly out of scope. |
| Days the app was never opened | No sync happens on a fully idle day, so no row is written by the device. | Densification at export (§3.6) reconstructs these as zero-activity days. |
| Pre-4B.5 history | Nothing daily was ever persisted server-side; device Room history predating this change can be backfilled later (the upsert accepts any past date), but v1 sends only the current run's day. | Optional multi-day backfill payload in a later phase. |

---

## 5. What this phase implements (summary)

1. `app/modules/runs/models.py` — new `UserDailyActivity` table model.
2. `app/modules/runs/schemas.py` — `DailyActivitySnapshot` (validated) +
   optional `daily_activity` on `RunSyncPayload`.
3. `app/modules/runs/service.py` — `upsert_daily_activity()` (merge upsert,
   same transaction), called from `process_run_sync`.
4. `alembic/versions/0002_user_daily_activity.py` — additive migration.
5. `apps/api/tests/test_runs_telemetry.py` — insert, idempotency, partial
   updates, late corrections, user isolation, validation, migration-applies
   check, legacy-payload compatibility.
6. `tools/synthetic_fitness/real_telemetry_compat.py` +
   `test_real_telemetry_compat.py` — the §3.6 adapter + proof that telemetry
   rows flow through the unmodified `features.build_features`.
7. Android (smallest change, reusing the run-sync path): optional
   `daily_activity` DTO on `RunSyncPayload`, computed in
   `CaptureScreenModel` from Room; `RunSyncer` signature extended;
   RunSyncerTest extended.
