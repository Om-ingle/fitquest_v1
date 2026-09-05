# Phase 4B.4 — First XGBoost Experiment Report

> ⚠ **This experiment ran on SYNTHETIC data.** It validates the ML pipeline
> (features → labels → time-aware splits → training → evaluation) only. It
> is **NOT evidence of real-user predictive performance** and must never be
> quoted as such. All numbers below describe the synthetic dataset's
> data-generating process, which is a deliberate cartoon of user archetypes.

Reproduce: `./.venv/Scripts/python.exe tools/synthetic_fitness/xgboost_experiment.py`
(writes `output/xgboost_experiment_results.json`; deterministic — same data +
seed ⇒ identical results, enforced by tests).

## Objective

Train and evaluate the first XGBoost binary classifier for the Phase 4B.3
target **`inactive_next_3d`** (≥ 2 of the next 3 days below the 1,000-step
bar) using exactly the 21 leakage-safe `MODEL_FEATURES` from Phase 4B.2, on
the Phase 4B.3 time-aware splits, against explicit baselines. The key
question: **does XGBoost meaningfully outperform the persistence baseline on
unseen test data?**

## Dataset & splits (from the existing artifacts; nothing redefined)

Features from `output/synthetic_fitness_features.csv`, labels from
`output/synthetic_fitness_dataset.csv` via `target.build_labels` (last 3 days
per user excluded — label `None`, never imputed; embargo rows dropped).

| Split | Dates | Rows | Positives | Prevalence |
| --- | --- | --- | --- | --- |
| train | ≤ 2025-05-17 | 4,110 | 1,870 | 45.5% |
| *(embargo)* | 2025-05-18…20 | *(90 dropped)* | | |
| validation | 2025-05-21…06-09 | 600 | 267 | 44.5% |
| test | 2025-06-10…06-26 | 510 | 239 | 46.9% |

Raw dataset: 5,400 rows (30 users × 180 days) → 5,310 labeled → 5,220 used
(after embargo).

**Class imbalance:** train prevalence 45.5% — balanced. **No class weighting
used** (`scale_pos_weight` left at default); no resampling.

## Model configuration (fixed; no sweep)

```text
XGBoost 3.4.1 (native API, DMatrix), seed=42, nthread=1
objective=binary:logistic   tree_method=hist   max_depth=4   eta=0.1
min_child_weight=1   subsample=1.0   colsample_bytree=1.0
lambda=1.0   alpha=0.0   eval_metric=logloss   num_boost_round=200
early stopping: NONE (fixed rounds — validation is never consulted during
fitting, which makes that guarantee structural; see tests)
```

## Baselines

- **Majority class** — always predict the train majority class (0).
- **Persistence** — predict 1 iff `active_today == 0` (already quiet today).
- **days_since_active ≥ 1** — *observation:* this is mathematically identical
  to persistence (`days_since_active == 0` exactly when today is active), so
  its metrics coincide by construction. Kept in the code for transparency;
  it adds no third reference point.

## Threshold selection

Argmax-F1 over the 0.01…0.99 grid on **validation only** → **0.27**, then
frozen and applied to test exactly once. Tests prove test labels cannot
change the chosen threshold, and that it equals the argmax recomputed from
validation data alone.

## Results

### Validation

| method | ROC-AUC | PR-AUC | accuracy | precision | recall | F1 | Brier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| majority | 0.5000 | 0.4450 | 0.5550 | 0.0000 | 0.0000 | 0.0000 | 0.2471 |
| persistence | 0.7878 | 0.6885 | 0.7900 | 0.7621 | 0.7678 | 0.7649 | 0.2100 |
| **XGBoost** | **0.9313** | **0.9281** | 0.8000 | 0.6960 | 0.9775 | 0.8131 | **0.1002** |

### Test (frozen threshold 0.27, evaluated once)

| method | ROC-AUC | PR-AUC | accuracy | precision | recall | F1 | Brier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| majority | 0.5000 | 0.4686 | 0.5314 | 0.0000 | 0.0000 | 0.0000 | 0.2492 |
| persistence | 0.7953 | 0.7142 | 0.7961 | 0.7824 | 0.7824 | 0.7824 | 0.2039 |
| **XGBoost** | **0.9134** | **0.9085** | **0.8118** | 0.7375 | 0.9289 | **0.8222** | **0.1184** |

### XGBoost vs persistence (the Phase 4B.3 headline)

- Test ROC-AUC delta: **+0.1181** (0.9134 vs 0.7953)
- Validation ROC-AUC delta: +0.1435 (0.9313 vs 0.7878)
- Val↔test ROC-AUC gap: **0.0180** (0.9313 → 0.9134 — reasonably consistent)

### Success criterion — **PASSED**

Rule (Phase 4B.3): test ROC-AUC ≥ persistence + 0.05 **and** val/test
reasonably consistent (gap ≤ 0.10). Measured: Δ = +0.118 ≥ +0.05, gap =
0.018. Reported as measured, not forced.

### Calibration (test, threshold-free)

| bin | n | mean predicted | observed rate |
| --- | --- | --- | --- |
| [0.0, 0.2) | 189 | 0.029 | 0.053 |
| [0.2, 0.4) | 53 | 0.307 | 0.434 |
| [0.4, 0.6) | 95 | 0.503 | 0.590 |
| [0.6, 0.8) | 44 | 0.679 | 0.568 |
| [0.8, 1.0) | 129 | 0.973 | 0.969 |

Brier 0.1184 (vs persistence 0.2039). Well-calibrated at the extremes,
mildly under-confident in the low-mid bins and slightly over-confident in
[0.6, 0.8). Acceptable for a first experiment; no calibration layer added
(by design).

## Feature importance (gain-based, top 8; NOT causal)

| feature | gain share |
| --- | --- |
| `goal_steps` | 0.3818 |
| `steps_7d_avg` | 0.3253 |
| `hexes_owned` | 0.0231 |
| `active_minutes_7d_avg` | 0.0212 |
| `defense_ratio_7d` | 0.0209 |
| `days_since_active` | 0.0203 |
| `defense_steps_7d` | 0.0191 |
| `losses_7d` | 0.0181 |

Interpretation (synthetic-data-specific, non-causal): the two dominant
features are exactly the ones that identify *which profile* a user is
(`goal_steps` is a per-profile constant; `steps_7d_avg` separates the
archetypes). This matches the data-generating process — within a profile,
days are i.i.d. draws, so the model's best achievable signal is
profile-level prevalence. The long tail of small importances is consistent
with that. **These importances must not be read as "what matters for real
users."**

## Limitations

1. **Synthetic only** — the generator's fixed per-profile activity
   probabilities make this target far more predictable than real behavior.
   The AUC is an upper bound on pipeline sanity, not a forecast.
2. **Profile-identity shortcut** — with i.i.d. within-profile days, the
   model mostly learns "who the user is," not "what is changing." Real
   telemetry has temporal structure (fatigue, motivation, weekday effects)
   this dataset lacks by construction.
3. **LAPSED tail shift** — LAPSED users are almost all label-1 in the test
   window (their forced inactive tail), making test slightly easy.
4. **30 users** — enough to validate the pipeline, not to make
   population-level claims.
5. `days_since_active ≥ 1` baseline is identical to persistence by
   definition (documented above), so only two genuinely distinct baselines
   exist.

## Explicit statement

This is **synthetic-data pipeline validation**. It demonstrates that the
feature set, target, splits, training, and evaluation mechanics work
end-to-end and leakage-safely. It does **not** demonstrate predictive
performance for real FitQuest users; real telemetry (Supabase, same schema,
`data_source="real"`) is required before any such claim.
