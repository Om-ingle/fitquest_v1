import datetime
import hashlib
import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.runs.models import CapturedHex, RunSession, UserDailyActivity
from app.modules.runs.schemas import DailyActivitySnapshot, RunSyncPayload, RunSyncSummary
from app.modules.map.models import HexOwnership
from app.modules.users.models import User

from app.modules.triggers.engine import (
    CoachingTrigger,
    TriggerType,
    canonical_key,
    highest_milestone_crossed,
    trigger_engine,
)

logger = logging.getLogger(__name__)


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


def _already_processed_summary(user: User | None) -> RunSyncSummary:
    return RunSyncSummary(
        hexes_defended=0,
        hexes_stolen=0,
        hexes_newly_captured=0,
        xp_earned=0,
        new_total_lifetime_steps=user.total_lifetime_steps if user else 0,
        already_processed=True,
    )


def _legacy_content_scope(payload: RunSyncPayload) -> str:
    """Deterministic pseudo-id for the (rare) run sync that carries no run_id.

    Two replayed copies of the same legacy sync have identical content and
    therefore map to the same scope, so a retry can never double-emit. New
    clients always send a real run_id and never hit this path.
    """
    parts = [payload.total_session_steps]
    parts.extend(
        f"{hex_id}:{steps}"
        for hex_id, steps in sorted(payload.hexes_to_steps.items())
    )
    if payload.daily_activity is not None:
        parts.append(payload.daily_activity.activity_date.isoformat())
        parts.append(payload.daily_activity.steps)
    canonical = "|".join(str(p) for p in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _emit_run_triggers(
    current_user_id: uuid.UUID,
    payload: RunSyncPayload,
    summary: RunSyncSummary,
    occurred_at: datetime.datetime,
    territory_outcomes: list[dict[str, object]],
    prior_daily_steps: int | None,
) -> None:
    """M8.1 — emit coaching triggers for a run that JUST committed credit.

    Called only after the successful commit of a genuinely new run (replay
    paths return before reaching here). Read-only inputs collected during
    processing; the authoritative XP/territory/lifetime math is untouched.

    Strictly advisory: the whole emission is wrapped so a bug here can never
    turn an already-committed run sync into an error response. The engine
    itself does no I/O and its subscriber seam swallows subscriber errors, so
    this guard is belt-and-suspenders.
    """
    try:
        run_id = (payload.run_id or "").strip() or None
        # Dedupe identity for the run: the stable run_id when present, else a
        # content-derived scope for legacy clients (see _legacy_content_scope).
        run_scope = run_id or _legacy_content_scope(payload)
        ukey = str(current_user_id)

        # WORKOUT_COMPLETED — the run itself is the meaningful moment.
        trigger_engine.accept(
            CoachingTrigger(
                trigger_type=TriggerType.WORKOUT_COMPLETED,
                user_id=current_user_id,
                occurred_at=occurred_at,
                dedupe_key=canonical_key(ukey, TriggerType.WORKOUT_COMPLETED.value, run_scope),
                event_id=run_scope,
                payload={
                    "run_id": run_id,
                    "total_session_steps": payload.total_session_steps,
                    "xp_earned": summary.xp_earned,
                    "hexes_newly_captured": summary.hexes_newly_captured,
                    "hexes_stolen": summary.hexes_stolen,
                    "hexes_defended": summary.hexes_defended,
                    "new_total_lifetime_steps": summary.new_total_lifetime_steps,
                },
            )
        )

        # TERRITORY_CAPTURED — one per hex whose ownership changed to the user
        # (fresh claim of empty land OR a steal from a rival). Reinforcing a
        # hex you already own is not a capture and emits nothing.
        for outcome in territory_outcomes:
            trigger_engine.accept(
                CoachingTrigger(
                    trigger_type=TriggerType.TERRITORY_CAPTURED,
                    user_id=current_user_id,
                    occurred_at=occurred_at,
                    dedupe_key=canonical_key(
                        ukey,
                        TriggerType.TERRITORY_CAPTURED.value,
                        run_scope,
                        outcome["hex_id"],
                    ),
                    event_id=run_scope,
                    payload={
                        "hex_id": outcome["hex_id"],
                        "kind": outcome["kind"],
                        "defense_score_steps": outcome["defense_score_steps"],
                        "run_id": run_id,
                    },
                )
            )

        # ACTIVITY_MILESTONE — at most one per sync: the highest fixed daily
        # step milestone this sync pushed the user across (the persisted daily
        # row is the memory that makes the same day idempotent).
        if payload.daily_activity is not None and prior_daily_steps is not None:
            crossed = highest_milestone_crossed(
                prior_daily_steps, payload.daily_activity.steps
            )
            if crossed is not None:
                trigger_engine.accept(
                    CoachingTrigger(
                        trigger_type=TriggerType.ACTIVITY_MILESTONE,
                        user_id=current_user_id,
                        occurred_at=occurred_at,
                        dedupe_key=canonical_key(
                            ukey,
                            TriggerType.ACTIVITY_MILESTONE.value,
                            payload.daily_activity.activity_date.isoformat(),
                            crossed,
                        ),
                        event_id=run_scope,
                        payload={
                            "activity_date": payload.daily_activity.activity_date.isoformat(),
                            "daily_steps": payload.daily_activity.steps,
                            "milestone_steps": crossed,
                        },
                    )
                )
    except Exception:  # noqa: BLE001 — triggers are advisory, never fatal.
        logger.exception("M8.1 trigger emission failed for run scope (advisory; ignored)")


def process_run_sync(db: Session, payload: RunSyncPayload, current_user_id: uuid.UUID) -> RunSyncSummary:
    summary = RunSyncSummary(
        hexes_defended=0,
        hexes_stolen=0,
        hexes_newly_captured=0,
        xp_earned=0,
        new_total_lifetime_steps=0
    )
    # M8.1 — read-only outcome collectors for trigger emission. Gathered while
    # territory is processed below; the authoritative XP/ownership math above
    # is untouched.
    territory_outcomes: list[dict[str, object]] = []
    prior_daily_steps: int | None = None

    # Client-supplied stable run/session id. New clients send it so a retried
    # sync is recognised as already applied (Fix A replay guard). Old clients
    # omit it -> behaviour is exactly as before.
    run_id = (payload.run_id or "").strip() or None

    # 1. Update the user's total lifetime steps
    user = db.get(User, current_user_id)

    # Idempotency guard: if this run was already applied for this user, do not
    # apply it again. runsession is the natural replay ledger — one row per
    # applied run_id, keyed by id, keyed to the owning user.
    if run_id is not None:
        existing = db.get(RunSession, run_id)
        if existing is not None and existing.user_id == str(current_user_id):
            return _already_processed_summary(user)

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
            territory_outcomes.append(
                {"hex_id": hex_id, "kind": "captured", "defense_score_steps": steps_walked}
            )
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
                    territory_outcomes.append(
                        {"hex_id": hex_id, "kind": "stolen", "defense_score_steps": steps_walked}
                    )

    # 3. Persist the daily telemetry snapshot (Phase 4B.5), if the client
    # sent one. Same transaction as the game state; skipped when the user
    # row is missing (unseeded env) exactly like the lifetime-steps update
    # above — PostgreSQL FKs make this a no-op concern in seeded envs.
    # M8.1: read the PRE-update day total first so a milestone crossing can be
    # computed after commit (the upsert overwrites the row in place).
    if payload.daily_activity is not None and user is not None:
        stored_daily = db.get(
            UserDailyActivity,
            (current_user_id, payload.daily_activity.activity_date),
        )
        prior_daily_steps = stored_daily.steps if stored_daily is not None else 0
        upsert_daily_activity(db, current_user_id, payload.daily_activity)

    # Record the run in the replay ledger in the SAME transaction as the
    # credit, so a crash between commit and a lost response cannot double-
    # credit on replay. runsession is the natural marker (existing table,
    # no schema change); id is the client's run_id.
    if run_id is not None:
        db.add(RunSession(id=run_id, user_id=str(current_user_id)))

    try:
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent replay of the same run (same id
        # committed first). Roll back our partial write and confirm the
        # winner really was this run for this user before reporting it as
        # already processed; anything else is an unexpected conflict.
        db.rollback()
        existing = db.get(RunSession, run_id) if run_id is not None else None
        if existing is not None and existing.user_id == str(current_user_id):
            return _already_processed_summary(user)
        raise

    # M8.1 — coaching trigger engine. Only AFTER a successful commit of a
    # genuinely new run: every earlier return is a replay (no credit applied),
    # so it emits nothing. Strictly advisory (see _emit_run_triggers).
    if user is not None:
        _emit_run_triggers(
            current_user_id,
            payload,
            summary,
            occurred_at=datetime.datetime.now(datetime.timezone.utc),
            territory_outcomes=territory_outcomes,
            prior_daily_steps=prior_daily_steps,
        )
    return summary