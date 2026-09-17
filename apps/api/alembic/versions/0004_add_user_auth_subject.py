"""link user rows to a Supabase Auth identity (M11 / F-04)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-13

Adds ``user.auth_subject``: the verified JWT ``sub`` claim, i.e. the
``auth.users.id`` the row belongs to. It is the bridge between the identity
provider and FitQuest's own user rows, and it is deliberately NOT the primary
key — every domain table keeps referencing the internal ``user.id``.

Purely additive and deliberately un-backfilled:

* NULL means "not linked to any login". All existing rows — including the
  seeded dev/test users — stay NULL, so no existing data is rewritten,
  reassigned, or orphaned by this milestone. Linking a row to a real account
  is an explicit act (the seed script for the dev/test users, first login for
  a real one), never a side effect of deploying a migration.
* The unique index is what makes the mapping one-to-one and lets a first
  login resolve deterministically. PostgreSQL treats NULLs as distinct, so any
  number of unlinked rows coexist under it.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("auth_subject", sa.String(), nullable=True))
    # SQLModel's Field(unique=True, index=True) produces a UNIQUE index named
    # by op.f(); matching that name keeps the model and the schema in step.
    op.create_index(
        op.f("ix_user_auth_subject"), "user", ["auth_subject"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_auth_subject"), table_name="user")
    op.drop_column("user", "auth_subject")
