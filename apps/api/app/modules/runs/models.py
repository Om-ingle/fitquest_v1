import datetime
import uuid

from sqlmodel import Field, SQLModel


class RunSession(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    started_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))


class CapturedHex(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    hex_id: str = Field(index=True)


class UserDailyActivity(SQLModel, table=True):
    """One row per (user, activity_date): the user's day as last reported by
    their device (Phase 4B.5 telemetry).

    Raw daily signals only — never ML features, never game state. The device
    sends absolute day-to-date values; the row is merge-upserted so repeated
    syncs are idempotent and late corrections deterministically overwrite.
    Optional columns are NULL = "not reported", which keeps a previous value
    on partial updates. Game state (XP, hex ownership) stays in its own
    authoritative tables; this table is observational telemetry for the ML
    pipeline (see tools/synthetic_fitness/real_telemetry_gap_analysis.md).
    """

    user_id: uuid.UUID = Field(primary_key=True, foreign_key="user.id")
    activity_date: datetime.date = Field(primary_key=True)
    steps: int = Field(nullable=False, default=0)
    active_minutes: int = Field(nullable=False, default=0)
    goal_steps: int | None = Field(default=None)
    goal_completed: bool | None = Field(default=None)
    hexes_owned: int | None = Field(default=None)
    hexes_captured: int | None = Field(default=None)
    hexes_lost: int | None = Field(default=None)
    defense_steps: int | None = Field(default=None)
    updated_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
