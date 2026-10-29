"""SQLite connection settings for the ETL database (spec 018, TD-018).

libbase's ``SqlRepository.add()`` commits after every record, so a Lattes phase
issues ~180 000 commits for 435 curricula. In SQLite's default rollback-journal
mode each commit forces the disk (~3.6 ms on NVMe): 63% of ``lattes_projects``.
In write-ahead-log mode with ``synchronous=NORMAL`` a commit only appends to
``horizon.db-wal`` and the disk is forced at checkpoints. Same snapshot, same
disk: both Lattes phases went from 46.2 to 23.3 min with identical data.

The trade-off is that a power loss can roll back the last transactions; it
cannot corrupt the database. Since spec 021 the database persists between
runs and each source document is committed in one transaction, so a lost
transaction is a whole document that has no processing state yet: the next
run processes it again.

The libraries create every engine (no ``create_engine`` in this repository), so
the settings are applied by a listener on the SQLAlchemy ``Engine`` class, which
reaches engines created before and after it is installed.

Savepoints (spec 021, research R5) are the exception: they need pysqlite's own
``BEGIN``/``COMMIT`` handling turned off, and that is done per engine, only for
the dedicated engine of the one-transaction-per-document connection. Turned on
for every engine, every read would open a snapshot transaction, and a later
write from that connection could fail with ``database is locked`` when another
connection wrote in between.
"""

import os
import sqlite3
from typing import Optional

from loguru import logger
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url

_PRAGMAS = ("PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL")
_installed = False


def _apply_pragmas(dbapi_connection: sqlite3.Connection) -> None:
    cursor = dbapi_connection.cursor()
    try:
        for pragma in _PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def _apply_sqlite_settings(dbapi_connection, connection_record) -> None:
    """SQLAlchemy ``connect`` listener; a no-op for non-SQLite drivers.

    An in-memory database answers ``memory`` to the journal pragma and keeps
    working. A failing pragma only costs speed, so the connection is still
    handed out.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    try:
        _apply_pragmas(dbapi_connection)
    except sqlite3.Error as exc:
        logger.warning("SQLite connection settings not applied: {}", exc)


def install_sqlite_connection_settings() -> None:
    """Applies WAL + synchronous=NORMAL to every SQLite connection opened from
    now on in this process, including those of engines created earlier."""
    global _installed
    if _installed:
        return
    event.listen(Engine, "connect", _apply_sqlite_settings)
    _installed = True


def _disable_pysqlite_transactions(dbapi_connection, connection_record) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.isolation_level = None


def _emit_begin(connection) -> None:
    connection.exec_driver_sql("BEGIN")


def install_savepoint_support(engine: Engine) -> None:
    """Lets SAVEPOINT work on this SQLite engine (SQLAlchemy's documented pysqlite
    recipe): the driver stops issuing its own BEGIN/COMMIT, and SQLAlchemy emits
    BEGIN when a transaction starts. Other engines are not touched."""
    if engine.dialect.name != "sqlite":
        return
    event.listen(engine, "connect", _disable_pysqlite_transactions)
    event.listen(engine, "begin", _emit_begin)


def finalize_sqlite_database(database_url: Optional[str]) -> dict:
    """Moves the write-ahead log into the main file and returns it to the
    rollback journal, so ``db/horizon.db`` is complete on its own.

    Run it only when no other connection is open: switching the journal mode
    fails with ``database is locked`` otherwise, even if that connection is
    idle in a pool. Never raises; the outcome is in the returned dict, where
    ``skipped`` marks the cases with nothing to finalize (no URL, another
    database, in-memory, missing file), as opposed to a failure.
    """
    if not database_url:
        return {"finalized": False, "reason": "no DATABASE_URL", "skipped": True}
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return {"finalized": False, "reason": "not a SQLite database", "skipped": True}
    path = url.database
    if not path or path == ":memory:":
        return {"finalized": False, "reason": "in-memory database", "skipped": True}
    if not os.path.exists(path):
        return {"finalized": False, "reason": f"{path} does not exist", "skipped": True}

    con = None
    try:
        con = sqlite3.connect(path)
        checkpoint = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        journal_mode = con.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
    except sqlite3.Error as exc:
        logger.error("SQLite finalize failed for {}: {}", path, exc)
        return {"finalized": False, "reason": str(exc)}
    finally:
        if con is not None:
            con.close()

    logger.info(
        "SQLite database {} checkpointed {}, journal_mode={}",
        path,
        checkpoint,
        journal_mode,
    )
    return {
        "finalized": True,
        "checkpoint": tuple(checkpoint),
        "journal_mode": journal_mode,
    }
