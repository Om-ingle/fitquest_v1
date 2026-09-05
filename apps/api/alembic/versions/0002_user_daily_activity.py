"""user daily activity telemetry table (Phase 4B.5)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05

Adds the ``userdailyactivity`` table: one row per (user, activity_date)
holding the device-reported daily telemetry snapshot (steps, active minutes,
goal, territory observations) that the ML feature pipeline consumes. Purely
additive — no existing table is modified.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "userdailyactivity",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("active_minutes", sa.Integer(), nullable=False),
        sa.Column("goal_steps", sa.Integer(), nullable=True),
        sa.Column("goal_completed", sa.Boolean(), nullable=True),
        sa.Column("hexes_owned", sa.Integer(), nullable=True),
        sa.Column("hexes_captured", sa.Integer(), nullable=True),
        sa.Column("hexes_lost", sa.Integer(), nullable=True),
        sa.Column("defense_steps", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("user_id", "activity_date"),
    )
    # Export queries scan date ranges across all users.
    op.create_index(
        op.f("ix_userdailyactivity_activity_date"),
        "userdailyactivity",
        ["activity_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_userdailyactivity_activity_date"), table_name="userdailyactivity"
    )
    op.drop_table("userdailyactivity")
