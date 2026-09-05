"""Tests for the Phase 4B.4 XGBoost experiment.

Pure-Python tests (no DB, no FastAPI). They prove the leakage safeguards the
experiment depends on: only MODEL_FEATURES enter X (no target, no metadata),
splits match the Phase 4B.3 design with the embargo intact, validation/test
are never used for fitting, the threshold comes from validation only, and
the whole experiment is deterministic. Metric helpers are unit-tested on
hand-computed values.

These tests require xgboost (a dev-only dependency, requirements-dev.txt);
they are skipped cleanly when it is absent.
"""
import sys
from pathlib import Path

import pytest

pytest.importorskip("xgboost")  # dev-only dependency; skip gracefully

sys.path.insert(0, str(Path(__file__).resolve().parent))

import xgboost_experiment as xe  # noqa: E402
from features import MODEL_FEATURES  # noqa: E402
from generator import generate_dataset  # noqa: E402
from target import TEST_START, TRAIN_END, VAL_END, VAL_START  # noqa: E402


@pytest.fixture(scope="module")
def raw_default():
    return generate_dataset(num_users=30, num_days=180, seed=42)


@pytest.fixture(scope="module")
def splits_default(raw_default):
    return xe.assemble_from_raw(raw_default)


@pytest.fixture(scope="module")
def results_default(splits_default):
    return xe.run_experiment(splits_default)


# ─────────────────────────────────────────────────────────────────────────────
# Metric helpers (hand-computed expectations)
# ─────────────────────────────────────────────────────────────────────────────


def test_roc_auc_known_values():
    # Perfect separation.
    assert xe.roc_auc([1, 0, 1, 0], [0.9, 0.1, 0.8, 0.2]) == 1.0
    # Perfectly wrong separation.
    assert xe.roc_auc([1, 0], [0.1, 0.9]) == 0.0
    # Hand-computed with a tie: positives {.8, .4}, negatives {.8, .2}.
    # (0.5 + 1 + 0 + 1) / 4 = 0.625.
    assert xe.roc_auc([1, 0, 1, 0], [0.8, 0.8, 0.4, 0.2]) == pytest.approx(0.625)
    # Single-class sets have no AUC.
    assert xe.roc_auc([1, 1], [0.3, 0.7]) is None
    assert xe.roc_auc([0, 0], [0.3, 0.7]) is None


def test_average_precision_known_values():
    # Perfect ranking.
    assert xe.average_precision([1, 0, 1], [0.9, 0.5, 0.7]) == 1.0
    # Hand-computed: thresholds .9 -> P=1,R=.5; .8 -> P=.5,R=.5; .7 -> P=2/3,R=1.
    # AP = 0.5*1 + 0 + 0.5*(2/3) = 0.8333...
    assert xe.average_precision([1, 0, 1], [0.9, 0.8, 0.7]) == pytest.approx(5 / 6)
    # All-tied scores: AP equals prevalence.
    assert xe.average_precision([1, 0, 0, 0], [0.5, 0.5, 0.5, 0.5]) == pytest.approx(0.25)
    assert xe.average_precision([0, 0], [0.1, 0.2]) is None


def test_brier_score_known_values():
    assert xe.brier_score([1, 0], [0.8, 0.2]) == pytest.approx(0.04)
    assert xe.brier_score([1, 1], [1.0, 1.0]) == 0.0


def test_classification_metrics_known_values():
    m = xe.classification_metrics([1, 0, 1, 0], [1, 1, 0, 0])
    assert m["accuracy"] == pytest.approx(0.5)
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["f1"] == pytest.approx(0.5)
    # Degenerate guards: no predicted positives / no actual positives.
    m = xe.classification_metrics([1, 0], [0, 0])
    assert m["precision"] == 0.0 and m["recall"] == 0.0 and m["f1"] == 0.0
    assert m["accuracy"] == pytest.approx(0.5)


def test_select_threshold_picks_first_grid_argmax_f1():
    # Perfect F1 is reachable only for thresholds in (.3, .7]; the first grid
    # value there is 0.31.
    y = [1, 1, 0, 0]
    p = [0.9, 0.7, 0.3, 0.1]
    assert xe.select_threshold(y, p) == 0.31
    # And it is deterministic.
    assert xe.select_threshold(y, p) == xe.select_threshold(y, p)


def test_calibration_table_known_values():
    table = xe.calibration_table([1, 1, 0, 0], [0.05, 0.15, 0.25, 0.35])
    assert table[0]["n"] == 2
    assert table[0]["mean_predicted"] == pytest.approx(0.1)
    assert table[0]["observed_rate"] == pytest.approx(1.0)  # both positives
    assert table[1]["n"] == 2
    assert table[1]["observed_rate"] == pytest.approx(0.0)  # both negatives
    # p == 1.0 lands in the last bin (inclusive upper edge).
    table = xe.calibration_table([1], [1.0])
    assert table[-1]["n"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Data assembly: X contents, sizes, splits, embargo
# ─────────────────────────────────────────────────────────────────────────────


def test_x_contains_exactly_model_features(splits_default):
    for split in ("train", "val", "test"):
        x, y = xe.to_xy(splits_default[split])
        assert all(len(row) == len(MODEL_FEATURES) == 21 for row in x)
        assert all(label in (0, 1) for label in y)
        assert len(x) == len(y)


def test_target_and_metadata_never_enter_the_feature_list():
    forbidden = {"label", "target", "synthetic_user_id", "day", "data_source"}
    assert not (forbidden & set(MODEL_FEATURES))
    # The assembled samples keep bookkeeping fields OUTSIDE the feature names.
    assert "label" not in MODEL_FEATURES
    # And to_xy projects strictly MODEL_FEATURES.
    sample = {"steps_today": 1.0, "label": 1, "synthetic_user_id": "x", "day": "d"}
    for name in MODEL_FEATURES:
        sample.setdefault(name, 0.0)
    x, y = xe.to_xy([sample])
    assert len(x[0]) == 21
    assert y == [1]


def test_split_sizes_and_prevalence_match_design(splits_default):
    expected = {
        "train": (4110, 45.5),
        "val": (600, 44.5),
        "test": (510, 46.86),
    }
    for name, (rows, prevalence) in expected.items():
        s = splits_default[name]
        assert len(s) == rows, name
        actual = sum(r["label"] for r in s) / len(s) * 100.0
        assert abs(actual - prevalence) < 0.5, name


def test_split_dates_and_embargo_are_correct(splits_default):
    days = {
        name: {r["day"] for r in rows} for name, rows in splits_default.items()
    }
    assert max(days["train"]) <= TRAIN_END.isoformat()
    assert min(days["val"]) >= VAL_START.isoformat()
    assert max(days["val"]) <= VAL_END.isoformat()
    assert min(days["test"]) >= TEST_START.isoformat()
    # Disjoint, ordered, and no embargo day (2025-05-18..20) survives.
    assert not (days["train"] & days["val"] or days["val"] & days["test"])
    for d in ("2025-05-18", "2025-05-19", "2025-05-20"):
        assert d not in days["train"] | days["val"] | days["test"]


def test_no_future_rows_leak_into_assembled_features(raw_default, splits_default):
    user_id = raw_default[0]["synthetic_user_id"]
    cutoff = "2025-02-15"  # compare days whose features AND label window end earlier

    tampered = []
    for row in raw_default:
        copy = dict(row)
        if copy["synthetic_user_id"] == user_id and copy["day"] > cutoff:
            copy["steps"] = int(copy["steps"]) * 1000 + 7
            copy["hexes_captured"] = int(copy["hexes_captured"]) + 3
            copy["defense_steps"] = int(copy["defense_steps"]) * 99
        tampered.append(copy)

    def _features_of(splits, before):
        return [
            tuple(r[name] for name in MODEL_FEATURES)
            for split in splits.values()
            for r in split
            if r["synthetic_user_id"] == user_id and r["day"] <= before
        ]

    assert _features_of(splits_default, cutoff) == _features_of(
        xe.assemble_from_raw(tampered), cutoff
    )


def test_persistence_scores_follow_definition(splits_default):
    for split in ("train", "val", "test"):
        for sample, score in zip(
            splits_default[split], xe.persistence_scores(splits_default[split])
        ):
            expected = 1.0 if sample["active_today"] == 0.0 else 0.0
            assert score == expected


# ─────────────────────────────────────────────────────────────────────────────
# Fitting / threshold discipline
# ─────────────────────────────────────────────────────────────────────────────


def test_validation_labels_cannot_affect_the_fitted_model(splits_default):
    # fit_model receives TRAIN rows only (structural), so corrupting the
    # validation labels cannot change the model or its probability outputs.
    booster = xe.fit_model(splits_default["train"])
    probs_before = xe.predict_scores(booster, splits_default["val"])

    corrupted_val = [dict(r, label=1 - r["label"]) for r in splits_default["val"]]
    corrupted = {**splits_default, "val": corrupted_val}
    booster2 = xe.fit_model(corrupted["train"])
    probs_after = xe.predict_scores(booster2, corrupted_val)

    assert probs_before == probs_after


def test_threshold_is_selected_on_validation_only(splits_default, results_default):
    # Recompute the pipeline's threshold from val data alone: same answer.
    booster = xe.fit_model(splits_default["train"])
    val_p = xe.predict_scores(booster, splits_default["val"])
    val_y = [r["label"] for r in splits_default["val"]]
    assert results_default["threshold"] == xe.select_threshold(val_y, val_p)


def test_test_labels_cannot_change_the_threshold(splits_default, results_default):
    corrupted_test = [dict(r, label=1 - r["label"]) for r in splits_default["test"]]
    rerun = xe.run_experiment({**splits_default, "test": corrupted_test})
    assert rerun["threshold"] == results_default["threshold"]


# ─────────────────────────────────────────────────────────────────────────────
# Experiment-level behavior
# ─────────────────────────────────────────────────────────────────────────────


def test_experiment_is_deterministic(splits_default, results_default):
    assert xe.run_experiment(splits_default) == results_default


def test_results_shape_and_success_criterion(results_default):
    for key in (
        "target",
        "threshold",
        "model_params",
        "class_weighting",
        "baselines",
        "xgboost",
        "calibration",
        "feature_importance_gain",
        "improvement_over_persistence",
        "success_criterion",
    ):
        assert key in results_default
    assert results_default["target"] == "inactive_next_3d"
    # All three methods have full metric blocks on both val and test.
    for method in ("majority", "persistence", "days_since_active"):
        for split in ("val", "test"):
            metrics = results_default["baselines"][method][split]
            for name in ("roc_auc", "pr_auc", "accuracy", "precision", "recall", "f1", "brier"):
                assert name in metrics
    for split in ("val", "test"):
        for name in ("roc_auc", "pr_auc", "accuracy", "precision", "recall", "f1", "brier"):
            assert name in results_default["xgboost"][split]
    # The criterion verdict is a computed boolean consistent with its inputs.
    criterion = results_default["success_criterion"]
    delta = results_default["improvement_over_persistence"]["test_roc_auc_delta"]
    assert criterion["passed"] == (delta >= 0.05 and criterion["val_test_roc_auc_gap"] <= 0.10)


def test_feature_importance_sums_to_one(results_default):
    shares = [entry["gain_share"] for entry in results_default["feature_importance_gain"]]
    assert shares, "importance list must not be empty"
    assert sum(shares) == pytest.approx(1.0, abs=1e-4)
    assert shares == sorted(shares, reverse=True)
    # Only real model features appear.
    assert {entry["feature"] for entry in results_default["feature_importance_gain"]} <= set(MODEL_FEATURES)


def test_persistence_and_days_since_baseline_are_identical_by_construction(results_default):
    # days_since_active == 0 exactly when today is active, so
    # "days_since_active >= 1" is mathematically the same rule as
    # persistence — documented as an observation in the experiment report.
    for split in ("val", "test"):
        assert (
            results_default["baselines"]["persistence"][split]
            == results_default["baselines"]["days_since_active"][split]
        )


def test_results_json_round_trips(tmp_path, results_default):
    import json

    path = tmp_path / "results.json"
    path.write_text(json.dumps(results_default, indent=2), encoding="utf-8")
    reread = json.loads(path.read_text(encoding="utf-8"))
    assert reread == results_default
