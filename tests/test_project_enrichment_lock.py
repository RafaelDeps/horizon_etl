"""A failed row must not keep the SQLite write lock (spec 019).

ProjectEnrichmentLoader writes each row inside a SAVEPOINT, and the tracking
recorder writes through other sessions. When a row fails, ROLLBACK TO SAVEPOINT
undoes it but leaves the SQLite transaction -- and its write lock -- open, so
the next tracking write waits and fails with "database is locked". That only
shows with a database FILE and two connections, which the in-memory tests in
tests/test_project_enrichment_db.py cannot reproduce.
"""

import sqlite3
from types import SimpleNamespace

import pytest
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.core.logic.project_enrichment import ProjectEnrichmentLoader


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "lock.db"


@pytest.fixture
def engine(db_path):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 0.5})
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE initiatives (id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
        )
        conn.execute(
            text("CREATE TABLE source_records (id INTEGER PRIMARY KEY, x TEXT)")
        )
        conn.execute(text("INSERT INTO initiatives (name) VALUES ('dup')"))
    yield engine
    engine.dispose()


@pytest.fixture
def session_a(engine):
    session = Session(engine)
    # Mid-transaction like run(): the index loads autobegin before any write.
    session.execute(text("SELECT COUNT(*) FROM initiatives"))
    yield session
    session.close()


@pytest.fixture
def loader(session_a):
    instance = ProjectEnrichmentLoader.__new__(ProjectEnrichmentLoader)
    instance.overwrite = False
    instance.dry_run = False
    instance.controller = SimpleNamespace(
        _service=SimpleNamespace(_repository=SimpleNamespace(_session=session_a))
    )
    return instance


def _insert(session, name):
    return lambda: session.execute(
        text("INSERT INTO initiatives (name) VALUES (:n)"), {"n": name}
    )


def _in_transaction(session):
    return session.connection().connection.dbapi_connection.in_transaction


def test_failed_row_releases_the_lock(loader, session_a, engine):
    assert loader._write_row(_insert(session_a, "dup")) is False
    assert _in_transaction(session_a) is False

    with Session(engine) as session_b:
        session_b.execute(text("INSERT INTO source_records (x) VALUES ('tracking')"))
        session_b.commit()


def test_rows_written_before_a_failure_are_kept(loader, session_a, db_path):
    assert loader._write_row(_insert(session_a, "a")) is True
    assert loader._write_row(_insert(session_a, "dup")) is False

    con = sqlite3.connect(db_path)
    try:
        names = {row[0] for row in con.execute("SELECT name FROM initiatives")}
    finally:
        con.close()
    assert names == {"a", "dup"}


def test_failed_release_does_not_raise(loader, session_a, monkeypatch):
    def failing_commit():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(session_a, "commit", failing_commit)
    messages = []
    sink = logger.add(messages.append, level="WARNING")
    try:
        assert loader._write_row(_insert(session_a, "dup")) is False
    finally:
        logger.remove(sink)

    assert any("disk I/O error" in str(m) for m in messages)
