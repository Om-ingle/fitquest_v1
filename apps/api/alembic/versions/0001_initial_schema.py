"""initial schema: users, friendships, hex ownership, runs, quests

Revision ID: 0001
Revises:
Create Date: 2026-09-05

Creates the Phase 1 FitQuest schema in PostgreSQL (Supabase), matching the
SQLModel metadata in app/modules/*/models.py:
  - user, friendship (users module)
  - hexownership (map module)
  - runsession, capturedhex (runs module)
  - quest, userquest (quests module)

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("total_lifetime_steps", sa.Integer(), nullable=False),
        sa.Column("total_hexes_captured", sa.Integer(), nullable=False),
        sa.Column("current_streak", sa.Integer(), nullable=False),
        sa.Column("longest_streak", sa.Integer(), nullable=False),
        sa.Column("last_activity_date", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # SQLModel's Field(unique=True, index=True) produces a UNIQUE index, not a
    # separate unique constraint.
    op.create_index(op.f("ix_user_username"), "user", ["username"], unique=True)

    op.create_table(
        "friendship",
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("addressee_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["addressee_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["requester_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("requester_id", "addressee_id"),
    )

    op.create_table(
        "hexownership",
        sa.Column("hex_id", sa.String(), nullable=False),
        sa.Column("king_id", sa.Uuid(), nullable=False),
        sa.Column("defense_score_steps", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("times_stolen", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["king_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("hex_id"),
    )
    op.create_index(op.f("ix_hexownership_king_id"), "hexownership", ["king_id"], unique=False)

    op.create_table(
        "runsession",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runsession_user_id"), "runsession", ["user_id"], unique=False)

    op.create_table(
        "capturedhex",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("hex_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_capturedhex_run_id"), "capturedhex", ["run_id"], unique=False)
    op.create_index(op.f("ix_capturedhex_hex_id"), "capturedhex", ["hex_id"], unique=False)

    op.create_table(
        "quest",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("target_metric", sa.String(), nullable=False),
        sa.Column("target_value", sa.Integer(), nullable=False),
        sa.Column("reward_xp", sa.Integer(), nullable=False),
        sa.Column("active_date", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quest_title"), "quest", ["title"], unique=False)
    op.create_index(op.f("ix_quest_active_date"), "quest", ["active_date"], unique=False)

    op.create_table(
        "userquest",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("quest_id", sa.Uuid(), nullable=False),
        sa.Column("current_progress", sa.Integer(), nullable=False),
        sa.Column("is_completed", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["quest_id"], ["quest.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("user_id", "quest_id"),
    )


def downgrade() -> None:
    op.drop_table("userquest")
    op.drop_index(op.f("ix_quest_active_date"), table_name="quest")
    op.drop_index(op.f("ix_quest_title"), table_name="quest")
    op.drop_table("quest")
    op.drop_index(op.f("ix_capturedhex_hex_id"), table_name="capturedhex")
    op.drop_index(op.f("ix_capturedhex_run_id"), table_name="capturedhex")
    op.drop_table("capturedhex")
    op.drop_index(op.f("ix_runsession_user_id"), table_name="runsession")
    op.drop_table("runsession")
    op.drop_index(op.f("ix_hexownership_king_id"), table_name="hexownership")
    op.drop_table("hexownership")
    op.drop_table("friendship")
    op.drop_index(op.f("ix_user_username"), table_name="user")
    op.drop_table("user")
