import uuid
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from app.modules.map.models import HexOwnership
from app.modules.recommendations.schemas import FitnessContext, Recommendation
from app.modules.runs.models import UserDailyActivity
from app.modules.users.models import User

# A capture counts as "recent" for this many days.
RECENT_CAPTURE_WINDOW_DAYS = 7
# Without a capture for more than this many days the player is lapsed.
LAPSED_AFTER_DAYS = 2
# Consistency bar for the harder challenge.
CONSISTENT_CAPTURES_7D = 3


def build_fitness_context(db: Session, user_id: uuid.UUID) -> FitnessContext:
    """Build the recommendation context from REAL server data only.

    A missing user row simply yields zeroed stats (the dev user may not
    exist yet) — the rules engine treats that as a cold start.

    Daily-activity telemetry is taken from the user's LATEST reported
    ``UserDailyActivity`` row (max activity_date). The row's own date is
    carried into ``activity_date`` so nothing is mislabeled as "today"
    when the latest report is older (server-UTC and device-local dates
    differ by design). When no row exists the daily fields stay None —
    never a fabricated zero.
    """
    user = db.get(User, user_id)
    total_lifetime_steps = user.total_lifetime_steps if user else 0

    # Territory aggregates from HexOwnership — the authoritative source
    # for hex counts (User.total_hexes_captured is never incremented).
    hexes_owned, total_defense_steps, last_capture_at = db.exec(
        select(
            func.count(HexOwnership.hex_id),
            func.sum(HexOwnership.defense_score_steps),
            func.max(HexOwnership.captured_at),
        ).where(HexOwnership.king_id == user_id)
    ).one()

    # Captures inside the 7-day window (captured_at only changes on new
    # captures/steals — reinforcement runs are not reflected, by design).
    cutoff = datetime.utcnow() - timedelta(days=RECENT_CAPTURE_WINDOW_DAYS)
    recent_captures_7d = db.exec(
        select(func.count(HexOwnership.hex_id)).where(
            HexOwnership.king_id == user_id,
            HexOwnership.captured_at >= cutoff,
        )
    ).one()

    # Latest reported activity day (single row per (user, activity_date)).
    latest_daily = db.exec(
        select(UserDailyActivity)
        .where(UserDailyActivity.user_id == user_id)
        .order_by(UserDailyActivity.activity_date.desc())
        .limit(1)
    ).first()

    goal_progress_ratio = None
    if latest_daily is not None:
        if latest_daily.goal_steps and latest_daily.goal_steps > 0:
            goal_progress_ratio = round(
                min(1.0, latest_daily.steps / latest_daily.goal_steps), 3
            )

    return FitnessContext(
        user_id=user_id,
        total_lifetime_steps=total_lifetime_steps,
        hexes_owned=hexes_owned or 0,
        recent_captures_7d=recent_captures_7d or 0,
        last_capture_at=last_capture_at,
        total_defense_steps=total_defense_steps or 0,
        activity_date=latest_daily.activity_date if latest_daily else None,
        steps_today=latest_daily.steps if latest_daily else None,
        active_minutes_today=latest_daily.active_minutes if latest_daily else None,
        goal_steps=latest_daily.goal_steps if latest_daily else None,
        goal_completed_today=latest_daily.goal_completed if latest_daily else None,
        goal_progress_ratio=goal_progress_ratio,
    )


def _naive_utc(dt: datetime) -> datetime:
    """Normalize to naive UTC so comparisons never raise on tz-aware values."""
    if dt.tzinfo is not None:
        return dt.astimezone(tz=None).replace(tzinfo=None)
    return dt


def _older_than_days(dt: datetime, days: int) -> bool:
    return datetime.utcnow() - _naive_utc(dt) > timedelta(days=days)


def recommend(context: FitnessContext) -> Recommendation:
    """Pure deterministic rules engine: same context in, same
    recommendation out — no randomness, no time-of-evaluation effects
    beyond the values already captured in the context.

    Priority: R1 COLD_START > R2 LAPSED_PLAYER > R3 TERRITORY_AT_RISK
    > R4 CONSISTENT_PERFORMER > R5 DEFAULT (MAINTAIN).
    """
    has_history = context.hexes_owned > 0 or context.total_lifetime_steps > 0
    is_lapsed = context.last_capture_at is None or _older_than_days(
        context.last_capture_at, LAPSED_AFTER_DAYS
    )

    # R1 COLD_START — brand new player with zero footprint.
    if context.hexes_owned == 0 and context.total_lifetime_steps == 0:
        return Recommendation(
            type="STARTER",
            title="Start your territory",
            description=(
                "You have no territory yet. Walk 1,000 steps to claim "
                "your very first hex and start your empire."
            ),
            target_metric="steps",
            target_value=1000,
            difficulty="easy",
            reason_code="COLD_START",
            reason="hexes_owned=0 and total_lifetime_steps=0",
        )

    # R2 LAPSED_PLAYER — has history but no recent capture.
    if is_lapsed and has_history:
        if context.last_capture_at is None:
            reason = (
                f"last_capture_at=None while hexes_owned={context.hexes_owned} "
                f"and total_lifetime_steps={context.total_lifetime_steps}"
            )
        else:
            reason = (
                f"last_capture_at={context.last_capture_at.isoformat()} is older "
                f"than {LAPSED_AFTER_DAYS} days while hexes_owned={context.hexes_owned}"
            )
        return Recommendation(
            type="RECOVERY",
            title="Get back out there",
            description=(
                "It's been more than two days since your last capture. "
                "An easy 2,000-step walk gets you back on the board."
            ),
            target_metric="steps",
            target_value=2000,
            difficulty="easy",
            reason_code="LAPSED_PLAYER",
            reason=reason,
        )

    # R3 TERRITORY_AT_RISK — owns land but nothing captured this week.
    if context.hexes_owned > 0 and context.recent_captures_7d == 0:
        return Recommendation(
            type="DEFENSE",
            title="Your territory needs you",
            description=(
                f"You own {context.hexes_owned} hexes but haven't captured "
                "or reinforced anything in over 7 days — defense scores "
                "are frozen. Walk and hold 1 owned hex to reinforce it."
            ),
            target_metric="hexes",
            target_value=1,
            difficulty="medium",
            reason_code="TERRITORY_AT_RISK",
            reason=(
                f"recent_captures_7d=0 while hexes_owned={context.hexes_owned}"
            ),
        )

    # R4 CONSISTENT_PERFORMER — actively capturing all week.
    if context.recent_captures_7d >= CONSISTENT_CAPTURES_7D:
        return Recommendation(
            type="PROGRESS",
            title="Expand your empire",
            description=(
                f"You've captured {context.recent_captures_7d} hexes in the "
                "last 7 days. Push for 3 more to grow your territory."
            ),
            target_metric="hexes",
            target_value=3,
            difficulty="hard",
            reason_code="CONSISTENT_PERFORMER",
            reason=f"recent_captures_7d={context.recent_captures_7d}",
        )

    # R5 DEFAULT — recently active at a moderate volume.
    return Recommendation(
        type="MAINTAIN",
        title="Keep the streak alive",
        description=(
            "You're active and holding territory. A steady 3,000-step "
            "walk today keeps your momentum going."
        ),
        target_metric="steps",
        target_value=3000,
        difficulty="medium",
        reason_code="MAINTAIN",
        reason=(
            f"recent_captures_7d={context.recent_captures_7d} and "
            f"hexes_owned={context.hexes_owned} (active within normal range)"
        ),
    )
