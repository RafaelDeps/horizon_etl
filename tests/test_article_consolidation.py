"""Spec 029: the one-time (and weekly, idempotent) consolidation of duplicate
articles, through the merge log so old ids stay resolvable."""

import json
import sqlite3

import pytest

from src.core.logic import reference_consolidator
from src.core.logic.reference_consolidator import ReferenceConsolidator

ARTICLES = """
CREATE TABLE articles (
    id INTEGER NOT NULL PRIMARY KEY, title VARCHAR(500) NOT NULL, doi VARCHAR(255),
    year INTEGER NOT NULL, type VARCHAR(16) NOT NULL, journal_conference VARCHAR(255),
    volume VARCHAR(100), pages VARCHAR(100));
CREATE TABLE horizon_ids (
    entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, horizon_id TEXT NOT NULL UNIQUE,
    rule TEXT NOT NULL, natural_key TEXT, parent_horizon_id TEXT, collision_suffix TEXT,
    assigned_at TEXT NOT NULL, UNIQUE (entity_type, entity_id));
"""


def _db(tmp_path, rows, ids=None, extra_sql=""):
    """rows: (id, title, doi, year, journal, volume); ids: {row id: horizon id}."""
    path = tmp_path / "articles.db"
    conn = sqlite3.connect(path)
    conn.executescript(ARTICLES + extra_sql)
    for row_id, title, doi, year, journal, volume in rows:
        conn.execute(
            "INSERT INTO articles (id, title, doi, year, type, journal_conference, "
            "volume) VALUES (?, ?, ?, ?, 'journal', ?, ?)",
            (row_id, title, doi, year, journal, volume),
        )
    for row_id, horizon_id in (ids or {}).items():
        conn.execute(
            "INSERT INTO horizon_ids VALUES ('article', ?, ?, 'r', NULL, NULL, NULL, 'now')",
            (row_id, horizon_id),
        )
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture(autouse=True)
def report_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(reference_consolidator, "REPORT_DIR", str(tmp_path / "reports"))
    return tmp_path / "reports"


def _ids(db):
    conn = sqlite3.connect(db)
    try:
        return [r[0] for r in conn.execute("SELECT id FROM articles ORDER BY id")]
    finally:
        conn.close()


def _row(db, row_id):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return dict(
            conn.execute("SELECT * FROM articles WHERE id=?", (row_id,)).fetchone()
        )
    finally:
        conn.close()


def test_groups_by_normalized_doi(tmp_path):
    db = _db(
        tmp_path,
        [
            (1, "First title", "10.1000/ABC", 2020, None, None),
            (2, "Totally other title", "https://doi.org/10.1000/abc", 2021, None, None),
            (3, "Unrelated", "10.1000/zzz", 2020, None, None),
        ],
    )

    stats = ReferenceConsolidator(db).consolidate_articles()

    assert _ids(db) == [1, 3]
    assert stats.merged == 1 and stats.groups == 1


def test_groups_by_normalized_title_and_year(tmp_path):
    db = _db(
        tmp_path,
        [
            (1, "Redes Neurais: uma Introdução", None, 2020, None, None),
            (2, "redes neurais - uma introducao!", None, 2020, None, None),
            (3, "redes neurais uma introducao", None, 2021, None, None),
        ],
    )

    stats = ReferenceConsolidator(db).consolidate_articles()

    assert _ids(db) == [1, 3]
    assert stats.merged == 1


def test_two_different_dois_merge_only_rows_with_the_same_doi(tmp_path):
    db = _db(
        tmp_path,
        [
            (1, "Same Title", "10.1000/x", 2020, None, None),
            (2, "Same Title", "10.1000/y", 2020, None, None),
            (3, "Same Title", None, 2020, None, None),
            (4, "Same Title", "10.1000/X", 2020, None, None),
        ],
    )

    stats = ReferenceConsolidator(db).consolidate_articles()

    assert _ids(db) == [1, 2, 3]  # 4 joined 1; 2 and the DOI-less 3 are left alone
    assert stats.skipped_conflicting_doi == 1


def test_a_doi_less_row_joins_the_single_doi_of_its_title_group(tmp_path):
    db = _db(
        tmp_path,
        [
            (1, "Same Title", None, 2020, None, None),
            (2, "Same Title", "10.1000/x", 2020, None, None),
        ],
        ids={1: "article:h:aaa", 2: "article:doi:10.1000/x"},
    )

    ReferenceConsolidator(db).consolidate_articles()

    assert _ids(db) == [2]  # the DOI row wins
    assert _row(db, 2)["title"] == "Same Title"


def test_blank_titles_are_never_grouped(tmp_path):
    db = _db(
        tmp_path,
        [
            (1, "", None, 2020, None, None),
            (2, "  ", None, 2020, None, None),
            (3, "...", None, 2020, None, None),
        ],
    )

    stats = ReferenceConsolidator(db).consolidate_articles()

    assert _ids(db) == [1, 2, 3]
    assert stats.merged == 0


def test_survivor_is_the_best_id_without_its_suffix_then_the_lowest_row(tmp_path):
    db = _db(
        tmp_path,
        [
            (5, "Alpha Work", None, 2020, None, None),
            (6, "alpha work", None, 2020, None, None),
            (7, "ALPHA WORK", None, 2020, None, None),
        ],
        ids={5: "article:h:bbb~x1", 6: "article:h:aaa", 7: "article:h:aaa~y2"},
    )

    ReferenceConsolidator(db).consolidate_articles()

    # "aaa" beats "bbb" once the suffix is ignored; 6 and 7 tie, 6 is lower.
    assert _ids(db) == [6]


def test_survivor_empty_fields_are_filled_and_nothing_is_overwritten(tmp_path):
    db = _db(
        tmp_path,
        [
            (1, "Work", None, 2020, "Journal A", None),
            (2, "work", "10.1000/x", 2020, "Journal B", "12"),
        ],
        ids={1: "article:h:aaa", 2: "article:h:bbb"},
    )
    conn = sqlite3.connect(db)
    conn.execute("UPDATE articles SET pages='1-9' WHERE id=2")
    conn.commit()
    conn.close()

    ReferenceConsolidator(db).consolidate_articles()

    survivor = _row(db, 1)
    assert survivor["journal_conference"] == "Journal A"  # kept
    assert survivor["doi"] == "10.1000/x"  # filled
    assert survivor["volume"] == "12"  # filled
    assert survivor["pages"] == "1-9"  # filled


def test_a_second_pass_finds_nothing(tmp_path):
    db = _db(
        tmp_path,
        [(1, "Work", None, 2020, None, None), (2, "work", None, 2020, None, None)],
    )
    consolidator = ReferenceConsolidator(db)

    first = consolidator.consolidate_articles()
    second = consolidator.consolidate_articles()

    assert first.merged == 1
    assert second.merged == 0 and second.groups == 0
    assert _ids(db) == [1]


def test_stats_count_groups_and_rows(tmp_path):
    db = _db(
        tmp_path,
        [
            (1, "A", None, 2020, None, None),
            (2, "a", None, 2020, None, None),
            (3, "a.", None, 2020, None, None),
            (4, "B", "10.1000/b", 2019, None, None),
            (5, "C", "10.1000/B", 2018, None, None),
        ],
    )

    stats = ReferenceConsolidator(db).consolidate_articles()

    assert stats.groups == 2
    assert stats.merged == 3
    assert json.loads(json.dumps(stats.__dict__))["merged"] == 3


# --- links follow the survivor ---

LINK_TABLES = """
CREATE TABLE researchers (id INTEGER PRIMARY KEY);
CREATE TABLE article_authors (
    article_id INTEGER NOT NULL, researcher_id INTEGER NOT NULL,
    PRIMARY KEY (article_id, researcher_id),
    FOREIGN KEY(article_id) REFERENCES articles (id),
    FOREIGN KEY(researcher_id) REFERENCES researchers (id));
CREATE TABLE source_records (id INTEGER PRIMARY KEY);
CREATE TABLE entity_matches (
    id INTEGER PRIMARY KEY, source_record_id INTEGER NOT NULL,
    canonical_entity_type TEXT NOT NULL, canonical_entity_id INTEGER NOT NULL,
    UNIQUE (source_record_id, canonical_entity_type, canonical_entity_id));
CREATE TABLE attribute_assertions (
    id INTEGER PRIMARY KEY, source_record_id INTEGER NOT NULL,
    canonical_entity_type TEXT NOT NULL, canonical_entity_id INTEGER NOT NULL,
    attribute_name TEXT NOT NULL, value_hash TEXT NOT NULL,
    UNIQUE (source_record_id, canonical_entity_type, canonical_entity_id,
            attribute_name, value_hash));
CREATE TABLE entity_change_logs (
    id INTEGER PRIMARY KEY, canonical_entity_type TEXT NOT NULL,
    canonical_entity_id INTEGER NOT NULL, operation TEXT);
CREATE TABLE source_document_items (
    source_system TEXT NOT NULL, document_key TEXT NOT NULL, item_type TEXT NOT NULL,
    item_ref TEXT NOT NULL, is_subject INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source_system, document_key, item_type, item_ref));
INSERT INTO researchers VALUES (10), (11);
INSERT INTO source_records VALUES (100), (101);
"""


def _linked_db(tmp_path):
    """Articles 1 (survivor, lowest id) and 2 (loser) with overlapping links."""
    db = _db(
        tmp_path,
        [(1, "Work", None, 2020, None, None), (2, "work", None, 2020, None, None)],
        ids={1: "article:h:aaa", 2: "article:h:bbb"},
        extra_sql=LINK_TABLES,
    )
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        INSERT INTO article_authors VALUES (1, 10), (2, 10), (2, 11);
        INSERT INTO entity_matches (source_record_id, canonical_entity_type, canonical_entity_id)
            VALUES (100, 'article', 1), (100, 'article', 2), (101, 'article', 2),
                   (100, 'researcher', 2);
        INSERT INTO attribute_assertions (source_record_id, canonical_entity_type,
            canonical_entity_id, attribute_name, value_hash)
            VALUES (100, 'article', 1, 'title', 'h1'), (100, 'article', 2, 'title', 'h1'),
                   (101, 'article', 2, 'title', 'h2'), (100, 'researcher', 2, 'title', 'h1');
        INSERT INTO entity_change_logs (canonical_entity_type, canonical_entity_id, operation)
            VALUES ('article', 2, 'create'), ('article', 1, 'create'), ('researcher', 2, 'create');
        INSERT INTO source_document_items VALUES
            ('lattes', 'cv1', 'article', '1', 0), ('lattes', 'cv1', 'article', '2', 0),
            ('lattes', 'cv2', 'article', '2', 0),
            ('lattes', 'cv1', 'article_author', '1:10', 0),
            ('lattes', 'cv1', 'article_author', '2:10', 0),
            ('lattes', 'cv2', 'article_author', '2:11', 0),
            ('lattes', 'cv1', 'person', '2', 0);
        """
    )
    conn.commit()
    conn.close()
    return db


def _all(db, sql):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_every_link_points_to_the_survivor(tmp_path):
    db = _linked_db(tmp_path)

    ReferenceConsolidator(db).consolidate_articles()

    assert _ids(db) == [1]
    assert _all(
        db, "SELECT article_id, researcher_id FROM article_authors ORDER BY 2"
    ) == [
        (1, 10),
        (1, 11),
    ]
    assert _all(
        db,
        "SELECT source_record_id, canonical_entity_id FROM entity_matches "
        "WHERE canonical_entity_type='article' ORDER BY 1",
    ) == [(100, 1), (101, 1)]
    assert _all(
        db,
        "SELECT source_record_id, value_hash FROM attribute_assertions "
        "WHERE canonical_entity_type='article' AND canonical_entity_id=1 ORDER BY 1, 2",
    ) == [(100, "h1"), (101, "h2")]
    assert _all(
        db,
        "SELECT COUNT(*) FROM entity_change_logs "
        "WHERE canonical_entity_type='article' AND canonical_entity_id=1",
    ) == [(2,)]
    assert _all(
        db,
        "SELECT document_key, item_ref FROM source_document_items "
        "WHERE item_type='article' ORDER BY 1, 2",
    ) == [("cv1", "1"), ("cv2", "1")]
    assert _all(
        db,
        "SELECT document_key, item_ref FROM source_document_items "
        "WHERE item_type='article_author' ORDER BY 1, 2",
    ) == [("cv1", "1:10"), ("cv2", "1:11")]


def test_no_orphan_or_duplicate_row_is_left(tmp_path):
    db = _linked_db(tmp_path)

    ReferenceConsolidator(db).consolidate_articles()

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
    for table, column in (
        ("entity_matches", "canonical_entity_id"),
        ("attribute_assertions", "canonical_entity_id"),
        ("entity_change_logs", "canonical_entity_id"),
    ):
        assert _all(
            db,
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE canonical_entity_type='article' AND {column}=2",
        ) == [(0,)]
    assert _all(db, "SELECT COUNT(*) FROM article_authors WHERE article_id=2") == [(0,)]
    # Other entity types that happen to share the id are untouched.
    assert _all(
        db,
        "SELECT COUNT(*) FROM entity_matches WHERE canonical_entity_type='researcher' "
        "AND canonical_entity_id=2",
    ) == [(1,)]
    assert _all(
        db, "SELECT COUNT(*) FROM source_document_items WHERE item_type='person'"
    ) == [(1,)]


# --- merge log, permanent ids and the report ---


def _id_db(tmp_path):
    """A real schema with three articles: 1 and 2 are the same work (same
    content id, so they collide and carry ``~`` ids); 3 is unrelated."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.db.migrations import run_migrations
    from tests.test_horizon_id_assigner import SCHEMA

    path = tmp_path / "ids.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for row_id, title, year in (
        (1, "Coconut shell gasification", 2015),
        (2, "coconut shell gasification!", 2015),
        (3, "Impact of supplementation", 2019),
    ):
        conn.execute(
            "INSERT INTO articles (id, title, doi, year, type, journal_conference) "
            "VALUES (?, ?, '', ?, 'Journal', 'ABCM')",
            (row_id, title, year),
        )
    conn.commit()
    conn.close()
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        run_migrations(session)
    engine.dispose()
    return str(path)


def _assign(db):
    from src.adapters.database.horizon_id_store import SqliteHorizonIdStore
    from src.core.logic.horizon_id_assigner import HorizonIdAssigner

    HorizonIdAssigner(SqliteHorizonIdStore(db, snapshot_path="", zip_path="")).assign()


def _article_ids(db):
    return dict(
        _all(
            db,
            "SELECT entity_id, horizon_id FROM horizon_ids WHERE entity_type='article'",
        )
    )


def _aliases(db):
    return {
        alias: (target, reason)
        for alias, target, reason in _all(
            db, "SELECT alias_horizon_id, horizon_id, reason FROM horizon_id_aliases"
        )
    }


def test_merge_is_logged_with_the_losers_and_the_survivors_suffixed_ids(tmp_path):
    db = _id_db(tmp_path)
    _assign(db)
    before = _article_ids(db)
    assert "~" in before[1] and "~" in before[2]

    ReferenceConsolidator(db).consolidate_articles()

    (entity_type, candidates, winner) = _all(
        db,
        "SELECT entity_type, loser_candidate_ids, winner_entity_id FROM horizon_merge_log",
    )[0]
    candidates = json.loads(candidates)
    assert entity_type == "article" and winner == 1
    assert before[2] in candidates  # the loser's current id
    assert before[1] in candidates  # the survivor's suffixed id
    assert any(c.startswith("article:h:") and "~" not in c for c in candidates)


def test_old_ids_resolve_as_aliases_and_the_survivor_takes_the_bare_id(tmp_path):
    db = _id_db(tmp_path)
    _assign(db)
    before = _article_ids(db)

    ReferenceConsolidator(db).consolidate_articles()
    _assign(db)

    after = _article_ids(db)
    survivor = after[1]
    assert "~" not in survivor
    assert 2 not in after
    aliases = _aliases(db)
    for old in (before[1], before[2]):
        assert aliases[old] == (survivor, "merge")
    # SC-009: an article that is not in a merge keeps its id.
    assert after[3] == before[3]


def test_report_holds_counts_only(tmp_path, report_dir):
    db = _id_db(tmp_path)
    _assign(db)

    ReferenceConsolidator(db).consolidate_articles()

    report = json.loads((report_dir / "article_consolidation_report.json").read_text())
    assert set(report) == {
        "groups",
        "rows_merged",
        "skipped_conflicting_doi",
        "ids_aliased",
    }
    assert report["groups"] == 1 and report["rows_merged"] == 1
    assert report["skipped_conflicting_doi"] == 0
    assert report["ids_aliased"] == 2  # the loser's and the survivor's suffixed ids


def test_a_second_pass_changes_nothing_in_the_log(tmp_path, report_dir):
    db = _id_db(tmp_path)
    _assign(db)
    ReferenceConsolidator(db).consolidate_articles()
    log = _all(db, "SELECT * FROM horizon_merge_log")
    articles = _ids(db)

    second = ReferenceConsolidator(db).consolidate_articles()

    assert second.merged == 0
    assert _all(db, "SELECT * FROM horizon_merge_log") == log
    assert _ids(db) == articles
    report = json.loads((report_dir / "article_consolidation_report.json").read_text())
    assert report["groups"] == 0 and report["rows_merged"] == 0


def test_a_shared_non_doi_value_does_not_group_articles(tmp_path):
    # Spec 033: a Scopus link without a DOI is no DOI.
    link = "http://www.scopus.com/x?partnerID=x&doi=null&md5=f8a2"
    db = _db(
        tmp_path,
        [
            (1, "Work A", link, 2013, None, None),
            (2, "Work B", link, 2007, None, None),
            (3, "Work C", link, 2013, None, None),
        ],
    )

    stats = ReferenceConsolidator(db).consolidate_articles()

    assert _ids(db) == [1, 2, 3]
    assert stats.merged == 0
