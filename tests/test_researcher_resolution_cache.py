"""Researcher resolution (spec 016): memoised name keys, same answers.

normalize_participant_name is memoised; resolve_researcher_by_name keeps its
loop and scoring. Both are checked against verbatim pre-016 copies
(tests/_name_matching_oracle.py).
"""

import itertools
import random
from types import SimpleNamespace

from _name_matching_oracle import (
    oracle_normalize_participant_name,
    oracle_resolve_researcher_by_name,
)
from loguru import logger

from src.core.logic.person_identity import normalize_participant_name
from src.core.logic.researcher_resolution import (
    ResearcherRef,
    log_researcher_resolution_summary,
    resolve_researcher_by_name,
)

PIECES = [
    "José",
    "JOSÉ",
    "jose",
    "da",
    "DE",
    "dos",
    "e",
    "Silva",
    "Júnior",
    "Jr.",
    "JR",
    "Filho",
    "Neto",
    "Dr.",
    "Profa.",
    "Ana-Maria",
    "O'Neil",
    "Ñoño",
    "  ",
    "123",
    "São",
    "Conceição",
    "D'Ávila",
    "Y",
    "del",
    "!!!",
    "ß",
    "Ørsted",
    "Μαρία",
]
FLAGS = list(itertools.product((True, False), repeat=3))


def _names(n, seed=16):
    rnd = random.Random(seed)
    out = [None, "", " ", 123, 4.5]
    while len(out) < n:
        out.append(" ".join(rnd.choice(PIECES) for _ in range(rnd.randint(1, 6))))
    return out


def _capture_info(fn):
    lines = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        fn()
    finally:
        logger.remove(sink)
    return lines


def test_memoised_normalisation_matches_oracle_for_every_flag_combination():
    names = _names(5000)
    for _ in range(2):  # second pass is served from the cache
        for name in names:
            for cp, cs, dp in FLAGS:
                assert normalize_participant_name(
                    name,
                    canonical_particles=cp,
                    canonical_suffixes=cs,
                    drop_particles=dp,
                ) == oracle_normalize_participant_name(
                    name,
                    canonical_particles=cp,
                    canonical_suffixes=cs,
                    drop_particles=dp,
                )


def test_ties_return_the_first_candidate_like_the_oracle():
    refs = [
        ResearcherRef(id=1, name="Maria da Silva"),
        ResearcherRef(id=2, name="MARIA DA SILVA"),
        ResearcherRef(id=3, name="Maria  da  Silva"),
    ]
    for query in ("maria da silva", "Maria da Silva", "MARIA DA SILVA"):
        expected = oracle_resolve_researcher_by_name(refs, name=query)
        assert resolve_researcher_by_name(refs, name=query) is expected


def test_every_scoring_tier_and_no_match_like_the_oracle():
    refs = [
        ResearcherRef(id=10, name="Alguém Outro", identification_id="ABC123"),
        ResearcherRef(id=11, name="Pedro Alves Junior"),
        ResearcherRef(id=12, name="Lúcia Ferreira"),
        ResearcherRef(id=13, name="Carlos dos Santos Jr."),
    ]
    cases = [
        dict(name="Ninguém", identification_id="abc123"),  # tier 200
        dict(name="pedro alves junior"),  # tier 150 (casefold)
        dict(name="LUCIA FERREIRA"),  # tier 100 (normalised)
        dict(name="Carlos Santos Júnior"),  # tier 90 (invariant)
        dict(name="Pessoa Inexistente"),  # no match
        dict(name=""),
    ]
    for case in cases:
        assert resolve_researcher_by_name(
            refs, **case
        ) is oracle_resolve_researcher_by_name(refs, **case)


def test_mixed_refs_and_entity_like_objects_and_renames():
    entity = SimpleNamespace(id=21, name="Renata Gomes", identification_id=None)
    refs = [ResearcherRef(id=20, name="Renata  Gomes"), entity]
    assert resolve_researcher_by_name(refs, name="renata gomes") is (
        oracle_resolve_researcher_by_name(refs, name="renata gomes")
    )
    refs[0].name = "Renata Gomes Prado"  # as sync_researcher_ref does
    assert resolve_researcher_by_name(refs, name="RENATA GOMES PRADO") is (
        oracle_resolve_researcher_by_name(refs, name="RENATA GOMES PRADO")
    )


def test_random_resolution_matches_oracle():
    rnd = random.Random(7)
    refs = [
        ResearcherRef(id=i, name=n, identification_id=f"id{i}" if i % 7 == 0 else None)
        for i, n in enumerate(_names(600, seed=3))
        if isinstance(n, str)
    ]
    for _ in range(800):
        name = (
            rnd.choice(refs).name if rnd.random() < 0.6 else rnd.choice(_names(50, 9))
        )
        ident = f"ID{rnd.randrange(600)}" if rnd.random() < 0.2 else None
        if not isinstance(name, str):
            name = None
        assert resolve_researcher_by_name(
            refs, name=name, identification_id=ident
        ) is oracle_resolve_researcher_by_name(refs, name=name, identification_id=ident)


def test_resolution_summary_counts_tiers_and_resets():
    log_researcher_resolution_summary("reset")  # start from zero
    refs = [
        ResearcherRef(id=1, name="Igor Mattos", identification_id="X1"),
        ResearcherRef(id=2, name="Joana Prates"),
        ResearcherRef(id=3, name="Luís Barros"),
        ResearcherRef(id=4, name="Marcos de Souza Jr."),
    ]
    resolve_researcher_by_name(refs, name="qualquer", identification_id="x1")
    resolve_researcher_by_name(refs, name="joana prates")
    resolve_researcher_by_name(refs, name="LUIS BARROS")
    resolve_researcher_by_name(refs, name="Marcos Souza Junior")
    resolve_researcher_by_name(refs, name="Ninguém Aqui")

    lines = _capture_info(lambda: log_researcher_resolution_summary("x"))
    assert lines == [
        "Researcher resolution [x]: lookups=5 tier200=1 tier150=1 tier100=1 "
        "tier90=1 unresolved=1"
    ]
    again = _capture_info(lambda: log_researcher_resolution_summary("x"))
    assert again == [
        "Researcher resolution [x]: lookups=0 tier200=0 tier150=0 tier100=0 "
        "tier90=0 unresolved=0"
    ]
