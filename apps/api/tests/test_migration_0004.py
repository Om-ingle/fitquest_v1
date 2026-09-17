"""M11 — migration 0004 round-trips, and is asserted on both paths.

Why this file exists
--------------------
0004 adds ``user.auth_subject`` and a unique index on it. Neither of the two
existing alembic tests looked at either object: one asserts the RAG tables and
the other the telemetry table, and both touch 0004 only incidentally, through
``upgrade head`` succeeding. So the migration could have created the wrong
column, a non-unique index, or an index on the wrong column, and the suite
would still have been green — the four assertions below are the ones that were
missing.

The unique part is not decoration. ``resolve_or_provision_user`` races on
insert and relies on this index as the arbiter, so a non-unique index here
would let two concurrent first logins of the same Supabase account create two
internal users. The migration is only correct if the index is unique, which is
why that is asserted rather than assumed.

Both ends are pinned to explicit revisions (``0004`` and ``0003``) rather than
``head``/``-1``, for the reason recorded in test_rag.py: a relative target
silently re-points when a revision is stacked above this one, and the
assertions then describe the wrong migration. Pinning keeps this file about
0004 no matter what is added above it.

SQLite only — the migration is portable DDL, and the PostgreSQL path is
exercised by the deployment runbook (SRS §18.3), which reaches the real
database and cannot be run from the test suite.
"""
import os
import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]

# The revision under test and the one immediately below it.
AUTH_SUBJECT_REVISION = "0004"
AUTH_SUBJECT_PARENT = "0003"

AUTH_SUBJECT_COLUMN = "auth_subject"
AUTH_SUBJECT_INDEX = "ix_user_auth_subject"

# The `user` columns as 0004's parent leaves them. 0004 is additive and
# backfills nothing, so this set must come back unchanged after a downgrade.
USER_COLUMNS_BEFORE_0004 = {
    "id",
    "username",
    "avatar_url",
    "current_streak",
    "longest_streak",
    "last_activity_date",
    "total_lifetime_steps",
    "total_hexes_captured",
}

# A pre-existing unique index on the same table, created back in 0001. 0004's
# downgrade must leave it alone; without this control, an implementation that
# dropped every index on `user` would satisfy the assertions above.
UNRELATED_INDEX = "ix_user_username"


def _run_alembic(db_url: str, *args: str) -> subprocess.CompletedProcess:
    """Run alembic in a subprocess, so it sees this DATABASE_URL and nothing
    the imported test app has already done to its own engine."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=API_DIR,
        env={**os.environ, "DATABASE_URL": db_url},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_auth_subject_migration_applies_and_reverts_cleanly(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    db_url = f"sqlite:///{(tmp_path / 'auth_subject_migration.db').as_posix()}"

    # ── Upgrade ──────────────────────────────────────────────────────────────
    upgrade = _run_alembic(db_url, "upgrade", AUTH_SUBJECT_REVISION)
    assert upgrade.returncode == 0, upgrade.stderr

    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        assert "user" in inspector.get_table_names()

        columns = {c["name"] for c in inspector.get_columns("user")}
        assert AUTH_SUBJECT_COLUMN in columns

        # Nullable, because 0004 backfills nothing: rows that predate it have
        # no Supabase identity until they next authenticate. A NOT NULL column
        # would have made the migration fail on a non-empty table.
        auth_subject = next(
            c for c in inspector.get_columns("user")
            if c["name"] == AUTH_SUBJECT_COLUMN
        )
        assert auth_subject["nullable"] is True

        indexes = {ix["name"]: ix for ix in inspector.get_indexes("user")}
        assert AUTH_SUBJECT_INDEX in indexes, sorted(indexes)
        index = indexes[AUTH_SUBJECT_INDEX]
        assert index["column_names"] == [AUTH_SUBJECT_COLUMN]
        # The arbiter for the provisioning race. Not cosmetic.
        assert index["unique"] == 1

        with engine.connect() as connection:
            revision = connection.execute(
                text("select version_num from alembic_version")
            ).scalar()
        assert revision == AUTH_SUBJECT_REVISION

        # A row written while 0004 is applied — the downgrade must not lose it.
        # The stats columns are NOT NULL with Python-side defaults, which a raw
        # insert does not run, so they are supplied explicitly.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into \"user\" (id, username, total_lifetime_steps, "
                    "total_hexes_captured, current_streak, longest_streak, "
                    "auth_subject) values ("
                    "'11111111-1111-4111-8111-111111111111', 'survivor', "
                    "4242, 7, 3, 5, "
                    "'22222222-2222-4222-8222-222222222222')"
                )
            )
    finally:
        engine.dispose()

    # ── Downgrade ────────────────────────────────────────────────────────────
    downgrade = _run_alembic(db_url, "downgrade", AUTH_SUBJECT_PARENT)
    assert downgrade.returncode == 0, downgrade.stderr

    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)

        # The column and its index are gone...
        assert AUTH_SUBJECT_COLUMN not in {
            c["name"] for c in inspector.get_columns("user")
        }
        assert AUTH_SUBJECT_INDEX not in {
            ix["name"] for ix in inspector.get_indexes("user")
        }

        # ...the table is not, and its schema is exactly what it was before.
        # This is the assertion that separates "0004 was undone" from "0004
        # took the user table with it".
        assert "user" in inspector.get_table_names()
        assert {c["name"] for c in inspector.get_columns("user")} == USER_COLUMNS_BEFORE_0004

        # Positive control: the downgrade dropped 0004's index, not indexes.
        assert UNRELATED_INDEX in {
            ix["name"] for ix in inspector.get_indexes("user")
        }

        with engine.connect() as connection:
            revision = connection.execute(
                text("select version_num from alembic_version")
            ).scalar()
            assert revision == AUTH_SUBJECT_PARENT

            # The row is still there and the values in the surviving columns are
            # unchanged — dropping a column must not have rebuilt the table
            # around the data.
            survivor = connection.execute(
                text(
                    "select username, total_lifetime_steps, total_hexes_captured, "
                    "current_streak, longest_streak from \"user\" "
                    "where id = '11111111-1111-4111-8111-111111111111'"
                )
            ).one()
        assert survivor.username == "survivor"
        assert survivor.total_lifetime_steps == 4242
        assert survivor.total_hexes_captured == 7
        assert survivor.current_streak == 3
        assert survivor.longest_streak == 5
    finally:
        engine.dispose()


def test_re_running_the_upgrade_is_a_no_op(tmp_path):
    """The runbook has an operator type the upgrade command; a retry must be safe.

    Alembic tracks the applied revision, so a second ``upgrade 0004`` finds the
    database already at the target and does nothing — it does not re-run the
    DDL, does not duplicate the column, and does not error. That is what makes
    the command safe to re-issue after an ambiguous failure (a dropped
    connection, a closed terminal), which is exactly when someone would.

    Asserted rather than assumed because the failure mode if it were untrue is
    silent: a duplicated column would leave ``auth_subject`` ambiguous and the
    unique index split across the two.
    """
    from sqlalchemy import create_engine, inspect

    db_url = f"sqlite:///{(tmp_path / 'auth_subject_rerun.db').as_posix()}"

    first = _run_alembic(db_url, "upgrade", AUTH_SUBJECT_REVISION)
    assert first.returncode == 0, first.stderr

    second = _run_alembic(db_url, "upgrade", AUTH_SUBJECT_REVISION)
    assert second.returncode == 0, second.stderr

    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("user")]
        # Exactly one auth_subject column — not two, and not zero.
        assert columns.count(AUTH_SUBJECT_COLUMN) == 1
        # And the index was not duplicated either.
        names = [ix["name"] for ix in inspector.get_indexes("user")]
        assert names.count(AUTH_SUBJECT_INDEX) == 1
    finally:
        engine.dispose()
