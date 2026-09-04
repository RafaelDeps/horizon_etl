"""Database-backed regression tests for ProjectEnrichmentLoader.run().

These complement tests/test_project_enrichment.py, which covers the pure
(DB-free) helpers. The write path needs a real SQLAlchemy Session because the
defect these tests guard against was a Session lifecycle bug: run() opened an
explicit transaction after the index SELECTs had already autobegun one, so the
phase aborted with InvalidRequestError before touching a single document -- even
when there was nothing to process. A mocked session would not have caught it.

Everything here is self-contained: an in-memory SQLite database and PJ_*.json
fixtures written to tmp_path. No project database, no network, no Prefect
server, no Docker.
"""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.core.logic.project_enrichment import ProjectEnrichmentLoader

RESEARCH_PROJECT_TYPE = "Research Project"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def session():
    """In-memory schema mirroring only what run() touches.

    ``initiatives`` is deliberately created WITHOUT ``enrichment_json`` so that
    ensure_schema()/run_migrations() has real work to do, exercising the same
    migration path the phase takes against a fresh database.
    """
    engine = create_engine("sqlite:///:memory:")
    db = Session(engine)
    db.execute(
        text("CREATE TABLE initiative_types (id INTEGER PRIMARY KEY, name TEXT)")
    )
    db.execute(
        text(
            "CREATE TABLE initiatives ("
            " id INTEGER PRIMARY KEY,"
            " name TEXT,"
            " description TEXT,"
            " status TEXT,"
            " start_date DATETIME,"
            " end_date DATETIME,"
            " initiative_type_id INTEGER,"
            " organization_id INTEGER)"
        )
    )
    db.execute(
        text(
            "CREATE TABLE source_records ("
            " id INTEGER PRIMARY KEY,"
            " source_system TEXT,"
            " source_entity_type TEXT,"
            " raw_payload_json TEXT)"
        )
    )
    db.execute(
        text(
            "CREATE TABLE attribute_assertions ("
            " id INTEGER PRIMARY KEY,"
            " source_record_id INTEGER,"
            " canonical_entity_type TEXT,"
            " canonical_entity_id INTEGER)"
        )
    )
    db.execute(
        text(
            "CREATE TABLE entity_matches ("
            " id INTEGER PRIMARY KEY,"
            " source_record_id INTEGER,"
            " canonical_entity_type TEXT,"
            " canonical_entity_id INTEGER,"
            " match_strategy TEXT,"
            " match_confidence REAL)"
        )
    )
    db.execute(
        text("INSERT INTO initiative_types (id, name) VALUES (1, :n)"),
        {"n": RESEARCH_PROJECT_TYPE},
    )
    db.commit()
    yield db
    db.close()


@pytest.fixture
def loader(session):
    """Loader wired to the in-memory session.

    Built via __new__ on purpose: __init__ instantiates InitiativeController,
    which would connect to the database configured in DATABASE_URL. Since
    ``_session`` is just a property walking controller._service._repository,
    a plain namespace stands in for the whole chain.
    """
    instance = ProjectEnrichmentLoader.__new__(ProjectEnrichmentLoader)
    instance.overwrite = False
    instance.dry_run = False
    instance.controller = SimpleNamespace(
        _service=SimpleNamespace(_repository=SimpleNamespace(_session=session))
    )
    return instance


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def add_initiative(session, init_id, name, description=None):
    session.execute(
        text(
            "INSERT INTO initiatives (id, name, description, initiative_type_id) "
            "VALUES (:id, :n, :d, 1)"
        ),
        {"id": init_id, "n": name, "d": description},
    )
    session.commit()


def write_pj(tmp_path, filename, **fields):
    """Writes one PJ_*.json document, filling the shape run() expects."""
    document = {
        "codigo": None,
        "titulo": None,
        "descricao": None,
        "objetivos": {"geral": None, "especificos": []},
        "cronograma": [],
        "linha_pesquisa": None,
        "palavras_chave": [],
        "area_conhecimento": None,
        "datas": {},
        "_meta": {"arquivo": filename, "extraido_em": None, "modelo": None},
    }
    document.update(fields)
    path = tmp_path / filename
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def count_needing_review(session):
    return session.execute(
        text(
            "SELECT COUNT(*) FROM initiatives "
            "WHERE enrichment_json LIKE '%\"needs_review\": true%'"
        )
    ).scalar()


def read_initiative(session, init_id):
    row = session.execute(
        text("SELECT description, enrichment_json FROM initiatives WHERE id = :id"),
        {"id": init_id},
    ).fetchone()
    return row[0], (json.loads(row[1]) if row[1] else None)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_run_enriches_initiative_with_empty_description(loader, session, tmp_path):
    """FR-001/FR-002/FR-003: run() completes and persists the enrichment.

    This is the regression guard: before the fix, run() raised
    InvalidRequestError here instead of writing anything.
    """
    add_initiative(session, 1, "Estudo sobre redes neurais", description=None)
    write_pj(
        tmp_path,
        "PJ_1.json",
        titulo="Estudo sobre redes neurais",
        descricao="Investiga arquiteturas profundas.",
        objetivos={"geral": "Avaliar desempenho", "especificos": ["Comparar modelos"]},
        palavras_chave=["redes neurais"],
        linha_pesquisa="Inteligência Artificial",
    )

    stats = loader.run(str(tmp_path), ingest_new=False)

    assert stats["enriched"] == 1
    assert stats["by_title_exact"] == 1
    assert stats["desc_filled"] == 1
    assert stats["errors"] == 0

    description, enrichment = read_initiative(session, 1)
    assert description == "Investiga arquiteturas profundas."
    assert enrichment is not None
    assert enrichment["match_strategy"] == "title_exact"
    assert enrichment["needs_review"] is False
    assert enrichment["objetivos"]["geral"] == "Avaliar desempenho"
    assert enrichment["linha_pesquisa"] == "Inteligência Artificial"


def test_run_preserves_existing_description(loader, session, tmp_path):
    """FR-003: an authoritative description is never overwritten."""
    add_initiative(session, 1, "Projeto com resumo", description="Resumo oficial.")
    write_pj(
        tmp_path,
        "PJ_1.json",
        titulo="Projeto com resumo",
        descricao="Texto extraído do documento.",
        objetivos={"geral": "Objetivo do documento", "especificos": []},
    )

    stats = loader.run(str(tmp_path), ingest_new=False)

    assert stats["enriched"] == 1
    assert stats["desc_filled"] == 0
    assert stats["desc_kept_existing"] == 1

    description, enrichment = read_initiative(session, 1)
    assert description == "Resumo oficial."
    assert enrichment["objetivos"]["geral"] == "Objetivo do documento"


def test_run_with_no_documents_completes(loader, session, tmp_path):
    """FR-001: zero documents is a success, not a failure.

    The defect hit this path too -- the phase aborted before ever checking
    whether there was anything to do.
    """
    add_initiative(session, 1, "Projeto intocado", description=None)

    stats = loader.run(str(tmp_path), ingest_new=False)

    assert stats["enriched"] == 0
    assert stats["skipped_no_match"] == 0
    assert stats["errors"] == 0

    description, enrichment = read_initiative(session, 1)
    assert description is None
    assert enrichment is None


def test_dry_run_writes_nothing(loader, session, tmp_path):
    """FR-006: dry run reports what it would do and touches nothing."""
    loader.dry_run = True
    add_initiative(session, 1, "Projeto simulado", description=None)
    write_pj(
        tmp_path,
        "PJ_1.json",
        titulo="Projeto simulado",
        descricao="Descrição que não deve ser gravada.",
        objetivos={"geral": "Objetivo", "especificos": []},
    )

    stats = loader.run(str(tmp_path), ingest_new=False)

    assert stats["enriched"] == 1

    description, enrichment = read_initiative(session, 1)
    assert description is None
    assert enrichment is None


def test_unmatched_document_is_counted_not_written(loader, session, tmp_path):
    """A document matching nothing is skipped without failing the run."""
    add_initiative(session, 1, "Projeto existente", description=None)
    write_pj(
        tmp_path,
        "PJ_1.json",
        titulo="Título que não existe no banco",
        descricao="Conteúdo irrelevante.",
    )

    stats = loader.run(str(tmp_path), ingest_new=False)

    assert stats["enriched"] == 0
    assert stats["skipped_no_match"] == 1

    description, enrichment = read_initiative(session, 1)
    assert description is None
    assert enrichment is None


# --------------------------------------------------------------------------- #
# Origin & review persistence (feature 006)
# --------------------------------------------------------------------------- #
def test_rerun_does_not_shrink_the_review_backlog(loader, session, tmp_path):
    """THE test for this feature: re-running must never downgrade the flag.

    Reproduces the observed defect. Run 1 invents an initiative from an
    unmatched document and flags it. Run 2 finds that initiative by exact title
    -- a trustworthy strategy -- and used to overwrite the flag with False. On
    the real database this took the count from 96 down to 49.
    """
    write_pj(
        tmp_path,
        "PJ_1.json",
        titulo="Projeto inventado do documento",
        descricao="Descricao rica o suficiente.",
        objetivos={"geral": "Objetivo geral", "especificos": []},
    )
    # Run 1: no matching initiative exists -> created from the document.
    add_initiative(session, 1, "Outro projeto qualquer", description="x")
    first = loader.run(str(tmp_path), ingest_new=False)
    assert first["enriched"] == 0, "nothing to match yet"

    # Simulate the creation the ingest path would do, flagged as such.
    session.execute(
        text(
            "INSERT INTO initiatives (id, name, description, initiative_type_id, "
            "enrichment_json) VALUES (2, :n, :d, 1, :j)"
        ),
        {
            "n": "Projeto inventado do documento",
            "d": "Descricao rica o suficiente.",
            "j": json.dumps(
                {
                    "source": "sigpesq_project_files",
                    "match_strategy": "new_from_document",
                    "origin": "new_from_document",
                    "needs_review": True,
                }
            ),
        },
    )
    session.commit()
    before = count_needing_review(session)
    assert before == 1

    # Run 2: now it matches by exact title.
    stats = loader.run(str(tmp_path), ingest_new=False)

    assert stats["by_title_exact"] == 1
    assert count_needing_review(session) >= before, "the backlog must not shrink"

    _, enrichment = read_initiative(session, 2)
    assert enrichment["needs_review"] is True
    assert enrichment["origin"] == "new_from_document"
    assert enrichment["match_strategy"] == "title_exact", "current run recorded"


def test_reviewed_initiative_stays_reviewed_across_reruns(loader, session, tmp_path):
    """FR-006: only a human review clears the flag, and it sticks."""
    loader.ensure_schema()  # the fixture omits the column on purpose
    write_pj(
        tmp_path,
        "PJ_1.json",
        titulo="Projeto revisado",
        descricao="Conteudo.",
        objetivos={"geral": "g", "especificos": []},
    )
    session.execute(
        text(
            "INSERT INTO initiatives (id, name, description, initiative_type_id, "
            "enrichment_json) VALUES (1, :n, :d, 1, :j)"
        ),
        {
            "n": "Projeto revisado",
            "d": "Conteudo.",
            "j": json.dumps(
                {
                    "source": "sigpesq_project_files",
                    "match_strategy": "new_from_document",
                    "origin": "new_from_document",
                    "needs_review": True,
                }
            ),
        },
    )
    session.commit()

    assert loader.mark_reviewed(1, "MAT-4321") is True
    _, after_review = read_initiative(session, 1)
    assert after_review["needs_review"] is False
    assert after_review["reviewed_by"] == "MAT-4321"
    assert after_review["origin"] == "new_from_document", "review keeps history"

    loader.run(str(tmp_path), ingest_new=False)

    _, after_rerun = read_initiative(session, 1)
    assert after_rerun["needs_review"] is False, "must not be re-flagged"
    assert after_rerun["reviewed_by"] == "MAT-4321"


def test_backfill_restores_origin_from_the_audit_trail(loader, session):
    """FR-009: repair a database whose payloads already lost the origin."""
    loader.ensure_schema()  # the fixture omits the column on purpose
    session.execute(
        text(
            "INSERT INTO initiatives (id, name, initiative_type_id, enrichment_json) "
            "VALUES (7, 'Projeto sem origem', 1, :j)"
        ),
        {
            "j": json.dumps(
                {
                    "source": "sigpesq_project_files",
                    "match_strategy": "title_exact",
                    "needs_review": False,
                }
            )
        },
    )
    session.execute(
        text(
            "INSERT INTO source_records (id, source_system, source_entity_type) "
            "VALUES (1, 'sigpesq_project_files', 'initiative')"
        )
    )
    session.execute(
        text(
            "INSERT INTO entity_matches (id, source_record_id, canonical_entity_type, "
            "canonical_entity_id, match_strategy) "
            "VALUES (1, 1, 'initiative', 7, 'new_from_document')"
        )
    )
    session.commit()

    stats = loader.backfill_origin_from_tracking()

    assert stats["candidates"] == 1
    assert stats["repaired"] == 1

    _, enrichment = read_initiative(session, 7)
    assert enrichment["origin"] == "new_from_document"
    assert enrichment["needs_review"] is True, "restored origin re-raises the flag"
