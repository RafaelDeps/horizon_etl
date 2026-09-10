"""Audit how many people the export can attribute a campus to, and from what.

Read-only operational script (constitution Principle III: scripts may inspect
the database, never ingest or export). It answers three questions the feature's
success criteria depend on:

- how much of the population still exports with no campus (SC-001);
- how that coverage splits between direct evidence and supervisor inference;
- whether anyone who had a campus in a previous export has lost it (SC-004).

Usage::

    python -m src.scripts.audit_campus_coverage
    python -m src.scripts.audit_campus_coverage --previous data/exports/researchers_canonical.json
"""

import argparse
import json
import os
import sqlite3
import sys
from typing import Any, Optional

from loguru import logger

sys.path.append(os.getcwd())

from src.core.logic.export_campus_resolver import ExportCampusResolver  # noqa: E402

DEFAULT_DB_PATH = "db/horizon.db"


class _SqliteCampusController:
    """Minimal campus controller so the audit does not need the ORM stack."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def get_all(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT id, name FROM organizational_units ORDER BY id"
        ).fetchall()
        return [{"id": row[0], "name": row[1]} for row in rows]


class _SqliteSession:
    """Adapts a sqlite3 connection to the tiny surface the resolver uses."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def execute(self, statement: Any) -> Any:
        return self._connection.execute(str(statement))


def collect_coverage(db_path: str = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Resolve every person's campus and report where the answer came from."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        resolver = ExportCampusResolver(
            _SqliteSession(connection), _SqliteCampusController(connection)
        )
        resolver._ensure_loaded()

        person_ids = [
            row[0] for row in connection.execute("SELECT id FROM persons").fetchall()
        ]

        direct = 0
        inferred = 0
        by_campus: dict[str, int] = {}
        for person_id in person_ids:
            key = ("researcher", person_id)
            campus = resolver._primary_by_entity.get(key)
            if campus:
                direct += 1
            else:
                campus = resolver._inferred_by_entity.get(key)
                if campus:
                    inferred += 1
            if campus:
                by_campus[campus["name"]] = by_campus.get(campus["name"], 0) + 1

        total = len(person_ids)
        without = total - direct - inferred
        return {
            "persons": total,
            "direct": direct,
            "inferred": inferred,
            "without_campus": without,
            "without_campus_share": (without / total) if total else 0.0,
            "campuses": len(resolver._campus_by_id),
            "by_campus": dict(sorted(by_campus.items(), key=lambda kv: -kv[1])),
        }
    finally:
        connection.close()


def find_regressions(db_path: str, previous_export_path: str) -> list[dict[str, Any]]:
    """List people who had a campus in a previous export and would lose it.

    This is SC-004 in executable form: the feature may add campuses, never take
    one away.
    """
    with open(previous_export_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = payload if isinstance(payload, list) else payload.get("data", payload)

    previous: dict[int, str] = {}
    for row in rows:
        campus = row.get("campus")
        person_id = row.get("id")
        if campus and person_id is not None:
            name = campus.get("name") if isinstance(campus, dict) else campus
            if name:
                previous[int(person_id)] = name

    connection = sqlite3.connect(db_path)
    # O resolver converte cada linha com dict(row); sem o row_factory isso
    # falha em silêncio e toda evidência some — fazendo parecer que todo mundo
    # perdeu o campus.
    connection.row_factory = sqlite3.Row
    try:
        resolver = ExportCampusResolver(
            _SqliteSession(connection), _SqliteCampusController(connection)
        )
        resolver._ensure_loaded()

        regressions = []
        for person_id, previous_name in previous.items():
            key = ("researcher", person_id)
            current = resolver._primary_by_entity.get(
                key
            ) or resolver._inferred_by_entity.get(key)
            if current is None:
                regressions.append(
                    {"person_id": person_id, "was": previous_name, "now": None}
                )
        return regressions
    finally:
        connection.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument(
        "--previous",
        default=None,
        help="Previous researchers_canonical.json to check for lost campuses",
    )
    args = parser.parse_args(argv)

    coverage = collect_coverage(args.db)
    logger.info(
        f"Persons: {coverage['persons']} | direct: {coverage['direct']} | "
        f"supervisor-inferred: {coverage['inferred']} | "
        f"without campus: {coverage['without_campus']} "
        f"({coverage['without_campus_share']:.1%})"
    )
    logger.info(f"Campuses known: {coverage['campuses']}")
    for name, count in list(coverage["by_campus"].items())[:10]:
        logger.info(f"  {name}: {count}")

    if args.previous:
        regressions = find_regressions(args.db, args.previous)
        if regressions:
            logger.error(
                f"{len(regressions)} people lost a campus they previously had "
                "— SC-004 violated"
            )
            for entry in regressions[:20]:
                logger.error(f"  person {entry['person_id']} was {entry['was']}")
            return 1
        logger.info("No person lost a campus (SC-004 holds)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
