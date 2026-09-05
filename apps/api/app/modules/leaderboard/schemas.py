import uuid
from typing import Optional

from pydantic import BaseModel


class LeaderboardEntry(BaseModel):
    """A single ranked player. The ranking metric is territory count
    (number of HexOwnership rows) — explicitly named `hexes_owned`."""

    rank: int
    user_id: uuid.UUID
    username: str
    avatar_url: Optional[str] = None
    hexes_owned: int
    is_current_user: bool


class LeaderboardResponse(BaseModel):
    """Server-backed leaderboard payload.

    `entries` holds the top-N players; `current_user_entry` repeats the
    current (dev) user's entry when they did not make the top-N cut.
    """

    metric: str = "hexes"
    total_players: int
    entries: list[LeaderboardEntry] = []
    current_user_entry: Optional[LeaderboardEntry] = None
