"""Phase 4B.5 tests: daily telemetry persistence on the run-sync path.

Covers the contract in tools/synthetic_fitness/real_telemetry_gap_analysis.md:
insert, idempotency (absolute snapshots, re-send -> identical row), partial
updates (null = keep stored value), deterministic late corrections, user
isolation, payload validation, legacy-payload compatibility, and the Alembic
migration applying cleanly.
"""
import datetime as dt
import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlmodel import Session, select

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.runs.models import UserDailyActivity
from app.modules.users.models import User

API_DIR = Path(__file__).resolve().parents[1]

TODAY = dt.datetime.now(dt.timezone.utc).date()


def _ensure_dev_user():
    """The telemetry upsert (like the lifetime-steps update) requires the
    authenticated user's row to exist; SQLite tests must create it."""
    with Session(engine) as db:
        if db.get(User, uuid.UUID(DEV_USER_ID)) is None:
            db.add(User(id=uuid.UUID(DEV_USER_ID), username="devuser"))
            db.commit()


def _snapshot(**overrides):
    snapshot = {
        "activity_date": TODAY.isoformat(),
        "steps": 4210,
        "active_minutes": 38,
        "goal_steps": 6000,
        "goal_completed": False,
        "hexes_owned": 12,
        "hexes_captured": 2,
        "hexes_lost": None,
        "defense_steps": None,
    }
    snapshot.update(overrides)
    return snapshot


def _sync(client, daily_activity="keep", **snapshot_overrides):
    """POST /runs/sync with an optional telemetry block.

    daily_activity="keep" -> the default snapshot with **snapshot_overrides
    applied; None -> legacy payload without the field at all; a dict -> used
    verbatim.
    """
    payload = {"total_session_steps": 350, "hexes_to_steps": {}}
    if daily_activity == "keep":
        payload["daily_activity"] = _snapshot(**snapshot_overrides)
    elif daily_activity is not None:
        payload["daily_activity"] = daily_activity
    return client.post("/api/v1/runs/sync", json=payload)


def _get_rows(user_id=None):
    with Session(engine) as db:
        statement = select(UserDailyActivity)
        if user_id is not None:
            statement = statement.where(UserDailyActivity.user_id == user_id)
        return list(db.exec(statement).all())


# ─────────────────────────────────────────────────────────────────────────────
# Insert & idempotency
# ─────────────────────────────────────────────────────────────────────────────


def test_sync_with_daily_activity_persists_snapshot(client):
    _ensure_dev_user()
    response = _sync(client)
    assert response.status_code == 200

    rows = _get_rows(uuid.UUID(DEV_USER_ID))
    assert len(rows) == 1
    row = rows[0]
    assert row.activity_date == TODAY
    assert row.steps == 4210
    assert row.active_minutes == 38
    assert row.goal_steps == 6000
    assert row.goal_completed is False
    assert row.hexes_owned == 12
    assert row.hexes_captured == 2
    # Not reported by the device in v1 -> stored as NULL ("unknown").
    assert row.hexes_lost is None
    assert row.defense_steps is None
    assert row.updated_at is not None


def test_repeated_identical_sync_is_idempotent(client):
    _ensure_dev_user()
    assert _sync(client).status_code == 200
    assert _sync(client).status_code == 200

    rows = _get_rows(uuid.UUID(DEV_USER_ID))
    assert len(rows) == 1  # upsert, never a duplicate
    assert rows[0].steps == 4210
    assert rows[0].hexes_captured == 2


def test_second_run_same_day_replaces_absolute_values(client):
    # A second run the same day sends the day-to-date ABSOLUTE totals, so the
    # row ends up with the new totals — no double counting.
    _ensure_dev_user()
    _sync(client, steps=1000, active_minutes=10)
    response = _sync(client, steps=4500, active_minutes=42, hexes_captured=5)
    assert response.status_code == 200

    rows = _get_rows(uuid.UUID(DEV_USER_ID))
    assert len(rows) == 1
    assert rows[0].steps == 4500
    assert rows[0].active_minutes == 42
    assert rows[0].hexes_captured == 5


def test_partial_update_nulls_keep_stored_values(client):
    # A client that only knows steps/minutes (e.g. an older app build) must
    # not wipe goal/territory fields it doesn't report.
    _ensure_dev_user()
    _sync(client)  # full snapshot
    response = _sync(
        client,
        daily_activity=_snapshot(steps=9000, goal_steps=None, hexes_owned=None),
    )
    assert response.status_code == 200

    row = _get_rows(uuid.UUID(DEV_USER_ID))[0]
    assert row.steps == 9000  # non-null -> replaced
    assert row.goal_steps == 6000  # null -> kept
    assert row.hexes_owned == 12  # null -> kept


def test_late_correction_is_deterministic_last_write_wins(client):
    _ensure_dev_user()
    _sync(client)  # today's snapshot, to prove other dates stay untouched
    yesterday = (TODAY - dt.timedelta(days=1)).isoformat()
    _sync(client, daily_activity=_snapshot(activity_date=yesterday, steps=100))
    # Late correction: the device re-reports the same older date.
    _sync(client, daily_activity=_snapshot(activity_date=yesterday, steps=222))
    _sync(client, daily_activity=_snapshot(activity_date=yesterday, steps=222))

    rows = sorted(_get_rows(uuid.UUID(DEV_USER_ID)), key=lambda r: r.activity_date)
    assert [r.activity_date for r in rows] == [TODAY - dt.timedelta(days=1), TODAY]
    assert rows[0].steps == 222  # deterministic: latest write, idempotent on repeat
    assert rows[1].steps == 4210  # the other date is untouched


# ─────────────────────────────────────────────────────────────────────────────
# Isolation & compatibility
# ─────────────────────────────────────────────────────────────────────────────


def test_sync_never_touches_another_users_telemetry(client):
    _ensure_dev_user()
    rival_id = uuid.uuid4()
    with Session(engine) as db:
        db.add(User(id=rival_id, username=f"rival-{str(rival_id)[:8]}"))
        db.add(
            UserDailyActivity(
                user_id=rival_id,
                activity_date=TODAY,
                steps=7777,
                active_minutes=99,
                goal_steps=8000,
                goal_completed=True,
                hexes_owned=3,
                hexes_captured=1,
            )
        )
        db.commit()

    assert _sync(client).status_code == 200

    rival_rows = _get_rows(rival_id)
    assert len(rival_rows) == 1
    assert rival_rows[0].steps == 7777
    assert rival_rows[0].hexes_owned == 3
    dev_rows = _get_rows(uuid.UUID(DEV_USER_ID))
    assert len(dev_rows) == 1  # rows are keyed by the AUTHENTICATED user only


def test_legacy_payload_without_daily_activity_writes_nothing(client):
    _ensure_dev_user()
    response = _sync(client, daily_activity=None)
    assert response.status_code == 200
    body = response.json()
    assert body["xp_earned"] == 0
    assert body["new_total_lifetime_steps"] == 350
    assert _get_rows() == []


def test_sync_without_user_row_skips_telemetry_but_succeeds(client):
    # Unseeded environment: the user row is missing, so (mirroring the
    # lifetime-steps update) telemetry is skipped and the sync still works.
    response = _sync(client)
    assert response.status_code == 200
    assert _get_rows() == []


# ─────────────────────────────────────────────────────────────────────────────
# Validation (422 on impossible values)
# ─────────────────────────────────────────────────────────────────────────────


def test_future_date_rejected(client):
    future = (TODAY + dt.timedelta(days=3)).isoformat()
    response = _sync(client, daily_activity=_snapshot(activity_date=future))
    assert response.status_code == 422


def test_device_local_date_one_day_ahead_of_utc_is_accepted(client):
    # A device at UTC+14 near midnight is legitimately one local day ahead.
    _ensure_dev_user()
    ahead = (TODAY + dt.timedelta(days=1)).isoformat()
    response = _sync(client, daily_activity=_snapshot(activity_date=ahead))
    assert response.status_code == 200
    rows = _get_rows(uuid.UUID(DEV_USER_ID))
    assert len(rows) == 1
    assert rows[0].activity_date == TODAY + dt.timedelta(days=1)


def test_negative_and_impossible_values_rejected(client):
    bad_values = [
        {"steps": -1},
        {"steps": 2_000_000},
        {"active_minutes": -5},
        {"active_minutes": 1441},  # more minutes than a day has
        {"goal_steps": -100},
        {"hexes_owned": -1},
        {"hexes_captured": 500_000},
    ]
    for overrides in bad_values:
        response = _sync(client, daily_activity=_snapshot(**overrides))
        assert response.status_code == 422, overrides
    # Nothing was persisted by rejected payloads.
    assert _get_rows() == []


def test_malformed_date_rejected(client):
    response = _sync(client, daily_activity=_snapshot(activity_date="2026-13-45"))
    assert response.status_code == 422
    assert _get_rows() == []


# ─────────────────────────────────────────────────────────────────────────────
# Alembic migration
# ─────────────────────────────────────────────────────────────────────────────


def test_migration_applies_and_reverts_cleanly(tmp_path):
    """alembic upgrade head on a fresh DB creates userdailyactivity (and the
    whole Phase 1 schema); downgrade base removes it. Run in a subprocess so
    the migration sees a clean DATABASE_URL, untouched by the test app."""
    db_url = f"sqlite:///{(tmp_path / 'migration_check.db').as_posix()}"
    env = {**os.environ, "DATABASE_URL": db_url}

    def run_alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=API_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    upgrade = run_alembic("upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    from sqlalchemy import create_engine, inspect

    inspection_engine = create_engine(db_url)
    try:
        inspector = inspect(inspection_engine)
        tables = set(inspector.get_table_names())
        assert "userdailyactivity" in tables
        # The additive migration did not disturb the Phase 1 schema.
        assert {"user", "friendship", "hexownership", "runsession", "capturedhex", "quest", "userquest"} <= tables
        columns = {c["name"] for c in inspector.get_columns("userdailyactivity")}
        assert columns == {
            "user_id", "activity_date", "steps", "active_minutes",
            "goal_steps", "goal_completed", "hexes_owned", "hexes_captured",
            "hexes_lost", "defense_steps", "updated_at",
        }
        pk = set(inspector.get_pk_constraint("userdailyactivity")["constrained_columns"])
        assert pk == {"user_id", "activity_date"}
    finally:
        inspection_engine.dispose()

    downgrade = run_alembic("downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stderr
    check_engine = create_engine(db_url)
    try:
        assert "userdailyactivity" not in set(inspect(check_engine).get_table_names())
    finally:
        check_engine.dispose()
