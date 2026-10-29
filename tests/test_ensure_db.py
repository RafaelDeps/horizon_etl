"""Spec 021, US5: the database persists by default. ``db/ensure_db.py``
creates it only when it is missing, and a database built under other rules is
rebuilt once (FR-013 to FR-015; the id history kept by the rebuild is
covered by tests/test_horizon_ids_flow.py)."""

import os
import sqlite3
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env(db):
    env = dict(os.environ)
    env.update(DATABASE_URL=f"sqlite:///{db}", STORAGE_TYPE="db", PYTHONPATH=REPO)
    return env


def _ensure(tmp_path, db):
    result = subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "ensure_db.py")],
        cwd=tmp_path,
        env=_env(db),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    return result.stdout


def _counts(db):
    con = sqlite3.connect(db)
    tables = [
        r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    ]
    counts = {
        t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables
    }
    con.close()
    return counts


def test_a_missing_database_is_created_with_the_state_tables(tmp_path):
    db = tmp_path / "data" / "new.db"
    db.parent.mkdir()
    out = _ensure(tmp_path, db)
    assert "created" in out
    counts = _counts(db)
    for table in (
        "source_document_states",
        "source_document_items",
        "source_document_references",
        "horizon_ids",
    ):
        assert table in counts
    # The path came from DATABASE_URL, not db/horizon.db.
    assert not (tmp_path / "db" / "horizon.db").exists()


def test_an_existing_database_is_kept(tmp_path):
    db = tmp_path / "kept.db"
    _ensure(tmp_path, db)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO persons (name) VALUES ('Maria da Silva')")
    con.commit()
    con.close()
    before = _counts(db)
    out = _ensure(tmp_path, db)
    assert "kept" in out
    assert _counts(db) == before


def test_a_database_of_other_rules_is_rebuilt_once(
    tmp_path, monkeypatch, _no_rule_version_reset
):
    from src.flows.maintenance import horizon_ids

    guard = _no_rule_version_reset  # the real guard (tests/conftest.py)

    db = tmp_path / "old.db"
    _ensure(tmp_path, db)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO persons (name) VALUES ('Maria da Silva')")
    con.execute(
        "INSERT OR REPLACE INTO horizon_meta (key, value) VALUES ('rule_version', '0')"
    )
    con.commit()
    con.close()

    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    calls = []
    monkeypatch.setattr(horizon_ids, "reset_database", lambda u: calls.append(u))
    # Another recorded rule version on a database with rows: rebuilt once.
    guard()
    assert calls == [url]

    con = sqlite3.connect(db)
    con.execute(
        "INSERT OR REPLACE INTO horizon_meta (key, value) VALUES ('rule_version', ?)",
        (str(horizon_ids.HORIZON_RULE_VERSION),),
    )
    con.commit()
    con.close()
    guard()
    assert calls == [url]
