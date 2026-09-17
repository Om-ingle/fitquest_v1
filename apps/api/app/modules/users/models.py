import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.modules.map.models import HexOwnership
    from app.modules.quests.models import UserQuest


class Friendship(SQLModel, table=True):
    """
    Tracks friend requests and accepted friends.
    Composite primary key prevents duplicate friendships.
    """

    requester_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    addressee_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    status: str = Field(default="pending")  # "pending", "accepted", "blocked"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    """Core User model with Profile stats, Streak logic, and Relationships."""

    # CRITICAL: `id` is the INTERNAL key every domain table references
    # (hexownership.king_id, runsession.user_id, userdailyactivity.user_id,
    # friendship.*). It is never the external identity — see `auth_subject`.
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    username: str = Field(unique=True, index=True)
    avatar_url: Optional[str] = None

    # M11 — the Supabase Auth identity this row belongs to: the `sub` claim of
    # the verified JWT, i.e. `auth.users.id`. Kept deliberately separate from
    # `id` so the two id spaces can never be confused: an external subject is
    # matched to a row here, and everything downstream keeps using the internal
    # UUID. NULL means "not linked to a login" — which is exactly the seeded
    # development/test users, whose existing rows are never rewritten,
    # reassigned, or mapped onto a real account.
    auth_subject: Optional[str] = Field(default=None, unique=True, index=True)

    # --- PROFILE STATS ---
    total_lifetime_steps: int = Field(default=0)
    total_hexes_captured: int = Field(default=0)

    # --- STREAK SYSTEM ---
    # To calculate a streak, we just check if today > last_activity_date + 1 day
    current_streak: int = Field(default=0)
    longest_streak: int = Field(default=0)
    last_activity_date: Optional[date] = None

    # --- RELATIONSHIPS ---
    # Defines the reverse relationship for the Map module
    owned_hexes: list["HexOwnership"] = Relationship(back_populates="king")
    active_quests: list["UserQuest"] = Relationship(back_populates="user")
