"""Weekly phase ``linkedin_links`` (spec 037).

Stores the LinkedIn profile link of the persons named in the maintainer's
local list. Runs after ``consolidate_duplicates``, so the names are compared
with the merged persons, and before ``export_canonical``, which publishes the
link as ``linkedin_url``.

The list is local and never versioned. It is only read: this phase never
creates or changes it, and reads nothing outside this repository. Without the
list (GitHub Actions) the phase does nothing.
"""

import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from prefect import flow, get_run_logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

load_dotenv()

from src.adapters.database.horizon_id_store import sqlite_path_from_url  # noqa: E402
from src.adapters.database.linkedin_link_store import LinkedinLinkStore  # noqa: E402
from src.core.logic.atomic_io import atomic_write_json  # noqa: E402
from src.core.logic.linkedin_links import (  # noqa: E402
    CONFLICT,
    INVALID,
    NOT_FOUND,
    SEVERAL_PERSONS,
    STORED,
    parse_list,
    plan,
)
from src.db.migrations import run_migrations  # noqa: E402
from src.notifications.telegram import telegram_flow_state_handlers  # noqa: E402

LIST_PATH = "data/linkedin_run/linkedin.list"
REPORT_PATH = "data/reports/linkedin_links_report.json"


def _run_migrations(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            run_migrations(session)
    finally:
        engine.dispose()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync_linkedin_links(
    list_path: str = LIST_PATH,
    database_url: Optional[str] = None,
    report_path: str = REPORT_PATH,
) -> dict:
    """Makes the stored links equal to the usable lines of the list and
    returns the counts of the run."""
    database_url = database_url or os.getenv("DATABASE_URL", "sqlite:///db/horizon.db")
    _run_migrations(database_url)
    store = LinkedinLinkStore(sqlite_path_from_url(database_url))

    if not os.path.isfile(list_path):
        # GitHub Actions, or a machine without the list: stored links stay.
        result = {
            "list_path": list_path,
            "list_found": False,
            "empty_list": False,
            "lines": 0,
            "stored": 0,
            "added": 0,
            "changed": 0,
            "removed": 0,
            "not_found": 0,
            "several_persons": 0,
            "conflicts": 0,
            "invalid": 0,
            "unused": [],
        }
        _write_report(report_path, result)
        return result

    with open(list_path, encoding="utf-8") as handle:
        lines = parse_list(handle)
    planned = plan(lines, store.persons(), store.stored())
    added, changed, removed = store.apply(
        planned.add, planned.change, planned.remove, _now()
    )

    def count(outcome: str) -> int:
        return sum(1 for o in planned.outcomes if o.outcome == outcome)

    result = {
        "list_path": list_path,
        "list_found": True,
        # No usable line: the plan changed nothing (see plan()).
        "empty_list": count(STORED) == 0,
        "lines": len(lines),
        "stored": count(STORED),
        "added": added,
        "changed": changed,
        "removed": removed,
        "not_found": count(NOT_FOUND),
        "several_persons": count(SEVERAL_PERSONS),
        "conflicts": count(CONFLICT),
        "invalid": count(INVALID),
        "unused": [
            {"line": o.number, "name": o.name, "reason": o.outcome}
            for o in planned.outcomes
            if o.outcome != STORED
        ],
    }
    _write_report(report_path, result)
    return result


def _write_report(report_path: str, result: dict) -> None:
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    atomic_write_json(report_path, result, indent=2)


def format_summary(result: dict) -> list:
    """The lines logged at the end of the phase: the counts, then each line
    of the list that was not used, with the name and the reason. A link is
    never printed."""
    if not result["list_found"]:
        return [
            "linkedin links: no list at {list_path}, nothing changed".format(**result)
        ]
    if result["empty_list"]:
        lines = [
            "linkedin links: the list has no usable line, nothing changed "
            "(lines {lines}, not found {not_found}, several persons "
            "{several_persons}, conflicts {conflicts}, invalid {invalid})".format(
                **result
            )
        ]
    else:
        lines = [_counts_line(result)]
    lines.extend(
        "line {line}: {name}: {reason}".format(
            line=entry["line"],
            name=entry["name"],
            reason=entry["reason"].replace("_", " "),
        )
        for entry in result["unused"]
    )
    return lines


def _counts_line(result: dict) -> str:
    return (
        "linkedin links: lines {lines}, stored {stored} "
        "(added {added}, changed {changed}, removed {removed}), "
        "not found {not_found}, several persons {several_persons}, "
        "conflicts {conflicts}, invalid {invalid}".format(**result)
    )


@flow(name="Sync LinkedIn Links", **telegram_flow_state_handlers())
def linkedin_links_flow(
    list_path: str = LIST_PATH,
    database_url: Optional[str] = None,
    report_path: str = REPORT_PATH,
) -> dict:
    logger = get_run_logger()
    result = sync_linkedin_links(list_path, database_url, report_path)
    summary = format_summary(result)
    # A list with nothing usable is worth a warning: it is likely a mistake.
    (logger.warning if result["empty_list"] else logger.info)(summary[0])
    for line in summary[1:]:
        logger.info(line)
    return result
