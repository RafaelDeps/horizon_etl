"""Unit tests for the pure (DB-free) logic of ProjectEnrichmentLoader.

The write path -- run() against a real Session -- is covered separately in
tests/test_project_enrichment_db.py. Keep this file DB-free: the split exists
because a Session lifecycle bug once survived precisely by living outside the
reach of these tests.
"""

from datetime import datetime

import pytest

from src.core.logic.project_enrichment import (
    ORIGIN_MATCHED_EXISTING,
    ORIGIN_NEW_FROM_DOCUMENT,
    Candidate,
    Match,
    build_enrichment,
    compose_description,
    derive_needs_review,
    derive_status,
    is_ingestable,
    match_pj,
    normalize_project_code,
    origin_from_prior,
    parse_sql_datetime,
    resolve_claims,
)


# --------------------------------------------------------------- normalize_project_code
@pytest.mark.parametrize(
    "value,expected",
    [
        ("PJ 6020", "6020"),
        ("PJ_6020", "6020"),
        ("6020", "6020"),
        ("PJ abc", ""),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize_project_code(value, expected):
    assert normalize_project_code(value) == expected


# --------------------------------------------------------------- compose_description
def test_compose_description_prefers_descricao():
    pj = {"descricao": "  resumo  ", "objetivos": {"geral": "obj"}}
    assert compose_description(pj) == "resumo"


def test_compose_description_falls_back_to_objetivo_geral():
    pj = {"descricao": "", "objetivos": {"geral": " meta geral "}}
    assert compose_description(pj) == "meta geral"


def test_compose_description_none_when_empty():
    assert compose_description({"descricao": "", "objetivos": {}}) is None
    assert compose_description({}) is None


# --------------------------------------------------------------- build_enrichment
def test_build_enrichment_shape():
    pj = {
        "objetivos": {"geral": "g", "especificos": ["a"]},
        "cronograma": [{"atividade": "x"}],
        "linha_pesquisa": "PLN",
        "palavras_chave": ["k"],
        "area_conhecimento": "CC",
        "_meta": {
            "extraido_em": "2026-07-18",
            "modelo": "mistral",
            "arquivo": "PJ_1.pdf",
        },
    }
    e = build_enrichment(pj, code="6020", strategy="title_fuzzy", match_uncertain=True)
    assert e["project_code"] == "6020"
    assert e["match_strategy"] == "title_fuzzy"
    assert e["needs_review"] is True
    assert e["objetivos"]["especificos"] == ["a"]
    assert e["cronograma"][0]["atividade"] == "x"
    assert e["extraction_model"] == "mistral"
    assert e["source_file"] == "PJ_1.pdf"


def test_build_enrichment_empty_code_becomes_none():
    e = build_enrichment(
        {}, code="", strategy="new_from_document", match_uncertain=True
    )
    assert e["project_code"] is None
    # objetivos is validated/normalized by the Pydantic model
    assert e["objetivos"] == {"geral": None, "especificos": []}
    assert e["cronograma"] == []
    assert e["palavras_chave"] == []


def test_build_enrichment_rejects_malformed_payload():
    from pydantic import ValidationError

    # palavras_chave must be a list of strings; a dict is invalid
    with pytest.raises(ValidationError):
        build_enrichment(
            {"palavras_chave": {"nope": 1}},
            code="1",
            strategy="title_exact",
            match_uncertain=False,
        )


# --------------------------------------------------------------- parse_sql_datetime
@pytest.mark.parametrize(
    "value,expected",
    [
        ("2020-08-01", "2020-08-01 00:00:00.000000"),
        ("2020-08-01T10:00:00", "2020-08-01 00:00:00.000000"),
        ("2020-08", None),
        ("garbage", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_sql_datetime(value, expected):
    assert parse_sql_datetime(value) == expected


# --------------------------------------------------------------- derive_status
def test_derive_status_concluded_when_end_in_past():
    now = datetime(2026, 7, 20)
    assert derive_status("2020-01-01", "2021-01-01", now=now) == "Concluded"


def test_derive_status_active_when_end_in_future():
    now = datetime(2026, 7, 20)
    assert derive_status("2026-01-01", "2027-01-01", now=now) == "Active"


def test_derive_status_active_with_start_no_end():
    now = datetime(2026, 7, 20)
    assert derive_status("2026-01-01", None, now=now) == "Active"


def test_derive_status_unknown_without_dates():
    now = datetime(2026, 7, 20)
    assert derive_status(None, None, now=now) == "Unknown"


# --------------------------------------------------------------- is_ingestable
def test_is_ingestable_requires_title_desc_and_objectives_or_schedule():
    assert is_ingestable({"titulo": "T", "descricao": "D", "objetivos": {"geral": "g"}})
    assert is_ingestable(
        {"titulo": "T", "descricao": "D", "cronograma": [{"atividade": "a"}]}
    )
    # missing description
    assert not is_ingestable({"titulo": "T", "objetivos": {"geral": "g"}})
    # missing title
    assert not is_ingestable({"descricao": "D", "objetivos": {"geral": "g"}})
    # no objectives and no schedule
    assert not is_ingestable({"titulo": "T", "descricao": "D"})


# --------------------------------------------------------------- match_pj
CODE_INDEX = {"6020": 10}
NAME_INDEX = {
    "correcao automatica de redacoes": [20],
    "titulo repetido": [30, 31],
}
FUZZY = {
    20: "correcao automatica de redacoes",
    30: "titulo repetido",
    31: "titulo repetido",
    40: "mapeamento dos dados do enem por municipio do espirito santo",
}


def test_match_by_code_wins():
    m = match_pj(
        {"codigo": "PJ 6020", "titulo": "irrelevante"}, CODE_INDEX, NAME_INDEX, FUZZY
    )
    assert m == Match(10, "sigpesq_project_code", False)


def test_match_exact_title_unique():
    m = match_pj(
        {"codigo": None, "titulo": "Correção Automática de Redações"},
        CODE_INDEX,
        NAME_INDEX,
        FUZZY,
    )
    assert m == Match(20, "title_exact", False)


def test_match_exact_title_ambiguous_flags_review():
    m = match_pj({"titulo": "Título Repetido"}, CODE_INDEX, NAME_INDEX, FUZZY)
    assert m.strategy == "title_exact"
    assert m.needs_review is True
    assert m.initiative_id in (30, 31)


def test_match_fuzzy_above_threshold():
    # one-char difference from initiative 40's normalized name -> ratio >= 90
    m = match_pj(
        {"titulo": "Mapeamento dos dados do ENEM por municipio do Espirito Santoo"},
        CODE_INDEX,
        NAME_INDEX,
        FUZZY,
    )
    assert m is not None
    assert m.strategy == "title_fuzzy"
    assert m.initiative_id == 40
    assert m.needs_review is True


def test_match_none_when_dissimilar():
    m = match_pj(
        {"titulo": "assunto totalmente diferente e sem relacao"},
        CODE_INDEX,
        NAME_INDEX,
        FUZZY,
    )
    assert m is None


def test_match_none_without_title_or_code():
    assert match_pj({"titulo": None}, CODE_INDEX, NAME_INDEX, FUZZY) is None


# --------------------------------------------------------------- resolve_claims
def _cand(path, init_id, strategy):
    return Candidate(path, {"codigo": path}, Match(init_id, strategy, False))


def test_resolve_claims_code_beats_title_on_same_initiative():
    cands = [
        _cand("PJ_b.json", 100, "title_exact"),
        _cand("PJ_a.json", 100, "sigpesq_project_code"),
    ]
    winners, collisions = resolve_claims(cands)
    assert collisions == 1
    assert len(winners) == 1
    assert winners[0].match.strategy == "sigpesq_project_code"


def test_resolve_claims_keeps_distinct_initiatives():
    cands = [
        _cand("PJ_a.json", 1, "sigpesq_project_code"),
        _cand("PJ_b.json", 2, "title_exact"),
        _cand("PJ_c.json", 3, "title_fuzzy"),
    ]
    winners, collisions = resolve_claims(cands)
    assert collisions == 0
    assert {w.match.initiative_id for w in winners} == {1, 2, 3}


def test_resolve_claims_ignores_unmatched():
    cands = [Candidate("PJ_x.json", {}, None), _cand("PJ_y.json", 5, "title_exact")]
    winners, collisions = resolve_claims(cands)
    assert collisions == 0
    assert [w.match.initiative_id for w in winners] == [5]


def test_resolve_claims_tie_broken_by_path():
    # same priority (both title_exact), same initiative -> first by filename wins
    cands = [
        _cand("PJ_z.json", 7, "title_exact"),
        _cand("PJ_a.json", 7, "title_exact"),
    ]
    winners, collisions = resolve_claims(cands)
    assert collisions == 1
    assert winners[0].path == "PJ_a.json"


# --------------------------------------------------------------- derive_needs_review
def test_document_born_initiative_always_needs_review():
    """An initiative invented from an auto-extracted document is never trusted
    on confidence alone -- not even when this run matched it by exact title."""
    assert (
        derive_needs_review(
            origin=ORIGIN_NEW_FROM_DOCUMENT, match_uncertain=False, reviewed_at=None
        )
        is True
    )


def test_uncertain_match_needs_review():
    assert (
        derive_needs_review(
            origin=ORIGIN_MATCHED_EXISTING, match_uncertain=True, reviewed_at=None
        )
        is True
    )


def test_confident_match_on_existing_initiative_does_not():
    assert (
        derive_needs_review(
            origin=ORIGIN_MATCHED_EXISTING, match_uncertain=False, reviewed_at=None
        )
        is False
    )


def test_human_review_settles_it():
    """A recorded review wins over everything, origin included."""
    assert (
        derive_needs_review(
            origin=ORIGIN_NEW_FROM_DOCUMENT,
            match_uncertain=True,
            reviewed_at="2026-08-25T10:00:00",
        )
        is False
    )


# --------------------------------------------------------------- origin_from_prior
def test_recorded_origin_wins():
    prior = {"origin": ORIGIN_NEW_FROM_DOCUMENT, "match_strategy": "title_exact"}
    assert origin_from_prior(prior, "title_exact") == ORIGIN_NEW_FROM_DOCUMENT


def test_legacy_payload_infers_origin_from_recorded_strategy():
    """Payloads written before the origin field existed are still readable."""
    prior = {"match_strategy": "new_from_document"}
    assert origin_from_prior(prior, "title_exact") == ORIGIN_NEW_FROM_DOCUMENT


def test_without_prior_this_run_decides():
    assert origin_from_prior(None, "new_from_document") == ORIGIN_NEW_FROM_DOCUMENT
    assert origin_from_prior(None, "title_exact") == ORIGIN_MATCHED_EXISTING


def test_build_enrichment_carries_origin_and_review_forward():
    """The defect this feature fixes, at payload level.

    Second run: same document, now matching an existing initiative by exact
    title. The flag must NOT flip to False just because the match got confident.
    """
    pj = {"titulo": "P", "descricao": "d", "objetivos": {"geral": "g"}}
    prior = {"origin": ORIGIN_NEW_FROM_DOCUMENT, "match_strategy": "new_from_document"}

    payload = build_enrichment(
        pj, code="1", strategy="title_exact", match_uncertain=False, prior=prior
    )

    assert payload["origin"] == ORIGIN_NEW_FROM_DOCUMENT
    assert payload["needs_review"] is True
    assert payload["match_strategy"] == "title_exact", "current run is still recorded"


def test_build_enrichment_keeps_review_record():
    pj = {"titulo": "P", "descricao": "d"}
    prior = {
        "origin": ORIGIN_NEW_FROM_DOCUMENT,
        "reviewed_at": "2026-08-25T10:00:00",
        "reviewed_by": "MAT-123",
    }

    payload = build_enrichment(
        pj, code="1", strategy="title_exact", match_uncertain=False, prior=prior
    )

    assert payload["needs_review"] is False
    assert payload["reviewed_by"] == "MAT-123"
    assert payload["origin"] == ORIGIN_NEW_FROM_DOCUMENT, "review must not erase origin"
