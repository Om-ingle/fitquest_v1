"""Real telemetry dataset builder/exporter (Phase 4B.6).

Reads persisted real FitQuest daily telemetry (the ``userdailyactivity`` table
written by run-sync since Phase 4B.5) and produces the same ML-ready
representation the synthetic experiment uses:

    userdailyactivity rows
        -> real_telemetry_raw.csv      extracted rows, VERBATIM (no fabrication)
        -> real_telemetry_daily.csv    densified generator.COLUMNS-shaped daily
                                       rows (+ provenance flags), data_source="real"
        -> real_telemetry_features.csv features.OUTPUT_COLUMNS + inactive_next_3d
        -> real_telemetry_manifest.json provenance / counts / policies

Reuse, not duplication (see real_telemetry_export.md):

- ``real_telemetry_compat.telemetry_to_raw_rows`` — telemetry -> raw daily rows
  (gap densification, streak recomputation, goal derivation, "real" labeling).
- ``features.build_features`` — the UNMODIFIED 21-feature pipeline.
- ``target.build_labels`` — the UNMODIFIED ``inactive_next_3d`` definition.

⚠  NO model is trained here and NO real-user ML performance is measured —
   this tool only builds datasets. The real Supabase table is still empty;
   everything exercised in tests is deterministic TEST-FIXTURE data shaped
   like real telemetry, never written to the real database.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import features  # noqa: E402
import generator  # noqa: E402
import real_telemetry_compat as rtc  # noqa: E402
import target  # noqa: E402

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = TOOL_DIR / "output"

SOURCE_TABLE = "userdailyactivity"

# Columns read from the source table (mirrors Alembic migration 0002;
# updated_at is intentionally not exported — it is sync bookkeeping, not data).
TELEMETRY_COLUMNS = ("user_id", "activity_date") + rtc.TELEMETRY_FIELDS

# Provenance flags appended to the densified daily rows. They document, per
# row, what was actually observed vs synthesized/unknown — the feature schema
# itself has no null representation (see real_telemetry_export.md §nulls).
DENSIFIED_FLAG = "densified"
KNOWN_FLAGS = ("hexes_lost_known", "defense_steps_known")
DAILY_COLUMNS = list(generator.COLUMNS) + [DENSIFIED_FLAG, *KNOWN_FLAGS]

# The ML-ready output: exact synthetic-pipeline columns + the Phase 4B.3 target.
FEATURE_COLUMNS = list(features.OUTPUT_COLUMNS) + [target.TARGET_NAME]

RAW_CSV = "real_telemetry_raw.csv"
DAILY_CSV = "real_telemetry_daily.csv"
FEATURES_CSV = "real_telemetry_features.csv"
MANIFEST_JSON = "real_telemetry_manifest.json"

HONESTY_NOTE = (
    "Dataset export only — no model was trained and no real-user ML "
    "performance was measured."
)


# ─────────────────────────────────────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────────────────────────────────────


def _iso_day(value: Any) -> str:
    """ activity_date as ISO text. The stored DATE is used as-is — it is the
    device-local calendar date the client reported; the exporter NEVER applies
    a server-timezone conversion (Phase 4B.6 requirement)."""
    if isinstance(value, str):
        return value
    if isinstance(value, rtc.dt.datetime):
        return value.date().isoformat()
    return value.isoformat()


def fetch_telemetry_rows(database_url: str, table: str = SOURCE_TABLE) -> list[dict]:
    """Read every telemetry row from the backend database, deterministically
    ordered by (user_id, activity_date).

    Uses SQLAlchemy (an existing backend dependency) so the same code works
    against SQLite and the real Supabase PostgreSQL. The URL is never printed
    or persisted — it can carry credentials.
    """
    from sqlalchemy import create_engine, text

    query = text(
        f"SELECT {', '.join(TELEMETRY_COLUMNS)} FROM {table} "
        "ORDER BY user_id, activity_date"
    )
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return [dict(row) for row in connection.execute(query).mappings()]
    finally:
        engine.dispose()


def validate_unique_telemetry(rows: Iterable[Mapping[str, Any]]) -> None:
    """Fail loudly on duplicate (user, activity_date) records.

    The table's composite primary key should make this impossible, but the
    exporter refuses to guess which record wins — an ambiguous dataset is a
    hard error, never a silent pick.
    """
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row["user_id"]), _iso_day(row["activity_date"]))
        if key in seen:
            raise ValueError(
                f"duplicate telemetry rows for user {key[0]!r} on "
                f"{key[1]!r} — the {SOURCE_TABLE} primary key "
                "(user_id, activity_date) should prevent this; refusing to "
                "export an ambiguous dataset"
            )
        seen.add(key)


# ─────────────────────────────────────────────────────────────────────────────
# Export (pure, in-memory)
# ─────────────────────────────────────────────────────────────────────────────


def _annotate_provenance(daily_rows: list[dict], extracted_rows: list[dict]) -> None:
    """Stamp each densified daily row with what was observed vs synthesized.

    - ``densified``: 1 for calendar days the device never synced (fabricated
      zero-activity row per the Phase 4B.5 telemetry contract).
    - ``hexes_lost_known`` / ``defense_steps_known``: 1 iff the stored row
      actually reported that field. The feature values are 0 where unknown —
      the flag is what keeps "unknown" distinguishable from a real zero.
    """
    sources = {
        (str(row["user_id"]), _iso_day(row["activity_date"])): row
        for row in extracted_rows
    }
    for row in daily_rows:
        source = sources.get((row["synthetic_user_id"], row["day"]))
        row[DENSIFIED_FLAG] = 0 if source is not None else 1
        if source is None:
            row["hexes_lost_known"] = 0
            row["defense_steps_known"] = 0
        else:
            row["hexes_lost_known"] = int(source["hexes_lost"] is not None)
            row["defense_steps_known"] = int(source["defense_steps"] is not None)


def export_dataset(telemetry_rows: Iterable[Mapping[str, Any]]) -> dict:
    """Convert persisted telemetry rows into the real-data ML datasets.

    Pure function (no I/O after the input rows). Raises on empty input,
    duplicate (user, date) records, or any schema drift away from the
    synthetic pipeline's 21 MODEL_FEATURES.
    """
    extracted = [dict(row) for row in telemetry_rows]
    if not extracted:
        raise ValueError("no telemetry rows to export")
    # Reject malformed or synthetic-pipeline-shaped rows up front with a
    # clear error (synthetic rows carry synthetic_user_id, not user_id).
    for row in extracted:
        missing = [k for k in rtc.REQUIRED_TELEMETRY_KEYS if k not in row]
        if missing:
            raise ValueError(f"telemetry row is missing keys: {missing}")
    validate_unique_telemetry(extracted)

    # Phase 4B.5 adapter: densify gaps, recompute streaks, derive goals,
    # label every row data_source="real".
    daily = rtc.telemetry_to_raw_rows(extracted)
    _annotate_provenance(daily, extracted)

    # Unmodified Phase 4B.2 / 4B.3 pipelines.
    feature_rows = features.build_features(daily)
    labels = target.build_labels(daily)
    for row in feature_rows:
        # None (no complete 3-day horizon) stays None — never imputed.
        row[target.TARGET_NAME] = labels[(row["synthetic_user_id"], row["day"])]

    _verify_feature_schema(feature_rows)

    labeled = [r for r in feature_rows if r[target.TARGET_NAME] is not None]
    return {
        "extracted": extracted,
        "daily": daily,
        "features": feature_rows,
        "labels": labels,
        "n_labeled": len(labeled),
        "n_unlabeled_tail": len(feature_rows) - len(labeled),
        "n_positives": sum(r[target.TARGET_NAME] for r in labeled),
        "n_users": len({r["synthetic_user_id"] for r in feature_rows}),
        "n_densified": sum(r[DENSIFIED_FLAG] for r in daily),
    }


def _verify_feature_schema(feature_rows: list[dict]) -> None:
    """The real dataset MUST be column-identical to the synthetic experiment."""
    for i, row in enumerate(feature_rows):
        if list(row.keys()) != FEATURE_COLUMNS:
            raise ValueError(
                f"feature row {i} has columns {list(row.keys())}, expected "
                f"{FEATURE_COLUMNS} — real/synthetic schema drift"
            )
        if row["data_source"] != rtc.REAL_DATA_SOURCE:
            raise ValueError(
                f"feature row {i} is data_source={row['data_source']!r}, "
                f"expected {rtc.REAL_DATA_SOURCE!r}"
            )


def feature_matrix(feature_rows: list[dict]) -> list[list]:
    """The X matrix: ONLY the 21 MODEL_FEATURES, in canonical order.

    Metadata (user id, day), provenance (data_source) and the target are
    excluded by construction — this function is the definition of X.
    """
    return [[row[name] for name in features.MODEL_FEATURES] for row in feature_rows]


# ─────────────────────────────────────────────────────────────────────────────
# Output files
# ─────────────────────────────────────────────────────────────────────────────


def _write_csv(rows: list[dict], columns: list[str], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_raw_telemetry(extracted_rows: list[dict], path: str | Path) -> Path:
    """Extracted rows verbatim — NULL stays empty, nothing is fabricated."""
    rows = [
        {
            "user_id": str(row["user_id"]),
            "activity_date": _iso_day(row["activity_date"]),
            **{field: row[field] for field in rtc.TELEMETRY_FIELDS},
        }
        for row in extracted_rows
    ]
    return _write_csv(rows, list(TELEMETRY_COLUMNS), Path(path))


def write_daily(daily_rows: list[dict], path: str | Path) -> Path:
    """Densified daily rows in generator.COLUMNS shape + provenance flags."""
    return _write_csv(daily_rows, DAILY_COLUMNS, Path(path))


def write_features(feature_rows: list[dict], path: str | Path) -> Path:
    """ML-ready rows: features.OUTPUT_COLUMNS + the target column.

    ``inactive_next_3d`` is empty for rows whose 3-day future horizon does
    not exist (the tail of each user's history) — never imputed.
    """
    return _write_csv(feature_rows, FEATURE_COLUMNS, Path(path))


def write_manifest(result: dict, out_dir: Path) -> Path:
    n_labeled = result["n_labeled"]
    path = out_dir / MANIFEST_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "dataset": (
            "FitQuest REAL daily telemetry export (Phase 4B.6), extracted "
            "from the backend userdailyactivity table. Rows are persisted "
            "real telemetry, NOT synthetic. " + HONESTY_NOTE
        ),
        "source_table": SOURCE_TABLE,
        "data_source": rtc.REAL_DATA_SOURCE,
        "outputs": {
            "raw": RAW_CSV,
            "daily": DAILY_CSV,
            "features": FEATURES_CSV,
        },
        "counts": {
            "users": result["n_users"],
            "extracted_rows": len(result["extracted"]),
            "densified_gap_rows": result["n_densified"],
            "daily_rows": len(result["daily"]),
            "feature_rows": len(result["features"]),
            "labeled_rows": n_labeled,
            "unlabeled_tail_rows": result["n_unlabeled_tail"],
            "positives": result["n_positives"],
            "prevalence_pct": (
                round(result["n_positives"] / n_labeled * 100.0, 2)
                if n_labeled
                else None
            ),
        },
        "model_features": list(features.MODEL_FEATURES),
        "target": {
            "name": target.TARGET_NAME,
            "description": target.TARGET_DESCRIPTION,
            "unlabeled_policy": (
                "Rows without a complete 3-day future horizon carry an empty "
                "target and are never imputed."
            ),
        },
        "densification_policy": (
            "Days with no stored row between a user's first and last recorded "
            "day become zero-step rows. Justification: FitQuest daily steps "
            "are tracked-run steps only (the app has no background step "
            "counting), so a day with no synced run has zero TRACKED steps by "
            "the app's own definition — zero means 'no tracked activity', not "
            "'the user did not walk'. Days after the last recorded day are "
            "NOT densified."
        ),
        "unknown_semantics": (
            "NULL telemetry fields mean 'unknown', not 'none'. The raw CSV "
            "preserves NULLs verbatim. The daily CSV carries hexes_lost_known "
            "/ defense_steps_known flags (1 = actually reported); where a "
            "flag is 0 the feature value 0 means unknown — losses_7d, "
            "defense_steps_7d and defense_ratio_7d are placeholders on such "
            "rows until a later phase observes those signals."
        ),
        "activity_date_semantics": (
            "activity_date is the device-local calendar date reported by the "
            "client and stored in userdailyactivity; the exporter uses the "
            "stored DATE as-is and never applies a server-timezone "
            "conversion."
        ),
        "leakage_policy": (
            "Features come from the unmodified features.py policy: every "
            "feature uses only day D and earlier of the SAME user; targets "
            "from the unmodified target.py: only days D+1..D+3 of the SAME "
            "user. No synthetic rows can enter (the exporter reads only "
            "userdailyactivity and labels every row data_source='real')."
        ),
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2)
        handle.write("\n")
    return path


def write_outputs(result: dict, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    return {
        "raw": write_raw_telemetry(result["extracted"], out / RAW_CSV),
        "daily": write_daily(result["daily"], out / DAILY_CSV),
        "features": write_features(result["features"], out / FEATURES_CSV),
        "manifest": write_manifest(result, out),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="real_telemetry_export",
        description=(
            "Export persisted REAL FitQuest daily telemetry "
            f"({SOURCE_TABLE}) into the ML-ready representation used by the "
            "synthetic experiment. " + HONESTY_NOTE
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "SQLAlchemy URL of the backend database "
            "(defaults to the DATABASE_URL environment variable; never "
            "printed or stored — it can carry credentials)"
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"directory for the output CSVs + manifest (default: {DEFAULT_OUT_DIR})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        _build_arg_parser().error(
            "a database URL is required: pass --database-url or set DATABASE_URL"
        )

    rows = fetch_telemetry_rows(database_url)
    if not rows:
        print(f"{SOURCE_TABLE} has no rows — nothing to export.")
        print("The real telemetry table has not been populated/deployed yet.")
        print(HONESTY_NOTE)
        return 0

    result = export_dataset(rows)
    paths = write_outputs(result, args.out_dir)

    counts = {
        "users": result["n_users"],
        "extracted": len(result["extracted"]),
        "densified": result["n_densified"],
        "features": len(result["features"]),
        "labeled": result["n_labeled"],
        f"{target.TARGET_NAME} positives": result["n_positives"],
    }
    print(f"Exported {SOURCE_TABLE} telemetry ({counts})")
    for name, path in paths.items():
        print(f"  {name:<9} {path}")
    print(f"rows are data_source={rtc.REAL_DATA_SOURCE!r}; target = "
          f"{target.TARGET_NAME} ({target.TARGET_DESCRIPTION})")
    print(HONESTY_NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
