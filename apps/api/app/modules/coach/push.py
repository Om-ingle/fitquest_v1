"""M8.3A — real-time trigger -> AI coaching -> WebSocket push.

Role in the SRS §15/§16 architecture (between M8.1 and M8.2):

    TriggerEngine (M8.1, unchanged)
        |  subscribe(...)            [this module, one more subscriber]
        v
    PushCoach                        (this module)
        |  coalesce + cooldown, then reuse the EXISTING AI stack
        v
    generate_coaching (RAG + LLM, unchanged)   ->   CoachResponse
        |  (only for a user with a live WebSocket session)
        v
    existing CoachingSessionManager (M8.2, unchanged)  -> coaching_message

It does NOT re-implement recommendation/RAG/LLM: it calls the SAME
``build_fitness_context`` / ``generate_coaching`` pipeline the pull path
uses, so there is exactly one grounded-AI implementation. It does NOT
replace ``GET /api/v1/coach`` (the pull path is untouched). It does NOT
change M8.1 trigger rules or M8.2 transport semantics (both are consumed
as-is).

Coalescing / cooldown policy (in-process, per user)
---------------------------------------------------
A run that completes AND captures hexes AND crosses a milestone fires three
triggers back-to-back. Paying for one LLM call per trigger is wasteful and
the messages would be near-duplicates. So per user:

  * at most ONE generation at a time (``armed``) — later triggers in the
    same instant fold their trigger types into the armed generation;
  * after it finishes, a short per-user cooldown (settings
    ``push_coach_cooldown_seconds``, default 30s) suppresses further pushes;
  * a trigger that arrives with NO armed generation and OUTSIDE cooldown
    starts a fresh generation.

Thus a burst collapses to one grounded push, and a genuine later event
(after the cooldown) generates fresh coaching. Cooldown is finite, so it
never suppresses changed coaching context indefinitely.

Cache / fingerprint decision (documented in the ADR)
----------------------------------------------------
The existing ``CoachCache`` is reused as the ONE response store, but push
generations are keyed by a SEPARATE reason-aware composite key
(fingerprint + trigger types), never by the plain FitnessContext
fingerprint. Rationale: ``GET /coach`` caching must stay fingerprint-only,
while a push may be worth generating even when the fitness context is
unchanged but the TRIGGER reason differs (a milestone push minutes after a
pull on the same context). The two key spaces never collide, so reusing the
same cache adds no second cache to maintain. ``generate_coaching`` is called
with ``cache=None`` so push never reads or writes the pull fingerprint
entries.

Failure containment
-------------------
The trigger producer never waits for the LLM: ``handle_trigger`` only
schedules a background job and returns. The job runs off the emitter thread,
builds FRESH context at generation time, and every failure (DB/context
construction, RAG retrieval, LLM timeout/error, WebSocket delivery) is
logged and contained — it can never roll back a committed run, change
XP/territory, break trigger processing, or break other WebSocket sessions.
A failed LLM/RAG call produces NO ``coaching_message``.

No-session behavior
-------------------
If the user has no live coaching WebSocket session the push is skipped
entirely (no paid generation for nobody). If they disconnect after a job is
scheduled but before it runs, the job re-checks and gives up.

Not in scope (unchanged): Android handling, TTS, Redis, authentication.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlmodel import Session

from app.core.config import settings
from app.core.database import engine
from app.modules.coach.cache import CoachCache, coach_cache, context_fingerprint
from app.modules.coach.llm import get_llm_provider
from app.modules.coach.schemas import CoachResponse
from app.modules.coach.service import generate_coaching
from app.modules.rag.providers import get_embedding_provider
from app.modules.recommendations.service import build_fitness_context
from app.modules.triggers.engine import (
    CoachingTrigger,
    TriggerType,
    trigger_engine,
)
from app.modules.triggers.ws import manager as ws_manager

logger = logging.getLogger(__name__)

# Stable wire envelope added by M8.3A, delivered over the SAME M8.2 transport.
# Shape: {"type": COACHING_MESSAGE_TYPE, "trigger": {...}, "coach": {...}}
# where ``trigger`` is the CoachingTrigger that armed this push and ``coach``
# is the real CoachResponse (existing schema, no invented fields). The M8.2
# raw ``coaching_trigger`` envelope remains valid and is sent first.
COACHING_MESSAGE_TYPE = "coaching_message"

# Version tag inside the composite push key, so changing the key semantics
# invalidates old push entries on the next deploy (mirrors context_fingerprint).
PUSH_KEY_VERSION = "m83a-push-v1"


def describe_event_context(reasons: tuple[TriggerType, ...]) -> str:
    """Human, third-person reason string for the prompt (M8.3A).

    Facts only: one phrase per distinct trigger type folded into this push.
    Used so the generated message can reflect WHY it was sent (a run, a
    capture, a milestone) without the prompt inventing specifics.
    """
    phrase = {
        TriggerType.WORKOUT_COMPLETED: "completed a run",
        TriggerType.TERRITORY_CAPTURED: "captured new territory",
        TriggerType.ACTIVITY_MILESTONE: "reached a daily step milestone",
    }
    parts = [phrase[t] for t in sorted(reasons, key=lambda t: t.value)]
    if not parts:
        return ""
    return "the user " + ", and ".join(parts)


def push_generation_key(
    user_id: uuid.UUID,
    fingerprint: str,
    reasons: tuple[TriggerType, ...],
) -> str:
    """Reason-aware cache key for a push generation (M8.3A).

    Deliberately SEPARATE from the plain FitnessContext fingerprint used by
    the pull path: it adds the folded trigger types, so two triggers with the
    same fitness context but different reasons (e.g. a milestone vs a
    territory capture) do NOT collide. The ``push:`` prefix guarantees it can
    never equal a raw fingerprint, so push entries and pull entries coexist in
    the same ``CoachCache`` without interfering.
    """
    payload = {
        "version": PUSH_KEY_VERSION,
        "user_id": str(user_id),
        "context_fingerprint": fingerprint,
        "reasons": sorted(r.value for r in reasons),
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return "push:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def serialize_coaching_message(
    trigger: CoachingTrigger, response: CoachResponse
) -> str:
    """Envelope a completed push generation for the M8.2 transport.

    Uses the REAL trigger and CoachResponse Pydantic JSON forms — nothing is
    invented. ``model_dump(mode="json")`` stringifies UUID/datetime.
    """
    return json.dumps(
        {
            "type": COACHING_MESSAGE_TYPE,
            "trigger": trigger.model_dump(mode="json"),
            "coach": response.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )


def _default_session_factory() -> Session:
    return Session(engine)


@dataclass
class _UserPushState:
    """Per-user push gate, guarded by ``PushCoach._lock``."""

    armed: bool = False
    reasons: set[TriggerType] = field(default_factory=set)
    rep_trigger: Optional[CoachingTrigger] = None
    cooldown_until: float = 0.0


class PushCoach:
    """Engine subscriber that turns accepted triggers into AI coaching pushes.

    Threading: ``handle_trigger`` runs on the emitter thread (M8.1 sync
    subscriber) and only schedules; the heavy generation runs via
    ``self.schedule`` (default: a bounded ThreadPoolExecutor). ``schedule``,
    ``now``, provider factories and the session factory are instance
    attributes so tests can substitute deterministic doubles.
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        ws=None,
        cache: CoachCache | None = None,
        session_factory: Callable[[], Session] | None = None,
        embedding_factory: Callable[[], object] | None = None,
        llm_factory: Callable[[], object] | None = None,
        schedule: Callable[[Callable[[], None]], None] | None = None,
        now: Callable[[], float] | None = None,
        cooldown_seconds: float | None = None,
        max_workers: int | None = None,
    ) -> None:
        self.enabled = settings.push_coach_enabled if enabled is None else enabled
        self.ws = ws_manager if ws is None else ws
        self.cache = coach_cache if cache is None else cache
        self.session_factory = _default_session_factory if session_factory is None else session_factory
        self.embedding_factory = (
            get_embedding_provider if embedding_factory is None else embedding_factory
        )
        self.llm_factory = get_llm_provider if llm_factory is None else llm_factory
        self.cooldown_seconds = (
            settings.push_coach_cooldown_seconds
            if cooldown_seconds is None
            else cooldown_seconds
        )
        self.now = time.monotonic if now is None else now
        if schedule is not None:
            self.schedule = schedule
        else:
            self._executor = ThreadPoolExecutor(
                max_workers=max_workers or settings.push_coach_max_workers,
                thread_name_prefix="push-coach",
            )
            self.schedule = self._executor.submit
        self._lock = threading.RLock()
        self._states: dict[str, _UserPushState] = {}

    # ── lifecycle / test isolation ─────────────────────────────────────────

    def reset(self) -> None:
        """Drop all per-user push state (armed/reasons/cooldown).

        Subscribers are NOT removed (mirrors trigger_engine.clear()); the
        enabled flag is NOT reset so tests keep whatever they configured.
        """
        with self._lock:
            self._states.clear()

    # ── engine subscriber (emitter thread) ─────────────────────────────────

    def handle_trigger(self, trigger: CoachingTrigger) -> None:
        """``trigger_engine.subscribe`` target (M8.3A).

        Runs synchronously on the emitter thread but NEVER blocks on the LLM:
        it only decides whether to schedule a background generation and
        returns immediately, so the run-sync that just committed can complete
        untouched. Failures here must never propagate to ``accept`` (the
        engine swallows subscriber exceptions anyway — belt and suspenders).
        """
        if not self.enabled:
            return
        uid = str(trigger.user_id)
        # No live session -> nobody to receive the push: don't pay for AI.
        if not self.ws.has_live_sessions(uid):
            return

        now = self.now()
        with self._lock:
            state = self._states.get(uid)
            if state is not None and state.armed:
                # A generation is already scheduled/running for this user:
                # fold this trigger type in rather than firing another LLM
                # call. One push per burst.
                state.reasons.add(trigger.trigger_type)
                return
            if state is not None and now < state.cooldown_until:
                # Inside the post-push cooldown window with nothing armed:
                # suppress (conservative rate limit, finite by construction).
                return
            if state is None:
                state = self._states[uid] = _UserPushState()
            state.armed = True
            state.reasons.add(trigger.trigger_type)
            state.rep_trigger = trigger
            state.cooldown_until = now + self.cooldown_seconds

        try:
            self.schedule(lambda: self._run(uid))
        except Exception:  # noqa: BLE001 — scheduler must not strand a user
            logger.exception("M8.3A: could not schedule push job for %s", uid)
            with self._lock:
                state.armed = False

    # ── background generation (worker thread) ──────────────────────────────

    def _run(self, uid: str) -> None:
        """Background job: generate + deliver one coalesced push for ``uid``.

        Runs off the emitter thread. Captures the folded reasons under the
        lock at job start (deterministic: whatever burst was visible when the
        job began), re-checks the live session, then builds FRESH context from
        current DB state. Every failure is contained.
        """
        with self._lock:
            state = self._states.get(uid)
            if state is None or not state.armed:
                return
            reasons = tuple(sorted(state.reasons, key=lambda t: t.value))
            rep_trigger = state.rep_trigger
            # Reset the fold-buffer; reasons folded during the run are within
            # the same cooldown window and intentionally coalesce away.
            state.reasons.clear()
            state.rep_trigger = None

        try:
            if not self.enabled or not reasons or rep_trigger is None:
                return
            # Re-check: the user may have disconnected while the job queued.
            if not self.ws.has_live_sessions(uid):
                return
            envelope = self._produce(uid, rep_trigger, reasons)
            if envelope is not None and self.ws.has_live_sessions(uid):
                self.ws.send_to_user(uid, envelope)
        except Exception:  # noqa: BLE001 — a failed push never breaks anything
            logger.exception(
                "M8.3A: AI coaching push failed for user %s (contained)", uid
            )
        finally:
            with self._lock:
                state = self._states.get(uid)
                if state is not None:
                    state.armed = False
                    state.reasons.clear()

    def _produce(
        self,
        uid: str,
        rep_trigger: CoachingTrigger,
        reasons: tuple[TriggerType, ...],
    ) -> str | None:
        """Run the EXISTING grounded-AI flow and return a wire envelope.

        Returns None when an identical (context, reasons) push was already
        generated (dedupe — no second LLM call for the same coaching moment).
        """
        user_id = uuid.UUID(uid)
        embedding_provider = self.embedding_factory()
        llm_provider = self.llm_factory()

        with self.session_factory() as db:
            # Fresh, authoritative context at GENERATION time — never a stale
            # context captured when the trigger fired. The trigger may inform
            # the reason, but the AI context reflects current server state.
            context = build_fitness_context(db, user_id)
            fingerprint = context_fingerprint(context)
            push_key = push_generation_key(user_id, fingerprint, reasons)

            # Same CoachCache as the pull path, but a reason-aware key that
            # cannot collide with a plain fingerprint (see module docstring).
            if self.cache.get_cached(user_id, push_key) is not None:
                return None

            response = generate_coaching(
                db,
                user_id=user_id,
                embedding_provider=embedding_provider,
                llm_provider=llm_provider,
                cache=None,  # push never reads/writes the pull fingerprint cache
                event_context=describe_event_context(reasons),
            )
            # Key the stored entry by the fingerprint of the context the LLM
            # actually generated from (== the pre-check fingerprint unless the
            # DB changed between the two builds; identical in the normal case).
            stored_key = push_generation_key(
                user_id, response.context_fingerprint, reasons
            )
            self.cache.store(user_id, stored_key, response)

        return serialize_coaching_message(rep_trigger, response)


# Module singleton shared by the engine subscription and (for tests) reset by
# tests/conftest.py. Subscribes to the trigger engine ONCE, at import, exactly
# like the M8.2 transport — the engine stays the sole producer.
push_coach = PushCoach()
trigger_engine.subscribe(push_coach.handle_trigger)
