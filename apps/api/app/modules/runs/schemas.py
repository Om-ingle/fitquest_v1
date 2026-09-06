from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional

from pydantic import BaseModel, field_validator


class DailyActivitySnapshot(BaseModel):
    """The user's device-local day, as of the moment a run syncs (Phase 4B.5).

    Absolute day-to-date values (never deltas) so repeated syncs of the same
    day are idempotent. ``activity_date`` is the DEVICE's local calendar date
    — the same date the app uses for streaks and HomeTab — not server UTC.
    Null optional fields mean "not reported"; the backend keeps the previous
    value for those fields on upsert. See
    tools/synthetic_fitness/real_telemetry_gap_analysis.md for the contract.
    """

    activity_date: date
    steps: int
    active_minutes: int
    goal_steps: Optional[int] = None
    goal_completed: Optional[bool] = None
    hexes_owned: Optional[int] = None
    hexes_captured: Optional[int] = None
    hexes_lost: Optional[int] = None
    defense_steps: Optional[int] = None

    @field_validator("activity_date")
    @classmethod
    def _date_not_in_future(cls, value: date) -> date:
        # The date is the DEVICE's local calendar date, which can legitimately
        # be up to one day ahead of UTC (UTC+14) — allow that, reject further.
        latest = datetime.now(timezone.utc).date() + timedelta(days=1)
        if value > latest:
            raise ValueError(f"activity_date {value} is in the future (latest allowed is {latest})")
        return value

    @field_validator("steps", "defense_steps")
    @classmethod
    def _steps_sane(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and not 0 <= value <= 1_000_000:
            raise ValueError(f"{value} is outside the plausible daily step range 0..1,000,000")
        return value

    @field_validator("active_minutes")
    @classmethod
    def _minutes_sane(cls, value: int) -> int:
        if not 0 <= value <= 1440:
            raise ValueError(f"{value} is outside a day's 0..1440 minutes")
        return value

    @field_validator(
        "goal_steps", "hexes_owned", "hexes_captured", "hexes_lost"
    )
    @classmethod
    def _counts_sane(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and not 0 <= value <= 100_000:
            raise ValueError(f"{value} is outside the plausible range 0..100,000")
        return value


class RunSyncPayload(BaseModel):
    """
    The exact payload the Android app sends when a run finishes.
    Matches the Android Map<String, Int> (HexID to Steps) perfectly.

    ``daily_activity`` (Phase 4B.5, optional) carries the device's absolute
    day-to-date telemetry snapshot; older clients omit it and behavior is
    unchanged.
    """

    total_session_steps: int
    # Maps hex_id -> steps_walked_in_hex
    hexes_to_steps: Dict[str, int]
    daily_activity: Optional[DailyActivitySnapshot] = None
    # Optional stable run/session id (Fix A replay guard). New Android builds
    # send the local session id so a retried sync is recognised as already
    # applied instead of double-crediting. Older clients omit it and behaviour
    # is exactly as before.
    run_id: Optional[str] = None


class RunSyncSummary(BaseModel):
    """
    Gamified result of the run.
    Triggers animations on the Android side.
    """
    hexes_defended: int  # Hexes retained from previous owner
    hexes_stolen: int  # Hexes captured from another player
    hexes_newly_captured: int  # Unclaimed hexes now captured
    xp_earned: int
    new_total_lifetime_steps: int
    # True when the payload carried a run_id that this user had already synced.
    # No credit was applied; the client should keep its existing local XP value
    # rather than overwriting it with the zeroed xp_earned above.
    already_processed: bool = False
