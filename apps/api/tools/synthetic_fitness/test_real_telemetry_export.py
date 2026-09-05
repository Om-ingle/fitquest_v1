"""Tests for the Phase 4B.6 real telemetry exporter.

All database data here is DETERMINISTIC TEST-FIXTURE data, shaped exactly like
real ``userdailyactivity`` rows. It is created in throwaway SQLite files under
pytest's tmp_path and is NEVER written to the real Supabase database — the
fixtures only prove the exporter's extraction, densification, labeling,
multi-user, and leakage-safeguard behavior.

No real-user ML performance is (or can be) measured by these tests.
"""

import csv
import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import features  # noqa: E402
import generator  # noqa: E402
import real_telemetry_export as rte  # noqa: E402
import target  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# TEST FIXTURES (never the real Supabase database)
# ─────────────────────────────────────────────────────────────────────────────

# Mirrors the userdailyactivity DDL from Alembic migration 0002 (SQLite types).
FIXTURE_DDL = """
CREATE TABLE userdailyactivity (
    user_id TEXT NOT NULL,
    activity_date TEXT NOT NULL,
    steps INTEGER NOT NULL,
    active_minutes INTEGER NOT NULL,
    goal_steps INTEGER,
    goal_completed INTEGER,
    hexes_owned INTEGER,
    hexes_captured INTEGER,
    hexes_lost INTEGER,
    defense_steps INTEGER,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, activity_date)
)
"""


def _fixture_row(user, day, steps, minutes=30, goal=6000, goal_completed=False,
                 owned=5, captured=1, lost=None, defense=None):
    """One telemetry-shaped fixture row ( DailyActivitySnapshot persistence)."""
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


USER_A = "00000000-0000-0000-0000-00000000000a"
USER_B = "00000000-0000-0000-0000-00000000000b"

# User A: gap on 01-03 (no sync), explicit losses/defense on 01-04,
# inactive stretch 01-05..01-07 for the target.
USER_A_ROWS = [
    _fixture_row(USER_A, "2026-01-01", 8000, minutes=60, goal_completed=True, owned=2, captured=2),
    _fixture_row(USER_A, "2026-01-02", 500, minutes=0, owned=4, captured=1),
    # 2026-01-03: no stored row — the app was never opened (densified later).
    _fixture_row(USER_A, "2026-01-04", 9500, minutes=80, goal_completed=True, owned=5,
                 captured=1, lost=1, defense=500),
    _fixture_row(USER_A, "2026-01-05", 1200, minutes=10, owned=5, captured=0),
    _fixture_row(USER_A, "2026-01-06", 300, minutes=5, owned=5, captured=0),
    _fixture_row(USER_A, "2026-01-07", 400, minutes=5, owned=5, captured=0),
    _fixture_row(USER_A, "2026-01-08", 7000, minutes=55, owned=6, captured=1),
]

USER_B_ROWS = [
    _fixture_row(USER_B, "2026-01-01", 4000, minutes=40, owned=1, captured=1),
    _fixture_row(USER_B, "2026-01-02", 200, minutes=0, owned=1, captured=0),
    _fixture_row(USER_B, "2026-01-03", 150, minutes=0, owned=1, captured=0),
    _fixture_row(USER_B, "2026-01-04", 3000, minutes=30, owned=2, captured=1),
]


def _make_fixture_db(tmp_path, rows, with_pk=True, name="fixture_telemetry.db"):
    """Create a throwaway SQLite database holding FIXTURE telemetry rows.

    ``with_pk=False`` creates the table without the primary key so the
    exporter's duplicate detection can be exercised end-to-end (the real
    table's PK makes duplicates impossible at the database level).
    """
    db_path = tmp_path / name
    con = sqlite3.connect(db_path)
    ddl = FIXTURE_DDL if with_pk else FIXTURE_DDL.replace(
        ",\n    PRIMARY KEY (user_id, activity_date)\n", "\n"
    )
    con.execute(ddl)
    for row in rows:
        con.execute(
            "INSERT INTO userdailyactivity (user_id, activity_date, steps,"
            " active_minutes, goal_steps, goal_completed, hexes_owned,"
            " hexes_captured, hexes_lost, defense_steps, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00')",
            (
                row["user_id"], row["activity_date"], row["steps"],
                row["active_minutes"], row["goal_steps"],
                int(bool(row["goal_completed"])), row["hexes_owned"],
                row["hexes_captured"], row["hexes_lost"], row["defense_steps"],
            ),
        )
    con.commit()
    con.close()
    return f"sqlite:///{db_path.as_posix()}"


# ─────────────────────────────────────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────────────────────────────────────


def test_fetch_reads_stored_rows_deterministically(tmp_path):
    url = _make_fixture_db(tmp_path, USER_B_ROWS + USER_A_ROWS)
    rows = rte.fetch_telemetry_rows(url)
    assert len(rows) == len(USER_A_ROWS) + len(USER_B_ROWS)
    # ORDER BY user_id, activity_date regardless of insertion order.
    assert [r["user_id"] for r in rows] == sorted(r["user_id"] for r in rows)
    for row in rows:
        assert set(rte.TELEMETRY_COLUMNS) <= set(row)
    assert rows[0]["activity_date"] == "2026-01-01"  # stored value, as-is


def test_validate_unique_fails_loudly_on_duplicates():
    rows = [
        _fixture_row(USER_A, "2026-01-01", 100),
        _fixture_row(USER_A, "2026-01-01", 200),  # impossible under the real PK
    ]
    with pytest.raises(ValueError, match="duplicate telemetry rows"):
        rte.validate_unique_telemetry(rows)


def test_duplicate_records_from_a_pkless_table_fail_loudly(tmp_path):
    # A table without the PK (only constructible in a fixture) must not be
    # silently de-duplicated or arbitrarily resolved by the exporter.
    dup = USER_B_ROWS + [_fixture_row(USER_B, "2026-01-01", 999)]
    url = _make_fixture_db(tmp_path, dup, with_pk=False)
    rows = rte.fetch_telemetry_rows(url)
    with pytest.raises(ValueError, match="duplicate telemetry rows"):
        rte.export_dataset(rows)


def test_export_rejects_empty_input():
    with pytest.raises(ValueError, match="no telemetry rows"):
        rte.export_dataset([])


# ─────────────────────────────────────────────────────────────────────────────
# Export shape & feature compatibility
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def export_result():
    return rte.export_dataset(USER_A_ROWS + USER_B_ROWS)


def test_raw_output_is_extracted_rows_verbatim(export_result):
    raw = export_result["extracted"]
    assert len(raw) == len(USER_A_ROWS) + len(USER_B_ROWS)
    # NULLs (unknown) are preserved as None — never turned into zeros.
    by_key = {(r["user_id"], r["activity_date"]): r for r in raw}
    assert by_key[(USER_A, "2026-01-02")]["hexes_lost"] is None
    assert by_key[(USER_A, "2026-01-04")]["hexes_lost"] == 1


def test_daily_rows_are_densified_generator_columns(export_result):
    daily = export_result["daily"]
    user_a_days = [r["day"] for r in daily if r["synthetic_user_id"] == USER_A]
    # 7 stored days + 1 densified gap day (2026-01-03) = 8 contiguous days.
    assert user_a_days == [f"2026-01-{d:02d}" for d in range(1, 9)]
    for row in daily:
        assert set(generator.COLUMNS) <= set(row)
        assert row["data_source"] == "real"
        assert set(rte.KNOWN_FLAGS) <= set(row)
        assert rte.DENSIFIED_FLAG in row


def test_gap_day_is_a_zero_tracked_steps_row_with_flags(export_result):
    gap = next(
        r for r in export_result["daily"]
        if r["synthetic_user_id"] == USER_A and r["day"] == "2026-01-03"
    )
    assert gap["steps"] == 0 and gap["active_minutes"] == 0
    assert gap[rte.DENSIFIED_FLAG] == 1
    assert gap["hexes_lost_known"] == 0 and gap["defense_steps_known"] == 0
    # goal_steps / hexes_owned carry forward across the gap (Phase 4B.5).
    assert gap["goal_steps"] == 6000 and gap["hexes_owned"] == 4


def test_known_flags_distinguish_reported_from_unknown(export_result):
    daily = {(r["synthetic_user_id"], r["day"]): r for r in export_result["daily"]}
    reported = daily[(USER_A, "2026-01-04")]  # lost=1, defense=500 reported
    assert reported["hexes_lost"] == 1 and reported["hexes_lost_known"] == 1
    assert reported["defense_steps"] == 500 and reported["defense_steps_known"] == 1
    unknown = daily[(USER_A, "2026-01-02")]  # both NULL in the table
    assert unknown["hexes_lost"] == 0 and unknown["hexes_lost_known"] == 0
    assert unknown["defense_steps"] == 0 and unknown["defense_steps_known"] == 0


def test_feature_rows_have_exactly_synthetic_schema_plus_target(export_result):
    feature_rows = export_result["features"]
    assert len(feature_rows) == len(export_result["daily"])
    for row in feature_rows:
        assert list(row.keys()) == rte.FEATURE_COLUMNS
        assert row["data_source"] == "real"
    # 21 model features, exact names and canonical order.
    assert rte.FEATURE_COLUMNS[: len(features.OUTPUT_COLUMNS)] == features.OUTPUT_COLUMNS
    assert features.MODEL_FEATURES == [
        c for c in features.OUTPUT_COLUMNS if c not in features.EXCLUDED_METADATA
    ]


def test_feature_matrix_excludes_metadata_and_target(export_result):
    matrix = rte.feature_matrix(export_result["features"])
    assert all(len(row) == len(features.MODEL_FEATURES) for row in matrix)
    for name in ("synthetic_user_id", "day", "data_source", target.TARGET_NAME):
        assert name not in features.MODEL_FEATURES


def test_hand_computed_features_match(export_result):
    rows = {
        r["day"]: r
        for r in export_result["features"]
        if r["synthetic_user_id"] == USER_A
    }
    d5 = rows["2026-01-05"]
    assert d5["steps_today"] == 1200
    assert d5["steps_3d_avg"] == round((0 + 9500 + 1200) / 3, 6)
    assert d5["current_streak"] == 2  # 01-04, 01-05 above the bar
    assert d5["losses_7d"] == 1       # reported loss on 01-04
    assert d5["defense_steps_7d"] == 500


# ─────────────────────────────────────────────────────────────────────────────
# Target semantics (unmodified target.py)
# ─────────────────────────────────────────────────────────────────────────────


def test_targets_follow_inactive_next_3d_exactly(export_result):
    labels = export_result["labels"]
    # User A steps: 8000, 500, (0), 9500, 1200, 300, 400, 7000
    expected = {
        "2026-01-01": 1,  # next 3 = 500, 0, 9500 -> 2 of 3 < 1000
        "2026-01-02": 0,  # 0, 9500, 1200 -> 1
        "2026-01-03": 0,  # 9500, 1200, 300 -> 1
        "2026-01-04": 1,  # 1200, 300, 400 -> 2
        "2026-01-05": 1,  # 300, 400, 7000 -> 2
        "2026-01-06": None,  # incomplete horizon (tail)
        "2026-01-07": None,
        "2026-01-08": None,
    }
    for day, value in expected.items():
        assert labels[(USER_A, day)] == value, day


def test_tail_rows_have_no_target_and_are_not_imputed(export_result):
    rows = export_result["features"]
    for user in (USER_A, USER_B):
        user_rows = [r for r in rows if r["synthetic_user_id"] == user]
        for row in user_rows[-target.HORIZON_DAYS:]:
            assert row[target.TARGET_NAME] is None
        for row in user_rows[:-target.HORIZON_DAYS]:
            assert row[target.TARGET_NAME] in (0, 1)
    assert export_result["n_unlabeled_tail"] == 2 * target.HORIZON_DAYS


# ─────────────────────────────────────────────────────────────────────────────
# Leakage safeguards
# ─────────────────────────────────────────────────────────────────────────────


def _features_by_day(result, user):
    return {
        r["day"]: r
        for r in result["features"]
        if r["synthetic_user_id"] == user
    }


def test_future_day_changes_cannot_alter_earlier_features():
    before = rte.export_dataset(USER_A_ROWS)
    # Rewrites history's last day drastically.
    tampered = [
        (dict(row) | {"steps": 50, "hexes_captured": 3})
        if row["activity_date"] == "2026-01-08"
        else dict(row)
        for row in USER_A_ROWS
    ]
    after = rte.export_dataset(tampered)

    before_rows, after_rows = _features_by_day(before, USER_A), _features_by_day(after, USER_A)
    for day in [f"2026-01-{d:02d}" for d in range(1, 8)]:  # all days before D8
        assert before_rows[day] == after_rows[day], day
    assert after_rows["2026-01-08"]["steps_today"] == 50  # only D8 changed


def test_future_day_changes_only_reach_targets_whose_horizon_includes_them():
    # Baseline: one user, days d1..d7 = 5000,5000,5000,5000,200,5000,10000.
    base_rows = [
        _fixture_row(USER_A, f"2026-02-{d:02d}", steps, minutes=30, owned=3, captured=0)
        for d, steps in zip(range(1, 8), (5000, 5000, 5000, 5000, 200, 5000, 10000))
    ]
    before = rte.export_dataset(base_rows)["labels"]
    # Flip day d7 (X) from active to inactive.
    tampered = [dict(r) for r in base_rows]
    tampered[-1]["steps"] = 100
    after = rte.export_dataset(tampered)["labels"]

    # Days whose 3-day horizon EXCLUDES d7 (d1: d2-d4, d2: d3-d5, d3: d4-d6)
    # must be untouched...
    for day in ("2026-02-01", "2026-02-02", "2026-02-03"):
        assert before[(USER_A, day)] == after[(USER_A, day)] == 0
    # ...while d4's horizon (d5, d6, d7) includes the changed day and flips.
    assert before[(USER_A, "2026-02-04")] == 0   # 200, 5000, 10000 -> 1 inactive
    assert after[(USER_A, "2026-02-04")] == 1    # 200, 5000, 100  -> 2 inactive
    # d5..d7 are tail rows without a full horizon either way.
    for day in ("2026-02-05", "2026-02-06", "2026-02-07"):
        assert before[(USER_A, day)] is None and after[(USER_A, day)] is None


def test_users_are_isolated():
    before = rte.export_dataset(USER_A_ROWS)
    after = rte.export_dataset(USER_A_ROWS + USER_B_ROWS)

    # Adding another user changes nothing about user A — features or targets.
    assert _features_by_day(before, USER_A) == _features_by_day(after, USER_A)
    assert {
        k: v for k, v in before["labels"].items() if k[0] == USER_A
    } == {
        k: v for k, v in after["labels"].items() if k[0] == USER_A
    }

    # And tampering with user B cannot reach user A either.
    tampered_b = [dict(r) for r in USER_B_ROWS]
    tampered_b[0]["steps"] = 99999
    tampered = rte.export_dataset(USER_A_ROWS + tampered_b)
    assert _features_by_day(after, USER_A) == _features_by_day(tampered, USER_A)


def test_no_synthetic_rows_can_enter_the_real_dataset(export_result):
    # Everything the exporter emits is labeled real...
    assert all(r["data_source"] == "real" for r in export_result["daily"])
    assert all(r["data_source"] == "real" for r in export_result["features"])

    # ...and synthetic-pipeline rows are rejected at the door: they do not
    # have the telemetry shape (user_id / activity_date keys).
    synthetic_rows = generator.generate_dataset(num_users=2, num_days=10, seed=7)
    with pytest.raises(ValueError, match="missing keys"):
        rte.export_dataset(synthetic_rows)


def test_export_is_deterministic():
    first = rte.export_dataset(USER_A_ROWS + USER_B_ROWS)
    second = rte.export_dataset(list(USER_B_ROWS + USER_A_ROWS))  # re-ordered
    # Row order within a user follows the calendar; user block order follows
    # first appearance, so compare content order-independently.
    key = lambda r: (r["synthetic_user_id"], r["day"])  # noqa: E731
    assert sorted(first["daily"], key=key) == sorted(second["daily"], key=key)
    assert sorted(first["features"], key=key) == sorted(second["features"], key=key)
    assert first["labels"] == second["labels"]


# ─────────────────────────────────────────────────────────────────────────────
# Output files & CLI
# ─────────────────────────────────────────────────────────────────────────────


def test_write_outputs_round_trip(tmp_path, export_result):
    paths = rte.write_outputs(export_result, tmp_path)
    assert set(paths) == {"raw", "daily", "features", "manifest"}

    with paths["raw"].open(newline="", encoding="utf-8") as handle:
        raw_rows = list(csv.DictReader(handle))
    assert len(raw_rows) == len(export_result["extracted"])
    by_key = {(r["user_id"], r["activity_date"]): r for r in raw_rows}
    # Unknown stays empty in the raw CSV — never a fake zero.
    assert by_key[(USER_A, "2026-01-02")]["hexes_lost"] == ""

    with paths["features"].open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == rte.FEATURE_COLUMNS
        feature_rows = list(reader)
    assert len(feature_rows) == len(export_result["features"])
    tail = [r for r in feature_rows if r["synthetic_user_id"] == USER_A][-1]
    assert tail[target.TARGET_NAME] == ""  # no horizon -> empty, not imputed

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["data_source"] == "real"
    assert manifest["model_features"] == features.MODEL_FEATURES
    assert manifest["counts"]["feature_rows"] == len(feature_rows)
    assert "no real-user ML performance was measured" in manifest["dataset"]


def test_cli_end_to_end_from_fixture_database(tmp_path):
    url = _make_fixture_db(tmp_path, USER_A_ROWS + USER_B_ROWS)
    out_dir = tmp_path / "export"
    assert rte.main(["--database-url", url, "--out-dir", str(out_dir)]) == 0

    features_csv = out_dir / rte.FEATURES_CSV
    assert features_csv.exists()
    with features_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(USER_A_ROWS) + 1 + len(USER_B_ROWS)  # + densified day
    assert all(r["data_source"] == "real" for r in rows)


def test_cli_handles_empty_database_gracefully(tmp_path, capsys):
    url = _make_fixture_db(tmp_path, [])
    out_dir = tmp_path / "export"
    assert rte.main(["--database-url", url, "--out-dir", str(out_dir)]) == 0
    assert not (out_dir / rte.FEATURES_CSV).exists()  # nothing fabricated
    assert "no rows" in capsys.readouterr().out.lower()


def test_cli_requires_a_database_url(capsys, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)  # never inherit one
    with pytest.raises(SystemExit):
        rte.main(["--out-dir", "unused"])
    assert "database URL is required" in capsys.readouterr().err


# A canary proving the fixture users above are fixture-only identifiers that
# can never collide with the backend's dev-user id.
def test_fixture_users_are_not_real_ids():
    dev_user = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for user in (USER_A, USER_B):
        assert uuid.UUID(user) != dev_user
