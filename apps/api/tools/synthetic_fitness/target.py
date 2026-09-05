"""Phase 4B.3 target design: the near-term disengagement label.

⚠  The label — like everything else in this tool — is computed from SYNTHETIC
   data. It demonstrates that the ML data path is well-posed (enough
   positives/negatives, leakage-free, time-aware splits). It does NOT say
   anything about real FitQuest users.

Target (see target_design.md for the full rationale):

    inactive_next_3d(D) = 1  iff  at least INACTIVE_DAYS_REQUIRED (2) of the
    HORIZON_DAYS (3) days following D have steps < 1,000 (the game's
    activity bar).

Deliberately NOT the rules engine's recommendation output: labeling rows
with STARTER/RECOVERY/DEFENSE/PROGRESS/MAINTAIN would make the experiment
circular — the model would mostly learn to replay the rules (see
target_design.md §5).

Split policy (calendar dates, so uneven real-world histories slot in too):

    train   : days on/before 2025-05-17 (history index 0..136)
    embargo : 2025-05-18 .. 2025-05-20 (train rows whose 3-day target
              window would reach into the validation period)
    val     : 2025-05-21 .. 2025-06-09 (index 140..159)
    test    : 2025-06-10 .. 2025-06-26 (index 160..176)

Rows in the last HORIZON_DAYS days of each user's history have no full
target window and carry a ``None`` label — they are excluded from the
labeled experiment set, never imputed.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import generator
from generator import STREAK_MIN_STEPS

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = TOOL_DIR / "output" / "synthetic_fitness_dataset.csv"

# ── Target definition ────────────────────────────────────────────────────────

TARGET_NAME = "inactive_next_3d"
TARGET_DESCRIPTION = (
    "1 iff at least 2 of the 3 days after D (D+1..D+3) have steps < 1000."
)
HORIZON_DAYS = 3
INACTIVE_DAYS_REQUIRED = 2
INACTIVE_STEPS_MAX = STREAK_MIN_STEPS - 1  # "inactive" := steps < 1000

# ── Time-aware split boundaries (calendar dates) ─────────────────────────────
# The synthetic dataset starts 2025-01-01 with 180 days per user, so these
# correspond to per-user history indices 0..136 / 137..139 / 140..159 /
# 160..176. The 3-day embargo keeps every training row's target window
# strictly before the validation period.

TRAIN_END = date(2025, 5, 17)  # last training day
VAL_START = date(2025, 5, 21)  # first validation day
VAL_END = date(2025, 6, 9)  # last validation day
TEST_START = date(2025, 6, 10)  # first test day

SPLIT_NAMES = ("train", "embargo", "val", "test")


def assign_split(day_iso: str) -> str:
    """Map one ISO day to its experiment split (total, deterministic)."""
    day = date.fromisoformat(day_iso)
    if day <= TRAIN_END:
        return "train"
    if day < VAL_START:
        return "embargo"
    if day <= VAL_END:
        return "val"
    return "test"


# ── Label construction ───────────────────────────────────────────────────────


def build_labels(raw_rows: list[dict]) -> dict[tuple[str, str], int | None]:
    """Compute the target for every (user, day).

    Returns ``{(synthetic_user_id, day_iso): 1 | 0 | None}``. ``None`` marks
    the last ``HORIZON_DAYS`` days of a user's history, where the full future
    window does not exist. Only days D+1..D+3 of the SAME user are read —
    features are never touched, so the label cannot leak backward into them.
    """
    grouped: dict[str, list[dict]] = {}
    for row in raw_rows:
        grouped.setdefault(row["synthetic_user_id"], []).append(row)

    labels: dict[tuple[str, str], int | None] = {}
    for user_id, user_rows in grouped.items():
        user_rows = sorted(user_rows, key=lambda r: r["day"])
        n = len(user_rows)
        for i, row in enumerate(user_rows):
            if i + HORIZON_DAYS >= n:
                labels[(user_id, row["day"])] = None  # no full horizon
                continue
            window = user_rows[i + 1 : i + 1 + HORIZON_DAYS]
            inactive = sum(
                1 for r in window if int(r["steps"]) <= INACTIVE_STEPS_MAX
            )
            labels[(user_id, row["day"])] = int(inactive >= INACTIVE_DAYS_REQUIRED)
    return labels


def label_for(labels: dict[tuple[str, str], int | None], user_id: str, day_iso: str):
    """Convenience lookup with a helpful error for unknown keys."""
    try:
        return labels[(user_id, day_iso)]
    except KeyError as exc:
        raise KeyError(f"no label for user {user_id!r} on day {day_iso!r}") from exc


# ── Distribution summary (validation of the design, not training) ───────────


def summarize_labels(raw_rows: list[dict]) -> dict:
    """Overall / by-profile / by-split prevalence of the target.

    Pure stdlib; used by the CLI and the design tests to prove the target is
    usable (both classes populated in every split).
    """
    labels = build_labels(raw_rows)
    grouped: dict[str, list[dict]] = {}
    for row in raw_rows:
        grouped.setdefault(row["synthetic_user_id"], []).append(row)

    def _bucket():
        return [0, 0]  # [labeled_rows, positives]

    overall = _bucket()
    by_profile: dict[str, list] = {}
    by_split: dict[str, list] = {name: _bucket() for name in SPLIT_NAMES}

    for user_id, user_rows in grouped.items():
        profile = generator.profile_from_user_id(user_id)
        for row in user_rows:
            label = labels[(user_id, row["day"])]
            if label is None:
                continue
            overall[0] += 1
            overall[1] += label
            prof = by_profile.setdefault(profile, _bucket())
            prof[0] += 1
            prof[1] += label
            split = by_split[assign_split(row["day"])]
            split[0] += 1
            split[1] += label

    def _pct(bucket):
        return round(bucket[1] / bucket[0] * 100.0, 2) if bucket[0] else None

    return {
        "target": TARGET_NAME,
        "horizon_days": HORIZON_DAYS,
        "inactive_days_required": INACTIVE_DAYS_REQUIRED,
        "labeled_rows": overall[0],
        "unlabeled_tail_rows": sum(
            1
            for user_id, user_rows in grouped.items()
            for row in user_rows[-HORIZON_DAYS:]
        ),
        "positives": overall[1],
        "prevalence_pct": _pct(overall),
        "by_profile": {
            name: {"rows": b[0], "positives": b[1], "prevalence_pct": _pct(b)}
            for name, b in sorted(by_profile.items())
        },
        "by_split": {
            name: {"rows": b[0], "positives": b[1], "prevalence_pct": _pct(b)}
            for name, b in by_split.items()
        },
    }


def format_summary(summary: dict) -> str:
    lines = [
        f"── Target '{summary['target']}' distribution (SYNTHETIC data) ──",
        (
            f"labeled={summary['labeled_rows']} "
            f"(+{summary['unlabeled_tail_rows']} tail rows without a full horizon) "
            f"| positives={summary['positives']} "
            f"({summary['prevalence_pct']}%)"
        ),
    ]
    lines.append("split    rows  positives  prevalence%")
    for name, s in summary["by_split"].items():
        lines.append(f"{name:<8} {s['rows']:>5} {s['positives']:>10} {s['prevalence_pct']:>11}")
    lines.append("profile             rows  positives  prevalence%")
    for name, s in summary["by_profile"].items():
        lines.append(f"{name:<18} {s['rows']:>5} {s['positives']:>10} {s['prevalence_pct']:>11}")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="synthetic_target",
        description=(
            "Analyze the distribution of the Phase 4B.3 ML target on a "
            "SYNTHETIC dataset (never present results as real user data)."
        ),
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="raw daily dataset CSV")
    args = parser.parse_args(argv)

    raw_rows = generator.read_dataset(args.input)
    print(format_summary(summarize_labels(raw_rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
