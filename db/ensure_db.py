"""Create the local database only when it does not exist (spec 021).

The database persists between runs: ``make weekly-flows`` keeps it and
processes only the source documents that changed. On a fresh machine or CI
runner there is no file yet, and this creates it exactly as ``make db-init``
does. On an existing file it only applies the pending ETL migrations, so a
database kept from an older version of the ETL gets the new tables; it never
drops anything. A full rebuild stays ``make db-reset`` (or ``make
full-refresh``), and the weekly rebuilds once on its own when the database
was built under other rules (``HORIZON_RULE_VERSION``).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DEFAULT_URL = "sqlite:///db/horizon.db"


def ensure_database(database_url: str) -> str:
    """``created`` or ``migrated``: what was done to the database."""
    from src.adapters.database.horizon_id_store import sqlite_path_from_url

    path = sqlite_path_from_url(database_url)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        from src.flows.maintenance.horizon_ids import _run_migrations

        _run_migrations(database_url)
        return "migrated"

    from db.create_db import run_demo

    run_demo()
    return "created"


def main() -> None:
    database_url = os.getenv("DATABASE_URL", DEFAULT_URL)
    os.environ["DATABASE_URL"] = database_url
    done = ensure_database(database_url)
    if done == "created":
        print(f"Database created: {database_url}")
    else:
        print(f"Database kept, pending migrations applied: {database_url}")


if __name__ == "__main__":
    main()
