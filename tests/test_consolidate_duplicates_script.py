import sqlite3
from pathlib import Path

from src.scripts.consolidate_duplicates import build_report, execute


def test_build_report_and_execute_for_references(tmp_path: Path):
    db_path = tmp_path / "consolidate.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, identification_id TEXT);
        CREATE TABLE researchers (id INTEGER PRIMARY KEY, cnpq_url TEXT, google_scholar_url TEXT, resume TEXT, citation_names TEXT);
        CREATE TABLE person_emails (id INTEGER PRIMARY KEY, person_id INTEGER, email TEXT);
        CREATE TABLE advisorships (id INTEGER PRIMARY KEY, fellowship_id INTEGER, institution_id INTEGER);
        CREATE TABLE advisorship_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            advisorship_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL,
            role_id INTEGER,
            role_name TEXT,
            start_date DATETIME,
            end_date DATETIME
        );
        CREATE TABLE academic_educations (
            id INTEGER PRIMARY KEY,
            researcher_id INTEGER NOT NULL,
            education_type_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            start_year INTEGER NOT NULL,
            end_year INTEGER,
            thesis_title TEXT,
            institution_id INTEGER NOT NULL,
            advisor_id INTEGER,
            co_advisor_id INTEGER
        );
        CREATE TABLE article_authors (article_id INTEGER NOT NULL, researcher_id INTEGER NOT NULL, PRIMARY KEY (article_id, researcher_id));
        CREATE TABLE researcher_knowledge_areas (researcher_id INTEGER NOT NULL, area_id INTEGER NOT NULL, PRIMARY KEY (researcher_id, area_id));
        CREATE TABLE initiative_persons (initiative_id INTEGER NOT NULL, person_id INTEGER NOT NULL, PRIMARY KEY (initiative_id, person_id));
        CREATE TABLE organization_persons (organization_id INTEGER NOT NULL, person_id INTEGER NOT NULL, PRIMARY KEY (organization_id, person_id));
        CREATE TABLE knowledge_areas (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE group_knowledge_areas (group_id INTEGER NOT NULL, area_id INTEGER NOT NULL, PRIMARY KEY (group_id, area_id));
        CREATE TABLE initiative_knowledge_areas (initiative_id INTEGER NOT NULL, area_id INTEGER NOT NULL, PRIMARY KEY (initiative_id, area_id));
        CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT, short_name TEXT, organization_id INTEGER);
        CREATE TABLE team_members (id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER NOT NULL, team_id INTEGER NOT NULL, role_id INTEGER, start_date DATETIME, end_date DATETIME);
        CREATE TABLE initiative_teams (initiative_id INTEGER NOT NULL, team_id INTEGER NOT NULL, PRIMARY KEY (initiative_id, team_id));
        CREATE TABLE research_groups (id INTEGER PRIMARY KEY, campus_id INTEGER, cnpq_url TEXT, site TEXT, start_date DATETIME);
        """
    )
    conn.execute("INSERT INTO teams (id, name) VALUES (1, 'Conecta FAPES')")
    conn.execute("INSERT INTO teams (id, name) VALUES (2, 'Conecta Fapes')")
    conn.execute("INSERT INTO knowledge_areas (id, name) VALUES (1, 'Física')")
    conn.execute("INSERT INTO knowledge_areas (id, name) VALUES (2, 'Fisica')")
    conn.commit()
    conn.close()

    report = build_report(str(db_path), "references")
    result = execute(str(db_path), "references")

    assert report["team_duplicate_groups"] == 1
    assert report["knowledge_area_duplicate_groups"] == 1
    assert result["teams_merged"] == 1
    assert result["knowledge_areas_merged"] == 1


# --- Spec 029: the weekly consolidation also merges duplicate articles ---


class _FakePersonConsolidator:
    def __init__(self, *_args, **_kwargs):
        pass

    def find_all_groups(self):
        return []

    def build_report(self, groups=None):
        return {"refused_groups": 0}

    def consolidate_all(self):
        return 0


def _articles_db(tmp_path: Path) -> str:
    path = tmp_path / "weekly.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, doi TEXT, year INTEGER NOT NULL,
            type TEXT NOT NULL, journal_conference TEXT, volume TEXT, pages TEXT);
        INSERT INTO articles (id, title, year, type) VALUES
            (1, 'Same Work', 2020, 'journal'), (2, 'same work', 2020, 'journal'),
            (3, 'Another Work', 2020, 'journal');
        """
    )
    conn.commit()
    conn.close()
    return str(path)


def test_weekly_consolidation_merges_duplicate_articles_and_writes_the_report(
    tmp_path: Path, monkeypatch
):
    from src.scripts import consolidate_duplicates

    monkeypatch.setattr(
        consolidate_duplicates, "PersonConsolidator", _FakePersonConsolidator
    )
    db = _articles_db(tmp_path)
    reports = tmp_path / "reports"

    result = consolidate_duplicates.run_person_dedup(db, str(reports))

    conn = sqlite3.connect(db)
    assert [r[0] for r in conn.execute("SELECT id FROM articles ORDER BY id")] == [1, 3]
    conn.close()
    assert result["articles"]["rows_merged"] == 1
    assert (reports / "article_consolidation_report.json").exists()
    assert (reports / "dedup_report.json").exists()


def test_a_failing_article_consolidation_does_not_crash_the_weekly_phase(
    tmp_path: Path, monkeypatch
):
    from src.core.logic.reference_consolidator import ReferenceConsolidator
    from src.scripts import consolidate_duplicates

    monkeypatch.setattr(
        consolidate_duplicates, "PersonConsolidator", _FakePersonConsolidator
    )

    def boom(self, *args, **kwargs):
        raise sqlite3.OperationalError("boom")

    monkeypatch.setattr(ReferenceConsolidator, "consolidate_articles", boom)
    reports = tmp_path / "reports"

    result = consolidate_duplicates.run_person_dedup(
        _articles_db(tmp_path), str(reports)
    )

    assert result["records_merged"] == 0
    assert "error" in result["articles"]
    assert (reports / "dedup_report.json").exists()


def test_person_dedup_keeps_document_links_and_linkedin_links_of_merged_persons(
    tmp_path, monkeypatch
):
    # Spec 037: the LinkedIn link of a merged person stays with the survivor.
    from unittest.mock import MagicMock

    from src.adapters.database.document_item_store import repoint_person_links
    from src.adapters.database.linkedin_link_store import repoint_linkedin_link
    from src.scripts import consolidate_duplicates as module

    consolidator = MagicMock()
    consolidator.return_value.build_report.return_value = {"refused_groups": 0}
    consolidator.return_value.consolidate_all.return_value = 0
    monkeypatch.setattr(module, "PersonConsolidator", consolidator)
    monkeypatch.setattr(module, "_consolidate_articles", lambda *_: {})
    monkeypatch.setattr(module, "_write_report", lambda *_: "report.json")

    module.run_person_dedup(str(tmp_path / "x.db"), str(tmp_path))

    assert consolidator.call_args.kwargs["merge_hooks"] == [
        repoint_person_links,
        repoint_linkedin_link,
    ]
