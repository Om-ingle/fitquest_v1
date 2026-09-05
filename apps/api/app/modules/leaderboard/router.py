import uuid

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.dependencies import get_db, get_current_user
from app.modules.leaderboard.schemas import LeaderboardResponse
from app.modules.leaderboard.service import get_leaderboard

router = APIRouter()


@router.get("", response_model=LeaderboardResponse)
def leaderboard_endpoint(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> LeaderboardResponse:
    """Territory leaderboard ranked by hex count (COUNT(HexOwnership)).

    Returns the top-N players and, when the current (dev) user is outside
    the top N, their entry separately via `current_user_entry`.
    """
    user_id = uuid.UUID(current_user["id"])
    return get_leaderboard(db, user_id, limit)
