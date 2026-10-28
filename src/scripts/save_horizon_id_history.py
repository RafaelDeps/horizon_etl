"""Saves the id history before ``make db-reset`` deletes the database (spec 020).

Writes ``db/horizon_id_history.json`` (data-model.md, "Id history snapshot")
from the database's ``horizon_ids``, candidates, aliases and merge log, so the
next ``assign_horizon_ids`` turns the old ids into aliases even after a reset
(research R5). Only reads the database. Never blocks the reset: nothing to save
or a failed write logs and exits 0.

Usage: PYTHONPATH=. python src/scripts/save_horizon_id_history.py
"""

import os
import sys

from dotenv import load_dotenv
from loguru import logger

from src.adapters.database.horizon_id_store import (
    DEFAULT_SNAPSHOT_PATH,
    SqliteHorizonIdStore,
    sqlite_path_from_url,
)
from src.core.logic.atomic_io import atomic_write_json


def save_history(database_url: str, snapshot_path: str) -> bool:
    """Writes the snapshot. Returns False when there was nothing to save or
    the write failed (logged); never raises."""
    try:
        store = SqliteHorizonIdStore(sqlite_path_from_url(database_url))
        snapshot = store.history_snapshot()
        if snapshot is None:
            logger.info("No horizon ids in {}; no id history saved", database_url)
            return False
        atomic_write_json(snapshot_path, snapshot, indent=2)
    except Exception as exc:  # the reset must go on
        logger.warning("Could not save the id history to {}: {}", snapshot_path, exc)
        return False
    logger.info(
        "Saved {} ids and {} aliases to {}",
        len(snapshot["ids"]),
        len(snapshot["aliases"]),
        snapshot_path,
    )
    return True


def main() -> int:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "sqlite:///db/horizon.db")
    save_history(database_url, DEFAULT_SNAPSHOT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
