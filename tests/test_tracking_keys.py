"""Spec 020: tracking keys built from source data only, and the canonical hash."""

from src.core.logic.horizon_identity import (
    cnpq_line_key,
    cnpq_member_key,
    cnpq_payload_key,
    dedupe_same_document,
    lattes_advisorship_key,
    lattes_article_key,
    lattes_education_key,
    lattes_initiative_key,
)
from src.tracking.recorder import stable_hash

GROUP_URL = "http://dgp.cnpq.br/dgp/espelhogrupo/4439471564090237"
CV = "/x/data/lattes_json/219_Karin-Satie-Komati_9860697624155451.json"


def test_cnpq_keys_use_the_cnpq_id_and_the_dates():
    assert cnpq_payload_key(GROUP_URL) == "cnpq:4439471564090237"
    first = cnpq_member_key(
        GROUP_URL,
        {
            "name": "João Paulo",
            "role": "Pesquisador (Egresso)",
            "data_inicio": "04/11/2014",
            "data_fim": "21/04/2015",
        },
    )
    second = cnpq_member_key(
        GROUP_URL,
        {
            "name": "João Paulo",
            "role": "Pesquisador (Egresso)",
            "data_inicio": "Não informada",
            "data_fim": "23/10/2014",
        },
    )
    assert first.startswith("cnpq:4439471564090237|joao paulo|pesquisador egresso|")
    assert first != second  # two membership periods are two records
    assert cnpq_line_key(GROUP_URL, "Ensino de Física") == (
        "cnpq:4439471564090237|ensino de fisica"
    )


def test_education_key_uses_the_cv_not_the_researcher_id():
    edu = {
        "course_name": "Política Social",
        "degree": "Doutorado",
        "start_year": "2020",
        "end_year": "2024",
        "institution": "UFES",
    }
    key = lattes_education_key(CV, edu)
    assert key.startswith(
        "lattes:9860697624155451|politica social|doutorado|2020|2024|"
    )
    # The same CV after a person merge (different researchers.id) gives the
    # same key: nothing in it comes from the database.
    assert key == lattes_education_key(CV, dict(edu))


def test_article_key_tells_journal_and_conference_versions_apart():
    base = {"title": "A mulher espírito-santense", "year": "2015", "doi": ""}
    journal = lattes_article_key(
        CV, {**base, "type": "Journal", "journal_conference": "Caderno"}
    )
    event = lattes_article_key(
        CV, {**base, "type": "Conference Event", "journal_conference": "Fazendo Gênero"}
    )
    assert journal != event
    with_doi = lattes_article_key(
        CV, {**base, "doi": "https://doi.org/10.1/ABC", "type": "J"}
    )
    assert "|10.1/abc|" in with_doi


def test_lattes_initiative_and_advisorship_keys_carry_the_cv():
    a = lattes_initiative_key(CV, "lattes project|p|ana|2020|rp")
    b = lattes_initiative_key(
        CV.replace("9860697624155451", "1111111111111111"),
        "lattes project|p|ana|2020|rp",
    )
    assert a.startswith("lattes:9860697624155451|lattes project|") and a != b
    adv = lattes_advisorship_key(
        CV,
        "lattes advisorship|t|x|y|2020|tcc",
        {"type": "Undergraduate Thesis", "institution": "IFES"},
    )
    assert adv.endswith("|undergraduate thesis|ifes")


def test_payload_hash_is_type_stable():
    assert stable_hash({"Valor": 600}) == stable_hash({"Valor": "600"})
    assert stable_hash({"Valor": 600.0, "x": float("nan")}) == stable_hash(
        {"Valor": "600", "x": ""}
    )
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})


def test_same_document_duplicates_keep_one_fixed_version():
    v1 = {"title": "T", "year": "2019", "authors_str": "COUTO, S. R. B."}
    v2 = {"title": "T", "year": "2019", "authors_str": "COUTO, SAMUEL R.B."}
    other = {"title": "U", "year": "2019"}
    key = lambda item: (item["title"], item["year"])  # noqa: E731
    kept_a, dropped_a = dedupe_same_document([v1, other, v2], key)
    kept_b, dropped_b = dedupe_same_document([v2, other, v1], key)
    assert dropped_a == dropped_b == 1
    assert [k for k in kept_a if k["title"] == "T"] == [
        k for k in kept_b if k["title"] == "T"
    ]
    assert other in kept_a and other in kept_b
