"""Tests for the synthetic-fitness feature-engineering pipeline.

Pure-Python tests (no DB, no FastAPI). They prove the properties that matter
for ML readiness: determinism, exact rolling-window semantics, NO temporal
leakage, user isolation, expanding early-history windows, no metadata in the
model feature list, and CSV round-tripping.
"""
import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import features  # noqa: E402
import generator  # noqa: E402
from features import (  # noqa: E402
    EXCLUDED_METADATA,
    FEATURE_MANIFEST,
    METADATA_COLUMNS,
    MODEL_FEATURES,
    OUTPUT_COLUMNS,
    build_features,
    read_features,
    write_features,
)
from generator import DATA_SOURCE, STREAK_MIN_STEPS, generate_dataset  # noqa: E402

SEED = 42
N_USERS, N_DAYS = 30, 180

# Feature names the Phase 4B.2 spec requires to exist.
REQUIRED_FEATURES = {
    "steps_today",
    "active_minutes_today",
    "steps_3d_avg",
    "steps_7d_avg",
    "active_minutes_3d_avg",
    "active_minutes_7d_avg",
    "activity_days_7d",
    "steps_change_vs_7d_avg",
    "current_streak",
    "goal_completion_rate_7d",
    "days_since_active",
    "hexes_owned",
    "captures_7d",
    "losses_7d",
    "territory_change_7d",
    "defense_steps_7d",
    "defense_ratio_7d",
    "goal_steps",
    "goal_completed_today",
}


def _default_raw():
    return generate_dataset(num_users=N_USERS, num_days=N_DAYS, seed=SEED)


def _by_user(rows):
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["synthetic_user_id"], []).append(row)
    return grouped


# A small hand-crafted history whose features can be verified by hand.
_HAND_STEPS = [1500, 200, 3000, 0, 8000, 1200, 400, 6000, 1000, 500]
_HAND_MINUTES = [15, 0, 30, 0, 80, 12, 0, 60, 10, 0]
_HAND_OWNED = [1, 1, 2, 2, 2, 3, 3, 3, 4, 4]
_HAND_CAPTURED = [1, 0, 1, 0, 0, 1, 0, 0, 1, 0]
_HAND_DEFENSE = [100, 0, 200, 0, 500, 50, 0, 300, 100, 0]
_HAND_STREAK = [1, 0, 1, 0, 1, 1, 0, 1, 1, 0]
_HAND_GOAL = 2000


def _hand_rows(user_id="syn_test_0001"):
    rows = []
    for i in range(10):
        rows.append(
            {
                "synthetic_user_id": user_id,
                "day": (date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                "steps": _HAND_STEPS[i],
                "active_minutes": _HAND_MINUTES[i],
                "hexes_owned": _HAND_OWNED[i],
                "hexes_captured": _HAND_CAPTURED[i],
                "hexes_lost": 0,
                "defense_steps": _HAND_DEFENSE[i],
                "streak": _HAND_STREAK[i],
                "goal_steps": _HAND_GOAL,
                "goal_completed": 1 if _HAND_STEPS[i] >= _HAND_GOAL else 0,
                "data_source": DATA_SOURCE,
            }
        )
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Schema / counts / columns
# ─────────────────────────────────────────────────────────────────────────────


def test_expected_output_row_count():
    # One ML row per (user, day): nothing is dropped, early days included.
    feats = build_features(_default_raw())
    assert len(feats) == N_USERS * N_DAYS
    by_user = _by_user(feats)
    assert len(by_user) == N_USERS
    for rows in by_user.values():
        assert len(rows) == N_DAYS


def test_expected_feature_columns():
    assert OUTPUT_COLUMNS == METADATA_COLUMNS + MODEL_FEATURES + ["data_source"]
    assert REQUIRED_FEATURES.issubset(set(MODEL_FEATURES))
    # Exactly the two justified extras beyond the spec's required set.
    extras = set(MODEL_FEATURES) - REQUIRED_FEATURES
    assert extras == {"active_today", "goal_progress_ratio"}
    assert len(MODEL_FEATURES) == 21


def test_feature_rows_carry_metadata_and_label():
    feats = build_features(_hand_rows())
    assert all(r["data_source"] == "synthetic" for r in feats)
    assert all(r["synthetic_user_id"] == "syn_test_0001" for r in feats)
    assert [r["day"] for r in feats] == sorted(r["day"] for r in feats)


def test_build_features_accepts_csv_strings_and_ints():
    # The CLI rereads the raw CSV (all strings); build_features must produce
    # identical output as from the generator's int rows.
    from generator import write_dataset

    raw = _default_raw()[:50]
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = write_dataset(raw, Path(tmp) / "raw.csv")
        reread = generator.read_dataset(path)
        assert build_features(reread) == build_features(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────────────────────────────────────


def test_deterministic_output():
    raw = _default_raw()
    assert build_features(raw) == build_features(raw)


def test_written_csv_is_byte_identical_across_runs(tmp_path):
    raw = _default_raw()
    a = write_features(build_features(raw), tmp_path / "a.csv")
    b = write_features(build_features(raw), tmp_path / "b.csv")
    assert a.read_bytes() == b.read_bytes()


# ─────────────────────────────────────────────────────────────────────────────
# Rolling-window correctness (hand-computed expectations)
# ─────────────────────────────────────────────────────────────────────────────


def test_rolling_windows_match_hand_computed_values():
    feats = build_features(_hand_rows())
    d6 = feats[6]  # 2025-01-07, the spec's worked example day

    # steps_7d_avg on 2025-01-07 = mean(2025-01-01 .. 2025-01-07)
    assert d6["steps_7d_avg"] == pytest.approx(
        sum(_HAND_STEPS[0:7]) / 7
    )  # = 2042.857...
    assert d6["steps_3d_avg"] == pytest.approx(sum(_HAND_STEPS[4:7]) / 3)  # 3200
    assert d6["active_minutes_7d_avg"] == pytest.approx(sum(_HAND_MINUTES[0:7]) / 7)
    assert d6["active_minutes_3d_avg"] == pytest.approx(sum(_HAND_MINUTES[4:7]) / 3)

    # Activity days: >= 1000 steps within days 0..6 -> 1500, 3000, 8000, 1200.
    assert d6["activity_days_7d"] == 4

    # steps_change_vs_7d_avg = today - mean of the PREVIOUS 7 days (0..5).
    assert d6["steps_change_vs_7d_avg"] == pytest.approx(
        400 - sum(_HAND_STEPS[0:6]) / 6
    )

    # Consistency.
    assert d6["current_streak"] == 0
    assert d6["goal_completion_rate_7d"] == pytest.approx(2 / 7)  # days 2 and 4
    assert d6["days_since_active"] == 1  # day 5 was active, day 6 was not

    # Territory (as of end of day 6).
    assert d6["hexes_owned"] == 3
    assert d6["captures_7d"] == 3  # days 0, 2, 5
    assert d6["losses_7d"] == 0
    assert d6["territory_change_7d"] == 3 - 0  # baseline 0 before history start
    assert d6["defense_steps_7d"] == 850
    # Features are rounded to 6 decimals — compare with an absolute tolerance.
    assert d6["defense_ratio_7d"] == pytest.approx(
        850 / sum(_HAND_STEPS[0:7]), abs=1e-6
    )

    # Goals + derived extras.
    assert d6["goal_steps"] == 2000
    assert d6["goal_completed_today"] == 0
    assert d6["active_today"] == 0
    assert d6["goal_progress_ratio"] == pytest.approx(400 / 2000)


def test_full_windows_slide_and_use_the_oldest_dropped_day():
    feats = build_features(_hand_rows())
    # Day 7 (index 7): the 7-day window is days 1..7 — day 0 has slid out.
    assert feats[7]["steps_7d_avg"] == pytest.approx(sum(_HAND_STEPS[1:8]) / 7)
    # territory_change_7d at index 7 = owned[7] - owned[0].
    assert feats[7]["territory_change_7d"] == 3 - 1
    # steps_change_vs_7d_avg at index 7 = steps[7] - mean(steps[0..6]).
    assert feats[7]["steps_change_vs_7d_avg"] == pytest.approx(
        6000 - sum(_HAND_STEPS[0:7]) / 7
    )


def test_early_history_uses_expanding_windows():
    feats = build_features(_hand_rows())
    first = feats[0]
    # First day: every rolling feature is just that day's value — no dropping.
    assert first["steps_7d_avg"] == first["steps_3d_avg"] == 1500
    assert first["active_minutes_7d_avg"] == first["active_minutes_3d_avg"] == 15
    assert first["activity_days_7d"] == 1
    assert first["goal_completion_rate_7d"] == 0.0
    assert first["days_since_active"] == 0  # active today
    assert first["steps_change_vs_7d_avg"] == 0.0  # no baseline yet
    assert first["territory_change_7d"] == 1  # owned[0] - 0

    # Second day: 3-day window is days 0..1 (partial), correctly averaged.
    assert feats[1]["steps_3d_avg"] == pytest.approx((1500 + 200) / 2)


def test_days_since_active_semantics():
    feats = build_features(_hand_rows())
    assert feats[0]["days_since_active"] == 0  # active day
    assert feats[1]["days_since_active"] == 1  # yesterday was active
    # Days 3 is inactive and day 2 was active -> 1; day 6 -> 1 (day 5 active).
    assert feats[3]["days_since_active"] == 1
    assert feats[6]["days_since_active"] == 1

    never = build_features(
        [
            {
                "synthetic_user_id": "syn_test_0002",
                "day": (date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                "steps": 100,
                "active_minutes": 0,
                "hexes_owned": 0,
                "hexes_captured": 0,
                "hexes_lost": 0,
                "defense_steps": 0,
                "streak": 0,
                "goal_steps": 2000,
                "goal_completed": 0,
                "data_source": DATA_SOURCE,
            }
            for i in range(5)
        ]
    )
    # Never active: days since the (nonexistent) last active day = index + 1.
    assert [r["days_since_active"] for r in never] == [1, 2, 3, 4, 5]


def test_current_streak_passes_through_raw_streak():
    feats = build_features(_default_raw())
    raw_by_user = _by_user(_default_raw())
    for row in feats:
        matching = raw_by_user[row["synthetic_user_id"]]
        idx = [r["day"] for r in matching].index(row["day"])
        assert row["current_streak"] == matching[idx]["streak"]


# ─────────────────────────────────────────────────────────────────────────────
# Leakage: no future rows, no cross-user rows
# ─────────────────────────────────────────────────────────────────────────────


def _perturb_future(rows, user_id, from_index, factor=1000):
    """Deep-copy rows, wildly inflating user_id's rows STRICTLY AFTER
    from_index. If any feature for day <= from_index changes, the pipeline
    leaks future information."""
    out, i = [], -1
    for row in rows:
        copy = dict(row)
        if copy["synthetic_user_id"] == user_id:
            i += 1
            if i > from_index:
                for field in (
                    "steps",
                    "active_minutes",
                    "hexes_captured",
                    "hexes_lost",
                    "defense_steps",
                ):
                    copy[field] = copy[field] * factor + 7
                copy["hexes_owned"] = copy["hexes_owned"] + 50
                copy["goal_completed"] = 1
                copy["streak"] = 99
        out.append(copy)
    return out


def test_no_future_rows_contribute_to_any_feature():
    raw = _default_raw()
    user_id = raw[0]["synthetic_user_id"]
    cutoff = 100  # a day well inside the history

    original = _by_user(build_features(raw))[user_id]
    perturbed = _by_user(build_features(_perturb_future(raw, user_id, cutoff)))[user_id]

    # Every feature row up to and including the cutoff day is IDENTICAL.
    assert original[: cutoff + 1] == perturbed[: cutoff + 1]
    # Sanity: the perturbation really does change later days (it is not a no-op).
    assert original[cutoff + 1] != perturbed[cutoff + 1]


def test_user_histories_remain_isolated():
    raw = _default_raw()
    user_a = raw[0]["synthetic_user_id"]
    user_b = raw[-1]["synthetic_user_id"]
    assert user_a != user_b

    original = build_features(raw)
    # Wildly rewrite user_b's entire history; user_a's features must not move.
    tampered = []
    for row in raw:
        copy = dict(row)
        if copy["synthetic_user_id"] == user_b:
            for field in ("steps", "active_minutes", "hexes_captured", "defense_steps"):
                copy[field] = copy[field] * 999 + 13
        tampered.append(copy)

    a_before = _by_user(original)[user_a]
    a_after = _by_user(build_features(tampered))[user_a]
    assert a_before == a_after


def test_rolling_features_use_only_current_and_past_data():
    # Direct restatement on the hand dataset: day 6's every rolling feature is
    # a function of raw days 0..6 only. Remove days 7..9 entirely and day 6's
    # feature row must be unchanged.
    full = build_features(_hand_rows())
    truncated = build_features(_hand_rows()[:7])
    assert full[6] == truncated[6]


# ─────────────────────────────────────────────────────────────────────────────
# Metadata exclusion & manifest
# ─────────────────────────────────────────────────────────────────────────────


def test_metadata_not_in_model_features():
    for column in EXCLUDED_METADATA:
        assert column not in MODEL_FEATURES
    # And the metadata columns are exactly the non-feature output columns.
    assert set(OUTPUT_COLUMNS) - set(MODEL_FEATURES) == set(EXCLUDED_METADATA)


def test_manifest_is_complete_and_consistent():
    entries = {entry["feature_name"]: entry for entry in FEATURE_MANIFEST}
    # Every output column appears exactly once in the manifest.
    assert len(FEATURE_MANIFEST) == len(entries) == len(OUTPUT_COLUMNS)
    assert set(entries) == set(OUTPUT_COLUMNS)
    # Model features are exactly the manifest entries allowed for training.
    allowed = {
        name for name, entry in entries.items() if entry["allowed_for_training"]
    }
    assert allowed == set(MODEL_FEATURES)
    # Metadata is explicitly disallowed for training.
    for column in EXCLUDED_METADATA:
        assert entries[column]["allowed_for_training"] is False
    # Every training entry documents its window and description.
    for name in MODEL_FEATURES:
        entry = entries[name]
        assert entry["window"]
        assert entry["description"]
        assert entry["source_fields"]


# ─────────────────────────────────────────────────────────────────────────────
# Value sanity
# ─────────────────────────────────────────────────────────────────────────────


def test_no_nan_or_invalid_values():
    feats = build_features(_default_raw())
    for row in feats:
        for name in MODEL_FEATURES:
            value = row[name]
            assert isinstance(value, (int, float))
            assert math.isfinite(value)
        # Bounded ratio/rate features stay in [0, 1] by construction.
        assert 0.0 <= row["goal_completion_rate_7d"] <= 1.0
        assert 0.0 <= row["defense_ratio_7d"] <= 1.0
        assert row["activity_days_7d"] >= 0
        assert row["current_streak"] >= 0
        assert row["days_since_active"] >= 0
        assert row["active_minutes_today"] <= row["steps_today"]


def test_no_ml_target_is_defined():
    # Phase 4B.2 must NOT introduce a target/label column.
    forbidden = {"target", "label", "recommendation", "coach_action"}
    assert not (forbidden & set(OUTPUT_COLUMNS))
    assert not (forbidden & set(MODEL_FEATURES))


# ─────────────────────────────────────────────────────────────────────────────
# CSV round-trip
# ─────────────────────────────────────────────────────────────────────────────


def test_output_csv_round_trips(tmp_path):
    raw = _default_raw()
    feats = build_features(raw)
    out = write_features(feats, tmp_path / "features.csv")

    reread = read_features(out)
    assert len(reread) == len(feats)
    assert list(reread[0].keys()) == OUTPUT_COLUMNS
    assert all(r["data_source"] == "synthetic" for r in reread)
    # Numeric fields survive the round trip (string form of the same values).
    for fresh, original in zip(reread, feats):
        for name in MODEL_FEATURES:
            assert float(fresh[name]) == float(original[name])


def test_manifest_json_round_trips(tmp_path):
    import json

    path = features.write_manifest(tmp_path / "manifest.json", source_path="raw.csv")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["n_model_features"] == len(MODEL_FEATURES)
    assert doc["model_features"] == MODEL_FEATURES
    assert len(doc["features"]) == len(OUTPUT_COLUMNS)
    assert doc["target"].startswith("None by design")
