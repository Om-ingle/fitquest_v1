#!/usr/bin/env python3
"""Verify FitQuest's Room MIGRATION_5_6 against a real device database.

WHY THIS EXISTS
    `MIGRATION_5_6` rebuilds all six local tables to scope them by
    `ownerSubject`. Room validates the result against the entities when the
    database is opened, and if anything does not line up it throws
    IllegalStateException and the app cannot reach its own data. That check is
    only reachable on a device — and the database it would run against is the
    user's real one.

    So this applies the migration to a COPY of a real pre-migration database and
    checks three things that a JVM unit test cannot:

      1. The SQL actually runs on real SQLite, on real rows.
      2. The resulting columns match what the Kotlin entities declare — parsed
         from the entity sources, which is an independent source of truth from
         the migration's own column list. A typo'd name, a wrong affinity or a
         forgotten column shows up here rather than as a crash on first launch.
      3. Every pre-existing row survives, stamped with the quarantine sentinel,
         and none is deleted.

    The SQL is EXTRACTED FROM `FitQuestDatabase.kt`, not retyped here. A
    copy-pasted duplicate would verify itself rather than the shipping code.

SAFETY
    The source database is opened read-only and never modified: it and its
    -wal/-shm siblings are copied to a temporary directory first, and all
    writes happen there. Nothing this script does can change the original. The
    -wal file is copied too, because committed pages can live there and reading
    the .db alone would silently report stale row counts.

USAGE
    python tools/verify_migration_5_6.py                       # default backup
    python tools/verify_migration_5_6.py --backup-dir DIR
    python tools/verify_migration_5_6.py --keep-temp          # inspect the copy

EXIT CODES
    0  migration verified
    1  verification failed (the report says what)
    2  the tool could not run (missing source or database)
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BACKUP_DIR = Path("F:/Projects/fitquest-device-backup-2026-09-17")
DEFAULT_SOURCE_ROOT = Path(__file__).resolve().parent.parent / "fitquest/src/main/java/com/example/mobileapp"

DB_NAME = "fitquest.db"
TARGET_VERSION = 6
SENTINEL_CONST = "LEGACY_UNOWNED_SUBJECT"

# Kotlin type -> SQLite affinity, as Room maps them.
AFFINITY = {
    "String": "TEXT",
    "Int": "INTEGER",
    "Long": "INTEGER",
    "Boolean": "INTEGER",
    "Double": "REAL",
    "Float": "REAL",
}


class ToolError(Exception):
    """The verifier could not run. Distinct from a verification failure."""


# ── Kotlin source extraction ────────────────────────────────────────────────


def strip_comments(source: str) -> str:
    """Remove // and /* */ comments.

    Load-bearing: the KDoc in FitQuestDatabase.kt discusses `rebuildScopedTable`
    and the entities' KDocs discuss their columns, so an unstripped parse can
    find declarations in prose.
    """
    out = []
    i = 0
    while i < len(source):
        if source.startswith("//", i):
            while i < len(source) and source[i] != "\n":
                i += 1
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = len(source) if end < 0 else end + 2
        else:
            out.append(source[i])
            i += 1
    return "".join(out)


def string_literals(text: str) -> str:
    """Every `"..."` literal in `text`, joined — i.e. evaluate Kotlin's `+`."""
    return "".join(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', text))


def balanced(text: str, open_index: int) -> int:
    """Index of the bracket closing the one at `open_index`, ignoring strings."""
    depth = 0
    i = open_index
    while i < len(text):
        char = text[i]
        if char == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ToolError(f"unbalanced brackets from offset {open_index}")


def call_arguments(text: str, call: str) -> list[str]:
    """Top-level argument strings of every `<call>(...)` in `text`."""
    found = []
    for match in re.finditer(rf"\b{re.escape(call)}\s*\(", text):
        open_index = text.index("(", match.start())
        found.append(text[open_index + 1 : balanced(text, open_index)])
    return found


def top_level_split(text: str, separator: str = ",") -> list[str]:
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        char = text[i]
        if char == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [p for p in (part.strip() for part in parts) if p]


@dataclass(frozen=True)
class Rebuild:
    table: str
    new_columns: str
    primary_key: str
    carried_columns: str


def parse_migration(source_root: Path) -> list[Rebuild]:
    """The six rebuilds, read out of MIGRATION_5_6 in FitQuestDatabase.kt."""
    path = source_root / "core/data/local/FitQuestDatabase.kt"
    source = strip_comments(path.read_text(encoding="utf-8"))

    start = source.find("val MIGRATION_5_6")
    if start < 0:
        raise ToolError("MIGRATION_5_6 not found in FitQuestDatabase.kt")
    end = source.find("private fun rebuildScopedTable", start)
    block = source[start : end if end > 0 else len(source)]

    rebuilds = []
    for argument in call_arguments(block, "rebuildScopedTable"):
        named = {}
        for part in top_level_split(argument):
            if "=" not in part:
                continue
            key, _, value = part.partition("=")
            named[key.strip()] = string_literals(value)
        missing = {"table", "newColumns", "primaryKey", "carriedColumns"} - named.keys()
        if missing:
            raise ToolError(f"rebuildScopedTable missing {sorted(missing)} in {named}")
        rebuilds.append(
            Rebuild(
                table=named["table"],
                new_columns=named["newColumns"],
                primary_key=named["primaryKey"],
                carried_columns=named["carriedColumns"],
            )
        )

    if len(rebuilds) != 6:
        raise ToolError(f"expected 6 rebuildScopedTable calls, found {len(rebuilds)}")
    return rebuilds


def parse_sentinel(source_root: Path) -> str:
    source = strip_comments((source_root / "core/data/local/OwnerScope.kt").read_text(encoding="utf-8"))
    match = re.search(rf'const\s+val\s+{SENTINEL_CONST}\s*=\s*"([^"]*)"', source)
    if not match:
        raise ToolError(f"{SENTINEL_CONST} not found in OwnerScope.kt")
    return match.group(1)


@dataclass(frozen=True)
class Column:
    name: str
    affinity: str
    not_null: bool


@dataclass(frozen=True)
class Entity:
    table: str
    columns: list[Column]
    primary_key: list[str]


def parse_entity(source_root: Path, file_name: str) -> Entity:
    """The table shape Room would generate from one entity data class."""
    source = strip_comments((source_root / "core/data/local" / file_name).read_text(encoding="utf-8"))

    entity_call = re.search(r"@Entity\s*\(", source)
    if not entity_call:
        raise ToolError(f"{file_name}: no @Entity")
    args = source[entity_call.end() : balanced(source, entity_call.end() - 1)]

    table_match = re.search(r'tableName\s*=\s*"([^"]*)"', args)
    if not table_match:
        raise ToolError(f"{file_name}: no tableName")
    table = table_match.group(1)

    keys_match = re.search(r"primaryKeys\s*=\s*\[([^\]]*)]", args)
    if keys_match:
        primary_key = re.findall(r'"([^"]*)"', keys_match.group(1))
    else:
        inline = re.search(r"@PrimaryKey\s+val\s+(\w+)", source)
        if not inline:
            raise ToolError(f"{file_name}: no primary key declared")
        primary_key = [inline.group(1)]

    # The primary-constructor properties, in declaration order.
    class_body = source.index("(", source.index("class "))
    constructor = source[class_body + 1 : balanced(source, class_body)]

    columns = []
    for raw in top_level_split(constructor):
        # A property may carry its own annotations — `@PrimaryKey val id: String`
        # is exactly the shape that must not be skipped, since the primary key is
        # a real column like any other.
        declaration = re.sub(r"^(?:@\w+(?:\([^)]*\))?\s*)+", "", raw).strip()
        if not re.match(r"val\s+", declaration):
            continue
        match = re.match(r"val\s+(\w+)\s*:\s*([\w<>.?]+)", declaration)
        if not match:
            raise ToolError(f"{file_name}: cannot read property '{declaration}'")
        name, kotlin_type = match.group(1), match.group(2)
        nullable = kotlin_type.endswith("?")
        base = kotlin_type.rstrip("?")
        if base not in AFFINITY:
            raise ToolError(f"{file_name}.{name}: unmapped type '{kotlin_type}'")
        columns.append(Column(name, AFFINITY[base], not nullable))

    if not columns:
        raise ToolError(f"{file_name}: no columns parsed")
    return Entity(table=table, columns=columns, primary_key=primary_key)


def column_list(sql_columns: str) -> list[Column]:
    """Parse a `\\`a\\` TEXT NOT NULL, \\`b\\` INTEGER` fragment into Columns."""
    columns = []
    for part in top_level_split(sql_columns):
        match = re.match(r"`(\w+)`\s+(\w+)(\s+NOT\s+NULL)?", part.strip(), re.IGNORECASE)
        if not match:
            raise ToolError(f"cannot parse column definition '{part}'")
        columns.append(Column(match.group(1), match.group(2).upper(), bool(match.group(3))))
    return columns


# ── Applying the migration ──────────────────────────────────────────────────


def apply_rebuild(conn: sqlite3.Connection, rebuild: Rebuild, sentinel: str) -> None:
    """Exactly what rebuildScopedTable() does, on a real database."""
    staging = f"{rebuild.table}__v6"
    conn.execute(f"CREATE TABLE `{staging}` ({rebuild.new_columns}, {rebuild.primary_key})")
    conn.execute(
        f"INSERT INTO `{staging}` (`ownerSubject`, {rebuild.carried_columns}) "
        f"SELECT '{sentinel}', {rebuild.carried_columns} FROM `{rebuild.table}`"
    )
    conn.execute(f"DROP TABLE `{rebuild.table}`")
    conn.execute(f"ALTER TABLE `{staging}` RENAME TO `{rebuild.table}`")


# ── Reporting ───────────────────────────────────────────────────────────────


@dataclass
class Report:
    lines: list[str]
    problems: list[str]

    def say(self, text: str = "") -> None:
        self.lines.append(text)
        print(text)

    def check(self, ok: bool, description: str) -> None:
        self.say(f"  {'ok  ' if ok else 'FAIL'}  {description}")
        if not ok:
            self.problems.append(description)


def table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'android_%' ORDER BY name"
        )
    ]


def row_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM `{table}`").fetchone()[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--keep-temp", action="store_true", help="leave the migrated copy on disk")
    args = parser.parse_args()

    report = Report(lines=[], problems=[])

    try:
        rebuilds = parse_migration(args.source_root)
        sentinel = parse_sentinel(args.source_root)
        entities = [
            parse_entity(args.source_root, name)
            for name in (
                "RunSessionEntity.kt",
                "CapturedHexEntity.kt",
                "DailyQuestEntity.kt",
                "AchievementEntity.kt",
                "ActiveRunEntity.kt",
                "UserProfileEntity.kt",
            )
        ]
    except (ToolError, FileNotFoundError) as error:
        print(f"tool error: {error}", file=sys.stderr)
        return 2

    source_db = args.backup_dir / DB_NAME
    if not source_db.is_file():
        print(f"tool error: no database at {source_db}", file=sys.stderr)
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="fitquest-migration-verify-"))
    conn = None
    try:
        # Copy the whole WAL set: committed pages can live in -wal, so a bare
        # .db copy reports row counts that are silently out of date.
        for suffix in ("", "-wal", "-shm"):
            sibling = source_db.with_name(source_db.name + suffix)
            if sibling.is_file():
                shutil.copy2(sibling, workdir / sibling.name)
        target = workdir / DB_NAME

        report.say(f"source      : {source_db} (read-only; copied to {workdir})")
        report.say(f"sentinel    : {sentinel!r}")
        report.say(f"tables      : {', '.join(r.table for r in rebuilds)}")
        report.say()

        # Opened explicitly rather than via `with`: sqlite3's context manager
        # commits but does NOT close, and on Windows an open handle keeps the
        # copied database — which is a copy of the user's real data — locked
        # against the cleanup below.
        conn = sqlite3.connect(target)
        try:
            version_before = conn.execute("PRAGMA user_version").fetchone()[0]
            before = {table: row_count(conn, table) for table in table_names(conn)}

            report.say(f"BEFORE  user_version={version_before}")
            for table, count in sorted(before.items()):
                report.say(f"  {table:<20} {count:>5} rows")
            report.say()

            if version_before != 5:
                report.say(f"note: expected a v5 database, found v{version_before}. Continuing.")

            # Room wraps a migration in a transaction and stamps the version
            # itself once every statement has succeeded.
            with conn:
                for rebuild in rebuilds:
                    apply_rebuild(conn, rebuild, sentinel)
                conn.execute(f"PRAGMA user_version = {TARGET_VERSION}")

            version_after = conn.execute("PRAGMA user_version").fetchone()[0]
            after = {table: row_count(conn, table) for table in table_names(conn)}

            report.say(f"AFTER   user_version={version_after}")
            for table, count in sorted(after.items()):
                report.say(f"  {table:<20} {count:>5} rows")
            report.say()

            report.say("CHECKS")
            report.check(version_after == TARGET_VERSION, f"user_version is {TARGET_VERSION}")

            report.check(
                not [t for t in after if t.endswith("__v6")],
                "no staging table was left behind",
            )

            # 1. Every row survives.
            for table in sorted(set(before) | set(after)):
                if table not in after:
                    report.check(False, f"{table}: table is gone")
                elif table in before:
                    report.check(
                        before[table] == after[table],
                        f"{table}: {before[table]} rows in, {after[table]} rows out",
                    )

            # 2. Every row is quarantined, and only quarantined.
            total_rows = 0
            for rebuild in rebuilds:
                total = after.get(rebuild.table, 0)
                total_rows += total
                if total == 0:
                    continue
                owned = conn.execute(
                    f"SELECT COUNT(*) FROM `{rebuild.table}` WHERE `ownerSubject` = ?",
                    (sentinel,),
                ).fetchone()[0]
                report.check(
                    owned == total,
                    f"{rebuild.table}: all {total} rows carry the sentinel ({owned} do)",
                )

            # 3. No query for a real account can see a quarantined row.
            for rebuild in rebuilds:
                visible = conn.execute(
                    f"SELECT COUNT(*) FROM `{rebuild.table}` WHERE `ownerSubject` <> ?",
                    (sentinel,),
                ).fetchone()[0]
                report.check(
                    visible == 0,
                    f"{rebuild.table}: no row is visible to a real account ({visible} would be)",
                )

            # 4. The rebuilt shape is what the entities declare. This is the
            #    check that catches a column typo or a wrong affinity, which
            #    would otherwise surface as an IllegalStateException on the
            #    first launch against the user's migrated database.
            by_table = {entity.table: entity for entity in entities}
            for rebuild in rebuilds:
                entity = by_table.get(rebuild.table)
                if entity is None:
                    report.check(False, f"{rebuild.table}: no entity declares this table")
                    continue

                actual = column_list(rebuild.new_columns)
                expected = entity.columns
                if actual == expected:
                    report.check(True, f"{rebuild.table}: {len(actual)} columns match the entity")
                else:
                    report.check(False, f"{rebuild.table}: columns differ from the entity")
                    for column in expected:
                        if column not in actual:
                            report.say(f"        missing or wrong: {column}")
                    for column in actual:
                        if column not in expected:
                            report.say(f"        unexpected:       {column}")
                    if [c.name for c in actual] != [c.name for c in expected]:
                        report.say(f"        order: migration={[c.name for c in actual]}")
                        report.say(f"        order: entity   ={[c.name for c in expected]}")

                # 5. The primary key Room will read back must match the entity.
                keys = re.findall(r"`(\w+)`", rebuild.primary_key)
                report.check(
                    keys == entity.primary_key,
                    f"{rebuild.table}: primary key {keys} matches @Entity {entity.primary_key}",
                )

            # 6. What SQLite actually ended up with, not just what was asked for.
            for rebuild in rebuilds:
                info = conn.execute(f"PRAGMA table_info(`{rebuild.table}`)").fetchall()
                names = [row[1] for row in info]
                entity = by_table[rebuild.table]
                report.check(
                    names == [c.name for c in entity.columns],
                    f"{rebuild.table}: live schema has the expected columns in order",
                )
                pk = [row[1] for row in sorted((r for r in info if r[5]), key=lambda r: r[5])]
                report.check(
                    pk == entity.primary_key,
                    f"{rebuild.table}: live primary key {pk} matches @Entity {entity.primary_key}",
                )
                with_default = [row[1] for row in info if row[4] is not None]
                report.check(
                    not with_default,
                    f"{rebuild.table}: no DB-level DEFAULT (would break Room's validation): {with_default}",
                )

            # 7. Room also matches indices; the entities declare none, so the
            #    migration must not have created one either.
            for rebuild in rebuilds:
                indices = conn.execute(f"PRAGMA index_list(`{rebuild.table}`)").fetchall()
                auto = [row[1] for row in indices if row[3] == "pk"]
                custom = [row[1] for row in indices if row[3] != "pk"]
                report.check(
                    not custom,
                    f"{rebuild.table}: no indices beyond the primary key (found {len(auto)} pk, {custom})",
                )

            report.say()
            report.say(f"rows preserved across the migration: {total_rows}")
        finally:
            # Closed before the cleanup below. On Windows an open handle keeps
            # the copied database — a copy of the user's real data — locked
            # against deletion, and rmtree would then fail silently and leave it
            # behind.
            conn.close()

        report.say()
        if report.problems:
            report.say(f"VERIFICATION FAILED - {len(report.problems)} problem(s):")
            for problem in report.problems:
                report.say(f"  - {problem}")
            return 1

        report.say("VERIFICATION PASSED - migration 5->6 applies cleanly and preserves every row.")
        return 0

    except sqlite3.Error as error:
        print(f"sqlite error while applying the migration: {error}", file=sys.stderr)
        return 1
    finally:
        if args.keep_temp:
            print(f"\nmigrated copy kept at: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
            if workdir.exists():
                # Loudly, because what is left behind is a copy of a real user's
                # database rather than a scratch file.
                print(
                    f"WARNING: could not remove the migrated copy at {workdir}. "
                    "It contains a copy of the real database — delete it manually.",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    sys.exit(main())
