# Real Telemetry Dataset Builder (Phase 4B.6)

> ⚠ **No model was trained and no real-user ML performance was measured in
> this phase.** This tool only *builds datasets*. The real Supabase
> `userdailyactivity` table is still empty (Phase 4B.5 deployed the schema but
> no telemetry has been collected); every result in the tests comes from
> deterministic TEST-FIXTURE data shaped like real telemetry, which is never
> written to the real database.

`real_telemetry_export.py` reads persisted real FitQuest daily telemetry and
produces the same ML-ready representation the synthetic experiment
(Phases 4B.2–4B.4) uses. It duplicates nothing: feature definitions come from
`features.py`, the target from `target.py`, and telemetry→raw-row semantics
from `real_telemetry_compat.py` (Phase 4B.5) — all unmodified.

## Source table

`userdailyactivity` (Alembic migration `0002_user_daily_activity.py`): one row
per `(user_id, activity_date)` — the device-reported daily snapshot run-sync
persists. The exporter selects exactly:

```
user_id, activity_date, steps, active_minutes, goal_steps, goal_completed,
hexes_owned, hexes_captured, hexes_lost, defense_steps
```

ordered by `(user_id, activity_date)`. `updated_at` is deliberately not
exported (sync bookkeeping, not data). Extraction runs through SQLAlchemy (an
existing backend dependency) so the identical code path works against SQLite
(tests) and the real Supabase PostgreSQL. The database URL is never printed or
persisted — it can carry credentials.

## Extraction process

```text
userdailyactivity (backend DB)
   │ fetch_telemetry_rows()        raw SQL SELECT, deterministic order
   ▼
extracted rows  ──────────────────────────────► real_telemetry_raw.csv (verbatim)
   │ export_dataset()
   │   1. shape check + uniqueness validation (fail loudly)
   │   2. real_telemetry_compat.telemetry_to_raw_rows()
   │      (densify gaps, recompute streaks, derive goal_completed,
   │       label data_source="real")
   │   3. provenance annotation (densified / *_known flags)
   │   4. features.build_features()   — UNMODIFIED 21-feature pipeline
   │   5. target.build_labels()       — UNMODIFIED inactive_next_3d
   │   6. schema verification (exact synthetic column set + target)
   ▼
real_telemetry_daily.csv   real_telemetry_features.csv   real_telemetry_manifest.json
```

### Corrections / duplicates

The table's composite primary key `(user_id, activity_date)` makes duplicate
records impossible at the database level. The exporter still validates
uniqueness after extraction and **fails loudly** (`ValueError`) rather than
silently picking a winner — proven by a test that creates a PK-less fixture
table with duplicate rows. Late corrections are handled upstream by the
Phase 4B.5 merge-upsert (last write wins per field at sync time); the exporter
only ever sees the final, unique rows.

## Densification semantics (missing days)

The app only syncs when a run ends, so a day with no stored row means the app
was never opened / no run happened. Between a user's first and last recorded
day, such days are **densified to zero-step rows** by the Phase 4B.5 adapter,
because:

- FitQuest "daily steps" are *tracked-run steps only* — the app has no
  background/all-day step counting; "steps today" is defined as the sum of
  run-session steps for the device-local date.
- Therefore, within the app's own measurement domain, a day with no synced
  run has **zero tracked steps** — zero means "no tracked activity", *not*
  "the user did not walk".
- Densification is also required for correctness: `features.py` rolling
  windows are index-based, so without it a "trailing 7 days" would silently
  span more than 7 calendar days; and the `inactive_next_3d` target needs
  inactive days to exist as rows.

What is **never** densified or fabricated:

- Days after a user's last recorded day are not extended — the future is
  unknown, and those tail days correctly end up with no target.
- `goal_steps` / `hexes_owned` on gap days are **carried forward** from the
  last recorded day (they are slow-moving state, not daily events).
- `streak` is recomputed from the densified steps history (the server never
  stored it), resetting across gaps and across users.
- No other metric is invented for gap days: captures are 0 (no run ⇒ no
  capture), losses/defense are unknown (flags say so).

## Feature generation

`features.build_features` runs **unmodified** on the densified daily rows —
the exact 21-feature pipeline, leakage policy, and expanding-window semantics
from Phase 4B.2. The exporter then verifies that every output row's columns
are exactly `features.OUTPUT_COLUMNS` + `inactive_next_3d` and that
`data_source == "real"`; any drift raises. `feature_matrix()` defines X: only
`features.MODEL_FEATURES`, in canonical order — metadata (`synthetic_user_id`,
`day`), provenance (`data_source`), and the target are excluded by
construction.

## Target generation

`target.build_labels` runs **unmodified** on the densified daily rows:
`inactive_next_3d(D) = 1` iff ≥ 2 of days D+1..D+3 (same user) have
steps < 1,000. Rows whose 3-day horizon does not fully exist — the last 3
days of each user's history — carry an **empty** target in the CSV and are
never imputed. Note the horizon may legitimately include densified
zero-step days (a gap inside history); that is the documented interpretation
above, and it is the same definition the synthetic experiment used.

## Missing-data behavior & null/unknown semantics

| Situation                        | Behavior                                                                 |
| -------------------------------- | ------------------------------------------------------------------------ |
| Day missing *inside* history     | Densified to a zero-tracked-step row, flagged `densified=1`               |
| Day missing *after* last record  | Not fabricated; those tail rows get no target                             |
| `hexes_lost` NULL (v1 always)    | Raw CSV keeps it empty; daily row is `0` **with `hexes_lost_known=0`**    |
| `defense_steps` NULL (v1 always) | Raw CSV keeps it empty; daily row is `0` **with `defense_steps_known=0`** |
| `goal_completed` NULL            | Derived as `steps >= goal_steps` (Phase 4B.5 documented semantics)        |
| `goal_steps`/`hexes_owned` NULL  | Carried forward from the user's last recorded value                       |

The unknown-vs-zero distinction is preserved **in the dataset itself**: the
raw CSV never converts NULLs, and the daily CSV carries the `hexes_lost_known`
/ `defense_steps_known` flags. The three features built from those fields
(`losses_7d`, `defense_steps_7d`, `defense_ratio_7d`) are numeric 0 on
unknown rows — the feature schema has no null representation — and are
placeholders until a later phase observes those signals. Downstream training
phases can filter or re-weight using the flags.

`activity_date` is the device-local calendar date the client reported; the
exporter uses the stored `DATE` as-is and never applies a server-timezone
conversion.

## Output schema

All outputs land in `tools/synthetic_fitness/output/` (git-ignored):

| File                             | Columns                                                                                             |
| -------------------------------- | --------------------------------------------------------------------------------------------------- |
| `real_telemetry_raw.csv`         | `user_id, activity_date, steps, active_minutes, goal_steps, goal_completed, hexes_owned, hexes_captured, hexes_lost, defense_steps` — extracted verbatim; NULL = empty |
| `real_telemetry_daily.csv`       | `generator.COLUMNS` + `densified, hexes_lost_known, defense_steps_known` — the exact input `build_features`/`build_labels` consumed (auditable) |
| `real_telemetry_features.csv`    | `features.OUTPUT_COLUMNS` + `inactive_next_3d` — ML-ready; empty target = no full horizon             |
| `real_telemetry_manifest.json`   | provenance, counts (users/rows/densified/labeled/positives), feature list, all policies above         |

The synthetic and real datasets are never mixed: this tool reads only
`userdailyactivity`, labels every row `data_source="real"`, and rejects
synthetic-pipeline-shaped rows (they lack the telemetry keys) with a
`ValueError`.

## Leakage safeguards (all proven by tests)

- **Future-day immutability of features**: rewriting a later day's
  steps/captures cannot change any earlier day's feature row.
- **Target horizon containment**: changing day X can only affect targets of
  days X−3..X−1 (whose 3-day horizon includes X); earlier targets are
  byte-identical, and the in-window flip is demonstrated.
- **User isolation**: adding or tampering with another user changes nothing
  for existing users — features or labels (streaks and windows reset per
  user inside the reused pipelines).
- **X hygiene**: `feature_matrix()` yields exactly the 21 `MODEL_FEATURES` in
  canonical order; metadata, provenance, and the target are excluded.
- **No synthetic contamination**: every emitted row is `data_source="real"`;
  synthetic rows are rejected at the door.
- **Schema pinning**: any column drift from the synthetic experiment raises.

## Fixture verification

`test_real_telemetry_export.py` (23 tests) builds throwaway SQLite databases
under pytest's `tmp_path` with deterministic, clearly-labeled TEST-FIXTURE
rows mirroring the `userdailyactivity` DDL (including a PK-less variant to
exercise duplicate detection). The fixtures cover: a mid-history gap day,
NULL vs reported losses/defense, an inactive stretch for the target, a
two-user history, hand-computed features and labels, tail rows without a
horizon, and the full CLI. Nothing is ever written to the real Supabase
database, and the fixture user ids can never collide with the backend dev
user (canary test).

## CLI

```powershell
# from apps/api — reads DATABASE_URL from the environment
./.venv/Scripts/python.exe tools/synthetic_fitness/real_telemetry_export.py

# explicit database + output directory
./.venv/Scripts/python.exe tools/synthetic_fitness/real_telemetry_export.py `
    --database-url "postgresql+psycopg://..." `
    --out-dir tools/synthetic_fitness/output
```

An empty table is handled gracefully: the tool prints that there is nothing
to export, writes no files, and fabricates nothing.

## Limitations

- **No real telemetry exists yet.** Against the real (still empty) Supabase
  table the exporter will correctly export nothing. It is ready for the day
  telemetry lands; no re-training, deployment, or schema change is implied.
- `losses_7d`, `defense_steps_7d`, `defense_ratio_7d` are placeholders on
  rows where the device could not observe those signals (flags mark them).
- Daily steps are tracked-run steps only — a user walking with the app closed
  is indistinguishable from a fully idle day within the app's measurement
  domain.
- Pre-Phase-4B.5 history can never be recovered; the export starts at each
  user's first recorded day.
- **No real-user ML performance was measured** — dataset construction only.
