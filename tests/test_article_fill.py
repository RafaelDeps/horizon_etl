"""Spec 020: an article listed in several CVs keeps the DOI whichever CV is
read first (empty fields are filled, never overwritten)."""

from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.flows.lattes.projects import _fill_missing_article_fields, _with_clean_doi


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    session = Session(engine)
    session.execute(
        text(
            "CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, doi TEXT, "
            "journal_conference TEXT, volume TEXT, pages TEXT)"
        )
    )
    session.execute(
        text(
            "INSERT INTO articles VALUES (1, 'Duration of co-feeding', '', "
            "'CIÊNCIA RURAL', NULL, '1-5')"
        )
    )
    session.commit()
    return session


def _row(session):
    return session.execute(
        text("SELECT doi, journal_conference, volume, pages FROM articles")
    ).fetchone()


@patch("src.flows.lattes.projects.tracking_recorder")
def test_empty_fields_take_the_later_cv_value(recorder, tmp_path):
    session = _session(tmp_path)
    art = {
        "doi": "http://dx.doi.org/10.1590/0103-8478cr20170579",
        "journal_conference": "Ciencia Rural",
        "volume": "48",
        "pages": "",
    }
    _fill_missing_article_fields(session, 1, art, 7)

    assert _row(session) == (
        "http://dx.doi.org/10.1590/0103-8478cr20170579",
        "CIÊNCIA RURAL",  # never overwritten
        "48",
        "1-5",
    )
    change = recorder.record_change.call_args.kwargs
    assert change["changed_fields"] == ["doi", "volume"]
    assert change["before"] == {"doi": "", "volume": None}


@patch("src.flows.lattes.projects.tracking_recorder")
def test_nothing_to_fill_writes_nothing(recorder, tmp_path):
    session = _session(tmp_path)
    _fill_missing_article_fields(session, 1, {"doi": "", "volume": None}, 7)
    recorder.record_change.assert_not_called()
    assert _row(session) == ("", "CIÊNCIA RURAL", None, "1-5")


# Spec 033: the article is stored with the cleaned DOI, or with none.
SCOPUS = "http://www.scopus.com/scopus/inward/citedby.url?partnerID=x&rel=R6.0.0"


def test_item_is_stored_with_the_cleaned_doi():
    cases = {
        "http://dx.doi.org/10.1590/0103-8478CR20170579": "10.1590/0103-8478cr20170579",
        f"{SCOPUS}&doi=10.1186/1753-6561-8-s4-p29&md5=abc": "10.1186/1753-6561-8-s4-p29",
        "10.3390 / fishes6030031": "10.3390/fishes6030031",
        f"{SCOPUS}&doi=null&md5=f8a2": None,
        "http://dx.doi.org/1982-9434": None,
    }
    for raw, expected in cases.items():
        art = {"title": "T", "year": 2020, "doi": raw, "volume": "1"}
        clean = _with_clean_doi(art)
        assert clean == {"title": "T", "year": 2020, "doi": expected, "volume": "1"}
        assert art["doi"] == raw  # the tracked source item is not modified


@patch("src.flows.lattes.projects.tracking_recorder")
def test_missing_doi_is_filled_with_the_cleaned_doi(recorder, tmp_path):
    session = _session(tmp_path)
    art = _with_clean_doi({"doi": "http://dx.doi.org/10.1000/ABC."})
    _fill_missing_article_fields(session, 1, art, 7)

    assert _row(session)[0] == "10.1000/abc"
    assert recorder.record_change.call_args.kwargs["after"] == {"doi": "10.1000/abc"}


@patch("src.flows.lattes.projects.tracking_recorder")
def test_a_non_doi_value_never_fills_the_doi(recorder, tmp_path):
    session = _session(tmp_path)
    art = _with_clean_doi({"doi": f"{SCOPUS}&doi=null&md5=f8a2"})
    _fill_missing_article_fields(session, 1, art, 7)

    recorder.record_change.assert_not_called()
    assert _row(session)[0] == ""
