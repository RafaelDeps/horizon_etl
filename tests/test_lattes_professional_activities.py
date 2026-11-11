"""Spec 034: the ingestion keeps every different professional activity of a
researcher and writes nothing for one that is already stored."""

from types import SimpleNamespace

import pytest

from src.core.logic.professional_activity_rules import STORED_FIELDS
from src.flows.lattes.projects import ingest_professional_activities_task

RESEARCHER = SimpleNamespace(id=7, name="R")


def _item(**fields):
    item = {name: None for name in STORED_FIELDS}
    item.update(
        institution="Universidade X, UX, Brasil",
        institution_name="Universidade X",
        institution_acronym="UX",
        institution_country="Brasil",
        start_year=2010,
        activity_type="Atuação profissional",
        current=False,
    )
    item.update(fields)
    return item


class _Session:
    """Answers ``query(...).filter_by(...).all()`` with the stored rows."""

    def __init__(self, rows):
        self.rows = rows

    def query(self, *_):
        return self

    def filter_by(self, **_):
        return self

    def all(self):
        return list(self.rows)


@pytest.fixture
def created(monkeypatch):
    rows = []

    class _Controller:
        def create_professional_activity(self, researcher_id, **fields):
            row = SimpleNamespace(
                id=len(rows) + 1, researcher_id=researcher_id, **fields
            )
            rows.append(row)
            return row

    monkeypatch.setattr(
        "src.flows.lattes.projects.ProfessionalActivityController", _Controller
    )
    return rows


def test_two_activities_at_one_institution_and_start_year_are_both_created(created):
    items = [_item(period="2010 - 2012"), _item(period="2010 - 2015")]
    ingest_professional_activities_task(items, RESEARCHER, _Session([]))
    assert [row.period for row in created] == ["2010 - 2012", "2010 - 2015"]
    assert {row.researcher_id for row in created} == {7}


def test_an_activity_equal_to_a_stored_row_is_not_created(created):
    item = _item(period="2010 - 2012", bond="Servidor")
    stored = SimpleNamespace(id=1, **item)
    ingest_professional_activities_task([item], RESEARCHER, _Session([stored]))
    assert created == []


@pytest.mark.parametrize(
    "field",
    [
        "period",
        "end_year",
        "bond",
        "classification",
        "work_regime",
        "role_function",
        "current",
    ],
)
def test_an_activity_that_differs_from_the_stored_row_is_created(created, field):
    stored = SimpleNamespace(id=1, **_item())
    item = _item(**{field: True if field == "current" else "another value"})
    ingest_professional_activities_task([item], RESEARCHER, _Session([stored]))
    assert len(created) == 1


def test_a_second_pass_creates_nothing(created):
    items = [_item(period="2010 - 2012"), _item(period="2010 - 2015")]
    ingest_professional_activities_task(items, RESEARCHER, _Session([]))
    stored = list(created)
    ingest_professional_activities_task(items, RESEARCHER, _Session(stored))
    assert len(created) == 2


def test_a_stored_current_flag_of_1_equals_true(created):
    stored = SimpleNamespace(id=1, **_item(current=1))
    ingest_professional_activities_task(
        [_item(current=True)], RESEARCHER, _Session([stored])
    )
    assert created == []
