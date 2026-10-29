"""Spec 021: the SQLite document state store on a real temporary database.

Runs in a subprocess, like tests/test_document_transaction.py, because the
store works on the shared connection of a DocumentTransaction, which rebinds
the libraries' process-wide session factory.
"""

import os
import subprocess
import sys
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRELUDE = """
import sqlite3, sys
from eo_lib import Person, PersonController
from src.adapters.database.document_state_store import SqliteDocumentStateStore
from src.adapters.database.document_transaction import DocumentTransaction
from src.core.ports.document_state_store import DocumentFailed, DocumentOutcome, Reference

DB = sys.argv[1]

def rows(sql):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()

def outcome(key, h="h1", items=(), refs=()):
    return DocumentOutcome("lattes_projects", key, h, "f", 1, None, list(refs), list(items))

tx = DocumentTransaction()
store = SqliteDocumentStateStore(tx, rule_version=1)
"""


def _run(tmp_path, body):
    db = tmp_path / "state.db"
    env = dict(os.environ)
    env.update(DATABASE_URL=f"sqlite:///{db}", STORAGE_TYPE="db", PYTHONPATH=REPO)
    subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "create_db.py")],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
    )
    script = tmp_path / "scenario.py"
    script.write_text(PRELUDE + textwrap.dedent(body) + "\ntx.close()\n")
    result = subprocess.run(
        [sys.executable, str(script), str(db)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_state_is_committed_with_the_document_data_or_not_at_all(tmp_path):
    _run(
        tmp_path,
        """
        store.begin_document()
        PersonController().create(Person(name="Ana"))
        store.commit_processed(outcome("1", refs=[Reference("person_name", "ana", "person:h:1")]))
        assert rows("SELECT COUNT(*) FROM source_document_states") == [(0,)]
        store.commit_document()
        assert rows("SELECT document_key, content_hash, status FROM source_document_states") == [("1", "h1", "active")]
        assert rows("SELECT kind, outcome FROM source_document_references") == [("person_name", "person:h:1")]
        assert len(store.load("lattes_projects")) == 1

        store.begin_document()
        PersonController().create(Person(name="Bia"))
        store.commit_processed(outcome("2"))
        store.rollback_document()
        tx.commit()
        assert rows("SELECT name FROM persons") == [("Ana",)]
        assert rows("SELECT document_key FROM source_document_states") == [("1",)]
        """,
    )


def test_failure_record_keeps_the_processing_state(tmp_path):
    _run(
        tmp_path,
        """
        store.begin_document(); store.commit_processed(outcome("1", h="h1")); store.commit_document()
        store.record_failure("lattes_projects", "1", "unidentified")
        store.record_failure("lattes_projects", "9", "download")
        store.begin_document(); store.commit_document()  # boundary: commits what was written between documents
        assert rows("SELECT document_key, content_hash, status, last_failure FROM source_document_states ORDER BY 1") == [
            ("1", "h1", "active", "unidentified"),
            ("9", None, "active", "download"),
        ]
        """,
    )


def test_total_loss_only_for_documents_that_had_items(tmp_path):
    _run(
        tmp_path,
        """
        store.begin_document()
        store.commit_processed(outcome("1", items=[("researcher", "1", True), ("article", "5", False)]))
        store.commit_document()
        assert rows("SELECT item_count FROM source_document_states") == [(1,)]
        store.begin_document()
        try:
            store.commit_processed(outcome("1", h="h2", items=[("researcher", "1", True)]))
            raise AssertionError("total loss not detected")
        except DocumentFailed as exc:
            assert exc.reason == "total_loss"
        store.rollback_document()
        store.begin_document()
        store.commit_processed(outcome("2", items=[("researcher", "2", True)]))  # never had items: fine
        store.commit_document()
        """,
    )


def test_listing_marks_inactive_and_reactivates_only_when_complete(tmp_path):
    _run(
        tmp_path,
        """
        for key in ("1", "2"):
            store.begin_document(); store.commit_processed(outcome(key)); store.commit_document()
        r = store.mark_listing("lattes_projects", ["1"], complete=False)
        assert r.newly_inactive == 0
        tx.begin(); tx.commit()
        seen_before = rows("SELECT last_seen_at FROM source_document_states WHERE document_key = '2'")
        r = store.mark_listing("lattes_projects", ["1", "3"], complete=True)
        assert (r.listed, r.newly_inactive) == (2, 1)
        tx.begin(); tx.commit()
        assert rows("SELECT document_key, status FROM source_document_states ORDER BY 1") == [
            ("1", "active"), ("2", "inactive"), ("3", "active"),
        ]
        seen_2 = rows("SELECT last_seen_at FROM source_document_states WHERE document_key = '2'")
        r = store.mark_listing("lattes_projects", ["1", "2", "3"], complete=False)
        assert r.reactivated == 0
        r = store.mark_listing("lattes_projects", ["1", "2", "3"], complete=True)
        assert r.reactivated == 1
        tx.begin(); tx.commit()
        assert rows("SELECT status FROM source_document_states WHERE document_key = '2'") == [("active",)]
        assert seen_2 == seen_before  # inactive keeps the date it was last seen
        """,
    )


# --------------------------------------------------------------------------
# US2: item links and the deletion of dropped items (FR-011, FR-011a)
# --------------------------------------------------------------------------

ITEMS = """
from sqlalchemy import text

def sql(statement, **params):
    return tx.connection.execute(text(statement), params)

def process(key, items, h):
    store.begin_document()
    deleted = store.commit_processed(outcome(key, h=h, items=items))
    store.commit_document()
    return deleted

# A CV owner (researcher 1), a student (person 2) known only through the CV,
# a co-author (researcher 3) of a second CV, a knowledge area.
sql("INSERT INTO persons (id, name) VALUES (1, 'Owner'), (2, 'Student'), (3, 'Coauthor')")
sql("INSERT INTO researchers (id) VALUES (1), (3)")
sql("INSERT INTO awards (id, researcher_id, title) VALUES (10, 1, 'Prize')")
sql("INSERT INTO articles (id, title, year, type) VALUES (20, 'Solo', 2020, 'ARTICLE'), "
    "(21, 'Shared', 2021, 'ARTICLE')")
sql("INSERT INTO article_authors VALUES (20, 1), (21, 1), (21, 3)")
sql("INSERT INTO knowledge_areas (id, name) VALUES (30, 'Area')")
sql("INSERT INTO initiatives (id, name) VALUES (40, 'Project')")
sql("INSERT INTO initiative_knowledge_areas VALUES (40, 30)")
sql("INSERT INTO teams (id, name) VALUES (50, 'Project team')")
sql("INSERT INTO initiative_teams VALUES (40, 50)")
sql("INSERT INTO roles (id, name) VALUES (60, 'Member')")
sql("INSERT INTO team_members (id, person_id, team_id, role_id) VALUES (70, 2, 50, 60)")
sql("INSERT INTO team_member_contributions (team_id, person_id, role_id, document_key) "
    "VALUES (50, 2, 60, 'cv-a|project')")
store.commit_document()  # the fixture rows, outside any document

cv_a = [
    ("researcher", "1", True), ("award", "10", False), ("article", "20", False),
    ("article_author", "20:1", False), ("article", "21", False),
    ("article_author", "21:1", False), ("initiative", "40", False),
    ("team_contribution", "50|cv-a|project", False), ("person", "2", False),
    ("knowledge_area", "30", False),
]
cv_b = [("researcher", "3", True), ("article", "21", False),
        ("article_author", "21:3", False)]
assert process("A", cv_a, "h1") == []
assert process("B", cv_b, "h1") == []
"""


def _items(tmp_path, body):
    _run(tmp_path, ITEMS + textwrap.dedent(body))


def test_dropped_items_are_deleted_unless_still_needed(tmp_path):
    _items(
        tmp_path,
        """
        # CV A now carries only its owner: everything else it dropped goes,
        # except what CV B still needs and the reference rows.
        deleted = process("A", [("researcher", "1", True), ("award", "10", False)], "h2")
        kinds = sorted((d.entity_type, d.entity_id) for d in deleted)
        assert kinds == [("article", 20), ("initiative", 40), ("person", 2)], kinds
        assert sql("SELECT id FROM articles ORDER BY id").fetchall() == [(21,)]
        assert sql("SELECT * FROM article_authors").fetchall() == [(21, 3)]
        assert sql("SELECT COUNT(*) FROM teams").scalar() == 0
        assert sql("SELECT COUNT(*) FROM team_members").scalar() == 0
        assert sql("SELECT COUNT(*) FROM initiative_knowledge_areas").scalar() == 0
        assert sql("SELECT id FROM knowledge_areas").fetchall() == [(30,)]
        assert sql("SELECT id FROM persons ORDER BY id").fetchall() == [(1,), (3,)]
        links = sql("SELECT item_type, item_ref FROM source_document_items "
                    "WHERE document_key = 'A' ORDER BY 1").fetchall()
        assert links == [("award", "10"), ("researcher", "1")], links
        """,
    )


def test_a_person_still_referenced_or_owning_an_active_cv_is_kept(tmp_path):
    _items(
        tmp_path,
        """
        # The student is also a member of another team (a row no document
        # carries), and the co-author owns an active Lattes CV.
        sql("UPDATE researchers SET cnpq_url = 'http://lattes.cnpq.br/1234567890123456' "
            "WHERE id = 3")
        sql("INSERT INTO source_document_states (source_system, document_key, "
            "rule_version, last_seen_at, status) VALUES ('lattes_projects', "
            "'1234567890123456', 1, 'x', 'active')")
        sql("INSERT INTO teams (id, name) VALUES (51, 'Other team')")
        sql("INSERT INTO team_members (id, person_id, team_id, role_id) "
            "VALUES (71, 2, 51, 60)")
        store.commit_document()
        process("A", [("researcher", "1", True), ("award", "10", False)], "h2")
        assert sql("SELECT id FROM persons ORDER BY id").fetchall() == [(1,), (2,), (3,)]
        # B drops its owner link: the owner of an active CV stays.
        process("B", [("article", "21", False)], "h2")
        assert sql("SELECT COUNT(*) FROM persons WHERE id = 3").scalar() == 1
        """,
    )


def test_merge_hook_moves_links_to_the_winner(tmp_path):
    _items(
        tmp_path,
        """
        from src.adapters.database.document_item_store import repoint_person_links

        tx.close()
        con = sqlite3.connect(DB)
        repoint_person_links(con, 3, 2)
        con.commit()
        links = sorted(con.execute(
            "SELECT document_key, item_ref FROM source_document_items "
            "WHERE item_type IN ('person', 'researcher')").fetchall())
        con.close()
        assert links == [("A", "1"), ("A", "3"), ("B", "3")], links
        tx = DocumentTransaction()
        """,
    )


def test_links_of_a_document_without_recorded_links_delete_nothing(tmp_path):
    _run(
        tmp_path,
        """
        from sqlalchemy import text
        tx.connection.execute(text("INSERT INTO persons (id, name) VALUES (2, 'S')"))
        # A state written before links were recorded (item_count 1, no links).
        tx.connection.execute(text(
            "INSERT INTO source_document_states (source_system, document_key, "
            "content_hash, rule_version, item_count, last_seen_at, status) VALUES "
            "('lattes_projects', 'A', 'h0', 1, 1, 'x', 'active')"))
        store.commit_document()
        store.begin_document()
        assert store.commit_processed(outcome("A", h="h1", items=[("award", "9", False)])) == []
        store.commit_document()
        assert rows("SELECT COUNT(*) FROM persons") == [(1,)]
        """,
    )
