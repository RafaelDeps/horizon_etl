"""Spec 020 (FR-024): a database built under other rules is rebuilt once."""

import sqlite3

from src.core.logic.horizon_identity import HORIZON_RULE_VERSION
from src.flows.maintenance.horizon_ids import rule_version_requires_reset
from tests.test_horizon_id_assigner import _assign, _build


def test_no_database_needs_no_reset(tmp_path):
    assert rule_version_requires_reset(str(tmp_path / "missing.db")) is False


def test_empty_database_needs_no_reset(tmp_path):
    db = tmp_path / "empty.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT)")
    con.close()
    assert rule_version_requires_reset(str(db)) is False


def test_same_version_needs_no_reset(tmp_path):
    db = tmp_path / "same.db"
    _build(db, order_seed=1)
    _assign(db)
    assert rule_version_requires_reset(str(db)) is False


def test_other_or_missing_version_needs_a_reset(tmp_path):
    db = tmp_path / "other.db"
    _build(db, order_seed=1)
    assert rule_version_requires_reset(str(db)) is True  # never assigned
    _assign(db)
    con = sqlite3.connect(db)
    con.execute(
        "UPDATE horizon_meta SET value = ? WHERE key = 'rule_version'",
        (str(HORIZON_RULE_VERSION + 1),),
    )
    con.commit()
    con.close()
    assert rule_version_requires_reset(str(db)) is True


def test_weekly_resets_once_before_the_phases(
    tmp_path, monkeypatch, _no_rule_version_reset
):
    import src.flows.maintenance.horizon_ids as horizon_ids

    real_guard = _no_rule_version_reset  # the suite stubs it in run_weekly
    db = tmp_path / "old.db"
    _build(db, order_seed=1)  # ingested rows, no rule version recorded
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    resets = []
    monkeypatch.setattr(horizon_ids, "reset_database", resets.append)

    real_guard()
    assert resets == [f"sqlite:///{db}"]

    _assign(db)  # now recorded with the code's version
    real_guard()
    assert resets == [f"sqlite:///{db}"]
