"""Tests for the Phase 4B.3 ML target design (target.py).

Pure-Python tests (no DB, no FastAPI). They prove: exact label semantics,
that the label reads ONLY days D+1..D+3 of the same user, that tail rows
without a full horizon are excluded rather than imputed, that calendar-date
splits are ordered/disjoint with a train→val embargo, that train target
windows never reach into validation, and that the target is well-distributed
(both classes populated in every split) on the default synthetic dataset.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import features  # noqa: E402
import target  # noqa: E402
from generator import DATA_SOURCE, generate_dataset  # noqa: E402
from target import (
    HORIZON_DAYS,
    TARGET_NAME,
    TEST_START,
    TRAIN_END,
    VAL_START,
    assign_split,
    build_labels,
    summarize_labels,
)


def _raw_rows(steps, user_id="syn_test_0001", start=date(2025, 1, 1)):
    """Minimal raw rows with the given per-day step counts."""
    return [
        {
            "synthetic_user_id": user_id,
            "day": (start + timedelta(days=i)).isoformat(),
            "steps": s,
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
        for i, s in enumerate(steps)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Label semantics
# ─────────────────────────────────────────────────────────────────────────────


def test_label_is_1_when_2_of_next_3_days_are_inactive():
    # Days D+1..D+3 = (500, 0, 8000): two inactive -> 1.
    rows = _raw_rows([5000, 500, 0, 8000, 5000])
    labels = build_labels(rows)
    assert labels[("syn_test_0001", "2025-01-01")] == 1


def test_label_is_0_when_at_most_1_of_next_3_days_is_inactive():
    # Only one inactive day in the window -> 0 (a single rest day is not
    # "disengagement").
    rows = _raw_rows([5000, 0, 8000, 9000, 5000])
    labels = build_labels(rows)
    assert labels[("syn_test_0001", "2025-01-01")] == 0
    # All three active -> 0 as well.
    rows = _raw_rows([5000, 2000, 3000, 4000, 5000])
    assert build_labels(rows)[("syn_test_0001", "2025-01-01")] == 0


def test_label_uses_exactly_the_next_three_days():
    # Day 0's label must react to days 1..3 and be invariant to day 4+.
    base = [5000, 500, 0, 8000, 5000, 6000, 7000]
    labels = build_labels(_raw_rows(base))
    key = ("syn_test_0001", "2025-01-01")
    assert labels[key] == 1

    # Changing day 4 (D+4, outside the window) cannot change day 0's label.
    mutated = list(base)
    mutated[4] = 0
    mutated[5] = 0
    mutated[6] = 0
    assert build_labels(_raw_rows(mutated))[key] == 1

    # Changing a day INSIDE the window does change it.
    mutated = list(base)
    mutated[2] = 4000  # now only one inactive day in D+1..D+3
    assert build_labels(_raw_rows(mutated))[key] == 0


def test_tail_rows_without_full_horizon_carry_no_label():
    rows = _raw_rows([5000] * 10)
    labels = build_labels(rows)
    days = sorted(day for (_uid, day) in labels)
    # Every day is present in the mapping...
    assert len(days) == 10
    # ...but the last HORIZON_DAYS days are None, never imputed.
    for day in days[-HORIZON_DAYS:]:
        assert labels[("syn_test_0001", day)] is None
    # And the day before the tail is labeled.
    assert labels[("syn_test_0001", days[-(HORIZON_DAYS + 1)])] == 0


def test_labels_are_per_user():
    rows = _raw_rows([5000, 0, 0, 5000], user_id="syn_a_0001") + _raw_rows(
        [5000, 5000, 5000, 5000], user_id="syn_b_0001"
    )
    labels = build_labels(rows)
    assert labels[("syn_a_0001", "2025-01-01")] == 1
    assert labels[("syn_b_0001", "2025-01-01")] == 0


def test_target_is_not_part_of_the_feature_matrix():
    # The label is defined OUTSIDE features.py — nothing about it may sneak
    # into the 4B.2 feature set (the features stay purely historical).
    assert TARGET_NAME not in features.OUTPUT_COLUMNS
    assert TARGET_NAME not in features.MODEL_FEATURES


# ─────────────────────────────────────────────────────────────────────────────
# Split policy
# ─────────────────────────────────────────────────────────────────────────────


def test_split_boundaries_are_ordered_with_embargo():
    assert TRAIN_END < VAL_START  # 3-day embargo between train and val
    assert (VAL_START - TRAIN_END).days == 4  # 05-17 -> 05-21
    # VAL and TEST are contiguous, and both strictly after train.
    assert VAL_START <= target.VAL_END < TEST_START


def test_assign_split_maps_known_days():
    assert assign_split("2025-01-01") == "train"
    assert assign_split("2025-05-17") == "train"
    assert assign_split("2025-05-18") == "embargo"
    assert assign_split("2025-05-20") == "embargo"
    assert assign_split("2025-05-21") == "val"
    assert assign_split("2025-06-09") == "val"
    assert assign_split("2025-06-10") == "test"
    assert assign_split("2025-06-26") == "test"


def test_every_training_targets_window_stops_before_validation():
    # With the embargo, the latest possible training day is TRAIN_END, whose
    # 3-day target window ends 3 days later — still before VAL_START.
    assert TRAIN_END + timedelta(days=HORIZON_DAYS) < VAL_START


# ─────────────────────────────────────────────────────────────────────────────
# Distribution on the default synthetic dataset (design validation)
# ─────────────────────────────────────────────────────────────────────────────


def _default_summary():
    raw = generate_dataset(num_users=30, num_days=180, seed=42)
    return summarize_labels(raw)


def test_labeled_row_count_and_tail_exclusion():
    s = _default_summary()
    assert s["labeled_rows"] == 30 * (180 - HORIZON_DAYS)  # 5,310
    assert s["unlabeled_tail_rows"] == 30 * HORIZON_DAYS  # 90


def test_target_prevalence_is_balanced_enough():
    s = _default_summary()
    # ~45% positives overall: comfortably learnable, not degenerate.
    assert 30.0 <= s["prevalence_pct"] <= 60.0


def test_both_classes_populated_in_every_split():
    s = _default_summary()
    for name in ("train", "val", "test"):
        bucket = s["by_split"][name]
        assert bucket["rows"] > 0
        assert bucket["positives"] >= 50, name
        assert bucket["rows"] - bucket["positives"] >= 50, name


def test_mid_profiles_have_both_classes():
    s = _default_summary()
    # The mid-activity profiles must not be all-one-class (that would make
    # the target a profile-identity fingerprint).
    for profile in ("CASUAL", "LAPSED", "RETURNING"):
        bucket = s["by_profile"][profile]
        assert 20.0 <= bucket["prevalence_pct"] <= 80.0, profile


def test_summary_is_deterministic():
    assert _default_summary() == _default_summary()
