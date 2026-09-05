import uuid

from sqlalchemy import func
from sqlmodel import Session, select

from app.modules.leaderboard.schemas import LeaderboardEntry, LeaderboardResponse
from app.modules.map.models import HexOwnership
from app.modules.users.models import User

# Ranking metric: territory count — COUNT(HexOwnership) GROUP BY king_id.
METRIC_NAME = "hexes"


def get_leaderboard(
    db: Session, current_user_id: uuid.UUID, limit: int
) -> LeaderboardResponse:
    # Territory counts per king (users without hexes simply get 0).
    count_rows = db.exec(
        select(HexOwnership.king_id, func.count())
        .group_by(HexOwnership.king_id)  # type: ignore[arg-type]
    ).all()
    hex_counts: dict[uuid.UUID, int] = {row[0]: row[1] for row in count_rows}

    # Every real user appears (zero-territory players included); no
    # fabricated users or scores. Ties break alphabetically on username
    # so ordering is deterministic.
    users = list(db.exec(select(User)).all())
    ranked = sorted(
        ((user, hex_counts.get(user.id, 0)) for user in users),
        key=lambda pair: (-pair[1], pair[0].username),
    )

    # Competition ranking: equal counts share a rank.
    entries: list[LeaderboardEntry] = []
    for position, (user, count) in enumerate(ranked, start=1):
        rank = position
        if entries and entries[-1].hexes_owned == count:
            rank = entries[-1].rank
        entries.append(
            LeaderboardEntry(
                rank=rank,
                user_id=user.id,
                username=user.username,
                avatar_url=user.avatar_url,
                hexes_owned=count,
                is_current_user=(user.id == current_user_id),
            )
        )

    top = entries[:limit]
    current_user_entry = next(
        (entry for entry in entries if entry.user_id == current_user_id), None
    )
    in_top = any(entry.is_current_user for entry in top)

    return LeaderboardResponse(
        metric=METRIC_NAME,
        total_players=len(entries),
        entries=top,
        # Only surface the current user separately when they missed the cut.
        current_user_entry=None if in_top else current_user_entry,
    )
