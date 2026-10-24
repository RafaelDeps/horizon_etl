"""SQLite connection settings and final-file step (spec 018).

Every test registers the listener on the SQLAlchemy ``Engine`` class, which is
process-wide, so the ``listener`` fixture removes it afterwards and the other
test files keep the default journal mode.
"""

import os
import shutil
import sqlite3
from unittest.mock import MagicMock

import pytest
from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from src.adapters.database import sqlite_settings
from src.adapters.database.sqlite_settings import (
    finalize_sqlite_database,
    install_sqlite_connection_settings,
)


def _remove_listener():
    if event.contains(Engine, "connect", sqlite_settings._apply_sqlite_settings):
        event.remove(Engine, "connect", sqlite_settings._apply_sqlite_settings)
    sqlite_settings._installed = False


@pytest.fixture
def listener():
    _remove_listener()
    yield
    _remove_listener()


def _pragmas(engine):
    with engine.connect() as conn:
        return (
            conn.execute(text("PRAGMA journal_mode")).scalar(),
            conn.execute(text("PRAGMA synchronous")).scalar(),
        )


def _wal_database(path, rows=3):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    con.commit()
    return con


# --- connection settings -----------------------------------------------------


def test_new_file_engine_gets_wal_and_normal(listener, tmp_path):
    install_sqlite_connection_settings()
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")

    assert _pragmas(engine) == ("wal", 1)
    engine.dispose()


def test_engine_created_before_install_gets_the_settings(listener, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'early.db'}")
    install_sqlite_connection_settings()

    assert _pragmas(engine) == ("wal", 1)
    engine.dispose()


def test_in_memory_database_stays_in_memory_mode(listener):
    install_sqlite_connection_settings()
    engine = create_engine("sqlite://")

    journal_mode, _ = _pragmas(engine)

    assert journal_mode == "memory"


def test_non_sqlite_connection_is_left_untouched(listener):
    dbapi_connection = MagicMock()

    sqlite_settings._apply_sqlite_settings(dbapi_connection, None)

    dbapi_connection.cursor.assert_not_called()


def test_install_twice_registers_once(listener, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sqlite_settings, "_apply_pragmas", calls.append)

    install_sqlite_connection_settings()
    install_sqlite_connection_settings()
    engine = create_engine(f"sqlite:///{tmp_path / 'b.db'}")
    with engine.connect():
        pass
    engine.dispose()

    assert len(calls) == 1


class _FailingCursorConnection(sqlite3.Connection):
    def cursor(self, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")


def test_failing_pragma_logs_warning_and_does_not_raise(listener):
    messages = []
    sink = logger.add(messages.append, level="WARNING")
    dbapi_connection = sqlite3.connect(":memory:", factory=_FailingCursorConnection)
    try:
        sqlite_settings._apply_sqlite_settings(dbapi_connection, None)
    finally:
        logger.remove(sink)
        dbapi_connection.close()

    assert any("disk I/O error" in str(m) for m in messages)


# --- final file ---------------------------------------------------------------


def test_finalize_makes_the_file_self_contained(tmp_path):
    db = tmp_path / "horizon.db"
    _wal_database(db).close()

    result = finalize_sqlite_database(f"sqlite:///{db}")

    assert result["finalized"] is True
    assert result["journal_mode"] == "delete"
    assert sorted(os.listdir(tmp_path)) == ["horizon.db"]

    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copy(db, lone / "horizon.db")
    os.chmod(lone, 0o555)
    try:
        ro = sqlite3.connect(f"file:{lone / 'horizon.db'}?mode=ro", uri=True)
        assert ro.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
        ro.close()
    finally:
        os.chmod(lone, 0o755)


def test_finalize_with_an_open_connection_reports_and_does_not_raise(tmp_path):
    db = tmp_path / "horizon.db"
    still_open = _wal_database(db)
    try:
        result = finalize_sqlite_database(f"sqlite:///{db}")
    finally:
        still_open.close()

    assert result["finalized"] is False
    assert "skipped" not in result
    assert "locked" in result["reason"]


@pytest.mark.parametrize(
    "url",
    [None, "postgresql://user:password@localhost:5432/db", "sqlite://"],
)
def test_finalize_is_a_no_op_without_a_sqlite_file(url):
    result = finalize_sqlite_database(url)

    assert result["finalized"] is False
    assert result["skipped"] is True


def test_finalize_is_a_no_op_when_the_file_does_not_exist(tmp_path):
    result = finalize_sqlite_database(f"sqlite:///{tmp_path / 'missing.db'}")

    assert result["finalized"] is False
    assert result["skipped"] is True
    assert not (tmp_path / "missing.db").exists()
