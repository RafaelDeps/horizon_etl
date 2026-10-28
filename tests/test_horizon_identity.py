"""Spec 020: pure identity primitives (canonical form, hashes, id extractors)."""

import math

from src.core.logic.horizon_identity import (
    canonical,
    canonical_hash,
    cnpq_group_id_from_url,
    hash12,
    lattes_id_from_cv_path,
    lattes_id_from_url,
    normalize_doi,
    slug,
)


def test_canonical_treats_empty_values_alike():
    for empty in (None, math.nan, "nan", "NaN", "", "  ", "None"):
        assert canonical(empty) is None


def test_canonical_treats_number_and_text_alike():
    assert canonical(600) == canonical(600.0) == canonical("600") == canonical(" 600 ")
    assert canonical(2.5) == "2.5"


def test_canonical_is_recursive():
    a = {"Valor": 600, "x": [1.0, "nan", {"y": None}]}
    b = {"Valor": "600", "x": ["1", None, {"y": ""}]}
    assert canonical(a) == canonical(b)
    assert canonical_hash(a) == canonical_hash(b)


def test_canonical_hash_ignores_key_order():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_hash12_ignores_accents_case_and_punctuation():
    h = hash12("Karin Satie Komati")
    assert len(h) == 12 and all(c in "0123456789abcdef" for c in h)
    assert hash12("KARIN SATIE KOMATI") == h
    assert hash12("Kárin  Satie-Komati") == h
    assert hash12("Karin Satie Komati", "2020") != h


def test_slug():
    assert slug("Educação") == "educacao"
    assert slug("Probabilidade e Estatística") == "probabilidade-e-estatistica"


def test_normalize_doi_strips_url_prefixes_and_case():
    expected = "10.1016/j.theriogenology.2018.10.032"
    for raw in (
        "10.1016/J.THERIOGENOLOGY.2018.10.032",
        "http://dx.doi.org/10.1016/j.theriogenology.2018.10.032",
        "https://doi.org/10.1016/j.theriogenology.2018.10.032",
        " https://dx.doi.org/10.1016/j.theriogenology.2018.10.032 ",
    ):
        assert normalize_doi(raw) == expected
    assert normalize_doi("") is None
    assert normalize_doi(None) is None


def test_id_extractors_on_real_examples():
    assert lattes_id_from_url("http://lattes.cnpq.br/9860697624155451") == (
        "9860697624155451"
    )
    assert (
        cnpq_group_id_from_url("http://dgp.cnpq.br/dgp/espelhogrupo/4439471564090237")
        == "4439471564090237"
    )
    assert (
        lattes_id_from_cv_path(
            "/x/data/lattes_json/219_Karin-Satie-Komati_9860697624155451.json"
        )
        == "9860697624155451"
    )


def test_id_extractors_on_garbage():
    for fn in (lattes_id_from_url, cnpq_group_id_from_url, lattes_id_from_cv_path):
        assert fn(None) is None
        assert fn("") is None
        assert fn("http://example.org/whatever") is None


# ---------------------------------------------------------------- rules (T012)
import re  # noqa: E402

from src.core.logic.horizon_identity import (  # noqa: E402
    article_decision,
    child_decision,
    fellowship_decision,
    initiative_decision,
    person_decision,
    reference_decision,
    research_group_decision,
    research_production_decision,
    resolve_collisions,
    team_decision,
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_CPF = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}")
_PHONE = re.compile(r"\(?\d{2}\)?\s?9?\d{4}-\d{4}")


def _no_pii(decision):
    for text in [decision.horizon_id, decision.natural_key or ""] + decision.candidates:
        assert not _EMAIL.search(text), text
        assert not _PHONE.search(text), text
        # 16-digit Lattes ids contain 11 digits in a row; only flag a CPF shape
        # with its punctuation, which never appears in a source id.
        assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", text), text


def _key(rid, entity_type="initiative", source_file="f.json"):
    return {
        "source_entity_type": entity_type,
        "source_record_id": rid,
        "source_file": source_file,
    }


def test_person_with_lattes_id_keeps_the_name_candidate():
    d = person_decision(
        {
            "id": 7,
            "name": "Karin Satie Komati",
            "cnpq_url": "http://lattes.cnpq.br/9860697624155451",
        }
    )
    assert d.horizon_id == "person:lattes:9860697624155451"
    assert d.rule == "lattes_id" and d.natural_key is None
    assert d.candidates == [d.horizon_id, f"person:h:{hash12('Karin Satie Komati')}"]
    _no_pii(d)


def test_person_lattes_id_from_profile_source_record():
    d = person_decision(
        {"id": 7, "name": "X", "cnpq_url": None},
        [_key("9860697624155451", "researcher_profile")],
    )
    assert d.horizon_id == "person:lattes:9860697624155451"


def test_person_without_lattes_id_uses_the_name():
    d = person_decision(
        {"id": 1, "name": "Carlos Roberto Pires Campos", "cnpq_url": None}
    )
    assert d.horizon_id == f"person:h:{hash12('Carlos Roberto Pires Campos')}"
    assert d.rule == "name" and d.natural_key == "carlos roberto pires campos"
    _no_pii(d)


def test_group_with_and_without_cnpq_url():
    d = research_group_decision(
        {
            "id": 1,
            "name": "DIVIPOP",
            "cnpq_url": "http://dgp.cnpq.br/dgp/espelhogrupo/4439471564090237",
        }
    )
    assert d.horizon_id == "group:cnpq:4439471564090237"
    d = research_group_decision({"id": 2, "name": "Grupo X", "cnpq_url": None})
    assert d.horizon_id == f"group:sigpesq:h:{hash12('Grupo X')}"
    assert d.rule == "sigpesq_name"


def test_initiative_rules_in_priority_order():
    row = {"id": 4, "name": "Projeto", "type_name": "Research Project"}
    lattes = _key("lattes project|projeto|ana|2020|research project")
    pj = _key("PJ 2342")
    code = _key("sigpesq project|6903")
    assert initiative_decision(row, [lattes, pj, code]).horizon_id == (
        "initiative:sigpesq-pj:6903"
    )
    assert (
        initiative_decision(row, [lattes, pj]).horizon_id
        == "initiative:sigpesq-pj:2342"
    )
    d = initiative_decision(row, [lattes])
    assert (
        d.horizon_id.startswith("initiative:lattes:h:") and d.rule == "lattes_identity"
    )
    d = initiative_decision(row, [])
    assert d.horizon_id == f"initiative:h:{hash12('Research Project', 'Projeto')}"
    assert d.rule == "name"
    # every source key is also a candidate
    assert len(initiative_decision(row, [lattes, pj, code]).candidates) == 4


def test_initiative_from_new_lattes_tracking_key_ignores_the_cv_prefix():
    row = {"id": 4, "name": "P", "type_name": "Research Project"}
    old = initiative_decision(row, [_key("lattes project|p|ana|2020|rp")])
    new_a = initiative_decision(
        row, [_key("lattes:1111111111111111|lattes project|p|ana|2020|rp")]
    )
    new_b = initiative_decision(
        row, [_key("lattes:2222222222222222|lattes project|p|ana|2020|rp")]
    )
    assert old.horizon_id == new_a.horizon_id == new_b.horizon_id


def test_advisorship_from_workplan():
    d = initiative_decision(
        {"id": 9, "name": "Plano", "type_name": "Advisorship"},
        [_key("sigpesq workplan|10045|4882", "advisorship")],
        entity_type="advisorship",
    )
    assert d.horizon_id == "advisorship:sigpesq-pt:10045-4882"


def test_sigpesq_identity_with_emails_is_never_hashed_into_an_id():
    d = initiative_decision(
        {"id": 9, "name": "Plano", "type_name": "Advisorship"},
        [
            _key(
                "sigpesq advisorship|1|plano|ana example org|bob example org|2020",
                "advisorship",
            )
        ],
        entity_type="advisorship",
    )
    assert d.rule == "name"
    assert all("example" not in c for c in d.candidates)


def test_article_doi_spellings_give_one_id_and_keep_the_content_candidate():
    base = {
        "id": 1,
        "title": "T",
        "year": "2019",
        "type": "Journal",
        "journal_conference": "J",
    }
    ids = {
        article_decision({**base, "doi": doi}).horizon_id
        for doi in (
            "10.1016/J.THERIOGENOLOGY.2018.10.032",
            "http://dx.doi.org/10.1016/j.theriogenology.2018.10.032",
            "https://doi.org/10.1016/j.theriogenology.2018.10.032",
        )
    }
    assert ids == {"article:doi:10.1016/j.theriogenology.2018.10.032"}
    without = article_decision({**base, "doi": ""})
    assert without.horizon_id.startswith("article:h:")
    assert without.horizon_id in article_decision({**base, "doi": "10.1/x"}).candidates


def test_production():
    d = research_production_decision(
        {"id": 1, "title": "Livro", "year": "2020", "type_name": "Book"}
    )
    assert d.horizon_id == f"production:h:{hash12('Livro', '2020', 'Book')}"


def test_children_follow_every_parent_candidate():
    parent = person_decision(
        {"id": 7, "name": "Karin", "cnpq_url": "http://lattes.cnpq.br/9860697624155451"}
    )
    edu = child_decision(
        "academic_education",
        {
            "id": 3,
            "parent_id": 7,
            "type_name": "Doutorado",
            "title": "Política Social",
            "start_year": "2020",
        },
        parent,
    )
    assert edu.horizon_id.startswith("person:lattes:9860697624155451/education:h:")
    assert edu.parent_horizon_id == parent.horizon_id
    assert len(edu.candidates) == 2
    assert edu.candidates[1].startswith(f"person:h:{hash12('Karin')}/education:h:")
    act = child_decision(
        "professional_activity",
        {
            "id": 1,
            "parent_id": 7,
            "institution_name": "IFES",
            "start_year": "2010",
            "end_year": None,
            "role_function": "Professor",
            "bond": "Servidor",
        },
        parent,
    )
    assert "/activity:h:" in act.horizon_id
    award = child_decision(
        "award", {"id": 1, "parent_id": 7, "title": "Prêmio", "year": "2020"}, parent
    )
    assert "/award:h:" in award.horizon_id
    prof = child_decision(
        "proficiency", {"id": 1, "parent_id": 7, "language": "Inglês"}, parent
    )
    assert prof.horizon_id == "person:lattes:9860697624155451/proficiency:ingles"


def test_team_under_initiative_and_alone():
    a = initiative_decision({"id": 1, "name": "B", "type_name": "RP"}, [_key("PJ 9")])
    b = initiative_decision({"id": 2, "name": "A", "type_name": "RP"}, [_key("PJ 1")])
    d = team_decision({"id": 5, "name": "B"}, [a, b])
    assert d.horizon_id == "initiative:sigpesq-pj:1/team"
    alone = team_decision({"id": 6, "name": "Equipe"}, [])
    assert alone.horizon_id == f"team:h:{hash12('Equipe')}"


def test_fellowship_carries_its_value():
    assert fellowship_decision(
        {"id": 1, "name": "PIBITI", "value": 700.0}
    ).horizon_id == ("fellowship:pibiti:700")
    assert fellowship_decision(
        {"id": 2, "name": "PIBITI", "value": 900}
    ).horizon_id == ("fellowship:pibiti:900")


def test_reference_slugs():
    assert (
        reference_decision("campus", {"id": 1, "name": "Serra"}).horizon_id
        == "campus:serra"
    )
    assert reference_decision(
        "knowledge_area", {"id": 1, "name": "Educação"}
    ).horizon_id == ("knowledge-area:educacao")


def test_collisions_get_document_suffix_then_content_order():
    def homonym(eid, doc):
        d = person_decision(
            {"id": eid, "name": "Ana Paula Souza", "cnpq_url": None},
            [_key("x", "s", doc)],
        )
        return d

    a, b = homonym(1, "report_a.xlsx"), homonym(2, "report_b.xlsx")
    report = resolve_collisions([a, b])
    assert a.horizon_id != b.horizon_id
    assert a.horizon_id.startswith("person:h:") and "~" in a.horizon_id
    assert report["person"]["groups"] == 1 and report["person"]["rows"] == 2
    # same document: content order decides, not input order
    c1, c2 = homonym(1, "same.xlsx"), homonym(2, "same.xlsx")
    c2.content_hash, c1.content_hash = "a", "b"
    resolve_collisions([c1, c2])
    assert c2.horizon_id.count("~") == 1 and c1.horizon_id.endswith("~2")


def test_collision_suffix_does_not_depend_on_the_checkout_path():
    """SC-006: the same CV under another directory gives the same suffix."""
    from src.core.logic.horizon_identity import article_decision, resolve_collisions

    row = {"id": 1, "title": "T", "year": "2020", "type": "J", "doi": ""}

    def pair(root):
        a = article_decision(
            row, [{"source_file": f"{root}/219_A_1111222233334444.json"}]
        )
        b = article_decision(
            dict(row, id=2), [{"source_file": f"{root}/220_B_5555666677778888.json"}]
        )
        resolve_collisions([a, b])
        return sorted([a.horizon_id, b.horizon_id])

    assert pair("/home/x/data/lattes_json") == pair("/runner/work/data/lattes_json")
