"""Real-telemetry compatibility adapter (Phase 4B.5).

Bridges the backend's daily telemetry rows (``userdailyactivity`` table /
``DailyActivitySnapshot`` API shape) into the raw-row schema that
``features.build_features`` consumes (``generator.COLUMNS``). This proves the
real-telemetry path is schema-compatible with the Phase 4B.2–4B.4 pipeline
WITHOUT modifying ``features.py``.

⚠  No real telemetry exists yet — this module is exercised by tests against
   synthetic *telemetry-shaped* data only. Nothing here is real user data.

Semantics (see real_telemetry_gap_analysis.md §3.6):

- ``streak`` is NOT stored server-side; it is recomputed here from the steps
  history using the generator's own definition (consecutive days with
  ``steps >= STREAK_MIN_STEPS`` ending on D).
- ``goal_completed`` is derived (``steps >= goal_steps``) when the device did
  not report it.
- Gap days (no sync happened — the app only syncs when a run ends) are
  densified to zero-step rows so that the index-based rolling windows in
  ``features.py`` measure calendar days, not "recorded days". The last known
  ``goal_steps``/``hexes_owned`` carry forward across gaps.
- NULL optional fields mean "unknown" (not "none"); they are emitted as 0
  because the feature schema has no null representation. ``hexes_lost`` and
  ``defense_steps`` are unknown in v1 — the loss/defense features computed
  from them are placeholders until a later phase observes those signals.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable, Mapping

import generator
from generator import STREAK_MIN_STEPS

REAL_DATA_SOURCE = "real"

# Telemetry fields (DailyActivitySnapshot / userdailyactivity columns).
TELEMETRY_FIELDS = (
    "steps",
    "active_minutes",
    "goal_steps",
    "goal_completed",
    "hexes_owned",
    "hexes_captured",
    "hexes_lost",
    "defense_steps",
)

# Optional fields an export query must be able to read off a telemetry row.
REQUIRED_TELEMETRY_KEYS = ("user_id", "activity_date") + TELEMETRY_FIELDS


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.datetime):
        return value.date()
    return dt.date.fromisoformat(str(value))


def _to_raw_row(
    user_id: Any,
    day: dt.date,
    steps: int,
    active_minutes: int,
    goal_steps: int,
    goal_completed: int,
    hexes_owned: int,
    hexes_captured: int,
    hexes_lost: int,
    defense_steps: int,
) -> dict:
    """One features-compatible raw row for a single (user, day)."""
    return {
        "synthetic_user_id": str(user_id),
        "day": day.isoformat(),
        "steps": int(steps),
        "active_minutes": int(active_minutes),
        "hexes_owned": int(hexes_owned),
        "hexes_captured": int(hexes_captured),
        "hexes_lost": int(hexes_lost),
        "defense_steps": int(defense_steps),
        "streak": 0,  # replaced by _compute_streaks below
        "goal_steps": int(goal_steps),
        "goal_completed": int(goal_completed),
        "data_source": REAL_DATA_SOURCE,
    }


def _compute_streaks(rows: list[dict]) -> None:
    """Fill the ``streak`` column: consecutive days with steps >= the
    activity bar ending on each row's day (the generator's definition).
    Streaks never carry across users or calendar gaps."""
    streak = 0
    previous_user: str | None = None
    previous_day: dt.date | None = None
    for row in rows:
        day = dt.date.fromisoformat(row["day"])
        contiguous = (
            row["synthetic_user_id"] == previous_user
            and previous_day is not None
            and (day - previous_day).days == 1
        )
        if not contiguous:
            streak = 0
        streak = streak + 1 if row["steps"] >= STREAK_MIN_STEPS else 0
        row["streak"] = streak
        previous_user = row["synthetic_user_id"]
        previous_day = day


def telemetry_to_raw_rows(telemetry_rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Convert telemetry rows into ``generator.COLUMNS``-shaped raw rows.

    Pure function, stdlib only. Groups by user, densifies calendar gaps with
    zero-activity rows, derives streak/goal_completed, and labels every row
    ``data_source="real"``. Deterministic for identical input.
    """
    rows = list(telemetry_rows)
    if not rows:
        return []

    for row in rows:
        missing = [k for k in REQUIRED_TELEMETRY_KEYS if k not in row]
        if missing:
            raise ValueError(f"telemetry row is missing keys: {missing}")

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["user_id"]), []).append(row)

    out: list[dict] = []
    for user_id, user_rows in grouped.items():
        user_rows.sort(key=lambda r: _as_date(r["activity_date"]))

        # Carry-forward state across gap days.
        last_goal = 0
        last_owned = 0
        previous_day: dt.date | None = None

        for row in user_rows:
            day = _as_date(row["activity_date"])

            # Densify: any skipped calendar day between recorded days becomes
            # a zero-activity row (the device only syncs when a run ends).
            if previous_day is not None:
                gap_day = previous_day + dt.timedelta(days=1)
                while gap_day < day:
                    out.append(
                        _to_raw_row(
                            user_id, gap_day, 0, 0, last_goal, 0,
                            last_owned, 0, 0, 0,
                        )
                    )
                    gap_day += dt.timedelta(days=1)

            steps = int(row["steps"])
            active_minutes = int(row["active_minutes"])
            goal_steps = row["goal_steps"]
            goal_steps = int(goal_steps) if goal_steps is not None else last_goal
            goal_completed = row["goal_completed"]
            if goal_completed is None:
                goal_completed = 1 if goal_steps and steps >= goal_steps else 0
            hexes_owned = row["hexes_owned"]
            hexes_owned = int(hexes_owned) if hexes_owned is not None else last_owned

            out.append(
                _to_raw_row(
                    user_id,
                    day,
                    steps,
                    active_minutes,
                    goal_steps,
                    int(bool(goal_completed)),
                    hexes_owned,
                    int(row["hexes_captured"] or 0),
                    int(row["hexes_lost"] or 0),
                    int(row["defense_steps"] or 0),
                )
            )

            last_goal = goal_steps
            last_owned = hexes_owned
            previous_day = day

    _compute_streaks(out)
    return out


def verify_feature_compatibility(telemetry_rows: Iterable[Mapping[str, Any]]) -> dict:
    """End-to-end check: telemetry -> raw rows -> features.build_features.

    Returns a summary dict; raises if the real-telemetry rows cannot flow
    through the UNMODIFIED Phase 4B.2 feature pipeline.
    """
    import features

    rows_in = list(telemetry_rows)
    if not rows_in:
        raise ValueError("no telemetry rows to verify")

    raw = telemetry_to_raw_rows(rows_in)

    # Every converted row must satisfy the exact raw schema features.py needs.
    for row in raw:
        missing = [c for c in generator.COLUMNS if c not in row]
        if missing:
            raise ValueError(f"converted row is missing columns: {missing}")
        if row["data_source"] != REAL_DATA_SOURCE:
            raise ValueError(f"expected data_source={REAL_DATA_SOURCE!r}")

    feature_rows = features.build_features(raw)
    for feature_row in feature_rows:
        for name in features.MODEL_FEATURES:
            value = feature_row[name]
            if value is None or value != value:  # None or NaN
                raise ValueError(f"feature {name} is null/NaN for {feature_row['day']}")

    return {
        "telemetry_rows_in": len(rows_in),
        "raw_rows_out": len(raw),
        "feature_rows_out": len(feature_rows),
        "model_features": list(features.MODEL_FEATURES),
        "data_source": REAL_DATA_SOURCE,
    }
