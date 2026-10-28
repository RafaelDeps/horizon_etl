"""Weekly phase ``assign_horizon_ids`` (spec 020).

Gives every entity its permanent ``horizon_id`` after ``consolidate_duplicates``
and before ``export_canonical``, so the ids are computed on the final,
consolidated state and the export can publish them.
"""

import json
import os
import subprocess
import sys
from typing import Optional

from dotenv import load_dotenv
from prefect import flow, get_run_logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

load_dotenv()

from src.adapters.database.horizon_id_store import (  # noqa: E402
    SqliteHorizonIdStore,
    sqlite_path_from_url,
)
from src.core.logic.horizon_id_assigner import HorizonIdAssigner  # noqa: E402
from src.core.logic.horizon_identity import HORIZON_RULE_VERSION  # noqa: E402
from src.db.migrations import run_migrations  # noqa: E402
from src.notifications.telegram import telegram_flow_state_handlers  # noqa: E402

DEFAULT_REPORT_DIR = "data/reports"
REPORT_NAME = "horizon_ids_report.json"


def _run_migrations(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            run_migrations(session)
    finally:
        engine.dispose()


def rule_version_requires_reset(db_path: str) -> bool:
    """FR-024: a database built under other key/hash/id rules is rebuilt once.

    False when there is no database or it is still empty (it is created fresh
    anyway); True when it has ingested rows and its recorded rule version is
    missing or differs from ``HORIZON_RULE_VERSION``.
    """
    if not os.path.exists(db_path):
        return False
    store = SqliteHorizonIdStore(db_path, snapshot_path="", zip_path="")
    if not store.has_entities():
        return False
    return store.get_meta("rule_version") != str(HORIZON_RULE_VERSION)


def reset_database(database_url: str) -> None:
    """The steps of ``make db-reset``: save the id history, delete the
    database files, create the schema again."""
    from src.scripts.save_horizon_id_history import save_history

    db_path = sqlite_path_from_url(database_url)
    save_history(database_url, "db/horizon_id_history.json")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db_path + suffix):
            os.remove(db_path + suffix)
    subprocess.run([sys.executable, "db/create_db.py"], check=True)


@flow(name="Assign Horizon Ids", **telegram_flow_state_handlers())
def assign_horizon_ids_flow(
    database_url: Optional[str] = None, report_dir: str = DEFAULT_REPORT_DIR
) -> dict:
    logger = get_run_logger()
    database_url = database_url or os.getenv("DATABASE_URL", "sqlite:///db/horizon.db")
    _run_migrations(database_url)

    store = SqliteHorizonIdStore(sqlite_path_from_url(database_url))
    report = HorizonIdAssigner(store).assign()

    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, REPORT_NAME)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    logger.info(
        "Horizon ids assigned: {} entities, {} collision groups (report: {})".format(
            report["entities"], report["collision_groups"], report_path
        )
    )
    return report
