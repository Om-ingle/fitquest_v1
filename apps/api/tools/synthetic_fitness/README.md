# FitQuest Synthetic Fitness Dataset Simulator

> ⚠ **This generates SYNTHETIC data.** Nothing in `output/` (or produced by this
> tool) is real FitQuest user data. It must **never** be presented as real user
> data in documentation, reports, metrics, demos, or research claims. Every row
> is labeled `data_source = "synthetic"` so it can be filtered out downstream.

## Why it exists

FitQuest is moving toward ML-driven personalization, but today the backend holds
data for essentially one development user. There is not enough real FitQuest
activity to train or meaningfully exercise an ML pipeline. Rather than wait, this
simulator produces a *plausible, reproducible* activity dataset for building and
validating the training/evaluation pipeline first.

Two hard rules that shape it:

1. **Deterministic** — the same seed always yields the identical dataset, so
   experiments are reproducible.
2. **Honest** — the generated behavior is a *cartoon* of user archetypes. It is
   not medically accurate, not a statistically representative human population,
   and is not a proxy for real FitQuest telemetry.

When real FitQuest data becomes available (activity sync, territory ownership,
leaderboards, quest completion), the dataset produced here will be
**augmented or replaced** by real records. The `data_source` column is the hook
for that transition: real rows will carry their own source label and the two can
be combined and separated cleanly.

## Scope

- Standard Python **standard library only** (`csv`, `random`, `datetime`).
  `pandas` is deliberately not added — it is not an existing backend dependency.
- **Isolated** — no database, no FastAPI imports, no migrations, nothing in the
  request path. It only writes a CSV file.
- No changes to recommendation, run-sync, schema, or Android behavior.

## Layout

```text
tools/synthetic_fitness/
├── generator.py                  # simulator (library API + CLI)
├── features.py                   # Phase 4B.2 feature engineering (library + CLI)
├── target.py                     # Phase 4B.3 ML target definition + analysis CLI
├── target_design.md              # Phase 4B.3 target-design report
├── xgboost_experiment.py         # Phase 4B.4 first XGBoost experiment (needs xgboost)
├── xgboost_experiment.md         # Phase 4B.4 experiment report (read this first)
├── test_synthetic_generator.py   # simulator tests (pure Python, no DB)
├── test_feature_engineering.py   # feature-pipeline tests (pure Python, no DB)
├── test_target_design.py         # target-design tests (pure Python, no DB)
├── test_xgboost_experiment.py    # experiment tests (skip if xgboost absent)
├── README.md                     # this file
└── output/
    ├── synthetic_fitness_dataset.csv             # raw synthetic dataset (git-ignored)
    ├── synthetic_fitness_features.csv            # ML-ready features (git-ignored)
    ├── synthetic_fitness_features_manifest.json  # feature manifest (git-ignored)
    └── xgboost_experiment_results.json           # experiment results (git-ignored)
```

## The profiles

Each synthetic user is assigned one behavior profile. With ≥ 7 users the default
composition always includes all seven at least once; extra users are drawn from a
weighted population mix.

| Profile            | What it looks like                                                            |
| ------------------ | ----------------------------------------------------------------------------- |
| `INACTIVE`         | Sporadic, minimal movement. Rarely meets a goal, almost no territory.         |
| `CASUAL`           | Active a few days/week, moderate volume, a small patch of territory.          |
| `CONSISTENT`       | Active most days, reliably completes goals, steadily grows a medium territory.|
| `HIGHLY_ACTIVE`    | Exercises nearly every day at high volume; the biggest captured territory.    |
| `LAPSED`           | Was active (history + territory) then went quiet — long inactive tail.        |
| `RETURNING`        | Active → a multi-week inactive spell → renewed activity afterwards.           |
| `TERRITORY_FOCUSED`| Territory-first: captures aggressively, spends much activity defending.       |

### Structural behaviors encoded in the generator

- **LAPSED** gets a *tail gap* (~40% of days forced inactive), so it models a
  player with real history and territory whose last capture is old — exactly the
  state the recommendation engine's LAPSED/RECOVERY rules target.
- **RETURNING** gets a *middle gap* (~30% of days forced inactive) with active
  days before and after — inactivity *followed by renewed activity*.
- **TERRITORY_FOCUSED** captures far more and holds far more hexes than
  **INACTIVE**.

## Fields (one row per user per day)

| Column                | Meaning                                                                    |
| --------------------- | -------------------------------------------------------------------------- |
| `synthetic_user_id`   | Stable synthetic id, e.g. `syn_casual_0003` (carries the profile name).    |
| `day`                 | ISO date (`YYYY-MM-DD`), contiguous per user.                              |
| `steps`               | Steps that day (0 on rest days; bounded ≤ 25,000).                         |
| `active_minutes`      | Active-bout minutes derived from steps (see modeling note below).          |
| `hexes_owned`         | End-of-day territory held (never negative, clamped per-profile).            |
| `hexes_captured`      | Hexes captured that day (≥ 0, ≤ 4).                                         |
| `hexes_lost`          | Hexes lost to rivals that day (≤ territory held at day start).             |
| `defense_steps`       | Steps spent reinforcing territory (≤ that day's steps; 0 if no territory).  |
| `streak`              | Consecutive days above the activity bar (1,000 steps), reset on rest days.  |
| `goal_steps`          | That user's fixed daily step goal.                                          |
| `goal_completed`      | `1` iff `steps >= goal_steps` — **derived**, never assigned independently.  |
| `data_source`         | Always `"synthetic"`.                                                       |

Key ledger invariant preserved per user across days:

```text
hexes_owned[t] = hexes_owned[t-1] + hexes_captured[t] - hexes_lost[t]
hexes_owned >= 0  and  hexes_lost[t] <= hexes_owned[t-1]
```

### How `active_minutes` is derived

Only a *share* of a day's tracked steps occur in continuous, measurable
"active bouts" — the rest are incidental movement. So each day's active
minutes are:

```text
active_minutes = round(steps * bout_share / cadence)
```

- `bout_share` ∈ [0.5, 1.0] varies per day — this is the noise that makes the
  steps↔minutes link *strongly but not perfectly* correlated (Pearson r ≈ 0.95
  on the default dataset, not ~1.0).
- `cadence` (steps per minute) is drawn from a **per-profile** range, so the
  same step count maps to different minutes across profiles:
  `INACTIVE` 95–120 · `CASUAL` 100–125 · `CONSISTENT` 105–130 ·
  `HIGHLY_ACTIVE` 130–175 (running-heavy) · `LAPSED` 100–125 · `RETURNING`
  105–130 · `TERRITORY_FOCUSED` 90–115 (meanders while claiming hexes).
- Days below the active-bout floor of **1,000 steps** are treated as incidental
  movement only → `0` minutes. At/above the floor a day is guaranteed
  `≥ 1` minute (and `≤ steps`), which makes the reported defect — high steps
  with zero active minutes — **structurally impossible**.

This is a deliberately simple cartoon of activity, not a medically accurate
model.

## Generating a dataset

Use the repo's venv (nothing extra to install):

```powershell
# from apps/api
./.venv/Scripts/python.exe tools/synthetic_fitness/generator.py `
    --users 30 --days 180 --seed 42 --output tools/synthetic_fitness/output/synthetic_fitness_dataset.csv
```

Defaults: `30` users × `180` days, seed `42`, output at
`tools/synthetic_fitness/output/synthetic_fitness_dataset.csv`.

All options:

| Flag          | Default | Purpose                                   |
| ------------- | ------- | ----------------------------------------- |
| `--users`     | `30`    | number of synthetic users                 |
| `--days`      | `180`   | days of history per user                  |
| `--seed`      | `42`    | RNG seed (reproducibility)                |
| `--start-date`| `2025-01-01` | first day of the window (ISO)         |
| `--output`    | (above) | output CSV path                           |
| `--check CSV` | —       | skip generation; print a data-quality summary of an existing CSV |

Generation always prints a data-quality summary afterwards. To re-summarize an
already-written CSV without regenerating:

```powershell
./.venv/Scripts/python.exe tools/synthetic_fitness/generator.py `
    --check tools/synthetic_fitness/output/synthetic_fitness_dataset.csv
```

The summary reports steps min/max/mean/median, active_minutes
min/max/mean/median, the two quality red flags (`%` of rows with steps > 10k /
> 20k but **0** active minutes — both are 0.0 by construction), goal-completion
% overall, the steps↔active_minutes Pearson r, and a per-profile table
(users, rows, avg steps/minutes, goal %, avg captures/hexes_owned/streak). It
is pure standard library (`statistics`).

### Library API

```python
from tools.synthetic_fitness import generator  # tools/ is a namespace pkg when run from apps/api

rows = generator.generate_dataset(num_users=30, num_days=180, seed=42)
generator.write_dataset(rows, "synthetic_fitness_dataset.csv")

# One specific user (also how the per-profile tests exercise each profile):
history = generator.generate_user_days("LAPSED", "syn_lapsed_0001", 40, seed=3)
```

## Feature engineering (Phase 4B.2)

The ML pipeline stage looks like this:

```text
Raw dataset                        Feature engineering                 ML-ready dataset
(synthetic_fitness_dataset.csv)    (features.py, leakage-safe           (synthetic_fitness_features.csv)
 30 users × 180 days = 5,400        rolling/expanding windows)            5,400 rows × 21 features
 daily rows                                                                + manifest JSON)
        ↓                                  ↓                                  ↓
                        Phase 4B.3 target design (inactive_next_3d — see
                        target_design.md; target/label NOT in the features)
                                 ↓
                        Phase 4B.4 first XGBoost experiment (done — see
                        xgboost_experiment.md; SYNTHETIC pipeline validation
                        only, criterion PASSED on synthetic data)
```

⚠ **These features are generated from SYNTHETIC data.** Feature engineering
here demonstrates *pipeline feasibility only*. It does **not** establish
real-world predictive performance of any kind. Real FitQuest telemetry will
eventually replace/augment the synthetic dataset and flow through the same
code under a different `data_source` label.

**No ML target column exists in the features CSV.** Phase 4B.3 separately
designed the first experiment's target — `inactive_next_3d` (≥ 2 of the next
3 days below the 1,000-step bar; a *future-behavior* label, deliberately NOT
the rules engine's recommendation output, which would make the experiment
circular). The full rationale, horizon, splits, baselines, and metrics are in
[`target_design.md`](target_design.md); the executable definition is
`target.py`. Phase 4B.4 will train the first model.

### Leakage policy

Every feature describes one user **as of the end of day D** and is computed
**only from days D and earlier of that same user**:

- Trailing windows are inclusive of D and **expand at history start** — a
  7-day average on a user's first day is just that day's value, so no early
  rows are dropped.
- `steps_7d_avg` on 2025-01-07 = mean of 2025-01-01 … 2025-01-07.
- `steps_change_vs_7d_avg` compares D against the **prior** 7 days
  (D-7 … D-1) so it is never self-referential; it is 0.0 on the first day
  (no baseline).
- No future steps, captures, losses, or holdings ever appear in day D's
  features, and users never share history. Both properties are proven by
  tests (future-perturbation and cross-user-tampering).

### The feature set (21 model features)

`synthetic_user_id` and `day` are kept as metadata for traceability and
`data_source` stays `"synthetic"`, but all three are **excluded from the
feature matrix**.

| Feature                     | Window                              | Description                                                        |
| --------------------------- | ----------------------------------- | ------------------------------------------------------------------ |
| `steps_today`               | D                                   | Steps on day D.                                                     |
| `active_minutes_today`      | D                                   | Active-bout minutes on day D.                                       |
| `steps_3d_avg`              | D-2 … D (expanding)                 | Mean steps, trailing 3 days.                                        |
| `steps_7d_avg`              | D-6 … D (expanding)                 | Mean steps, trailing 7 days.                                        |
| `active_minutes_3d_avg`     | D-2 … D (expanding)                 | Mean active minutes, trailing 3 days.                               |
| `active_minutes_7d_avg`     | D-6 … D (expanding)                 | Mean active minutes, trailing 7 days.                               |
| `activity_days_7d`          | D-6 … D                             | Days with steps ≥ 1,000 in the trailing week.                       |
| `steps_change_vs_7d_avg`    | D-7 … D-1 (prior days only)         | Today's steps minus the prior-7-day mean; 0.0 on day one.           |
| `current_streak`            | cumulative to D                     | Consecutive days ≥ 1,000 steps ending on D (raw streak).            |
| `goal_completion_rate_7d`   | D-6 … D                             | Fraction of the trailing week's goals met.                          |
| `days_since_active`         | lookback from D                     | Days since the last ≥ 1,000-step day (0 if active today).           |
| `hexes_owned`               | end of D                            | Territory held at end of day D.                                     |
| `captures_7d`               | D-6 … D                             | Hexes captured in the trailing week.                                |
| `losses_7d`                 | D-6 … D                             | Hexes lost in the trailing week.                                    |
| `territory_change_7d`       | D vs D-7                            | `hexes_owned[D] − hexes_owned[D-7]` (baseline 0 at history start).  |
| `defense_steps_7d`          | D-6 … D                             | Defense/reinforcement steps in the trailing week.                   |
| `defense_ratio_7d`          | D-6 … D                             | `defense_steps_7d` / total steps in the same window (0 if no steps).|
| `goal_steps`                | per-user constant                   | The user's fixed daily step goal.                                   |
| `goal_completed_today`      | D                                   | 1 iff `steps_today ≥ goal_steps`.                                   |
| `active_today`              | D                                   | 1 iff `steps_today ≥ 1,000` (the game's activity bar).              |
| `goal_progress_ratio`       | D                                   | `steps_today / goal_steps` (scale-free, can exceed 1.0).            |

A machine-readable version of this table — `feature_name`, `description`,
`source field(s)`, `window`, `allowed_for_training` — is written to
`output/synthetic_fitness_features_manifest.json` on every run (also available
as `features.FEATURE_MANIFEST`), for research reproducibility.

### Building the feature dataset

```powershell
# from apps/api — defaults read the raw dataset and write next to it
./.venv/Scripts/python.exe tools/synthetic_fitness/features.py

# explicit paths
./.venv/Scripts/python.exe tools/synthetic_fitness/features.py `
    --input  tools/synthetic_fitness/output/synthetic_fitness_dataset.csv `
    --output tools/synthetic_fitness/output/synthetic_fitness_features.csv `
    --manifest tools/synthetic_fitness/output/synthetic_fitness_features_manifest.json
```

Library API:

```python
from tools.synthetic_fitness import features

raw = features.generator.read_dataset(".../synthetic_fitness_dataset.csv")
ml_rows = features.build_features(raw)     # one row per (user, day)
features.write_features(ml_rows, ".../synthetic_fitness_features.csv")
features.MODEL_FEATURES                    # the 21-name feature matrix
features.FEATURE_MANIFEST                  # manifest entries (incl. metadata)
```

## Running the tests

```powershell
# from apps/api — synthetic tests only
./.venv/Scripts/python.exe -m pytest tools/synthetic_fitness -q

# synthetic tests + the existing backend suite
./.venv/Scripts/python.exe -m pytest tests tools/synthetic_fitness -q
```

The tests are pure Python (no DB, no `DATABASE_URL`) and cover: determinism
(same seed → identical rows), different seeds → different rows, required
columns, requested user/day counts, `data_source == "synthetic"` everywhere,
the territory-ledger and derived-field constraints, bounded/realistic values,
the steps↔active_minutes quality invariants (high steps never carry zero
minutes; minutes rise with steps; Pearson r in a healthy band), the summary
metrics (zero red flags, distinct per-profile statistics), profile-specific
behavior (LAPSED tail, RETURNING renewed activity, TERRITORY_FOCUSED >
INACTIVE on territory, activity/goal/streak ordering), and generation of every
required profile. The feature-engineering tests additionally prove: expected
row/column counts, deterministic + byte-identical CSV output, hand-computed
rolling-window values, expanding early-history windows, **no future leakage**
(perturbing days after D cannot change day D's features), **user isolation**
(tampering with one user's history cannot change another's), no NaN/invalid
values, metadata (`synthetic_user_id`, `day`, `data_source`) excluded from the
model feature list, no ML target column, and CSV/manifest round-tripping.

## How this gets replaced/augmented with real data

1. Keep generating synthetic data for pipeline development; always label it.
2. As real telemetry lands (run-sync, HexOwnership, leaderboard), export real
   daily aggregates into the *same column schema* under a different
   `data_source` (e.g. `"real"`).
3. Train/evaluate on the real subset; use the synthetic subset only to
   smoke-test the pipeline shape before real data reaches it.
4. Never report metrics derived from synthetic data as if they came from real
   FitQuest users.
