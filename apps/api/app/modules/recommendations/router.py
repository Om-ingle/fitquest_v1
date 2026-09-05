import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.dependencies import get_db, get_current_user
from app.modules.recommendations.schemas import RecommendationResponse
from app.modules.recommendations.service import build_fitness_context, recommend

router = APIRouter()


@router.get("", response_model=RecommendationResponse)
def recommendations_endpoint(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> RecommendationResponse:
    """Personalized, deterministic (rules-first) recommendation for the
    current (dev) user, built from real server data only.

    No request parameters — the context (lifetime steps, territory
    ownership, capture recency, defense investment) is computed fresh
    from the database on every call.
    """
    user_id = uuid.UUID(current_user["id"])
    context = build_fitness_context(db, user_id)
    return RecommendationResponse(
        generated_at=datetime.utcnow(),
        context=context,
        recommendation=recommend(context),
    )
