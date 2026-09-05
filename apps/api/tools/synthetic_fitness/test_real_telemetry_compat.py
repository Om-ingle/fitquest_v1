"""Tests for the Phase 4B.5 real-telemetry compatibility adapter.

Pure Python (no DB, no FastAPI). They prove that telemetry-shaped rows —
exactly what the ``userdailyactivity`` table / ``DailyActivitySnapshot`` API
persists — flow through the UNMODIFIED Phase 4B.2 feature pipeline
(``features.build_features``), including gap densification, streak
recomputation, goal carry-forward, and the ``data_source="real"`` label.

No real telemetry exists yet; all fixtures are synthetic *telemetry-shaped*
data and never represent real user behavior.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import features  # noqa: E402
import generator  # noqa: E402
import real_telemetry_compat as rtc  # noqa: E402


def _telemetry(user, day, steps, minutes=30, goal=6000, goal_completed=None,
               owned=5, captured=1, lost=None, defense=None):
    return {
        "user_id": user,
        "activity_date": day,
        "steps": steps,
        "active_minutes": minutes,
        "goal_steps": goal,
        "goal_completed": goal_completed,
        "hexes_owned": owned,
        "hexes_captured": captured,
        "hexes_lost": lost,
        "defense_steps": defense,
    }


FIXTURE_DAYS = ["2026-01-01", "2026-01-02", "2026-01-04", "2026-01-05"]  # gap on 01-03


@pytest.fixture()
def telemetry_fixture():
    return [
        _telemetry("u1", "2026-01-01", 8000, minutes=60, goal_completed=True, owned=2, captured=2),
        _telemetry("u1", "2026-01-02", 500, minutes=0, goal_completed=False, owned=4, captured=1),
        # 2026-01-03: no sync happened (no run) -> must be densified to zero.
        _telemetry("u1", "2026-01-04", 9500, minutes=80, goal_completed=True, owned=5, captured=1),
        _telemetry("u1", "2026-01-05", 1200, minutes=10, goal_completed=False, owned=5, captured=0),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Conversion shape
# ─────────────────────────────────────────────────────────────────────────────


def test_converted_rows_match_generator_columns_exactly(telemetry_fixture):
    raw = rtc.telemetry_to_raw_rows(telemetry_fixture)
    assert len(raw) == 5  # 4 recorded + 1 densified gap day
    for row in raw:
        assert set(generator.COLUMNS) <= set(row)
        assert row["data_source"] == "real"


def test_gap_days_are_densified_with_zero_activity(telemetry_fixture):
    raw = rtc.telemetry_to_raw_rows(telemetry_fixture)
    days = [r["day"] for r in raw]
    assert days == ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]

    gap = raw[2]
    assert gap["steps"] == 0
    assert gap["active_minutes"] == 0
    assert gap["hexes_captured"] == 0
    assert gap["goal_completed"] == 0
    # Carried forward across the gap: the goal from 01-02 and the owned
    # count last seen on 01-02.
    assert gap["goal_steps"] == 6000
    assert gap["hexes_owned"] == 4


def test_streak_never_carries_across_users():
    # u1 ends on 01-02 with an active day; u2 starts 01-03 — the days are
    # contiguous but they are DIFFERENT users, so u2's streak must restart.
    rows = [
        _telemetry("u1", "2026-01-01", 5000),
        _telemetry("u1", "2026-01-02", 5000),
        _telemetry("u2", "2026-01-03", 5000),
    ]
    raw = rtc.telemetry_to_raw_rows(rows)
    streaks = {(r["synthetic_user_id"], r["day"]): r["streak"] for r in raw}
    assert streaks[("u1", "2026-01-02")] == 2
    assert streaks[("u2", "2026-01-03")] == 1  # not 3


def test_streak_is_recomputed_from_steps_history(telemetry_fixture):
    raw = rtc.telemetry_to_raw_rows(telemetry_fixture)
    streaks = [r["streak"] for r in raw]
    # 8000 (>=1000) -> 1; 500 -> reset 0; gap 0 -> 0; 9500 -> 1; 1200 -> 2.
    assert streaks == [1, 0, 0, 1, 2]


def test_goal_completed_derived_when_unreported():
    rows = [
        _telemetry("u1", "2026-01-01", 7000, goal_completed=None, goal=6000),
        _telemetry("u1", "2026-01-02", 5999, goal_completed=None, goal=6000),
    ]
    raw = rtc.telemetry_to_raw_rows(rows)
    assert [r["goal_completed"] for r in raw] == [1, 0]


def test_explicit_goal_completed_is_respected_not_recomputed():
    rows = [_telemetry("u1", "2026-01-01", 9000, goal_completed=False, goal=6000)]
    raw = rtc.telemetry_to_raw_rows(rows)
    assert raw[0]["goal_completed"] == 0  # device said so; keep it


def test_unknown_fields_null_become_zero_with_documented_caveat():
    rows = [_telemetry("u1", "2026-01-01", 3000, lost=None, defense=None, captured=None)]
    raw = rtc.telemetry_to_raw_rows(rows)
    assert raw[0]["hexes_lost"] == 0
    assert raw[0]["defense_steps"] == 0
    assert raw[0]["hexes_captured"] == 0


def test_users_are_converted_independently():
    rows = [
        _telemetry("u2", "2026-01-01", 10000, owned=9),
        _telemetry("u1", "2026-01-01", 2000, owned=1),
        _telemetry("u2", "2026-01-02", 3000, owned=10),
    ]
    raw = rtc.telemetry_to_raw_rows(rows)
    by_user = {uid: [r for r in raw if r["synthetic_user_id"] == uid] for uid in ("u1", "u2")}
    assert len(by_user["u1"]) == 1 and len(by_user["u2"]) == 2
    assert by_user["u1"][0]["hexes_owned"] == 1
    assert by_user["u2"][0]["hexes_owned"] == 9


def test_missing_keys_raise(telemetry_fixture):
    broken = {k: v for k, v in telemetry_fixture[0].items() if k != "steps"}
    with pytest.raises(ValueError, match="missing keys"):
        rtc.telemetry_to_raw_rows([broken])


def test_empty_input_returns_empty():
    assert rtc.telemetry_to_raw_rows([]) == []


def test_conversion_is_deterministic(telemetry_fixture):
    assert rtc.telemetry_to_raw_rows(telemetry_fixture) == rtc.telemetry_to_raw_rows(
        list(telemetry_fixture)
    )


def test_accepts_datetime_and_date_objects():
    import datetime as dt

    rows = [
        {
            "user_id": "u1",
            "activity_date": dt.date(2026, 1, 1),
            "steps": 1000, "active_minutes": 10, "goal_steps": 500,
            "goal_completed": None, "hexes_owned": 1, "hexes_captured": 0,
            "hexes_lost": None, "defense_steps": None,
        },
        {
            "user_id": "u1",
            "activity_date": dt.datetime(2026, 1, 2, 23, 59, 59),
            "steps": 1000, "active_minutes": 10, "goal_steps": 500,
            "goal_completed": None, "hexes_owned": 1, "hexes_captured": 0,
            "hexes_lost": None, "defense_steps": None,
        },
    ]
    raw = rtc.telemetry_to_raw_rows(rows)
    assert [r["day"] for r in raw] == ["2026-01-01", "2026-01-02"]


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: telemetry -> unmodified features.build_features
# ─────────────────────────────────────────────────────────────────────────────


def test_telemetry_flows_through_unmodified_feature_pipeline(telemetry_fixture):
    raw = rtc.telemetry_to_raw_rows(telemetry_fixture)
    feature_rows = features.build_features(raw)

    assert len(feature_rows) == 5
    assert all(len(r) == len(features.OUTPUT_COLUMNS) for r in feature_rows)

    # Spot-check hand-computed features for 2026-01-05 (i = 4):
    # steps history = [8000, 500, 0, 9500, 1200]
    row = feature_rows[-1]
    assert row["day"] == "2026-01-05"
    assert row["steps_today"] == 1200
    assert row["steps_3d_avg"] == round((0 + 9500 + 1200) / 3, 6)
    assert row["steps_7d_avg"] == round((8000 + 500 + 0 + 9500 + 1200) / 5, 6)
    assert row["active_today"] == 1
    assert row["current_streak"] == 2
    assert row["goal_steps"] == 6000
    assert row["goal_completed_today"] == 0
    assert row["hexes_owned"] == 5
    assert row["data_source"] == "real"
    # 01-02's active_minutes=0 gap contributes to the 3d minute average.
    assert row["active_minutes_3d_avg"] == round((0 + 80 + 10) / 3, 6)


def test_rolling_windows_count_calendar_days_not_recorded_days(telemetry_fixture):
    # Without densification, 01-05's trailing-3 window would span 01-02..01-05
    # (4 calendar days). With it, it is exactly 01-03..01-05.
    raw = rtc.telemetry_to_raw_rows(telemetry_fixture)
    row = features.build_features(raw)[-1]
    assert row["steps_3d_avg"] == round((0 + 9500 + 1200) / 3, 6)


def test_verify_feature_compatibility_summary(telemetry_fixture):
    summary = rtc.verify_feature_compatibility(telemetry_fixture)
    assert summary["telemetry_rows_in"] == 4
    assert summary["raw_rows_out"] == 5  # densified
    assert summary["feature_rows_out"] == 5
    assert summary["data_source"] == "real"
    assert len(summary["model_features"]) == 21


def test_verify_feature_compatibility_rejects_empty():
    with pytest.raises(ValueError, match="no telemetry rows"):
        rtc.verify_feature_compatibility([])


def test_long_history_verifies_cleanly():
    # 30 days of realistic telemetry incl. unknown loss/defense fields and
    # several no-run gaps — the shape real data will actually have.
    import datetime as dt_module

    rows = []
    start = dt_module.date(2026, 2, 1)
    for i in range(30):
        day = (start + dt_module.timedelta(days=i)).isoformat()
        if i % 7 in (3, 4):  # two quiet days a week: no sync, no run
            continue
        rows.append(_telemetry("u1", day, 2500 + 100 * i, minutes=25 + i // 2,
                               lost=None, defense=None))
    summary = rtc.verify_feature_compatibility(rows)
    # 30 days, 8 gap days removed, 8 densified back -> 30 raw rows.
    assert summary["raw_rows_out"] == 30
    assert summary["feature_rows_out"] == 30
