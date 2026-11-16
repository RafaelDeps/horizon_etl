"""Field claims through the document phase (branch 030, US1 and US2).

Each scenario plays the documents the way the loaders do: the handler writes
its own values over the row (the old last-writer behaviour), then the
document claims them. The claims and the resolution run at the end of the
document, on a real SQLite connection, so the stored value must be the same
whatever the order of the documents and whichever of them a run reprocesses.
"""

import itertools

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.adapters.database.field_claim_store import (
    SqliteFieldClaimStore,
    SqliteFieldWriter,
)
from src.core.logic.document_skip import DocumentSkip, claim, set_claim_source
from src.core.logic.field_merge import (
    MERGED_FIELDS,
    FieldMergeApplier,
    FieldMergeStats,
    lattes_source,
    sigpesq_source,
)
from src.db.migrations import run_migrations


class _Store:
    """Document states that keep nothing: every document is processed."""

    def load(self, source_system):
        return {}

    def begin_document(self):
        pass

    def commit_document(self):
        pass

    def rollback_document(self):
        pass

    def commit_processed(self, outcome):
        return []

    def record_failure(self, source_system, document_key, reason):
        pass


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
            "CREATE TABLE source_document_states (source_system TEXT, document_key TEXT)"
        )
    )
    connection.execute(text("INSERT INTO initiatives (id, name) VALUES (1, 'P')"))
    connection.execute(
        text("INSERT INTO fellowships (id, name, value) VALUES (7, 'PIBIC', 0)")
    )
    connection.execute(text("INSERT INTO initiatives (id, name) VALUES (8, 'A')"))
    connection.execute(text("INSERT INTO advisorships (id, cancelled) VALUES (8, 0)"))
    connection.commit()
    with Session(bind=connection) as session:
        run_migrations(session)
    yield connection
    connection.close()
    engine.dispose()


def _skip(conn, source_system, stats=None):
    skip = DocumentSkip(_Store(), source_system)
    store = SqliteFieldClaimStore(lambda: conn)
    skip.claim_store = store
    skip.field_merge = FieldMergeApplier(
        store, SqliteFieldWriter(lambda: conn), stats or FieldMergeStats()
    )
    return skip


def _play(conn, doc, stats=None, entity=("initiative", 1)):
    """One document: last-writer write, then claims (like the loaders)."""
    system, key, source, values = doc
    skip = _skip(conn, system, stats)
    with skip.document(key) as d:
        d.unchanged({"key": key, **values})
        d.begin()
        set_claim_source(source)
        table = {"fellowship": "fellowships", "advisorship": "advisorships"}.get(
            entity[0], "initiatives"
        )
        filled = {
            f: (f"{v} 00:00:00.000000" if f.endswith("_date") else v)
            for f, v in values.items()
            if v not in (None, "")
        }
        if filled:
            sets = ", ".join(f"{f} = :{f}" for f in filled)
            conn.execute(
                text(f"UPDATE {table} SET {sets} WHERE id = :_id"),
                {**filled, "_id": entity[1]},
            )
        for field, value in values.items():
            claim(entity[0], entity[1], field, value)
    assert skip.counts.get("processed") == 1, skip.failures
    return skip


def _row(conn, fields=MERGED_FIELDS):
    row = conn.execute(
        text(f"SELECT {', '.join(fields)} FROM initiatives WHERE id = 1")
    ).mappings()
    return dict(next(iter(row)))


CV_MARCH = (
    "lattes_projects",
    "0000000000000009",
    lattes_source("2026-03-10", "0000000000000009"),
    {"description": "March text", "status": "Active", "start_date": "2022-01-01"},
)
CV_SEPT = (
    "lattes_projects",
    "0000000000000005",
    lattes_source("2026-09-02", "0000000000000005"),
    {"description": "September text", "status": "Active", "end_date": None},
)
ROW = (
    "sigpesq_project",
    "sigpesq project|6903",
    sigpesq_source(6903),
    {
        "description": "Report text",
        "status": "Concluded",
        "start_date": "2022-08-01",
        "end_date": "2026-12-31",
    },
)

EXPECTED = {
    "description": "September text",
    "status": "Active",
    "start_date": "2022-01-01 00:00:00.000000",
    "end_date": "2026-12-31 00:00:00.000000",
}


class TestInitiatives:
    @pytest.mark.parametrize(
        "order", list(itertools.permutations([CV_MARCH, CV_SEPT, ROW]))
    )
    def test_every_order_gives_the_same_values(self, conn, order):
        for doc in order:
            _play(conn, doc)
        assert _row(conn) == EXPECTED

    def test_reprocessing_one_document_changes_nothing(self, conn):
        for doc in (CV_MARCH, CV_SEPT, ROW):
            _play(conn, doc)
        before = conn.execute(text("SELECT COUNT(*) FROM source_field_claims")).scalar()
        _play(conn, CV_MARCH)  # the oldest CV is read again, last
        assert _row(conn) == EXPECTED
        after = conn.execute(text("SELECT COUNT(*) FROM source_field_claims")).scalar()
        assert before == after

    def test_lattes_beats_the_undated_sigpesq_row(self, conn):
        _play(conn, CV_SEPT)
        _play(conn, ROW)
        assert _row(conn)["status"] == "Active"

    def test_sigpesq_fills_what_every_cv_leaves_empty(self, conn):
        _play(conn, ROW)
        _play(conn, CV_SEPT)
        assert _row(conn)["end_date"] == "2026-12-31 00:00:00.000000"

    def test_same_date_lowest_lattes_id_wins(self, conn):
        a = (
            "lattes_projects",
            "2",
            lattes_source("2026-01-01", "2"),
            {"start_date": "2020-01-01"},
        )
        b = (
            "lattes_projects",
            "1",
            lattes_source("2026-01-01", "1"),
            {"start_date": "2019-01-01"},
        )
        for order in ((a, b), (b, a)):
            for doc in order:
                _play(conn, doc)
            assert _row(conn)["start_date"] == "2019-01-01 00:00:00.000000"

    def test_highest_sigpesq_id_wins(self, conn):
        a = (
            "sigpesq_project",
            "sigpesq project|1",
            sigpesq_source(1),
            {"description": "one"},
        )
        b = (
            "sigpesq_project",
            "sigpesq project|2",
            sigpesq_source(2),
            {"description": "two"},
        )
        for order in ((a, b), (b, a)):
            for doc in order:
                _play(conn, doc)
            assert _row(conn)["description"] == "two"


class TestEmptyValues:
    def test_unknown_never_replaces_a_status(self, conn):
        _play(conn, ROW)
        unknown = (
            "lattes_projects",
            "3",
            lattes_source("2026-10-01", "3"),
            {"status": "Unknown"},
        )
        _play(conn, unknown)
        assert _row(conn)["status"] == "Concluded"

    def test_a_newer_empty_field_does_not_win(self, conn):
        _play(conn, ROW)
        _play(conn, CV_SEPT)  # newer, end date empty
        assert _row(conn)["end_date"] == "2026-12-31 00:00:00.000000"

    def test_a_project_removed_from_a_cv_stops_taking_part(self, conn):
        for doc in (CV_MARCH, CV_SEPT):
            _play(conn, doc)
        skip = _skip(conn, "lattes_projects")
        with skip.document(CV_SEPT[1]) as d:  # the CV no longer lists it
            d.unchanged({"removed": True})
            d.begin()
        assert _row(conn)["description"] == "March text"


class TestProjectFiles:
    def test_pdf_fills_an_empty_description(self, conn):
        pdf = (
            "sigpesq_project_files",
            "PJ 1",
            (None, 1, "1|PJ 1"),
            {"description": "PDF text"},
        )
        _play(conn, pdf)
        _play(
            conn,
            (
                "lattes_projects",
                "4",
                lattes_source("2026-01-01", "4"),
                {"description": None},
            ),
        )
        assert _row(conn)["description"] == "PDF text"

    def test_pdf_keeps_the_status_set_by_the_parent_recalculation(self, conn):
        _play(conn, ROW)
        # recalculate_parent_projects sets the status from the children.
        conn.execute(text("UPDATE initiatives SET status = 'Active' WHERE id = 1"))
        pdf = (
            "sigpesq_project_files",
            "PJ 1",
            (None, 1, "1|PJ 1"),
            {"description": "PDF text"},
        )
        _play(conn, pdf)
        assert _row(conn)["status"] == "Active"

    def test_pdf_never_replaces_a_row_or_cv_description(self, conn):
        pdf = (
            "sigpesq_project_files",
            "PJ 1",
            (None, 1, "1|PJ 1"),
            {"description": "PDF text"},
        )
        for order in ((ROW, pdf), (pdf, ROW)):
            for doc in order:
                _play(conn, doc)
            assert _row(conn)["description"] == "Report text"


class TestFellowships:
    def _value(self, conn):
        return conn.execute(text("SELECT value FROM fellowships WHERE id = 7")).scalar()

    def test_highest_workplan_id_sets_the_value(self, conn):
        a = (
            "sigpesq_advisorship",
            "sigpesq workplan|1|4882",
            sigpesq_source(4882),
            {"value": 600},
        )
        b = (
            "sigpesq_advisorship",
            "sigpesq workplan|2|5120",
            sigpesq_source(5120),
            {"value": 700},
        )
        for order in ((a, b), (b, a)):
            for doc in order:
                _play(conn, doc, entity=("fellowship", 7))
            assert self._value(conn) == 700

    def test_a_zero_value_never_replaces_one(self, conn):
        a = (
            "sigpesq_advisorship",
            "sigpesq workplan|1|4882",
            sigpesq_source(4882),
            {"value": 600},
        )
        b = (
            "sigpesq_advisorship",
            "sigpesq workplan|2|5120",
            sigpesq_source(5120),
            {"value": 0},
        )
        for doc in (a, b):
            _play(conn, doc, entity=("fellowship", 7))
        assert self._value(conn) == 600


class TestCancelledAdvisorships:
    """A workplan whose student was replaced: the cancelled row and the new
    row write the same advisorship; the highest SigPesq Id decides."""

    def _cancelled(self, conn):
        return conn.execute(
            text("SELECT cancelled FROM advisorships WHERE id = 8")
        ).scalar()

    def test_the_newest_workplan_decides_in_every_order(self, conn):
        old = (
            "sigpesq_advisorship",
            "sigpesq workplan|8732|3961",
            sigpesq_source(3961),
            {"cancelled": True},
        )
        new = (
            "sigpesq_advisorship",
            "sigpesq workplan|8732|4145",
            sigpesq_source(4145),
            {"cancelled": False},
        )
        for order in ((old, new), (new, old)):
            for doc in order:
                _play(conn, doc, entity=("advisorship", 8))
            assert self._cancelled(conn) == 0


class TestMergeLog:
    def test_counts_add_up_to_the_conflicting_fields(self, conn):
        stats = FieldMergeStats()
        for doc in (CV_MARCH, CV_SEPT, ROW):
            _play(conn, doc, stats)
        counts = stats.counts()
        # description (3 values), status (2), start_date (2) differ; end_date has one.
        assert counts["fields"] == 3
        assert counts["by_date"] + counts["by_source"] + counts["by_tiebreak"] == 3

    def test_no_conflict_counts_zero(self, conn):
        stats = FieldMergeStats()
        _play(conn, ROW, stats)
        assert stats.counts()["fields"] == 0
