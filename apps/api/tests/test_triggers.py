"""M8.1 trigger-engine tests.

Two layers, mirroring the module's two responsibilities:

  * pure engine tests (no DB): classification rules (``TriggerDecision``),
    deterministic dedupe, per-(user, type) cooldown, milestone-boundary and
    key behaviour, bounded dedupe log, the M8.2 subscribe seam.
  * integration tests against real ``process_run_sync`` commits: only a
    genuinely NEW run emits; a replay emits nothing; claiming empty land,
    stealing from a rival and reinforcing your own hex map to exactly the
    right TERRITORY_CAPTURED triggers; a fixed milestone ladder fires at most
    one ACTIVITY_MILESTONE per sync and is idempotent across runs/restarts.

The three implemented trigger types each correspond to a real event source
(workout completion, territory ownership change, daily-step milestone). The
engine never triggers on irrelevant events — a run with no territory change
or milestone crossing still emits only WORKOUT_COMPLETED.
"""
import datetime as dt
import uuid

import pytest
from sqlmodel import Session, SQLModel

from app.api.dependencies import DEV_USER_ID
from app.core.database import engine
from app.modules.map.models import HexOwnership
from app.modules.runs.schemas import DailyActivitySnapshot, RunSyncPayload
from app.modules.runs.service import process_run_sync
from app.modules.triggers.engine import (
    ACTIVITY_MILESTONE_STEPS,
    CoachingTrigger,
    TriggerDecision,
    TriggerEngine,
    TriggerType,
    canonical_key,
    highest_milestone_crossed,
    trigger_engine,
)
from app.modules.users.models import User

USER_ID = uuid.UUID(DEV_USER_ID)
RIVAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
T0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures & helpers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def db():
    # The service emits into the process-global trigger_engine singleton;
    # clear it with the DB so accepted triggers never leak across tests.
    trigger_engine.clear()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)
    trigger_engine.clear()


def _seed_user(session, user_id: uuid.UUID, steps: int = 0) -> None:
    session.add(
        User(id=user_id, username=f"user-{user_id.hex[-12:]}",
             total_lifetime_steps=steps)
    )
    session.commit()


def _trigger(
    *,
    user_id: uuid.UUID = USER_ID,
    trigger_type: TriggerType = TriggerType.WORKOUT_COMPLETED,
    dedupe_key: str = "k",
    occurred_at: dt.datetime = T0,
    event_id: str | None = "e",
    payload: dict | None = None,
) -> CoachingTrigger:
    return CoachingTrigger(
        trigger_type=trigger_type,
        user_id=user_id,
        occurred_at=occurred_at,
        dedupe_key=dedupe_key,
        event_id=event_id,
        payload=payload or {},
    )


def _daily(steps: int, *, activity_date: dt.date | None = None) -> DailyActivitySnapshot:
    return DailyActivitySnapshot(
        activity_date=activity_date or dt.date.today(),
        steps=steps,
        active_minutes=30,
    )


def _payload(*, run_id=None, session_steps=0, hexes=None, daily=None) -> RunSyncPayload:
    return RunSyncPayload(
        total_session_steps=session_steps,
        hexes_to_steps=hexes or {},
        daily_activity=daily,
        run_id=run_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pure engine: accept / dedupe / cooldown / log
# ─────────────────────────────────────────────────────────────────────────────


def test_default_cooldowns_match_design():
    eng = TriggerEngine()
    assert eng.default_cooldown_seconds(TriggerType.WORKOUT_COMPLETED) > 0
    # Distinct captures / crossings are never dropped by the cooldown gate;
    # they are deduplicated exactly instead.
    assert eng.default_cooldown_seconds(TriggerType.TERRITORY_CAPTURED) == 0.0
    assert eng.default_cooldown_seconds(TriggerType.ACTIVITY_MILESTONE) == 0.0


def test_accept_records_and_accepted_is_filterable_by_user():
    # Territory type (cooldown 0) so cooldown doesn't mask the point of the
    # test: distinct keys of one user are all accepted and filterable.
    eng = TriggerEngine()
    a = _trigger(trigger_type=TriggerType.TERRITORY_CAPTURED, dedupe_key="a")
    b = _trigger(trigger_type=TriggerType.TERRITORY_CAPTURED, dedupe_key="b")
    other = _trigger(
        user_id=RIVAL_ID,
        trigger_type=TriggerType.TERRITORY_CAPTURED,
        dedupe_key="other",
    )
    assert eng.accept(a) is TriggerDecision.ACCEPTED
    assert eng.accept(b) is TriggerDecision.ACCEPTED
    assert eng.accept(other) is TriggerDecision.ACCEPTED

    assert [t.dedupe_key for t in eng.accepted()] == ["a", "b", "other"]
    assert [t.dedupe_key for t in eng.accepted(user_id=USER_ID)] == ["a", "b"]
    assert eng.accepted(user_id=RIVAL_ID)[0].dedupe_key == "other"


def test_duplicate_same_dedupe_key_accepted_once():
    eng = TriggerEngine()
    t = _trigger(dedupe_key="user|workout_completed|run-1")
    assert eng.accept(t) is TriggerDecision.ACCEPTED
    # Repeated processing of the same event -> no duplicate trigger.
    assert eng.accept(t) is TriggerDecision.DUPLICATE
    assert eng.accept(t) is TriggerDecision.DUPLICATE
    assert len(eng.accepted()) == 1


def test_distinct_keys_of_same_user_and_type_are_all_accepted():
    # Two territory captures from one run carry distinct (run, hex) keys and
    # must never be conflated by dedupe.
    eng = TriggerEngine()
    c1 = _trigger(trigger_type=TriggerType.TERRITORY_CAPTURED, dedupe_key="run1|hexA")
    c2 = _trigger(
        trigger_type=TriggerType.TERRITORY_CAPTURED,
        dedupe_key="run1|hexB",
        occurred_at=T0 + dt.timedelta(seconds=2),
    )
    assert eng.accept(c1) is TriggerDecision.ACCEPTED
    assert eng.accept(c2) is TriggerDecision.ACCEPTED
    assert len(eng.accepted()) == 2


def test_workout_cooldown_suppresses_burst_then_allows_after_window():
    eng = TriggerEngine()
    base = _trigger(dedupe_key="run-1", occurred_at=T0)
    burst = _trigger(dedupe_key="run-2", occurred_at=T0 + dt.timedelta(seconds=2))
    later = _trigger(dedupe_key="run-3", occurred_at=T0 + dt.timedelta(seconds=12))

    assert eng.accept(base) is TriggerDecision.ACCEPTED
    # Distinct run, but inside the 10s per-(user, type) window.
    assert eng.accept(burst) is TriggerDecision.COOLDOWN
    assert len(eng.accepted()) == 1
    # After the window a genuine new run is accepted again.
    assert eng.accept(later) is TriggerDecision.ACCEPTED
    assert len(eng.accepted()) == 2


def test_zero_cooldown_types_pass_at_same_instant_when_keys_differ():
    eng = TriggerEngine()
    # Two milestones on the SAME day/instant but different thresholds: both
    # are meaningful and both survive (cooldown 0; keys differ by threshold).
    m5 = _trigger(
        trigger_type=TriggerType.ACTIVITY_MILESTONE,
        dedupe_key="2026-01-01|5000",
    )
    m10 = _trigger(
        trigger_type=TriggerType.ACTIVITY_MILESTONE,
        dedupe_key="2026-01-01|10000",
    )
    assert eng.accept(m5) is TriggerDecision.ACCEPTED
    assert eng.accept(m10) is TriggerDecision.ACCEPTED
    assert len(eng.accepted()) == 2


def test_raising_subscriber_never_fails_accept():
    eng = TriggerEngine()

    def boom(_trigger: CoachingTrigger) -> None:
        raise RuntimeError("subscriber exploded")

    eng.subscribe(boom)
    assert eng.accept(_trigger(dedupe_key="x")) is TriggerDecision.ACCEPTED


def test_subscriber_sees_accepted_triggers_only():
    # Territory (cooldown 0) so the second distinct key is not cooldown-gated.
    eng = TriggerEngine()
    seen: list[str] = []
    eng.subscribe(lambda t: seen.append(t.dedupe_key))

    eng.accept(_trigger(trigger_type=TriggerType.TERRITORY_CAPTURED, dedupe_key="a"))
    eng.accept(_trigger(trigger_type=TriggerType.TERRITORY_CAPTURED, dedupe_key="a"))  # duplicate
    eng.accept(_trigger(trigger_type=TriggerType.TERRITORY_CAPTURED, dedupe_key="b"))
    assert seen == ["a", "b"]


def test_dedupe_log_is_bounded_and_evicts_lru():
    # Territory (cooldown 0) so eviction semantics aren't masked by cooldown.
    eng = TriggerEngine(capacity=2)
    c1 = _trigger(trigger_type=TriggerType.TERRITORY_CAPTURED, dedupe_key="hexA")
    c2 = _trigger(trigger_type=TriggerType.TERRITORY_CAPTURED, dedupe_key="hexB")
    c3 = _trigger(trigger_type=TriggerType.TERRITORY_CAPTURED, dedupe_key="hexC")

    eng.accept(c1)
    eng.accept(c2)
    eng.accept(c3)  # evicts hexA (oldest)
    assert eng.accept(c3) is TriggerDecision.DUPLICATE  # still resident
    assert eng.accept(c1) is TriggerDecision.ACCEPTED  # evicted -> accepted again


# ─────────────────────────────────────────────────────────────────────────────
# Pure engine: classification rules (milestones, keys)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "previous,current,expected",
    [
        (0, 0, None),               # no movement
        (0, 4999, None),            # below first rung
        (0, 5000, 5000),            # exactly on the boundary
        (4999, 5000, 5000),         # strict crossing
        (5000, 5000, None),         # same value is NOT a crossing
        (5000, 4999, None),         # decrease is not a crossing
        (8000, 12000, 10000),       # crosses only 10k
        (5000, 15000, 15000),       # highest of several crossed rungs
        (0, 20000, 20000),          # jumps the whole ladder -> top rung only
        (15000, 10000, None),       # already past, now reporting lower
    ],
)
def test_highest_milestone_crossed_boundaries(previous, current, expected):
    assert highest_milestone_crossed(previous, current) == expected


def test_milestone_ladder_is_sorted_and_includes_default_goal():
    assert ACTIVITY_MILESTONE_STEPS == tuple(sorted(ACTIVITY_MILESTONE_STEPS))
    assert 10_000 in ACTIVITY_MILESTONE_STEPS  # the app's default daily goal


def test_canonical_key_is_stable_and_type_scoped():
    k1 = canonical_key(str(USER_ID), "workout_completed", "run-1")
    assert k1 == canonical_key(str(USER_ID), "workout_completed", "run-1")
    # Type rides inside the key so identical parts of different types never
    # collide.
    assert k1 != canonical_key(str(USER_ID), "territory_captured", "run-1")
    assert canonical_key(str(USER_ID), "territory_captured", "run-1", "hexA") != \
        canonical_key(str(USER_ID), "territory_captured", "run-1", "hexB")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: process_run_sync emission
# ─────────────────────────────────────────────────────────────────────────────


def test_new_run_claiming_empty_hex_emits_workout_and_captured_territory(db):
    _seed_user(db, USER_ID)
    summary = process_run_sync(
        db, _payload(run_id="run-1", session_steps=2000, hexes={"hexA": 2000}), USER_ID
    )
    assert summary.hexes_newly_captured == 1

    accepted = trigger_engine.accepted(user_id=USER_ID)
    assert any(t.trigger_type is TriggerType.WORKOUT_COMPLETED for t in accepted)
    territory = [t for t in accepted if t.trigger_type is TriggerType.TERRITORY_CAPTURED]
    assert len(territory) == 1
    assert territory[0].payload == {
        "hex_id": "hexA",
        "kind": "captured",
        "defense_score_steps": 2000,
        "run_id": "run-1",
    }
    # No daily snapshot -> no activity milestone for an irrelevant sync type.
    assert not any(t.trigger_type is TriggerType.ACTIVITY_MILESTONE for t in accepted)


def test_reinforcing_own_hex_emits_workout_but_no_territory_trigger(db):
    _seed_user(db, USER_ID)
    db.add(HexOwnership(hex_id="hexM", king_id=USER_ID, defense_score_steps=1000))
    db.commit()

    summary = process_run_sync(
        db, _payload(run_id="run-2", session_steps=500, hexes={"hexM": 500}), USER_ID
    )
    assert summary.hexes_defended == 1

    accepted = trigger_engine.accepted(user_id=USER_ID)
    assert any(t.trigger_type is TriggerType.WORKOUT_COMPLETED for t in accepted)
    # Defense is not a capture: ownership did not change to the user.
    assert not any(t.trigger_type is TriggerType.TERRITORY_CAPTURED for t in accepted)


def test_stealing_rival_hex_emits_stolen_territory_trigger(db):
    _seed_user(db, USER_ID)
    _seed_user(db, RIVAL_ID)
    db.add(HexOwnership(hex_id="hexR", king_id=RIVAL_ID, defense_score_steps=300))
    db.commit()

    summary = process_run_sync(
        db, _payload(run_id="run-3", session_steps=1000, hexes={"hexR": 1000}), USER_ID
    )
    assert summary.hexes_stolen == 1

    territory = [
        t for t in trigger_engine.accepted(user_id=USER_ID)
        if t.trigger_type is TriggerType.TERRITORY_CAPTURED
    ]
    assert len(territory) == 1
    assert territory[0].payload["kind"] == "stolen"
    assert territory[0].payload["hex_id"] == "hexR"


def test_replaying_same_run_emits_nothing_second_time(db):
    _seed_user(db, USER_ID)
    payload = _payload(run_id="run-replay", session_steps=900, hexes={"hexC": 900})

    first = process_run_sync(db, payload, USER_ID)
    assert first.already_processed is False
    count_after_first = len(trigger_engine.accepted(user_id=USER_ID))

    second = process_run_sync(db, payload, USER_ID)
    assert second.already_processed is True
    # Replay applied no credit, so it must emit nothing new.
    assert len(trigger_engine.accepted(user_id=USER_ID)) == count_after_first


def test_milestone_emitted_on_crossing_and_is_idempotent_afterwards(db):
    _seed_user(db, USER_ID)

    def milestones():
        return [
            t.payload["milestone_steps"]
            for t in trigger_engine.accepted(user_id=USER_ID)
            if t.trigger_type is TriggerType.ACTIVITY_MILESTONE
        ]

    # 1) Below the first rung -> nothing.
    process_run_sync(db, _payload(run_id="m1", daily=_daily(4999)), USER_ID)
    assert milestones() == []

    # 2) Crossing 5,000 exactly -> one milestone.
    process_run_sync(db, _payload(run_id="m2", daily=_daily(5000)), USER_ID)
    assert milestones() == [5000]

    # 3) One sync from 5,000 to 15,000 crosses 10k AND 15k -> highest only.
    process_run_sync(db, _payload(run_id="m3", daily=_daily(15000)), USER_ID)
    assert milestones() == [5000, 15000]

    # 4) Replaying m3 (already processed) emits no new milestone.
    process_run_sync(db, _payload(run_id="m3", daily=_daily(15000)), USER_ID)
    assert milestones() == [5000, 15000]

    # 5) A NEW run that merely re-reports the same day total does not re-cross
    #    a threshold — the persisted daily row is the idempotency memory.
    process_run_sync(db, _payload(run_id="m4", daily=_daily(15000)), USER_ID)
    assert milestones() == [5000, 15000]


def test_legacy_sync_without_run_id_is_deduplicated_by_content_scope(db):
    _seed_user(db, USER_ID)
    payload = _payload(session_steps=777, hexes={"hX": 777})  # no run_id

    process_run_sync(db, payload, USER_ID)
    process_run_sync(db, payload, USER_ID)  # identical legacy replay

    accepted = trigger_engine.accepted(user_id=USER_ID)
    workouts = [t for t in accepted if t.trigger_type is TriggerType.WORKOUT_COMPLETED]
    assert len(workouts) == 1  # repeated processing -> one trigger, not two


def test_unseeded_user_sync_emits_nothing(db):
    # No User row exists for this id; the sync still processes (ledger row,
    # hexes would be gated by FK) but there is nobody to coach.
    summary = process_run_sync(db, _payload(run_id="ghost", session_steps=100), USER_ID)
    assert summary.already_processed is False
    assert trigger_engine.accepted() == []
