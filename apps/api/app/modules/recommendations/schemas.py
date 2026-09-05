import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class FitnessContext(BaseModel):
    """Personalized context for the recommendation engine.

    Every field is computed from REAL server data (User + HexOwnership)
    only — no XP, level, streak, distance, calories, or run history is
    invented here because none of those exist server-side yet.
    """

    user_id: uuid.UUID
    total_lifetime_steps: int
    hexes_owned: int
    recent_captures_7d: int
    last_capture_at: Optional[datetime] = None
    total_defense_steps: int


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
