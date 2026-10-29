"""Spec 020 (FR-014) and spec 021 (FR-002): the migrations only add the
ETL-owned tables (and columns on them, spec 023); every table that existed before keeps its columns, types and
indexes."""

import importlib.util
import os
import sqlite3

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.db.migrations import MIGRATIONS, _applied_ids, run_migrations

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NEW_TABLES = {
    "horizon_ids",
    "horizon_id_candidates",
    "horizon_id_aliases",
    "horizon_merge_log",
    "horizon_meta",
    "team_member_contributions",
    # spec 021
    "source_document_states",
    "source_document_items",
    "source_document_references",
}
# Migrations that create an index on a new table rather than a table.
NEW_INDEXES = {"0010_source_document_items_index"}
# Migrations that add a column to a new (ETL-owned) table (spec 023).
NEW_COLUMNS = {"0012_source_document_downloaded_at"}
# Shipped before spec 020; the base schema is taken after it.
PRE_020 = "0001_initiatives_enrichment_json"


def _base_metadata():
    """The tables db/create_db.py creates (it registers a few beyond eo_lib)."""
    spec = importlib.util.spec_from_file_location(
        "create_db_for_schema_test", os.path.join(REPO, "db", "create_db.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Base.metadata


def _schema(path):
    con = sqlite3.connect(path)
    tables = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]
    out = {}
    for table in tables:
        indexes = [
            (
                r[1],
                r[2],
                tuple(i[2] for i in con.execute(f'PRAGMA index_info("{r[1]}")')),
            )
            for r in con.execute(f'PRAGMA index_list("{table}")')
        ]
        out[table] = (
            tuple(con.execute(f'PRAGMA table_info("{table}")')),
            tuple(sorted(indexes)),
        )
    con.close()
    return out


def test_migrations_only_add_the_new_tables(tmp_path):
    path = tmp_path / "schema.db"
    engine = create_engine(f"sqlite:///{path}")
    _base_metadata().create_all(engine)
    with Session(engine) as session:
        _applied_ids(session)
        session.execute(text(dict(MIGRATIONS)[PRE_020]))
        session.execute(
            text("INSERT INTO schema_migrations (id) VALUES (:id)"), {"id": PRE_020}
        )
        session.commit()
    before = _schema(path)
    assert {"persons", "researchers", "initiatives", "source_records"} <= set(before)

    with Session(engine) as session:
        assert run_migrations(session) == len(NEW_TABLES) + len(NEW_INDEXES) + len(
            NEW_COLUMNS
        )
    engine.dispose()
    after = _schema(path)

    assert set(after) - set(before) == NEW_TABLES
    changed = [t for t in before if before[t] != after[t]]
    assert changed == []
