"""Tests for the synthetic FitQuest fitness dataset simulator.

These are pure-Python tests (no DB, no FastAPI, no DATABASE_URL needed).
They run from anywhere as long as ``generator.py``'s directory is on
sys.path, which the bootstrap below guarantees regardless of how pytest
is invoked.
"""
import csv as csv_module
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import generator  # noqa: E402
from generator import (  # noqa: E402
    ACTIVE_MINUTES_FLOOR_STEPS,
    COLUMNS,
    DATA_SOURCE,
    MAX_STEPS,
    PROFILE_NAMES,
    STREAK_MIN_STEPS,
    generate_dataset,
    generate_user_days,
    read_dataset,
    summarize_dataset,
    write_dataset,
)

# Fixed seeds make every assertion deterministic across runs.
SEED_A = 42
SEED_B = 1234

# Every profile's fixed daily step goal (canonical, keyed to the specs).
VALID_GOALS = {2000, 4500, 5000, 5500, 6000, 8000, 10000}

REQUIRED_COLUMNS = {
    "synthetic_user_id",
    "day",
    "steps",
    "active_minutes",
    "hexes_owned",
    "hexes_captured",
    "hexes_lost",
    "defense_steps",
    "streak",
    "goal_steps",
    "goal_completed",
    "data_source",
}

# Profiles whose single-user chains are asserted to separate cleanly (big,
# seed-stable margins — see test_profile_activity_ordering_*).
ACTIVE_CHAIN = ["INACTIVE", "CASUAL", "CONSISTENT", "HIGHLY_ACTIVE"]


def _rows_by_user(rows):
    """Group rows into ordered per-user lists keyed by synthetic_user_id."""
    by_user: dict[str, list[dict]] = {}
    for row in rows:
        by_user.setdefault(row["synthetic_user_id"], []).append(row)
    return by_user


def _mean(rows, key):
    return statistics.mean(float(row[key]) for row in rows)


def _goal_completion(rows):
    return statistics.mean(float(row["goal_completed"]) for row in rows)


def _profile_history(profile_name, days=180, seed=7):
    """One full history for a profile under a fixed seed."""
    return generate_user_days(profile_name, f"syn_{profile_name.lower()}_0001", days, seed=seed)


# ─────────────────────────────────────────────────────────────────────────────
# Determinism & variation
# ─────────────────────────────────────────────────────────────────────────────


def test_same_seed_produces_identical_data():
    a = generate_dataset(num_users=8, num_days=30, seed=SEED_A)
    b = generate_dataset(num_users=8, num_days=30, seed=SEED_A)
    assert a == b


def test_different_seed_produces_different_data():
    a = generate_dataset(num_users=8, num_days=30, seed=SEED_A)
    b = generate_dataset(num_users=8, num_days=30, seed=SEED_B)
    assert a != b


def test_users_do_not_all_look_identical():
    # Mix of profiles + intra-profile randomness -> at least a few distinct
    # step totals appear on the same day index across users.
    rows = generate_dataset(num_users=10, num_days=60, seed=SEED_A)
    by_user = _rows_by_user(rows)
    assert len(by_user) == 10
    day_zero_steps = {user_rows[0]["steps"] for user_rows in by_user.values()}
    assert len(day_zero_steps) > 1


# ─────────────────────────────────────────────────────────────────────────────
# Schema / counts / labeling
# ─────────────────────────────────────────────────────────────────────────────


def test_required_columns_exist():
    rows = generate_dataset(num_users=3, num_days=10, seed=SEED_A)
    assert REQUIRED_COLUMNS.issubset(rows[0].keys())
    assert list(rows[0].keys()) == COLUMNS  # canonical order preserved


def test_requested_user_and_day_counts_respected():
    rows = generate_dataset(num_users=5, num_days=20, seed=SEED_A)
    by_user = _rows_by_user(rows)
    assert len(rows) == 5 * 20
    assert len(by_user) == 5
    for user_rows in by_user.values():
        assert len(user_rows) == 20


def test_day_is_a_contiguous_date_sequence_per_user():
    rows = generate_dataset(num_users=4, num_days=25, seed=SEED_A)
    for user_rows in _rows_by_user(rows).values():
        days = [row["day"] for row in user_rows]
        assert days == sorted(days)
        assert len(set(days)) == len(days)


def test_data_source_is_always_synthetic():
    rows = generate_dataset(num_users=6, num_days=15, seed=SEED_A)
    assert all(row["data_source"] == DATA_SOURCE == "synthetic" for row in rows)


def test_csv_output_round_trips(tmp_path):
    rows = generate_dataset(num_users=2, num_days=5, seed=SEED_A)
    out = write_dataset(rows, tmp_path / "subset.csv")

    with out.open(newline="", encoding="utf-8") as handle:
        reader = csv_module.reader(handle)
        header = next(reader)
        body = list(reader)
    assert header == COLUMNS
    assert len(body) == 10

    # read_dataset must round-trip the same number of rows.
    reread = read_dataset(out)
    assert len(reread) == len(rows)
    for fresh, original in zip(reread, rows):
        assert set(fresh.keys()) == set(original.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Logical constraints
# ─────────────────────────────────────────────────────────────────────────────


def test_hexes_owned_never_negative_and_ledger_recomputes():
    # Recompute each user's ledger independently and assert it matches the
    # stored end-of-day holdings exactly: owned_t = owned_{t-1} + captured - lost.
    rows = generate_dataset(num_users=10, num_days=120, seed=SEED_A)
    for user_rows in _rows_by_user(rows).values():
        expected = 0
        for row in user_rows:
            assert row["hexes_owned"] >= 0
            assert row["hexes_owned"] == expected + row["hexes_captured"] - row["hexes_lost"]
            expected = row["hexes_owned"]


def test_hexes_lost_never_exceed_territory_held_at_day_start():
    rows = generate_dataset(num_users=10, num_days=120, seed=SEED_A)
    for user_rows in _rows_by_user(rows).values():
        held = 0
        for row in user_rows:
            assert row["hexes_lost"] <= held
            held = row["hexes_owned"]


def test_goal_completed_is_derived_from_steps():
    rows = generate_dataset(num_users=6, num_days=40, seed=SEED_A)
    for row in rows:
        assert row["goal_completed"] in (0, 1)
        expected = 1 if row["steps"] >= row["goal_steps"] else 0
        assert row["goal_completed"] == expected


def test_streak_reflects_consecutive_active_days():
    # Streak is recomputable purely from steps: it resets below the activity
    # bar and increments on each consecutive day above it.
    rows = generate_dataset(num_users=8, num_days=90, seed=SEED_A)
    for user_rows in _rows_by_user(rows).values():
        streak = 0
        for row in user_rows:
            streak = streak + 1 if row["steps"] >= STREAK_MIN_STEPS else 0
            assert row["streak"] == streak


def test_defense_steps_bounded_and_only_with_territory():
    rows = generate_dataset(num_users=8, num_days=60, seed=SEED_A)
    for user_rows in _rows_by_user(rows).values():
        held = 0
        for row in user_rows:
            assert 0 <= row["defense_steps"] <= row["steps"]
            if held == 0:
                assert row["defense_steps"] == 0
            held = row["hexes_owned"]


def test_values_are_bounded_and_realistic():
    rows = generate_dataset(num_users=30, num_days=60, seed=SEED_A)
    for row in rows:
        assert 0 <= row["steps"] <= MAX_STEPS
        assert 0 <= row["active_minutes"] <= row["steps"]
        assert row["goal_steps"] in VALID_GOALS
        assert 0 <= row["hexes_captured"] <= 4
        assert 0 <= row["hexes_lost"] <= 2
        assert 0 <= row["streak"] <= 60
        assert 0 <= row["defense_steps"] <= row["steps"]


def test_inactive_rest_days_stay_below_the_activity_bar():
    # A forced/rest day (steps drawn from the rest range) must never count as
    # meaningfully active for streak/capture purposes.
    rows = generate_dataset(num_users=4, num_days=30, seed=SEED_A)
    for row in rows:
        if row["steps"] == 0:
            continue
        # Rest-range steps are possible, but a day below the bar cannot have a capture.
        if row["steps"] < STREAK_MIN_STEPS:
            assert row["hexes_captured"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# steps <-> active_minutes relationship (the corrected quality target)
# ─────────────────────────────────────────────────────────────────────────────

# Default full dataset used by the minutes tests below.
def _default_dataset():
    return generate_dataset(num_users=30, num_days=180, seed=SEED_A)


def test_active_minutes_zero_only_below_the_activity_floor():
    # The model guarantees: steps < floor  -> 0 minutes (incidental only);
    # steps >= floor -> >= 1 minute. So a low-activity day is the *only* kind
    # that can show zero minutes.
    rows = _default_dataset()
    for row in rows:
        steps = row["steps"]
        minutes = row["active_minutes"]
        if steps < ACTIVE_MINUTES_FLOOR_STEPS:
            assert minutes == 0
        else:
            assert minutes >= 1
            assert minutes <= steps  # a day of walking can't exceed its own steps


def test_high_steps_never_have_zero_active_minutes():
    # The concrete defect from the review: "steps = 35,860, active_minutes = 0".
    # High-step days must always carry active minutes.
    rows = _default_dataset()
    assert sum(1 for r in rows if r["steps"] > 10000) > 0  # metric is meaningful
    assert all(r["active_minutes"] > 0 for r in rows if r["steps"] > 10000)
    assert all(r["active_minutes"] > 0 for r in rows if r["steps"] > 20000)


def test_active_minutes_increase_with_steps():
    # Not perfectly deterministic: minutes are steps * bout_share / cadence with
    # per-day noise, so the correlation is strong but well below 1.0. Bucket
    # means must rise with steps and the Pearson r must sit in a healthy band.
    rows = _default_dataset()
    high = [float(r["active_minutes"]) for r in rows if r["steps"] >= 12000]
    low = [float(r["active_minutes"]) for r in rows if 1000 <= r["steps"] < 6000]
    assert len(high) > 0 and len(low) > 0
    assert statistics.mean(high) > statistics.mean(low)

    steps = [float(r["steps"]) for r in rows]
    minutes = [float(r["active_minutes"]) for r in rows]
    r = statistics.correlation(steps, minutes)
    # Strongly (but not perfectly) correlated: ~0.95 with the noise model.
    assert 0.85 <= r < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# summarize_dataset / data-quality validation
# ─────────────────────────────────────────────────────────────────────────────


def test_summarize_dataset_shape_and_zero_red_flags():
    summary = summarize_dataset(_default_dataset())
    assert summary["n_rows"] == 30 * 180
    assert summary["n_users"] == 30
    # Both red-flag metrics are structurally impossible now.
    assert summary["pct_steps_over_10k_zero_active_minutes"] == 0.0
    assert summary["pct_steps_over_20k_zero_active_minutes"] == 0.0
    assert 0.85 <= summary["steps_active_minutes_pearson_r"] < 1.0
    assert 0.0 <= summary["goal_completion_pct"] <= 100.0
    assert summary["steps_min"] >= 0
    assert summary["steps_max"] <= MAX_STEPS
    # Every canonical profile is reported (default dataset guarantees coverage).
    assert set(summary["by_profile"].keys()) == set(PROFILE_NAMES)


def test_summarize_reports_distinct_profile_statistics():
    # On the default deterministic dataset the per-profile step/minute/goal
    # means separate in the intended, human-plausible order (large margins).
    by = summarize_dataset(_default_dataset())["by_profile"]

    def steps(name):
        return by[name]["avg_steps"]

    def minutes(name):
        return by[name]["avg_active_minutes"]

    # Most-active -> least-active step ladder.
    assert steps("INACTIVE") < steps("CASUAL")
    assert steps("CASUAL") < steps("CONSISTENT")
    assert steps("CONSISTENT") < steps("HIGHLY_ACTIVE")
    # Gap profiles spend a forced-inactive window, so they sit below CONSISTENT.
    assert steps("LAPSED") < steps("CONSISTENT")
    assert steps("RETURNING") < steps("CONSISTENT")

    # Active minutes follow the same ladder.
    assert minutes("INACTIVE") < minutes("CASUAL")
    assert minutes("CASUAL") < minutes("CONSISTENT")
    assert minutes("CONSISTENT") < minutes("HIGHLY_ACTIVE")

    # Territory profiles hold far more hexes than a mostly-sedentary profile
    # and than the general CONSISTENT walker (cap 30 vs cap 14).
    assert by["INACTIVE"]["avg_hexes_owned"] < by["CASUAL"]["avg_hexes_owned"]
    assert by["CONSISTENT"]["avg_hexes_owned"] < by["TERRITORY_FOCUSED"]["avg_hexes_owned"]
    # And the sedentary profile barely ever completes a goal.
    assert by["INACTIVE"]["goal_completion_pct"] < 1.0


def test_format_summary_is_renderable():
    summary = summarize_dataset(_default_dataset())
    text = generator.format_summary(summary)
    assert "DATA-QUALITY" in text.upper()
    assert "HIGHLY_ACTIVE" in text
    assert str(summary["n_rows"]) in text


def test_summarize_dataset_rejects_empty():
    with pytest.raises(ValueError):
        summarize_dataset([])


# ─────────────────────────────────────────────────────────────────────────────
# Profile behavior
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("profile_name", PROFILE_NAMES)
def test_every_required_profile_can_be_generated(profile_name):
    rows = generate_user_days(profile_name, f"syn_{profile_name.lower()}_0001", 20, seed=1)
    assert len(rows) == 20
    assert all(row["data_source"] == "synthetic" for row in rows)
    assert {row["synthetic_user_id"] for row in rows} == {f"syn_{profile_name.lower()}_0001"}


def test_profile_activity_ordering_is_stable():
    # Single-user histories under one seed: mean steps and mean active minutes
    # must separate INACTIVE < CASUAL < CONSISTENT < HIGHLY_ACTIVE with margins
    # far too large to be noise (verified across several seeds).
    rows = {name: _profile_history(name) for name in ACTIVE_CHAIN}

    for name in ACTIVE_CHAIN:
        assert any(r["steps"] >= ACTIVE_MINUTES_FLOOR_STEPS for r in rows[name])

    steps_means = {name: _mean(rows[name], "steps") for name in ACTIVE_CHAIN}
    minutes_means = {name: _mean(rows[name], "active_minutes") for name in ACTIVE_CHAIN}

    assert steps_means["INACTIVE"] < steps_means["CASUAL"]
    assert steps_means["CASUAL"] < steps_means["CONSISTENT"]
    assert steps_means["CONSISTENT"] < steps_means["HIGHLY_ACTIVE"]

    assert minutes_means["INACTIVE"] < minutes_means["CASUAL"]
    assert minutes_means["CASUAL"] < minutes_means["CONSISTENT"]
    assert minutes_means["CONSISTENT"] < minutes_means["HIGHLY_ACTIVE"]


def test_goal_and_streak_ordering_is_stable():
    rows = {name: _profile_history(name) for name in ACTIVE_CHAIN}

    goal_rates = {name: _goal_completion(rows[name]) for name in ACTIVE_CHAIN}
    streak_means = {name: _mean(rows[name], "streak") for name in ACTIVE_CHAIN}

    # Near-zero completion for the sedentary profile; strictly increasing for
    # the active ladder.
    assert goal_rates["INACTIVE"] < goal_rates["CASUAL"]
    assert goal_rates["CASUAL"] < goal_rates["CONSISTENT"]
    assert goal_rates["CONSISTENT"] < goal_rates["HIGHLY_ACTIVE"]

    # Streaks also rise with activity consistency.
    assert streak_means["INACTIVE"] < streak_means["CASUAL"]
    assert streak_means["CASUAL"] < streak_means["CONSISTENT"]
    assert streak_means["CONSISTENT"] < streak_means["HIGHLY_ACTIVE"]


def test_territory_focused_holds_territory_and_defends():
    inactive = _profile_history("INACTIVE")
    focused = _profile_history("TERRITORY_FOCUSED")

    inactive_max = max(r["hexes_owned"] for r in inactive)
    focused_max = max(r["hexes_owned"] for r in focused)
    inactive_captures = sum(r["hexes_captured"] for r in inactive)
    focused_captures = sum(r["hexes_captured"] for r in focused)
    focused_defense = sum(r["defense_steps"] for r in focused)

    assert focused_max > inactive_max  # territory cap 30 vs 2
    assert focused_captures > inactive_captures
    # Territory-first users spend real effort defending their holdings.
    assert focused_defense > 0
    # And they reach a much bigger territory than a plain CASUAL walker.
    casual_max = max(r["hexes_owned"] for r in _profile_history("CASUAL"))
    assert focused_max > casual_max


def test_lapsed_has_meaningful_inactive_tail():
    num_days = 40
    rows = generate_user_days("LAPSED", "syn_lapsed_0001", num_days, seed=3)
    window = generator._inactive_window(num_days, generator.PROFILE_BY_NAME["LAPSED"]["gap"])
    assert window is not None
    start, _end = window

    # Had real, capture-worthy history before going quiet.
    assert any(r["steps"] >= STREAK_MIN_STEPS for r in rows[:start])
    # Quiet tail: last day inactive, no captures late, and a long trailing run
    # that covers the whole forced window.
    assert rows[-1]["steps"] < STREAK_MIN_STEPS
    assert all(r["hexes_captured"] == 0 for r in rows[start:])
    trailing = 0
    for r in reversed(rows):
        if r["steps"] >= STREAK_MIN_STEPS:
            break
        trailing += 1
    assert trailing >= num_days * 0.4 - 1


def test_returning_has_inactive_spell_then_renewed_activity():
    num_days = 40
    rows = generate_user_days("RETURNING", "syn_returning_0001", num_days, seed=9)

    # The forced middle gap is real: its days are all below the activity bar.
    window = generator._inactive_window(num_days, generator.PROFILE_BY_NAME["RETURNING"]["gap"])
    assert window is not None
    start, end = window
    assert all(r["steps"] < STREAK_MIN_STEPS for r in rows[start:end])

    # Active before the spell and, crucially, renewed activity after it.
    assert any(r["steps"] >= STREAK_MIN_STEPS for r in rows[:start])
    assert any(r["steps"] >= STREAK_MIN_STEPS for r in rows[end:])


def test_default_dataset_contains_every_profile_once_given_room():
    # With >= 7 users the default composition guarantees full profile coverage.
    rows = generate_dataset(num_users=14, num_days=10, seed=SEED_A)
    ids = {r["synthetic_user_id"] for r in rows}
    prefixes = {uid.rsplit("_", 1)[0] for uid in ids}
    for profile_name in PROFILE_NAMES:
        assert f"syn_{profile_name.lower()}" in prefixes
