"""M8.1 — coaching trigger engine (real-time coaching foundations).

See ``app/modules/triggers/engine.py`` for the design and the SRS §15 notes
in the M8.1 doc (docs/docs/coaching/0001-m81-trigger-engine.md).
"""

from app.modules.triggers.engine import (
    ACTIVITY_MILESTONE_STEPS,
    DEFAULT_COOLDOWN_SECONDS,
    CoachingTrigger,
    TriggerDecision,
    TriggerEngine,
    TriggerType,
    canonical_key,
    highest_milestone_crossed,
    trigger_engine,
)

__all__ = [
    "ACTIVITY_MILESTONE_STEPS",
    "DEFAULT_COOLDOWN_SECONDS",
    "CoachingTrigger",
    "TriggerDecision",
    "TriggerEngine",
    "TriggerType",
    "canonical_key",
    "highest_milestone_crossed",
    "trigger_engine",
]
