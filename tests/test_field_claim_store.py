"""SQLite store of field claims and writer of resolved values (branch 030)."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.adapters.database.field_claim_store import (
    SqliteFieldClaimStore,
    SqliteFieldWriter,
)
from src.core.logic.field_merge import lattes_source, sigpesq_source
from src.core.ports.field_claim_store import FieldClaim
from src.db.migrations import run_migrations


@pytest.fixture
def conn():
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text(
            "CREATE TABLE initiatives (id INTEGER PRIMARY KEY, name TEXT, "
            "status TEXT, description TEXT, start_date DATETIME, end_date DATETIME)"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE fellowships (id INTEGER PRIMARY KEY, name TEXT, value FLOAT)"
        )
    )
    connection.execute(
        text("CREATE TABLE advisorships (id INTEGER PRIMARY KEY, cancelled BOOLEAN)")
    )
    connection.execute(
        text(
            "CREATE TABLE source_document_states (source_system TEXT, "
            "document_key TEXT)"
        )
    )
    connection.commit()
    with Session(bind=connection) as session:
        run_migrations(session)
    yield connection
    connection.close()
    engine.dispose()


def _claim(key, entity_id, field, value, source=None):
    doc_date, rank, tie = source or lattes_source("2026-01-01", key)
    return FieldClaim(
        source_system="lattes_projects",
        document_key=key,
        entity_type="initiative",
        entity_id=entity_id,
        field=field,
        value=value,
        doc_date=doc_date,
        source_rank=rank,
        tie_key=tie,
    )


def test_replace_touches_old_and_new_entities(conn):
    store = SqliteFieldClaimStore(lambda: conn)
    assert store.replace_document_claims(
        "lattes_projects", "A", [_claim("A", 1, "description", "x")]
    ) == {("initiative", 1): {"description"}}
    touched = store.replace_document_claims(
        "lattes_projects", "A", [_claim("A", 2, "status", "Active")]
    )
    assert touched == {
        ("initiative", 1): {"description"},
        ("initiative", 2): {"status"},
    }
    assert store.claims_for("initiative", 1) == []
    assert [c.value for c in store.claims_for("initiative", 2)] == ["Active"]


def test_replace_keeps_other_documents_claims(conn):
    store = SqliteFieldClaimStore(lambda: conn)
    store.replace_document_claims(
        "lattes_projects", "A", [_claim("A", 1, "description", "a")]
    )
    store.replace_document_claims(
        "sigpesq_project",
        "sigpesq project|9",
        [_claim("B", 1, "description", "b", sigpesq_source(9))],
    )
    store.replace_document_claims("lattes_projects", "A", [])
    assert [(c.source_system, c.value) for c in store.claims_for("initiative", 1)] == [
        ("sigpesq_project", "b")
    ]


def test_one_claim_per_document_and_field_the_first_wins(conn):
    store = SqliteFieldClaimStore(lambda: conn)
    store.replace_document_claims(
        "lattes_projects",
        "A",
        [_claim("A", 1, "status", "Active"), _claim("A", 1, "status", "Concluded")],
    )
    assert [c.value for c in store.claims_for("initiative", 1)] == ["Active"]


def test_dates_are_stored_as_iso_dates(conn):
    from datetime import datetime

    store = SqliteFieldClaimStore(lambda: conn)
    store.replace_document_claims(
        "lattes_projects", "A", [_claim("A", 1, "start_date", datetime(2022, 8, 1))]
    )
    assert store.claims_for("initiative", 1)[0].value == "2022-08-01"


def test_move_claims_to_the_winner(conn):
    store = SqliteFieldClaimStore(lambda: conn)
    store.replace_document_claims(
        "lattes_projects",
        "A",
        [_claim("A", 1, "status", "Active"), _claim("A", 2, "status", "Concluded")],
    )
    store.move_claims("initiative", 1, 2)
    assert [c.value for c in store.claims_for("initiative", 2)] == ["Concluded"]
    assert store.claims_for("initiative", 1) == []


def test_a_rollback_discards_the_claims(conn):
    store = SqliteFieldClaimStore(lambda: conn)
    transaction = conn.begin()
    store.replace_document_claims(
        "lattes_projects", "A", [_claim("A", 1, "description", "x")]
    )
    transaction.rollback()
    assert store.claims_for("initiative", 1) == []


def test_values_are_scrubbed(conn):
    store = SqliteFieldClaimStore(lambda: conn)
    store.replace_document_claims(
        "lattes_projects",
        "A",
        [_claim("A", 1, "description", "contato fulano@example.com")],
    )
    assert "fulano@example.com" not in store.claims_for("initiative", 1)[0].value


def test_writer_reads_and_writes_in_the_orm_format(conn):
    conn.execute(
        text("INSERT INTO initiatives (id, name, status) VALUES (1, 'P', 'Active')")
    )
    conn.execute(
        text("INSERT INTO fellowships (id, name, value) VALUES (3, 'PIBIC', 600)")
    )
    writer = SqliteFieldWriter(lambda: conn)
    writer.write("initiative", 1, {"start_date": "2022-08-01", "status": "Concluded"})
    writer.write("fellowship", 3, {"value": 700.0})
    assert writer.read("initiative", 1, ["status", "start_date"]) == {
        "status": "Concluded",
        "start_date": "2022-08-01 00:00:00.000000",
    }
    assert writer.read("fellowship", 3, ["value"]) == {"value": 700.0}
    assert writer.read("initiative", 99, ["status"]) == {}


def test_writer_spans_both_tables_of_an_advisorship(conn):
    conn.execute(
        text("INSERT INTO initiatives (id, name, status) VALUES (5, 'A', 'Active')")
    )
    conn.execute(text("INSERT INTO advisorships (id, cancelled) VALUES (5, 1)"))
    writer = SqliteFieldWriter(lambda: conn)
    writer.write("advisorship", 5, {"cancelled": False, "status": "Concluded"})
    assert writer.read("advisorship", 5, ["status", "cancelled"]) == {
        "status": "Concluded",
        "cancelled": 0,
    }
