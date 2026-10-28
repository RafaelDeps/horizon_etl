"""Spec 020: an article listed in several CVs keeps the DOI whichever CV is
read first (empty fields are filled, never overwritten)."""

from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.flows.lattes.projects import _fill_missing_article_fields


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
