"""M8.1 — coaching trigger engine.

WHY (FitQuest SRS §15 "Real-Time AI Coaching"): real-time coaching is
trigger-based. The §15 pipeline is

    real activity event -> trigger evaluation -> AI context ->
    recommendation/RAG -> LLM -> (M8.2+) WebSocket -> Android

This module implements the *trigger evaluation* layer of M8.1. A trigger is a
recorded, deduplicated "something meaningful just happened to this user"
moment that later milestones consume. M8.1 deliberately does NOT:

  * call the LLM or RAG directly (the coach service still owns that),
  * change GET /api/v1/coach (the existing pull-coach flow keeps working),
  * add WebSocket/SSE transport or any Android-side handling (that is M8.2),
  * require Redis (the SRS treats Redis as optional; see §17 and the
    in-process-on-purpose note below).

Only trigger types with a REAL event source in the current backend are
defined. The audit for M8.1 found exactly three:

  * ``WORKOUT_COMPLETED``   — a run sync that newly applied credit
                            (app/modules/runs/service.py::process_run_sync).
  * ``TERRITORY_CAPTURED``  — a hex whose owner changed to the user during a
                            run sync (fresh claim of empty land, or a steal
                            from a rival). One trigger per affected hex.
  * ``ACTIVITY_MILESTONE``  — a sync pushed the user's absolute day-to-date
                            steps across one of a fixed set of day milestones.

``WORKOUT_STARTED``, ``STREAK_MILESTONE`` and ``QUEST_PROGRESS`` were NOT
implemented: the backend has no reliable server-side event source for any of
them (see the M8.1 doc). The engine never fabricates an event that business
logic did not produce, and it never triggers on a GPS/step tick — the only
input is an explicit trigger handed in by code that just committed credit.

In-process on purpose: the app is a single-instance dev backend, and this
module has one narrow seam — ``TriggerEngine`` with ``subscribe()`` — that a
Redis-backed implementation (or the M8.2 WebSocket bridge as a subscriber)
can replace or attach to without touching the emitters.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Optional

from pydantic import BaseModel, Field


class TriggerType(str, Enum):
    """Every trigger the engine can emit, mapped 1:1 to a real event source.

    The ``value`` is the stable wire/JSON name. No entry exists for event
    types the backend does not actually produce (workout start, streak,
    quest progress) — adding them here before a real source exists would let
    the engine claim moments that never happen.
    """

    WORKOUT_COMPLETED = "workout_completed"
    TERRITORY_CAPTURED = "territory_captured"
    ACTIVITY_MILESTONE = "activity_milestone"


class TriggerDecision(str, Enum):
    """Outcome of handing a trigger to the engine.

    ``COOLDOWN`` only ever means a transient rate-gate suppression (the
    trigger is otherwise new and can legitimately be retried later).
    ``DUPLICATE`` means the exact moment was already accepted and stays
    suppressed until the bounded dedupe log evicts its key.
    """

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    COOLDOWN = "cooldown"


class CoachingTrigger(BaseModel):
    """A single meaningful moment, as classified by the engine.

    ``dedupe_key`` is the deterministic identity the engine deduplicates on
    (canonical_key over stable parts). ``event_id`` optionally names the
    originating run/session so a later consumer can correlate triggers to a
    run. ``payload`` is deliberately light — just enough context for the
    M8.2+ stage to build an AI coaching context; it never carries raw GPS or
    step-by-step telemetry.
    """

    trigger_type: TriggerType
    user_id: uuid.UUID
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dedupe_key: str
    event_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


# Fixed daily-step milestones (absolute day-to-date steps). Crossing one is a
# meaningful "you hit X today" moment. 10_000 mirrors the app's default daily
# goal; the ladder is kept small, fixed and monotonic so the same day never
# re-fires a threshold. Per-user goal customization is a later enhancement.
ACTIVITY_MILESTONE_STEPS: tuple[int, ...] = (5_000, 10_000, 15_000, 20_000)


def highest_milestone_crossed(
    previous: int,
    current: int,
    ladder: tuple[int, ...] = ACTIVITY_MILESTONE_STEPS,
) -> Optional[int]:
    """Largest ladder value crossed by moving from ``previous`` to ``current``.

    "Crossed" is strict: ``previous < milestone <= current``. A report that
    does not increase (or the same value again) never crosses, which makes a
    milestone per (activity_date, threshold) naturally idempotent even across
    process restarts — the persisted daily row is the memory. When one sync
    jumps several rungs (e.g. 4,999 -> 12,000) only the HIGHEST crossed value
    (10,000) is returned: one nudge per day, not one per rung.
    """
    crossed = [t for t in ladder if previous < t <= current]
    return max(crossed) if crossed else None


def canonical_key(*parts: object) -> str:
    """Deterministic dedupe key from stable, replay-safe parts.

    The same logical moment (same user, type, run and hex/date) must always
    produce the same string so a retried sync cannot double-emit. Parts are
    str()'d and pipe-joined; callers include the type so identical-looking
    parts of different trigger types never collide.
    """
    return "|".join(str(p) for p in parts)


# Default per-type cooldown (seconds) between ACCEPTED triggers of the same
# (user, type). A cooldown is a rate-gate against bursts, NOT the dedupe
# mechanism — distinct real moments still pass when cooldown is 0.
#
#   * WORKOUT_COMPLETED 10s — real runs are minutes long, so a 10s window
#     never drops a genuine completion; it only flattens a pathological
#     burst of legacy syncs that carry no run_id (whose dedupe key is
#     content-derived and therefore weaker).
#   * TERRITORY_CAPTURED / ACTIVITY_MILESTONE 0s — each distinct capture /
#     crossing is its own meaningful moment and must never be dropped; those
#     types are deduplicated exactly (run+hex / date+threshold) instead.
DEFAULT_COOLDOWN_SECONDS: dict[TriggerType, float] = {
    TriggerType.WORKOUT_COMPLETED: 10.0,
    TriggerType.TERRITORY_CAPTURED: 0.0,
    TriggerType.ACTIVITY_MILESTONE: 0.0,
}

# Bounded dedupe log: an exact moment stays suppressed only while its key is
# resident. Well beyond any plausible burst (a day of hex captures at a 10s
# hex-cadence would be ~8,640 keys), so eviction is a memory safety valve,
# never a source of spurious re-emission in practice.
DEDUPE_CAPACITY = 100_000

# Bounded ring of accepted triggers, for inspection/tests and as a light
# "last N moments" audit surface until M8.2 introduces a real transport.
ACCEPTED_LOG_SIZE = 250


class TriggerEngine:
    """Thread-safe, in-process dedupe + cooldown gate for coaching triggers.

    Only code that just committed authoritative business state emits triggers
    (see runs/service.py), so ``accept`` itself does no I/O and cannot fail a
    caller. Subscribers (the M8.2 WebSocket bridge, a later Redis-backed
    engine, tests) are notified outside the lock, and a raising subscriber is
    swallowed: triggers are advisory coaching moments and must never break the
    run-sync request that produced them.
    """

    def __init__(self, capacity: int = DEDUPE_CAPACITY) -> None:
        self._lock = threading.RLock()
        self._capacity = capacity
        # dedupe_key(str) -> occurred_at, kept in insertion order for LRU
        # eviction (OrderedDict.move_to_end on hit is unnecessary — dedupe is
        # one-shot, never refreshed).
        self._seen: OrderedDict[str, datetime] = OrderedDict()
        # (user_id, TriggerType) -> occurred_at of the last ACCEPTED trigger,
        # used for the per-type cooldown gate.
        self._last_accepted: dict[tuple[str, TriggerType], datetime] = {}
        self._subscribers: list[Callable[[CoachingTrigger], None]] = []
        self._accepted: deque[CoachingTrigger] = deque(maxlen=ACCEPTED_LOG_SIZE)

    # ── configuration / introspection ──────────────────────────────────────

    def subscribe(self, fn: Callable[[CoachingTrigger], None]) -> None:
        """Register a callback for every ACCEPTED trigger (M8.2 seam)."""
        with self._lock:
            self._subscribers.append(fn)

    def default_cooldown_seconds(self, trigger_type: TriggerType) -> float:
        return DEFAULT_COOLDOWN_SECONDS[trigger_type]

    def accepted(self, user_id: Optional[uuid.UUID] = None) -> list[CoachingTrigger]:
        """Accepted triggers in arrival order, optionally for one user."""
        with self._lock:
            if user_id is None:
                return list(self._accepted)
            return [t for t in self._accepted if t.user_id == user_id]

    def clear(self) -> None:
        """Reset dedupe + cooldown state and the accepted log (tests/reloads)."""
        with self._lock:
            self._seen.clear()
            self._last_accepted.clear()
            self._accepted.clear()

    # ── the gate ───────────────────────────────────────────────────────────

    def accept(
        self,
        trigger: CoachingTrigger,
        cooldown_seconds: Optional[float] = None,
    ) -> TriggerDecision:
        """Record ``trigger`` unless it is a duplicate or inside its cooldown.

        Order of checks:
          1. DUPLICATE — the exact dedupe_key was already accepted (and has
             not been LRU-evicted). Permanently suppressed for this session.
          2. COOLDOWN — same (user, type) fired less than ``cooldown_seconds``
             ago (default per ``trigger.trigger_type``). Transient: nothing is
             recorded, so the trigger is retryable later.
        """
        if cooldown_seconds is None:
            cooldown_seconds = self.default_cooldown_seconds(trigger.trigger_type)

        with self._lock:
            if trigger.dedupe_key in self._seen:
                return TriggerDecision.DUPLICATE

            last = self._last_accepted.get((str(trigger.user_id), trigger.trigger_type))
            if last is not None:
                elapsed = (trigger.occurred_at - last).total_seconds()
                if elapsed < cooldown_seconds:
                    return TriggerDecision.COOLDOWN

            self._seen[trigger.dedupe_key] = trigger.occurred_at
            if len(self._seen) > self._capacity:
                self._seen.popitem(last=False)
            self._last_accepted[(str(trigger.user_id), trigger.trigger_type)] = (
                trigger.occurred_at
            )
            self._accepted.append(trigger)

        for fn in tuple(self._subscribers):
            try:
                fn(trigger)
            except Exception:  # noqa: BLE001 — a subscriber must never fail a run sync
                pass
        return TriggerDecision.ACCEPTED


# Module singleton shared by emitters (runs/service.py) so every request
# shares one dedupe/cooldown gate, mirroring coach_cache. Tests that exercise
# the singleton clear it (see tests/conftest.py and tests/test_triggers.py);
# unit tests of the engine itself instantiate their own.
trigger_engine = TriggerEngine()
