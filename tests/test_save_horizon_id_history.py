"""Spec 020 (FR-013a): the id history survives ``make db-reset``."""

import json
import os
import sqlite3

from src.adapters.database.horizon_id_store import SqliteHorizonIdStore
from src.core.logic.horizon_id_assigner import HorizonIdAssigner
from src.scripts.save_horizon_id_history import save_history
from tests.test_horizon_id_assigner import (
    CARLOS_NAME_ID,
    _aliases,
    _assign,
    _build,
    _give_lattes,
    _merge,
    _sql,
)


def _seeded(tmp_path):
    db = tmp_path / "horizon.db"
    _build(db, order_seed=1)
    _sql(db, "INSERT INTO persons (id, name) VALUES (9001, 'Karin S. Komati')")
    _assign(db)
    _merge(db, "Karin Satie Komati", "Karin S. Komati")
    _assign(db)
    return db


def test_snapshot_has_ids_candidates_aliases_and_merge_log(tmp_path):
    db = _seeded(tmp_path)
    snapshot = tmp_path / "horizon_id_history.json"

    assert save_history(f"sqlite:///{db}", str(snapshot)) is True

    data = json.loads(snapshot.read_text())
    assert data["rule_version"] == 1
    assert {"entity_type", "horizon_id", "rule", "natural_key"} <= set(data["ids"][0])
    assert data["candidates"] and data["aliases"][0]["reason"] == "merge"
    assert data["merge_log"][0]["winner_horizon_id"] == (
        "person:lattes:9860697624155451"
    )


def test_database_without_ids_writes_nothing(tmp_path):
    db = tmp_path / "bare.db"
    sqlite3.connect(db).close()
    snapshot = tmp_path / "horizon_id_history.json"

    assert save_history(f"sqlite:///{db}", str(snapshot)) is False
    assert save_history(f"sqlite:///{tmp_path / 'missing.db'}", str(snapshot)) is False
    assert not snapshot.exists()


def test_unwritable_target_logs_and_returns(tmp_path):
    db = _seeded(tmp_path)
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a directory")

    assert save_history(f"sqlite:///{db}", str(blocked / "history.json")) is False


def test_history_resolves_an_upgraded_id_after_the_database_is_rebuilt(tmp_path):
    db = tmp_path / "horizon.db"
    _build(db, order_seed=1)
    _assign(db)
    snapshot = tmp_path / "horizon_id_history.json"
    assert save_history(f"sqlite:///{db}", str(snapshot))

    os.remove(db)  # make db-clean
    _build(db, order_seed=2)  # make db-init + the ingestion flows
    new_id = _give_lattes(db, "Carlos Roberto Pires Campos")
    store = SqliteHorizonIdStore(str(db), snapshot_path=str(snapshot), zip_path="")
    report = HorizonIdAssigner(store).assign()

    assert report["aliases"]["history_source"] == ["snapshot"]
    assert _aliases(db)[CARLOS_NAME_ID] == (new_id, "rebuild")
