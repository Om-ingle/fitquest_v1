import datetime
import uuid
from sqlmodel import Session, select

from app.modules.runs.models import CapturedHex, RunSession, UserDailyActivity
from app.modules.runs.schemas import DailyActivitySnapshot, RunSyncPayload, RunSyncSummary
from app.modules.map.models import HexOwnership
from app.modules.users.models import User


def upsert_daily_activity(
    db: Session,
    current_user_id: uuid.UUID,
    snapshot: DailyActivitySnapshot,
) -> UserDailyActivity:
    """Merge-upsert the user's daily telemetry snapshot (Phase 4B.5).

    The snapshot carries absolute day-to-date values, so re-sending the same
    snapshot is idempotent (same row, same values). Non-null incoming fields
    replace the stored ones; null fields keep the stored ones, which makes
    partial updates safe and late corrections deterministic per field.
    """
    existing = db.get(UserDailyActivity, (current_user_id, snapshot.activity_date))
    if existing is None:
        row = UserDailyActivity(
            user_id=current_user_id,
            activity_date=snapshot.activity_date,
            steps=snapshot.steps,
            active_minutes=snapshot.active_minutes,
            updated_at=datetime.datetime.now(datetime.timezone.utc),
        )
    else:
        row = existing
        row.steps = snapshot.steps
        row.active_minutes = snapshot.active_minutes
        row.updated_at = datetime.datetime.now(datetime.timezone.utc)

    # Optional fields: None means "not reported" -> keep whatever is stored.
    for field in (
        "goal_steps",
        "goal_completed",
        "hexes_owned",
        "hexes_captured",
        "hexes_lost",
        "defense_steps",
    ):
        value = getattr(snapshot, field)
        if value is not None:
            setattr(row, field, value)

    db.add(row)
    return row


def process_run_sync(db: Session, payload: RunSyncPayload, current_user_id: uuid.UUID) -> RunSyncSummary:
    summary = RunSyncSummary(
        hexes_defended=0,
        hexes_stolen=0,
        hexes_newly_captured=0,
        xp_earned=0,
        new_total_lifetime_steps=0
    )

    # 1. Update the user's total lifetime steps
    user = db.get(User, current_user_id)
    if user:
        user.total_lifetime_steps += payload.total_session_steps
        summary.new_total_lifetime_steps = user.total_lifetime_steps
        db.add(user)

    # 2. Process the Turf War for each Hexagon
    for hex_id, steps_walked in payload.hexes_to_steps.items():
        # Get the current hex from the database
        statement = select(HexOwnership).where(HexOwnership.hex_id == hex_id)
        current_hex = db.exec(statement).first()

        if not current_hex:
            # NO OWNER: The user claims empty territory
            new_hex = HexOwnership(
                hex_id=hex_id,
                king_id=current_user_id,
                defense_score_steps=steps_walked
            )
            db.add(new_hex)
            summary.hexes_newly_captured += 1
            summary.xp_earned += 50
            
        else:
            # SOMEONE OWNS IT: Let's see who it is and if we beat them
            if current_hex.king_id == current_user_id:
                # User already owns it! Just reinforce the defense score
                current_hex.defense_score_steps += steps_walked
                db.add(current_hex)
                summary.hexes_defended += 1
                summary.xp_earned += 10
            else:
                # RIVAL OWNS IT: Did we beat their score?
                if steps_walked > current_hex.defense_score_steps:
                    # WE STOLE IT!
                    current_hex.king_id = current_user_id
                    current_hex.defense_score_steps = steps_walked # Reset the bar to the new winner's score
                    current_hex.times_stolen += 1
                    db.add(current_hex)
                    summary.hexes_stolen += 1
                    summary.xp_earned += 100

    # 3. Persist the daily telemetry snapshot (Phase 4B.5), if the client
    # sent one. Same transaction as the game state; skipped when the user
    # row is missing (unseeded env) exactly like the lifetime-steps update
    # above — PostgreSQL FKs make this a no-op concern in seeded envs.
    if payload.daily_activity is not None and user is not None:
        upsert_daily_activity(db, current_user_id, payload.daily_activity)

    db.commit()
    return summary