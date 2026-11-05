"""Spec 029: the Lattes ingest finds an existing article by normalized DOI, or
by normalized title and year, so the same work is stored once."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.flows.lattes.projects import _find_article


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as con:
        con.execute(
            text(
                "CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, "
                "year INTEGER, doi TEXT)"
            )
        )
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


def _add(session, row_id, title, year, doi=None):
    session.execute(
        text("INSERT INTO articles (id, title, year, doi) VALUES (:i, :t, :y, :d)"),
        {"i": row_id, "t": title, "y": year, "d": doi},
    )
    session.commit()


def test_title_differing_in_case_accents_or_punctuation_matches(session):
    _add(session, 1, "Redes Neurais: uma Introdução", 2020)

    assert _find_article(session, "redes neurais uma introducao", 2020, None) == 1
    assert _find_article(session, "REDES NEURAIS - UMA INTRODUÇÃO!", 2020, None) == 1


def test_doi_differing_in_case_or_prefix_matches_whatever_the_title(session):
    _add(session, 1, "Some Title", 2019, "10.1000/ABC.123")

    assert _find_article(session, "Another Title", 2021, "10.1000/abc.123") == 1
    assert (
        _find_article(session, "Another Title", 2021, "https://doi.org/10.1000/ABC.123")
        == 1
    )


def test_doi_stored_with_a_prefix_matches_a_bare_doi(session):
    _add(session, 1, "Some Title", 2019, "https://doi.org/10.1000/abc.123")

    assert _find_article(session, "Other", 2020, "10.1000/ABC.123") == 1


def test_two_different_dois_do_not_match_even_with_same_title_and_year(session):
    _add(session, 1, "Same Title", 2020, "10.1000/aaa")

    assert _find_article(session, "Same Title", 2020, "10.1000/bbb") is None


def test_blank_or_punctuation_only_titles_never_match(session):
    _add(session, 1, "   ", 2020)
    _add(session, 2, "...", 2020)
    _add(session, 3, "", 2020)

    for title in ("", "   ", "...", None):
        assert _find_article(session, title, 2020, None) is None


def test_a_doi_on_one_record_only_still_matches_by_title_and_year(session):
    _add(session, 1, "Same Title", 2020, None)
    _add(session, 2, "Other Title", 2021, "10.1000/zzz")

    assert _find_article(session, "same title", 2020, "10.1000/new") == 1
    assert _find_article(session, "other title", 2021, None) == 2


def test_different_years_do_not_match(session):
    _add(session, 1, "Same Title", 2020)

    assert _find_article(session, "Same Title", 2021, None) is None


def test_the_lowest_id_is_returned_when_several_match(session):
    _add(session, 7, "Same Title", 2020)
    _add(session, 3, "same title", 2020)
    _add(session, 5, "Same  Title.", 2020)

    assert _find_article(session, "Same Title", 2020, None) == 3


def test_the_lowest_id_wins_among_doi_matches(session):
    _add(session, 9, "A", 2020, "10.1000/x")
    _add(session, 4, "B", 2021, "10.1000/X")

    assert _find_article(session, "C", 2022, "10.1000/x") == 4


def test_no_match_returns_none(session):
    _add(session, 1, "One", 2020, "10.1000/a")

    assert _find_article(session, "Two", 2020, "10.1000/b") is None
    assert _find_article(session, "Two", 2020, None) is None


def test_a_doi_with_like_wildcards_is_matched_literally(session):
    _add(session, 1, "T", 2020, "10.1000/a_b")
    _add(session, 2, "U", 2020, "10.1000/axb")

    assert _find_article(session, "V", 2021, "10.1000/a_b") == 1
