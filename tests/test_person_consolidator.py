import json
import sqlite3
from pathlib import Path

from src.core.logic.person_consolidator import PersonConsolidator

SCHEMA_SQL = """
CREATE TABLE persons (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    identification_id VARCHAR,
    birthday DATE
);
CREATE TABLE researchers (
    id INTEGER PRIMARY KEY,
    cnpq_url VARCHAR(255),
    google_scholar_url VARCHAR(255),
    resume VARCHAR,
    citation_names VARCHAR(500)
);
CREATE TABLE person_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    email VARCHAR NOT NULL
);
CREATE TABLE advisorships (
    id INTEGER PRIMARY KEY,
    fellowship_id INTEGER,
    institution_id INTEGER
);
CREATE TABLE advisorship_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    advisorship_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    role_id INTEGER,
    role_name VARCHAR(50),
    start_date DATETIME,
    end_date DATETIME
);
CREATE TABLE academic_educations (
    id INTEGER PRIMARY KEY,
    researcher_id INTEGER NOT NULL,
    education_type_id INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    start_year INTEGER NOT NULL,
    end_year INTEGER,
    thesis_title VARCHAR(500),
    institution_id INTEGER NOT NULL,
    advisor_id INTEGER,
    co_advisor_id INTEGER
);
CREATE TABLE article_authors (
    article_id INTEGER NOT NULL,
    researcher_id INTEGER NOT NULL,
    PRIMARY KEY (article_id, researcher_id)
);
CREATE TABLE researcher_knowledge_areas (
    researcher_id INTEGER NOT NULL,
    area_id INTEGER NOT NULL,
    PRIMARY KEY (researcher_id, area_id)
);
CREATE TABLE initiative_persons (
    initiative_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    PRIMARY KEY (initiative_id, person_id)
);
CREATE TABLE organization_persons (
    organization_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    PRIMARY KEY (organization_id, person_id)
);
CREATE TABLE team_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    role_id INTEGER,
    start_date DATETIME,
    end_date DATETIME
);
"""


def test_consolidate_pair_moves_links_and_removes_loser(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)

    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES (2981, 'Paulo Sergio dos Santos Junior', '8400407353673370')"
    )
    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES (452, 'Paulo Sérgio Dos Santos Júnior', NULL)"
    )
    conn.execute(
        "INSERT INTO researchers (id, cnpq_url, resume) VALUES (2981, 'http://lattes.cnpq.br/8400407353673370', 'resume ok')"
    )
    conn.execute("INSERT INTO researchers (id) VALUES (452)")
    conn.execute(
        "INSERT INTO person_emails (person_id, email) VALUES (452, 'paulo@example.com')"
    )
    conn.execute("INSERT INTO advisorships (id) VALUES (1)")
    conn.execute(
        "INSERT INTO advisorship_members (advisorship_id, person_id, role_name) VALUES (1, 452, 'Supervisor')"
    )
    conn.execute(
        "INSERT INTO academic_educations (id, researcher_id, education_type_id, title, start_year, institution_id) VALUES (1, 452, 1, 'Mestrado', 2007, 1)"
    )
    conn.execute(
        "INSERT INTO article_authors (article_id, researcher_id) VALUES (10, 452)"
    )
    conn.execute(
        "INSERT INTO researcher_knowledge_areas (researcher_id, area_id) VALUES (452, 99)"
    )
    conn.execute(
        "INSERT INTO initiative_persons (initiative_id, person_id) VALUES (77, 452)"
    )
    conn.execute(
        "INSERT INTO organization_persons (organization_id, person_id) VALUES (88, 452)"
    )
    conn.execute(
        "INSERT INTO team_members (person_id, team_id, role_id) VALUES (452, 55, 2)"
    )
    conn.commit()
    conn.close()

    consolidator = PersonConsolidator(str(db_path))
    consolidator.consolidate_pair(2981, 452)

    check = sqlite3.connect(db_path)
    cur = check.cursor()
    assert cur.execute("SELECT COUNT(*) FROM persons WHERE id = 452").fetchone()[0] == 0
    assert (
        cur.execute("SELECT COUNT(*) FROM researchers WHERE id = 452").fetchone()[0]
        == 0
    )
    assert (
        cur.execute(
            "SELECT person_id FROM advisorship_members WHERE advisorship_id = 1 AND role_name = 'Supervisor'"
        ).fetchone()[0]
        == 2981
    )
    assert (
        cur.execute(
            "SELECT researcher_id FROM academic_educations WHERE id = 1"
        ).fetchone()[0]
        == 2981
    )
    assert (
        cur.execute(
            "SELECT researcher_id FROM article_authors WHERE article_id = 10"
        ).fetchone()[0]
        == 2981
    )
    assert (
        cur.execute(
            "SELECT researcher_id FROM researcher_knowledge_areas WHERE area_id = 99"
        ).fetchone()[0]
        == 2981
    )
    assert (
        cur.execute(
            "SELECT person_id FROM initiative_persons WHERE initiative_id = 77"
        ).fetchone()[0]
        == 2981
    )
    assert (
        cur.execute(
            "SELECT person_id FROM organization_persons WHERE organization_id = 88"
        ).fetchone()[0]
        == 2981
    )
    assert (
        cur.execute("SELECT person_id FROM team_members WHERE team_id = 55").fetchone()[
            0
        ]
        == 2981
    )
    assert (
        cur.execute(
            "SELECT person_id FROM person_emails WHERE email = 'paulo@example.com'"
        ).fetchone()[0]
        == 2981
    )


def test_consolidate_all_merges_detected_duplicate_groups(tmp_path: Path):
    db_path = tmp_path / "test_all.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES (1, 'Gustavo Maia De Almeida', 'gustavo@ifes.edu.br')"
    )
    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES (2, 'Gustavo Maia de Almeida', 'Gustavo Maia de Almeida')"
    )
    conn.execute("INSERT INTO researchers (id, resume) VALUES (1, 'resume')")
    conn.execute("INSERT INTO researchers (id) VALUES (2)")
    conn.commit()
    conn.close()

    merged = PersonConsolidator(str(db_path)).consolidate_all()

    check = sqlite3.connect(db_path)
    cur = check.cursor()
    assert merged == 1
    assert cur.execute("SELECT COUNT(*) FROM persons").fetchone()[0] == 1
    assert cur.execute("SELECT id FROM persons").fetchone()[0] == 1


def test_find_duplicate_groups_prefers_real_identifier_over_name_identifier(
    tmp_path: Path,
):
    db_path = tmp_path / "quality.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES (1, 'Carlos Roberto Pires Campos', 'carlosr@ifes.edu.br')"
    )
    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES (2, 'Carlos Roberto Pires Campos', 'Carlos Roberto Pires Campos')"
    )
    conn.execute(
        "INSERT INTO person_emails (person_id, email) VALUES (1, 'carlosr@ifes.edu.br')"
    )
    conn.commit()
    conn.close()

    groups = PersonConsolidator(str(db_path)).find_duplicate_groups()

    assert len(groups) == 1
    assert groups[0].winner_id == 1
    assert groups[0].loser_ids == [2]


def test_consolidate_pair_transfers_identification_id_without_unique_conflict(
    tmp_path: Path,
):
    db_path = tmp_path / "unique_id.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "CREATE UNIQUE INDEX uq_person_identification_id ON persons(identification_id)"
    )
    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES (1, 'Pessoa A', NULL)"
    )
    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES (2, 'Pessoa A', 'pessoa@ifes.edu.br')"
    )
    conn.commit()
    conn.close()

    PersonConsolidator(str(db_path)).consolidate_pair(1, 2)

    check = sqlite3.connect(db_path)
    cur = check.cursor()
    assert (
        cur.execute("SELECT identification_id FROM persons WHERE id = 1").fetchone()[0]
        == "pessoa@ifes.edu.br"
    )
    assert cur.execute("SELECT COUNT(*) FROM persons WHERE id = 2").fetchone()[0] == 0


def test_consolidate_pair_reassigns_email_without_unique_conflict(tmp_path: Path):
    db_path = tmp_path / "unique_email.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "CREATE UNIQUE INDEX ux_person_emails_lower_email ON person_emails(lower(email))"
    )
    conn.execute("INSERT INTO persons (id, name) VALUES (1, 'Pessoa A')")
    conn.execute("INSERT INTO persons (id, name) VALUES (2, 'Pessoa A')")
    conn.execute(
        "INSERT INTO person_emails (person_id, email) VALUES (2, 'pessoa@ifes.edu.br')"
    )
    conn.commit()
    conn.close()

    PersonConsolidator(str(db_path)).consolidate_pair(1, 2)

    check = sqlite3.connect(db_path)
    cur = check.cursor()
    assert (
        cur.execute(
            "SELECT person_id FROM person_emails WHERE lower(email) = lower('pessoa@ifes.edu.br')"
        ).fetchone()[0]
        == 1
    )
    assert cur.execute("SELECT COUNT(*) FROM persons WHERE id = 2").fetchone()[0] == 0


def _israel_pair_db(tmp_path: Path, name: str) -> Path:
    db_path = tmp_path / name
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO persons (id, name) VALUES (1, 'Israel Magalhães do Carmo')"
    )
    conn.execute(
        "INSERT INTO persons (id, name) VALUES (2, 'Israel Magalhães do Carmo')"
    )
    for advisorship_id in (11, 12, 13, 14, 15):
        conn.execute(
            "INSERT INTO advisorship_members (advisorship_id, person_id, role_name) "
            "VALUES (?, 1, 'Estudante')",
            (advisorship_id,),
        )
    conn.execute(
        "INSERT INTO team_members (person_id, team_id, role_id) VALUES (2, 55, 2)"
    )
    conn.commit()
    conn.close()
    return db_path


def test_observed_pair_merges_into_one_record_with_union_of_data(tmp_path: Path):
    """Scenario A: the Israel pair (rich record + group-only record) becomes one
    person holding both the five initiatives and the research-group membership."""
    db_path = _israel_pair_db(tmp_path, "israel.db")

    merged = PersonConsolidator(str(db_path)).consolidate_all()
    assert merged == 1

    check = sqlite3.connect(db_path)
    cur = check.cursor()
    assert cur.execute("SELECT COUNT(*) FROM persons").fetchone()[0] == 1
    assert cur.execute("SELECT id FROM persons").fetchone()[0] == 1
    assert (
        cur.execute(
            "SELECT COUNT(*) FROM advisorship_members WHERE person_id = 1"
        ).fetchone()[0]
        == 5
    )
    assert (
        cur.execute("SELECT person_id FROM team_members WHERE team_id = 55").fetchone()[
            0
        ]
        == 1
    )


def test_union_transfers_complementary_initiative_data(tmp_path: Path):
    """Scenario D: record A holds advisorship X, record B holds project Y and a
    research-group membership; the winner ends with all of them."""
    db_path = tmp_path / "union.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO persons (id, name) VALUES (1, 'Pessoa A')")
    conn.execute("INSERT INTO persons (id, name) VALUES (2, 'Pessoa A')")
    conn.execute(
        "INSERT INTO advisorship_members (advisorship_id, person_id, role_name) "
        "VALUES (100, 1, 'Estudante')"
    )
    conn.execute(
        "INSERT INTO initiative_persons (initiative_id, person_id) VALUES (200, 2)"
    )
    conn.execute(
        "INSERT INTO team_members (person_id, team_id, role_id) VALUES (2, 55, 2)"
    )
    conn.commit()
    conn.close()

    PersonConsolidator(str(db_path)).consolidate_pair(1, 2)

    check = sqlite3.connect(db_path)
    cur = check.cursor()
    assert (
        cur.execute(
            "SELECT COUNT(*) FROM advisorship_members WHERE person_id = 1"
        ).fetchone()[0]
        == 1
    )
    assert (
        cur.execute(
            "SELECT person_id FROM initiative_persons WHERE initiative_id = 200"
        ).fetchone()[0]
        == 1
    )
    assert (
        cur.execute("SELECT person_id FROM team_members WHERE team_id = 55").fetchone()[
            0
        ]
        == 1
    )


def test_identical_shared_link_stays_once(tmp_path: Path):
    db_path = tmp_path / "shared.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO persons (id, name) VALUES (1, 'Pessoa A')")
    conn.execute("INSERT INTO persons (id, name) VALUES (2, 'Pessoa A')")
    conn.execute(
        "INSERT INTO initiative_persons (initiative_id, person_id) VALUES (77, 1)"
    )
    conn.execute(
        "INSERT INTO initiative_persons (initiative_id, person_id) VALUES (77, 2)"
    )
    conn.commit()
    conn.close()

    PersonConsolidator(str(db_path)).consolidate_pair(1, 2)

    check = sqlite3.connect(db_path)
    cur = check.cursor()
    assert (
        cur.execute(
            "SELECT COUNT(*) FROM initiative_persons WHERE initiative_id = 77"
        ).fetchone()[0]
        == 1
    )
    assert (
        cur.execute(
            "SELECT person_id FROM initiative_persons WHERE initiative_id = 77"
        ).fetchone()[0]
        == 1
    )


def test_consolidation_is_idempotent(tmp_path: Path):
    db_path = _israel_pair_db(tmp_path, "idem.db")
    consolidator = PersonConsolidator(str(db_path))
    assert consolidator.consolidate_all() == 1
    assert consolidator.consolidate_all() == 0


def test_simultaneous_advisorships_under_same_advisor_survive(tmp_path: Path):
    """Scenario E: overlapping advisorships and a shared researcher are normal;
    the merge must preserve every initiative, never collapse by time or advisor."""
    db_path = tmp_path / "simul.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO persons (id, name) VALUES (1, 'Pessoa A')")
    conn.execute("INSERT INTO persons (id, name) VALUES (2, 'Pessoa A')")
    conn.execute("INSERT INTO advisorships (id) VALUES (1)")
    conn.execute("INSERT INTO advisorships (id) VALUES (2)")
    conn.execute(
        "INSERT INTO advisorship_members (advisorship_id, person_id, role_name) "
        "VALUES (1, 1, 'Estudante')"
    )
    conn.execute(
        "INSERT INTO advisorship_members (advisorship_id, person_id, role_name) "
        "VALUES (2, 2, 'Estudante')"
    )
    conn.commit()
    conn.close()

    PersonConsolidator(str(db_path)).consolidate_pair(1, 2)

    check = sqlite3.connect(db_path)
    cur = check.cursor()
    assert (
        cur.execute(
            "SELECT COUNT(*) FROM advisorship_members WHERE person_id = 1"
        ).fetchone()[0]
        == 2
    )
    assert cur.execute(
        "SELECT advisorship_id FROM advisorship_members WHERE person_id = 1"
    ).fetchall() == [(1,), (2,)]


def test_same_researcher_across_initiatives_keeps_every_initiative(tmp_path: Path):
    db_path = tmp_path / "same_res.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO persons (id, name) VALUES (1, 'Pessoa A')")
    conn.execute("INSERT INTO persons (id, name) VALUES (2, 'Pessoa A')")
    for initiative_id in (31, 32, 33):
        conn.execute(
            "INSERT INTO initiative_persons (initiative_id, person_id) VALUES (?, 2)",
            (initiative_id,),
        )
    conn.commit()
    conn.close()

    PersonConsolidator(str(db_path)).consolidate_pair(1, 2)

    check = sqlite3.connect(db_path)
    cur = check.cursor()
    assert cur.execute(
        "SELECT initiative_id FROM initiative_persons WHERE person_id = 1"
    ).fetchall() == [(31,), (32,), (33,)]


def _two_jose_silva(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO persons (id, name) VALUES (1, 'José da Silva')")
    conn.execute("INSERT INTO persons (id, name) VALUES (2, 'José da Silva')")
    conn.commit()
    conn.close()


def test_homonyms_with_distinct_lattes_urls_are_never_merged(tmp_path: Path):
    """Scenario F: conflicting strong identifiers veto the merge entirely."""
    db_path = tmp_path / "homonym_cnpq.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO persons (id, name) VALUES (1, 'José da Silva')")
    conn.execute("INSERT INTO persons (id, name) VALUES (2, 'José da Silva')")
    conn.execute(
        "INSERT INTO researchers (id, cnpq_url) VALUES "
        "(1, 'http://lattes.cnpq.br/1111111111111111')"
    )
    conn.execute(
        "INSERT INTO researchers (id, cnpq_url) VALUES "
        "(2, 'http://lattes.cnpq.br/2222222222222222')"
    )
    conn.commit()
    conn.close()

    consolidator = PersonConsolidator(str(db_path))
    assert consolidator.consolidate_all() == 0
    assert consolidator.find_duplicate_groups() == []
    assert consolidator.build_report()["refused_groups"] == 1
    refused = consolidator.build_report()["groups"][0]
    assert refused["status"] == "refused_homonym"
    assert "cnpq_url" in refused["reason"]


def test_homonyms_with_distinct_identification_ids_are_never_merged(tmp_path: Path):
    db_path = tmp_path / "homonym_ident.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES "
        "(1, 'José da Silva', 'jose@ifes.edu.br')"
    )
    conn.execute(
        "INSERT INTO persons (id, name, identification_id) VALUES "
        "(2, 'José da Silva', 'jose2@ifes.edu.br')"
    )
    conn.commit()
    conn.close()

    consolidator = PersonConsolidator(str(db_path))
    assert consolidator.consolidate_all() == 0
    refused = consolidator.build_report()["groups"][0]
    assert refused["status"] == "refused_homonym"
    assert "identification_id" in refused["reason"]


def test_junk_names_are_never_merged(tmp_path: Path):
    """Scenario G: honorific-only records are refused, never fused."""
    db_path = tmp_path / "junk.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO persons (id, name) VALUES (1, 'Dr')")
    conn.execute("INSERT INTO persons (id, name) VALUES (2, 'Dr')")
    conn.commit()
    conn.close()

    consolidator = PersonConsolidator(str(db_path))
    assert consolidator.consolidate_all() == 0
    assert consolidator.find_duplicate_groups() == []
    refused = consolidator.build_report()["groups"][0]
    assert refused["status"] == "refused_junk"


def test_dedup_report_lists_merged_and_refused_groups(tmp_path: Path):
    db_path = _israel_pair_db(tmp_path, "report_merge.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO researchers (id, cnpq_url) VALUES (9, 'http://lattes.cnpq.br/9')"
    )
    conn.execute("INSERT INTO persons (id, name) VALUES (9, 'Fulano Ciclano')")
    conn.execute("INSERT INTO persons (id, name) VALUES (10, 'Fulano Ciclano')")
    conn.execute(
        "INSERT INTO researchers (id, cnpq_url) VALUES (10, 'http://lattes.cnpq.br/10')"
    )
    conn.commit()
    conn.close()

    consolidator = PersonConsolidator(str(db_path))
    report = consolidator.build_report()

    assert report["merged_groups"] == 1
    assert report["merged_records"] == 1
    assert report["refused_groups"] == 1
    statuses = {g["canonical_name"]: g["status"] for g in report["groups"]}
    assert statuses["ISRAEL MAGALHAES do CARMO"] == "merged"
    assert statuses["FULANO CICLANO"] == "refused_homonym"


def test_weekly_phase_report_artifact_records_merged_and_refused(tmp_path: Path):
    db_path = _israel_pair_db(tmp_path, "phase_report.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO researchers (id, cnpq_url) VALUES (9, 'http://lattes.cnpq.br/9')"
    )
    conn.execute("INSERT INTO persons (id, name) VALUES (9, 'Fulano Ciclano')")
    conn.execute("INSERT INTO persons (id, name) VALUES (10, 'Fulano Ciclano')")
    conn.execute(
        "INSERT INTO researchers (id, cnpq_url) VALUES (10, 'http://lattes.cnpq.br/10')"
    )
    conn.commit()
    conn.close()

    from src.scripts.consolidate_duplicates import run_person_dedup

    report_dir = tmp_path / "reports"
    run_person_dedup(db_path=str(db_path), report_dir=str(report_dir))

    artifact = report_dir / "dedup_report.json"
    assert artifact.exists()
    loaded = json.loads(artifact.read_text(encoding="utf-8"))
    assert loaded["merged_groups"] == 1
    assert loaded["merged_records"] == 1
    assert loaded["refused_groups"] == 1
    by_name = {g["canonical_name"]: g for g in loaded["groups"]}
    assert by_name["ISRAEL MAGALHAES do CARMO"]["status"] == "merged"
    assert by_name["FULANO CICLANO"]["status"] == "refused_homonym"
    assert "cnpq_url" in by_name["FULANO CICLANO"]["reason"]
