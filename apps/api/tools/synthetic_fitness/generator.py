"""FitQuest synthetic fitness-dataset simulator.

This module generates *realistic-looking* daily activity histories for
synthetic FitQuest users so that ML experimentation can proceed before
real FitQuest user data exists.

⚠  IMPORTANT — this data is SYNTHETIC.
   - Every row carries ``data_source="synthetic"``.
   - The behavior is a plausible cartoon of real users, NOT medically
     accurate, NOT statistically representative of real humans, and
     NEVER a stand-in for real FitQuest telemetry in any claim,
     metric, or evaluation.
   - It exists only for pipeline/experiment development. When real
     FitQuest data is available it will replace or augment this set.

Design constraints honored here:
   * Deterministic — same seed -> byte-identical output (stdlib
     ``random.Random`` instance; no OS randomness).
   * Standard library only — ``csv`` + ``random`` + ``datetime`` +
     ``statistics``. pandas is deliberately NOT pulled in (it is not an
     existing backend dependency).
   * Isolated — no database, no FastAPI imports, no migrations. The
     simulator only writes a CSV file.
   * Bounded — steps/active_minutes stay inside sane ranges and the
     territory ledger is clamped per profile.
   * Internally consistent — goal_completed, streak, active_minutes,
     hexes_owned/lost are all *derived* from the day's steps/captures,
     never assigned independently.

Modeling assumption for active_minutes (documented in README, not claimed
to be medically accurate):

   Only a *share* of a day's tracked steps occur in continuous, measurable
   "active bouts" — the rest are incidental movement. So a day's active
   minutes are derived as::

       active_minutes = steps * bout_share / cadence

   where ``bout_share`` (0.5–1.0) and ``cadence`` (steps/min, drawn from a
   per-profile walking/running range) both vary day-to-day. This keeps
   active_minutes *strongly but not perfectly* correlated with steps, and
   makes it structurally impossible to see high steps with zero minutes: a
   day below an "active-bout" floor (1,000 steps — incidental only) gets 0
   minutes, and any day at/above the floor is guaranteed >= 1 minute.
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
from datetime import date, timedelta
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Tunable constants
# ─────────────────────────────────────────────────────────────────────────────

# A day is "meaningfully active" (keeps the streak, enables a capture) when
# steps reach this many. Mirrors FitQuest's minimum-effort streak logic.
STREAK_MIN_STEPS = 1000

# Active minutes are only counted for days with at least this many steps:
# below it the steps are treated as incidental movement, not a real bout.
ACTIVE_MINUTES_FLOOR_STEPS = STREAK_MIN_STEPS

# Rest-day steps are drawn from 0..REST_STEPS_MAX (always below the streak bar).
REST_STEPS_MAX = 500

# Absolute safety cap on any single day's steps (all profiles draw below it).
MAX_STEPS = 25000

# Share of a day's steps spent in a continuous active bout (see module
# docstring). Drawn per day so the steps<->minutes link is noisy but strong.
BOUT_SHARE_LO = 0.5
BOUT_SHARE_HI = 1.0

# Fraction of days that may turn into a dedicated "reinforce/defend" run
# (defense_steps == the whole day's steps) for users who own territory.
# Profiles may override via ``defense_run_prob``.
DEFENSE_RUN_PROB = 0.12

DATA_SOURCE = "synthetic"
DATASET_START_DATE = date(2025, 1, 1)

DEFAULT_USERS = 30
DEFAULT_DAYS = 180
DEFAULT_SEED = 42
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent / "output" / "synthetic_fitness_dataset.csv"
)

COLUMNS = [
    "synthetic_user_id",
    "day",
    "steps",
    "active_minutes",
    "hexes_owned",
    "hexes_captured",
    "hexes_lost",
    "defense_steps",
    "streak",
    "goal_steps",
    "goal_completed",
    "data_source",
]

# Population mix used to fill user slots beyond the guaranteed all-profiles
# head (see generate_dataset). Must align index-for-index with PROFILE_SPECS.
DEFAULT_PROFILE_WEIGHTS = [
    0.18,  # INACTIVE
    0.30,  # CASUAL
    0.22,  # CONSISTENT
    0.06,  # HIGHLY_ACTIVE
    0.10,  # LAPSED
    0.08,  # RETURNING
    0.06,  # TERRITORY_FOCUSED
]

# ─────────────────────────────────────────────────────────────────────────────
# Behavior profile definitions
# ─────────────────────────────────────────────────────────────────────────────
#
# Keys:
#   activity_prob      P(day is meaningfully active, outside any forced gap)
#   active_steps       (min, max) steps drawn uniformly on an active day
#   cadence            (min, max) steps per active minute; higher = runnier
#   capture_prob       P(capture >= 1) on an active day at/above the step bar
#   max_captures       upper bound on hexes captured in one day
#   loss_prob          base P(losing >= 1 hex) on a day you hold territory
#                      (scaled up as holdings grow -> natural plateau)
#   max_loss           upper bound on hexes lost in one day
#   goal_steps         that user's fixed daily step goal
#   defense_share      typical share of an active day's steps spent reinforcing
#   defense_run_prob   optional override of DEFENSE_RUN_PROB (dedicated runs)
#   territory_cap      soft ceiling on hexes_owned for this profile
#   gap                None | ("tail", frac) | ("middle", frac):
#                      forces a contiguous inactive window of ~frac*num_days
#                      (tail = lapsed-style ending, middle = returning-style)
#   description        short human description used by the README/docs
#
# Distributions deliberately OVERLAP between adjacent profiles (rest days are
# always drawn from the same 0..500 low tail; step ranges overlap) so the
# profiles are not perfectly separable — like real populations.
# ─────────────────────────────────────────────────────────────────────────────

PROFILE_SPECS = [
    {
        "name": "INACTIVE",
        "description": (
            "Mostly sedentary. Low, sporadic step days (often pure rest); "
            "almost never meets the goal and essentially never captures a hex."
        ),
        "activity_prob": 0.13,
        "active_steps": (300, 1600),
        "cadence": (95, 120),
        "capture_prob": 0.04,
        "max_captures": 1,
        "loss_prob": 0.03,
        "max_loss": 1,
        "goal_steps": 2000,
        "defense_share": 0.0,
        "territory_cap": 2,
        "gap": None,
    },
    {
        "name": "CASUAL",
        "description": (
            "Irregular moderate activity — active roughly every other day with "
            "clear rest days. Occasionally hits the goal, holds a small patch "
            "of territory."
        ),
        "activity_prob": 0.52,
        "active_steps": (2200, 7000),
        "cadence": (100, 125),
        "capture_prob": 0.18,
        "max_captures": 2,
        "loss_prob": 0.05,
        "max_loss": 1,
        "goal_steps": 4500,
        "defense_share": 0.06,
        "territory_cap": 7,
        "gap": None,
    },
    {
        "name": "CONSISTENT",
        "description": (
            "Relatively stable — active on ~9 of 10 days with steady volume, "
            "long streaks, reliable goal completion, and a medium territory."
        ),
        "activity_prob": 0.90,
        "active_steps": (5000, 12000),
        "cadence": (105, 130),
        "capture_prob": 0.40,
        "max_captures": 2,
        "loss_prob": 0.06,
        "max_loss": 2,
        "goal_steps": 8000,
        "defense_share": 0.15,
        "territory_cap": 14,
        "gap": None,
    },
    {
        "name": "HIGHLY_ACTIVE",
        "description": (
            "Trains almost every day at high volume (some runs push past "
            "20k steps), strong goal completion, the largest captured territory."
        ),
        "activity_prob": 0.98,
        "active_steps": (10000, 22000),
        "cadence": (130, 175),  # running-heavy
        "capture_prob": 0.60,
        "max_captures": 4,
        "loss_prob": 0.08,
        "max_loss": 2,
        "goal_steps": 10000,
        "defense_share": 0.20,
        "territory_cap": 22,
        "gap": None,
    },
    {
        "name": "LAPSED",
        "description": (
            "Was previously active (real history and territory) but then went "
            "quiet: an active head followed by a long inactive tail."
        ),
        "activity_prob": 0.55,
        "active_steps": (3000, 8000),
        "cadence": (100, 125),
        "capture_prob": 0.22,
        "max_captures": 2,
        "loss_prob": 0.05,
        "max_loss": 1,
        "goal_steps": 5000,
        "defense_share": 0.08,
        "territory_cap": 9,
        "gap": ("tail", 0.4),
    },
    {
        "name": "RETURNING",
        "description": (
            "Active, then a multi-week inactive spell in the middle, then "
            "renewed activity afterwards."
        ),
        "activity_prob": 0.65,
        "active_steps": (4000, 9000),
        "cadence": (105, 130),
        "capture_prob": 0.30,
        "max_captures": 2,
        "loss_prob": 0.05,
        "max_loss": 1,
        "goal_steps": 6000,
        "defense_share": 0.10,
        "territory_cap": 11,
        "gap": ("middle", 0.3),
    },
    {
        "name": "TERRITORY_FOCUSED",
        "description": (
            "Territory-first player: walks steadily while claiming hexes "
            "(slower cadence) and dedicates frequent reinforcement/defense "
            "runs to a large territory."
        ),
        "activity_prob": 0.80,
        "active_steps": (4500, 10500),
        "cadence": (90, 115),  # meanders while claiming territory
        "capture_prob": 0.85,
        "max_captures": 3,
        "loss_prob": 0.02,
        "max_loss": 1,
        "goal_steps": 5500,
        "defense_share": 0.30,
        "defense_run_prob": 0.35,
        "territory_cap": 30,
        "gap": None,
    },
]

PROFILE_NAMES = [spec["name"] for spec in PROFILE_SPECS]
PROFILE_BY_NAME = {spec["name"]: spec for spec in PROFILE_SPECS}


# ─────────────────────────────────────────────────────────────────────────────
# Profile selection
# ─────────────────────────────────────────────────────────────────────────────


def _assign_profile_names(num_users: int, seed: int, profiles: list[str] | None):
    """Choose one profile name per synthetic user, deterministically.

    - If ``profiles`` is given it must already have exactly ``num_users``
      entries and is used verbatim.
    - Otherwise the first min(num_users, 7) users are assigned distinct
      profiles (so a default dataset always contains every profile once
      there are >= 7 users), and any remaining users are drawn from a
      weighted population mix.
    """
    if profiles is not None:
        if len(profiles) != num_users:
            raise ValueError(
                f"profiles list has {len(profiles)} entries but num_users={num_users}"
            )
        for name in profiles:
            if name not in PROFILE_BY_NAME:
                raise ValueError(f"unknown profile: {name!r}")
        return list(profiles)

    rng = random.Random(seed)
    if num_users <= len(PROFILE_NAMES):
        return rng.sample(PROFILE_NAMES, num_users)

    chosen = list(PROFILE_NAMES)
    rng.shuffle(chosen)  # the guaranteed all-profiles head
    chosen.extend(
        rng.choices(PROFILE_NAMES, weights=DEFAULT_PROFILE_WEIGHTS, k=num_users - 7)
    )
    return chosen


# ─────────────────────────────────────────────────────────────────────────────
# Day-generation helpers
# ─────────────────────────────────────────────────────────────────────────────


def _inactive_window(num_days: int, gap):
    """Map a profile ``gap`` spec to an inclusive-exclusive (start, end)
    window of forced-inactive day indices, or None."""
    if gap is None or num_days < 3:
        return None
    kind, frac = gap
    if kind == "tail":
        length = min(num_days - 1, max(4, int(num_days * frac)))
        if length <= 0:
            return None
        return (num_days - length, num_days)
    # kind == "middle" — leave at least one day on each side.
    length = min(num_days - 2, max(4, int(num_days * frac)))
    if length <= 0:
        return None
    before = (num_days - length) // 2
    return (before, before + length)


def _derive_active_minutes(
    steps: int, rng: random.Random, cadence_range: tuple[int, int]
) -> int:
    """Minutes in a continuous active bout, derived from total steps.

    Only a *share* of a day's steps occur in measurable active bouts; the
    rest are incidental. Below the active-bout floor the day counts as 0
    active minutes (incidental only); at/above the floor it is always
    >= 1 minute, so high-step days can never have zero active minutes.
    """
    if steps < ACTIVE_MINUTES_FLOOR_STEPS:
        return 0
    bout_share = rng.uniform(BOUT_SHARE_LO, BOUT_SHARE_HI)
    cadence = rng.uniform(cadence_range[0], cadence_range[1])  # steps / minute
    minutes = steps * bout_share / cadence
    minutes = round(minutes)
    # Both bounds are structural, not chosen ad hoc: 1 <= minutes <= steps
    # (cadence is >= ~90 steps/min, so minutes is well under `steps`).
    return max(1, min(steps, minutes))


def generate_user_days(
    profile_name: str,
    synthetic_user_id: str,
    num_days: int,
    seed: int | random.Random = DEFAULT_SEED,
    start_date: date = DATASET_START_DATE,
) -> list[dict]:
    """Generate ``num_days`` consecutive daily records for one synthetic user.

    ``seed`` may be an int (fresh Random seeded from it) or an existing
    ``random.Random`` instance (for deterministic composition inside
    generate_dataset). Returns a list of row dicts keyed by COLUMNS.
    """
    if profile_name not in PROFILE_BY_NAME:
        raise ValueError(f"unknown profile: {profile_name!r}")
    if num_days < 1:
        raise ValueError("num_days must be >= 1")

    spec = PROFILE_BY_NAME[profile_name]
    rng = seed if isinstance(seed, random.Random) else random.Random(seed)
    window = _inactive_window(num_days, spec["gap"])

    active_steps_lo, active_steps_hi = spec["active_steps"]
    cadence_range = spec["cadence"]
    defense_run_prob = spec.get("defense_run_prob", DEFENSE_RUN_PROB)

    rows: list[dict] = []
    hexes_owned = 0  # end-of-day holdings ledger
    streak = 0

    for day_index in range(num_days):
        forced_inactive = window is not None and window[0] <= day_index < window[1]
        is_active = (not forced_inactive) and rng.random() < spec["activity_prob"]

        steps = (
            rng.randint(active_steps_lo, active_steps_hi)
            if is_active
            else rng.randint(0, REST_STEPS_MAX)
        )
        steps = min(steps, MAX_STEPS)  # safety cap (no profile reaches it)

        # ── Captures: only possible on an active day at/above the step bar,
        #    and only while the profile has room below its territory cap so
        #    the ledger never exceeds it.
        holdings_before = hexes_owned
        captures = 0
        if is_active and steps >= STREAK_MIN_STEPS:
            if rng.random() < spec["capture_prob"]:
                room = spec["territory_cap"] - holdings_before
                if room > 0:
                    captures = rng.randint(1, min(spec["max_captures"], room))

        # ── Losses: only possible while holding territory, bounded by the
        #    territory you hold at the start of the day.
        losses = 0
        if holdings_before > 0:
            loss_prob = spec["loss_prob"] * min(1.0, holdings_before / 8.0)
            if rng.random() < loss_prob:
                losses = rng.randint(1, min(spec["max_loss"], holdings_before))

        hexes_owned = holdings_before + captures - losses  # >= 0 by construction

        # ── Defense/reinforcement steps are a share of an active day's steps
        #    (or the whole day for an occasional dedicated defense run),
        #    and only exist when the user actually holds territory.
        defense_steps = 0
        if steps > 0 and holdings_before > 0 and spec["defense_share"] > 0:
            if rng.random() < defense_run_prob and steps >= STREAK_MIN_STEPS:
                defense_steps = steps
            else:
                defense_steps = int(steps * spec["defense_share"])

        # ── Streak: consecutive days that clear the activity bar.
        streak = streak + 1 if steps >= STREAK_MIN_STEPS else 0

        # ── Goal completion is derived, never independent: met iff steps >= goal.
        goal_completed = 1 if steps >= spec["goal_steps"] else 0

        rows.append(
            {
                "synthetic_user_id": synthetic_user_id,
                "day": (start_date + timedelta(days=day_index)).isoformat(),
                "steps": steps,
                "active_minutes": _derive_active_minutes(steps, rng, cadence_range),
                "hexes_owned": hexes_owned,
                "hexes_captured": captures,
                "hexes_lost": losses,
                "defense_steps": defense_steps,
                "streak": streak,
                "goal_steps": spec["goal_steps"],
                "goal_completed": goal_completed,
                "data_source": DATA_SOURCE,
            }
        )

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Dataset composition + CSV I/O
# ─────────────────────────────────────────────────────────────────────────────


def generate_dataset(
    num_users: int = DEFAULT_USERS,
    num_days: int = DEFAULT_DAYS,
    seed: int = DEFAULT_SEED,
    start_date: date = DATASET_START_DATE,
    profiles: list[str] | None = None,
) -> list[dict]:
    """Generate a full dataset of daily records for ``num_users`` users.

    Returns a flat list of row dicts (num_users * num_days rows) suitable
    for write_dataset. Deterministic for a fixed seed.
    """
    if num_users < 1:
        raise ValueError("num_users must be >= 1")
    if num_days < 1:
        raise ValueError("num_days must be >= 1")

    names = _assign_profile_names(num_users, seed, profiles)
    master = random.Random(seed)

    rows: list[dict] = []
    for index, name in enumerate(names):
        user_id = f"syn_{name.lower()}_{index + 1:04d}"
        user_rng = random.Random(master.getrandbits(128))
        rows.extend(
            generate_user_days(name, user_id, num_days, seed=user_rng, start_date=start_date)
        )
    return rows


def write_dataset(rows: list[dict], output_path: str | Path) -> Path:
    """Write row dicts to a CSV file with the canonical column order.

    Returns the resolved output path. Missing parent directories are created.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def read_dataset(input_path: str | Path) -> list[dict]:
    """Read a generated CSV back into a list of row dicts (values as strings)."""
    path = Path(input_path)
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ─────────────────────────────────────────────────────────────────────────────
# Data-quality summary / validation (stdlib only)
# ─────────────────────────────────────────────────────────────────────────────


def profile_from_user_id(synthetic_user_id: str) -> str:
    """Recover the profile name from an id like ``syn_highly_active_0003``.

    Returns the canonical (uppercase) profile name, or the parsed stem
    unchanged for an id that does not match a known synthetic profile (so
    future real-data ids pass through harmlessly).
    """
    stem = synthetic_user_id[len("syn_") :] if synthetic_user_id.startswith("syn_") else synthetic_user_id
    stem = stem.rsplit("_", 1)[0]
    for name in PROFILE_NAMES:
        if name.lower() == stem:
            return name
    return stem


def summarize_dataset(rows: list[dict]) -> dict:
    """Compute aggregate data-quality statistics over a list of row dicts.

    Pure stdlib (``statistics``). Returns a nested plain dict; see the
    module tests and CLI for the exact shape. Metrics were chosen so that
    obviously broken rows (e.g. high steps with zero active minutes) are
    impossible to miss.
    """
    if not rows:
        raise ValueError("cannot summarize an empty dataset")

    def _num(row, key):
        return float(row[key])

    steps = [_num(r, "steps") for r in rows]
    minutes = [_num(r, "active_minutes") for r in rows]

    n_steps_over_10k = sum(1 for s, m in zip(steps, minutes) if s > 10000 and m == 0)
    n_steps_over_20k = sum(1 for s, m in zip(steps, minutes) if s > 20000 and m == 0)

    goal_rate = sum(_num(r, "goal_completed") for r in rows) / len(rows) * 100.0

    by_profile: dict[str, list[dict]] = {}
    for row in rows:
        by_profile.setdefault(profile_from_user_id(row["synthetic_user_id"]), []).append(row)

    def _pct(part, whole):
        return round(part / whole * 100.0, 4) if whole else 0.0

    profile_stats: dict[str, dict] = {}
    for name in PROFILE_NAMES:
        group = by_profile.get(name, [])
        if not group:
            continue
        g_steps = [_num(r, "steps") for r in group]
        g_minutes = [_num(r, "active_minutes") for r in group]
        g_goal = sum(_num(r, "goal_completed") for r in group) / len(group) * 100.0
        profile_stats[name] = {
            "users": len({r["synthetic_user_id"] for r in group}),
            "rows": len(group),
            "avg_steps": round(statistics.mean(g_steps), 2),
            "avg_active_minutes": round(statistics.mean(g_minutes), 3),
            "goal_completion_pct": round(g_goal, 2),
            "avg_captures": round(
                statistics.mean([_num(r, "hexes_captured") for r in group]), 4
            ),
            "avg_hexes_owned": round(
                statistics.mean([_num(r, "hexes_owned") for r in group]), 3
            ),
            "avg_streak": round(
                statistics.mean([_num(r, "streak") for r in group]), 3
            ),
        }

    return {
        "n_rows": len(rows),
        "n_users": len({r["synthetic_user_id"] for r in rows}),
        "steps_min": int(min(steps)),
        "steps_max": int(max(steps)),
        "steps_mean": round(statistics.mean(steps), 2),
        "steps_median": round(statistics.median(steps), 2),
        "active_minutes_min": int(min(minutes)),
        "active_minutes_max": int(max(minutes)),
        "active_minutes_mean": round(statistics.mean(minutes), 3),
        "active_minutes_median": round(statistics.median(minutes), 3),
        # The two data-quality red flags: high steps logged with zero minutes.
        "pct_steps_over_10k_zero_active_minutes": _pct(
            n_steps_over_10k, len(rows)
        ),
        "pct_steps_over_20k_zero_active_minutes": _pct(
            n_steps_over_20k, len(rows)
        ),
        "goal_completion_pct": round(goal_rate, 2),
        "steps_active_minutes_pearson_r": round(
            statistics.correlation(steps, minutes), 4
        ),
        "by_profile": profile_stats,
    }


def format_summary(summary: dict) -> str:
    """Render a summary dict into a compact human-readable report."""
    lines: list[str] = []
    lines.append("── Data-quality summary (SYNTHETIC data) ──")
    lines.append(
        f"rows={summary['n_rows']} users={summary['n_users']} | "
        f"goal_completion={summary['goal_completion_pct']}% | "
        f"steps<->active_minutes pearson r={summary['steps_active_minutes_pearson_r']}"
    )
    lines.append(
        "steps    min/max/mean/median = "
        f"{summary['steps_min']}/{summary['steps_max']}/"
        f"{summary['steps_mean']}/{summary['steps_median']}"
    )
    lines.append(
        "minutes  min/max/mean/median = "
        f"{summary['active_minutes_min']}/{summary['active_minutes_max']}/"
        f"{summary['active_minutes_mean']}/{summary['active_minutes_median']}"
    )
    lines.append(
        "% rows steps>10k with 0 minutes = "
        f"{summary['pct_steps_over_10k_zero_active_minutes']}"
    )
    lines.append(
        "% rows steps>20k with 0 minutes = "
        f"{summary['pct_steps_over_20k_zero_active_minutes']}"
    )
    header = (
        "profile            users rows avg_steps avg_min goal% avg_cap avg_hex avg_strk"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for name in PROFILE_NAMES:
        p = summary["by_profile"].get(name)
        if p is None:
            continue
        lines.append(
            f"{name:<18} {p['users']:>5} {p['rows']:>4} "
            f"{p['avg_steps']:>9.0f} {p['avg_active_minutes']:>7.1f} "
            f"{p['goal_completion_pct']:>6.1f} {p['avg_captures']:>6.2f} "
            f"{p['avg_hexes_owned']:>7.1f} {p['avg_streak']:>7.1f}"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synthetic_fitness",
        description=(
            "Generate a SYNTHETIC FitQuest fitness dataset (never present it "
            "as real user data)."
        ),
    )
    parser.add_argument("--users", type=int, default=DEFAULT_USERS, help="number of synthetic users")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="days of history per user")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed for reproducibility")
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=DATASET_START_DATE,
        help="first day of the history window (ISO YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="output CSV path",
    )
    parser.add_argument(
        "--check",
        type=Path,
        default=None,
        metavar="CSV",
        help="skip generation and print the data-quality summary for an existing CSV",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.check is not None:
        rows = read_dataset(args.check)
        print(format_summary(summarize_dataset(rows)))
        return 0

    rows = generate_dataset(
        num_users=args.users,
        num_days=args.days,
        seed=args.seed,
        start_date=args.start_date,
    )
    path = write_dataset(rows, args.output)

    n_users = len({row["synthetic_user_id"] for row in rows})
    print(f"Wrote {len(rows)} synthetic rows "
          f"({n_users} users x {args.days} days) to {path}")
    print(f"seed={args.seed} | rows are data_source={DATA_SOURCE!r}")
    print()
    print(format_summary(summarize_dataset(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
