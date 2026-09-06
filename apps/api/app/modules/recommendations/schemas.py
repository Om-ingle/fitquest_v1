import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class FitnessContext(BaseModel):
    """Personalized context for the recommendation engine.

    Every field is computed from REAL server data only (User +
    HexOwnership + the device's daily activity telemetry). No XP, level,
    streak, distance, calories, or run history is invented here because
    none of those exist server-side yet.
    """

    user_id: uuid.UUID
    total_lifetime_steps: int
    hexes_owned: int
    recent_captures_7d: int
    last_capture_at: Optional[datetime] = None
    total_defense_steps: int

    # Daily-activity telemetry from UserDailyActivity (Phase 4B.5) — the
    # LATEST reported activity day per user, never fabricated and never a
    # wrong zero. ``activity_date`` is the device's local calendar date for
    # the row, so the LLM can phrase the numbers honestly even when the
    # latest report is not literally "today" (server-UTC vs device-local
    # dates legitimately differ). All of these are None until a device has
    # reported a day.
    activity_date: Optional[date] = None
    steps_today: Optional[int] = None
    active_minutes_today: Optional[int] = None
    goal_steps: Optional[int] = None
    goal_completed_today: Optional[bool] = None
    goal_progress_ratio: Optional[float] = None


class Recommendation(BaseModel):
    """A single deterministic recommendation produced by the rules engine."""

    type: str
    title: str
    description: str
    target_metric: str  # "steps" | "hexes"
    target_value: int
    difficulty: str  # "easy" | "medium" | "hard"
    reason_code: str
    # Human-readable explanation built from the actual context values.
    reason: str


class RecommendationResponse(BaseModel):
    """GET /api/v1/recommendations payload. The context is echoed so the
    client (and any later LLM stage) can show WHY the engine decided."""

    generated_at: datetime
    context: FitnessContext
    recommendation: Recommendation
