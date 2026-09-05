"""Phase 4B.4 — the first XGBoost experiment on the SYNTHETIC dataset.

⚠  IMPORTANT — this experiment runs on SYNTHETIC data only. It validates the
   ML *pipeline* (features → labels → time-aware splits → model → metrics).
   Its numbers are NOT evidence of real-user predictive performance and must
   never be presented as such. See xgboost_experiment.md for the full report.

Design (all inherited, nothing redefined here):
   * target  : target.inactive_next_3d (Phase 4B.3)
   * features: the 21 MODEL_FEATURES from features.py (Phase 4B.2, purely
     historical — days <= D)
   * splits  : calendar dates from target.py — train <= 2025-05-17, embargo
     2025-05-18..20, val 2025-05-21..2025-06-09, test 2025-06-10..2025-06-26.
     Rows without a full 3-day horizon are excluded (label None).
   * baselines: majority class; persistence (active_today == 0);
     days_since_active >= 1.

Deliberate choices for a conservative, reproducible first experiment:
   * fixed seed, nthread=1, fixed 200 boosting rounds, no early stopping,
     no hyperparameter sweep — the validation set is NOT used for fitting
     at all, which makes that guarantee structural and testable;
   * no class weighting (train prevalence ~45.5% — balanced);
   * the classification threshold is argmax-F1 over a 0.01..0.99 grid on
     VALIDATION only, then frozen and applied to test exactly once.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import xgboost as xgb

import features
import generator
import target
from features import MODEL_FEATURES
from target import HORIZON_DAYS, TARGET_NAME, TEST_START, TRAIN_END, VAL_END, VAL_START

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = generator.DEFAULT_OUTPUT
DEFAULT_FEATURES = features.DEFAULT_OUTPUT
DEFAULT_RESULTS = TOOL_DIR / "output" / "xgboost_experiment_results.json"

# ── Model configuration (fixed, documented, no sweep) ────────────────────────

SEED = 42
NUM_BOOST_ROUND = 200

MODEL_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "tree_method": "hist",
    "max_depth": 4,
    "eta": 0.1,
    "min_child_weight": 1,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "lambda": 1.0,
    "alpha": 0.0,
    "seed": SEED,
    "nthread": 1,
}

THRESHOLD_GRID = [round(i / 100, 2) for i in range(1, 100)]  # 0.01 .. 0.99
CALIBRATION_BIN_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]

SUCCESS_CRITERION_ROC_AUC_DELTA = 0.05  # Phase 4B.3: test ROC-AUC vs persistence


# ─────────────────────────────────────────────────────────────────────────────
# Pure-Python metrics (no sklearn; xgboost is the only added dependency)
# ─────────────────────────────────────────────────────────────────────────────


def roc_auc(y_true: list[int], y_score: list[float]) -> float | None:
    """ROC-AUC via the Mann-Whitney U statistic with midrank tie handling."""
    n = len(y_true)
    n_pos = sum(y_true)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return None  # degenerate: AUC undefined for a single-class set

    order = sorted(range(n), key=lambda i: y_score[i])
    rank_sum_pos = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and y_score[order[j + 1]] == y_score[order[i]]:
            j += 1
        midrank = (i + j + 2) / 2.0  # 1-based average rank of the tie group
        for k in range(i, j + 1):
            if y_true[order[k]] == 1:
                rank_sum_pos += midrank
        i = j + 1
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def average_precision(y_true: list[int], y_score: list[float]) -> float | None:
    """PR-AUC as (threshold-grouped) average precision."""
    n_pos = sum(y_true)
    if n_pos == 0:
        return None
    order = sorted(zip(y_score, y_true), key=lambda pair: -pair[0])
    tp = fp = 0
    ap = 0.0
    prev_recall = 0.0
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and order[j + 1][0] == order[i][0]:
            j += 1
        for k in range(i, j + 1):
            tp += order[k][1]
            fp += 1 - order[k][1]
        precision = tp / (tp + fp)
        recall = tp / n_pos
        ap += (recall - prev_recall) * precision
        prev_recall = recall
        i = j + 1
    return ap


def brier_score(y_true: list[int], y_score: list[float]) -> float:
    """Mean squared error of predicted probabilities."""
    return sum((p - y) ** 2 for y, p in zip(y_true, y_score)) / len(y_true)


def classification_metrics(
    y_true: list[int], y_pred: list[int]
) -> dict[str, float]:
    """Accuracy / precision / recall / F1 at hard 0/1 predictions."""
    tp = sum(1 for y, p in zip(y_true, y_pred) if y == 1 and p == 1)
    fp = sum(1 for y, p in zip(y_true, y_pred) if y == 0 and p == 1)
    fn = sum(1 for y, p in zip(y_true, y_pred) if y == 1 and p == 0)
    n = len(y_true)
    accuracy = (tp + sum(1 for y, p in zip(y_true, y_pred) if y == 0 and p == 0)) / n
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate_scores(y_true: list[int], y_score: list[float], y_pred: list[int]) -> dict:
    """The full metric block for one (predictions, labels) pair."""
    metrics = {
        "roc_auc": roc_auc(y_true, y_score),
        "pr_auc": average_precision(y_true, y_score),
        "brier": brier_score(y_true, y_score),
        **classification_metrics(y_true, y_pred),
    }
    return {
        key: (round(value, 6) if isinstance(value, float) else value)
        for key, value in metrics.items()
    }


def select_threshold(y_true: list[int], y_score: list[float]) -> float:
    """Argmax-F1 threshold over the fixed grid — VALIDATION ONLY by contract.

    Ties resolve to the lowest threshold (first grid hit), deterministically.
    """
    best_threshold, best_f1 = THRESHOLD_GRID[0], -1.0
    for threshold in THRESHOLD_GRID:
        y_pred = [1 if p >= threshold else 0 for p in y_score]
        f1 = classification_metrics(y_true, y_pred)["f1"]
        if f1 > best_f1:
            best_threshold, best_f1 = threshold, f1
    return best_threshold


def calibration_table(y_true: list[int], y_score: list[float]) -> list[dict]:
    """Mean predicted vs observed positive rate per probability bin."""
    table = []
    for lo, hi in zip(CALIBRATION_BIN_EDGES, CALIBRATION_BIN_EDGES[1:]):
        in_bin = [
            (y, p) for y, p in zip(y_true, y_score)
            if lo <= p < hi or (hi == 1.0 and p == 1.0)
        ]
        if not in_bin:
            table.append({"bin": f"[{lo:.1f},{hi:.1f})", "n": 0})
            continue
        n = len(in_bin)
        mean_p = sum(p for _y, p in in_bin) / n
        obs = sum(y for y, _p in in_bin) / n
        table.append(
            {
                "bin": f"[{lo:.1f},{hi:.1f})",
                "n": n,
                "mean_predicted": round(mean_p, 4),
                "observed_rate": round(obs, 4),
            }
        )
    return table


# ─────────────────────────────────────────────────────────────────────────────
# Data assembly (existing feature CSV + target definition; nothing duplicated)
# ─────────────────────────────────────────────────────────────────────────────


def assemble_samples(feature_rows: list[dict], labels: dict) -> dict[str, list[dict]]:
    """Join feature rows with target labels and assign time-aware splits.

    Drops rows without a full horizon (label None) and embargo rows. Each
    kept sample carries exactly MODEL_FEATURES (as floats) plus
    synthetic_user_id / day / label for bookkeeping.
    """
    splits: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for row in feature_rows:
        user_id, day = row["synthetic_user_id"], row["day"]
        label = labels.get((user_id, day))
        if label is None:  # last HORIZON_DAYS days: no full future window
            continue
        split = target.assign_split(day)
        if split == "embargo":
            continue
        sample = {name: float(row[name]) for name in MODEL_FEATURES}
        sample.update({"synthetic_user_id": user_id, "day": day, "label": int(label)})
        splits[split].append(sample)
    _verify_split_integrity(splits)
    return splits


def assemble_from_raw(raw_rows: list[dict]) -> dict[str, list[dict]]:
    """Self-contained assembly (generator rows → features → labels → splits)."""
    return assemble_samples(features.build_features(raw_rows), target.build_labels(raw_rows))


def load_experiment_data(
    dataset_csv: str | Path = DEFAULT_DATASET,
    features_csv: str | Path = DEFAULT_FEATURES,
) -> dict[str, list[dict]]:
    """Load the existing on-disk artifacts: features CSV + raw CSV (labels)."""
    raw_rows = generator.read_dataset(dataset_csv)
    feature_rows = features.read_features(features_csv)
    return assemble_samples(feature_rows, target.build_labels(raw_rows))


def to_xy(samples: list[dict]):
    """Feature matrix (exactly MODEL_FEATURES, in order) and label vector."""
    x = [[sample[name] for name in MODEL_FEATURES] for sample in samples]
    y = [sample["label"] for sample in samples]
    return x, y


def _verify_split_integrity(splits: dict[str, list[dict]]) -> None:
    """Programmatic safeguard: split ordering, embargo, and label windows."""
    for name, rows in splits.items():
        assert rows, f"split {name!r} is empty"
        assert all(r["label"] in (0, 1) for r in rows), f"non-binary label in {name}"

    train_days = [date.fromisoformat(r["day"]) for r in splits["train"]]
    val_days = [date.fromisoformat(r["day"]) for r in splits["val"]]
    test_days = [date.fromisoformat(r["day"]) for r in splits["test"]]

    assert max(train_days) <= TRAIN_END, "train extends past TRAIN_END"
    assert min(val_days) >= VAL_START and max(val_days) <= VAL_END, "val dates out of range"
    assert min(test_days) >= TEST_START, "test starts before TEST_START"
    assert max(train_days) < min(val_days), "train/val overlap"
    assert max(val_days) < min(test_days), "val/test overlap"
    # Embargo: no training row's 3-day target window reaches into validation.
    assert max(train_days) + timedelta(days=HORIZON_DAYS) < VAL_START, "embargo violated"


# ─────────────────────────────────────────────────────────────────────────────
# Baselines & model
# ─────────────────────────────────────────────────────────────────────────────


def majority_baseline_scores(train_y: list[int]) -> list[float]:
    """Constant score = training prevalence (hard prediction = majority class)."""
    prevalence = sum(train_y) / len(train_y)
    return [prevalence] * len(train_y)


def persistence_scores(samples: list[dict]) -> list[float]:
    """Predict 1 iff the user is already inactive today (active_today == 0)."""
    return [1.0 if sample["active_today"] == 0.0 else 0.0 for sample in samples]


def days_since_active_scores(samples: list[dict]) -> list[float]:
    """Predict 1 iff the user has been inactive into yesterday too."""
    return [1.0 if sample["days_since_active"] >= 1.0 else 0.0 for sample in samples]


def fit_model(train_samples: list[dict]) -> xgb.Booster:
    """Train on TRAIN rows only. Validation/test are never passed in —
    fixed rounds, no early stopping — so they cannot influence fitting."""
    x, y = to_xy(train_samples)
    dtrain = xgb.DMatrix(x, label=y, feature_names=MODEL_FEATURES)
    return xgb.train(MODEL_PARAMS, dtrain, num_boost_round=NUM_BOOST_ROUND)


def predict_scores(booster: xgb.Booster, samples: list[dict]) -> list[float]:
    x, _ = to_xy(samples)
    dm = xgb.DMatrix(x, feature_names=MODEL_FEATURES)
    return [float(p) for p in booster.predict(dm)]


def feature_importance(booster: xgb.Booster) -> list[dict]:
    """Gain-based importance normalized to shares of total gain (desc order)."""
    gains = booster.get_score(importance_type="gain")
    total = sum(gains.values()) or 1.0
    ranked = sorted(gains.items(), key=lambda kv: -kv[1])
    return [
        {"feature": name, "gain_share": round(value / total, 6)}
        for name, value in ranked
    ]


# ─────────────────────────────────────────────────────────────────────────────
# The experiment
# ─────────────────────────────────────────────────────────────────────────────


def _split_summary(samples: list[dict]) -> dict:
    positives = sum(s["label"] for s in samples)
    return {
        "rows": len(samples),
        "positives": positives,
        "prevalence_pct": round(positives / len(samples) * 100.0, 2),
    }


def run_experiment(splits: dict[str, list[dict]]) -> dict:
    """Train once, select the threshold on validation, evaluate all on test."""
    train_y = [s["label"] for s in splits["train"]]
    train_prevalence = sum(train_y) / len(train_y)

    # ── Fit on train only.
    booster = fit_model(splits["train"])

    # ── Scores for every method on val and test.
    val_persistence = persistence_scores(splits["val"])
    test_persistence = persistence_scores(splits["test"])
    val_days_since = days_since_active_scores(splits["val"])
    test_days_since = days_since_active_scores(splits["test"])
    val_majority = majority_baseline_scores(train_y)
    test_majority = majority_baseline_scores(train_y)

    val_model = predict_scores(booster, splits["val"])
    test_model = predict_scores(booster, splits["test"])

    # ── Threshold: selected on VALIDATION only, then frozen.
    threshold = select_threshold([s["label"] for s in splits["val"]], val_model)

    def _eval(samples, scores, threshold, hard_from_scores=False):
        y = [s["label"] for s in samples]
        if hard_from_scores:  # binary-score baselines predict their own 0/1
            y_pred = [1 if p >= 0.5 else 0 for p in scores]
        else:
            y_pred = [1 if p >= threshold else 0 for p in scores]
        return evaluate_scores(y, scores, y_pred)

    val_labels = [s["label"] for s in splits["val"]]
    test_labels = [s["label"] for s in splits["test"]]
    majority_class = 1 if train_prevalence >= 0.5 else 0

    results = {
        "target": TARGET_NAME,
        "data_provenance": "SYNTHETIC — pipeline validation only, not real-user performance",
        "seed": SEED,
        "xgboost_version": xgb.__version__,
        "model_params": MODEL_PARAMS,
        "num_boost_round": NUM_BOOST_ROUND,
        "class_weighting": (
            "none — train prevalence "
            f"{train_prevalence:.3f} is balanced; no scale_pos_weight used"
        ),
        "threshold_selection": "argmax-F1 over 0.01..0.99 grid on validation only",
        "threshold": threshold,
        "majority_class": majority_class,
        "data": {
            "splits": {name: _split_summary(rows) for name, rows in splits.items()},
        },
        "baselines": {
            "majority": {
                "definition": f"always predict {majority_class} (train majority class)",
                "val": _eval(splits["val"], val_majority, None, hard_from_scores=True),
                "test": _eval(splits["test"], test_majority, None, hard_from_scores=True),
            },
            "persistence": {
                "definition": "predict 1 iff active_today == 0",
                "val": _eval(splits["val"], val_persistence, None, hard_from_scores=True),
                "test": _eval(splits["test"], test_persistence, None, hard_from_scores=True),
            },
            "days_since_active": {
                "definition": "predict 1 iff days_since_active >= 1",
                "val": _eval(splits["val"], val_days_since, None, hard_from_scores=True),
                "test": _eval(splits["test"], test_days_since, None, hard_from_scores=True),
            },
        },
        "xgboost": {
            "val": _eval(splits["val"], val_model, threshold),
            "test": _eval(splits["test"], test_model, threshold),
        },
        "calibration": {
            "val": calibration_table(val_labels, val_model),
            "test": calibration_table(test_labels, test_model),
        },
        "feature_importance_gain": feature_importance(booster),
    }

    # ── The Phase 4B.3 headline comparison: XGBoost vs persistence on test.
    test_delta = round(
        results["xgboost"]["test"]["roc_auc"]
        - results["baselines"]["persistence"]["test"]["roc_auc"],
        6,
    )
    val_delta = round(
        results["xgboost"]["val"]["roc_auc"]
        - results["baselines"]["persistence"]["val"]["roc_auc"],
        6,
    )
    consistency = abs(
        results["xgboost"]["val"]["roc_auc"] - results["xgboost"]["test"]["roc_auc"]
    )
    results["improvement_over_persistence"] = {
        "val_roc_auc_delta": val_delta,
        "test_roc_auc_delta": test_delta,
    }
    results["success_criterion"] = {
        "rule": "test ROC-AUC >= persistence + 0.05, val/test reasonably consistent",
        "required_test_delta": SUCCESS_CRITERION_ROC_AUC_DELTA,
        "test_delta": test_delta,
        "val_test_roc_auc_gap": round(consistency, 6),
        "passed": bool(
            test_delta >= SUCCESS_CRITERION_ROC_AUC_DELTA and consistency <= 0.10
        ),
    }
    return results


def format_report(results: dict) -> str:
    """Human-readable summary of the results dict."""
    lines = [
        "── XGBoost experiment #1 (SYNTHETIC data — pipeline validation only) ──",
        f"target={results['target']} | threshold={results['threshold']} "
        f"(argmax-F1 on validation, frozen for test)",
        "",
        "split    rows  positives  prevalence%",
    ]
    for name, s in results["data"]["splits"].items():
        lines.append(f"{name:<8} {s['rows']:>5} {s['positives']:>10} {s['prevalence_pct']:>11}")

    header = f"{'method':<18} {'roc_auc':>8} {'pr_auc':>8} {'acc':>7} {'prec':>7} {'rec':>7} {'f1':>7} {'brier':>7}"
    for split in ("val", "test"):
        lines.append("")
        lines.append(f"[{split}]")
        lines.append(header)
        rows = [
            ("majority", results["baselines"]["majority"][split]),
            ("persistence", results["baselines"]["persistence"][split]),
            ("days_since_active", results["baselines"]["days_since_active"][split]),
            ("xgboost", results["xgboost"][split]),
        ]
        for name, m in rows:
            lines.append(
                f"{name:<18} {m['roc_auc']:>8.4f} {m['pr_auc']:>8.4f} "
                f"{m['accuracy']:>7.4f} {m['precision']:>7.4f} {m['recall']:>7.4f} "
                f"{m['f1']:>7.4f} {m['brier']:>7.4f}"
            )

    imp = results["feature_importance_gain"][:8]
    lines.append("")
    lines.append("top feature importance (gain share):")
    for entry in imp:
        lines.append(f"  {entry['feature']:<24} {entry['gain_share']:.4f}")

    criterion = results["success_criterion"]
    lines.append("")
    lines.append(
        f"success criterion (test ROC-AUC >= persistence + 0.05): "
        f"{'PASSED' if criterion['passed'] else 'FAILED'} "
        f"(delta={criterion['test_delta']:.4f}, val/test gap={criterion['val_test_roc_auc_gap']:.4f})"
    )
    lines.append("")
    lines.append("calibration (test): bin, n, mean_predicted, observed_rate:")
    for entry in results["calibration"]["test"]:
        if entry["n"]:
            lines.append(
                f"  {entry['bin']}  n={entry['n']:>4}  pred={entry['mean_predicted']:.3f}  obs={entry['observed_rate']:.3f}"
            )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xgboost_experiment",
        description=(
            "Train/evaluate the first XGBoost model for inactive_next_3d on "
            "SYNTHETIC data (pipeline validation only — never present results "
            "as real-user performance)."
        ),
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="raw daily dataset CSV (labels)")
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES, help="ML-ready features CSV")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS, help="results JSON output path")
    args = parser.parse_args(argv)

    splits = load_experiment_data(args.dataset, args.features)
    results = run_experiment(splits)

    args.results.parent.mkdir(parents=True, exist_ok=True)
    with args.results.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
        handle.write("\n")

    print(format_report(results))
    print()
    print(f"results written to {args.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
