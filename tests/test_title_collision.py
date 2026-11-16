"""TD-029 (branch 030): a project keeps a title an advisorship holds, and the
advisorship gets the disambiguated title it would get in a rebuild."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.core.logic.initiative_handlers import AdvisorshipHandler
from src.core.logic.project_loader import ProjectLoader


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    with Session(engine) as s:
        s.execute(
            text("CREATE TABLE initiatives (id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
        )
        s.execute(
            text(
                "CREATE TABLE source_records (id INTEGER PRIMARY KEY, "
                "source_system TEXT, raw_payload_json TEXT)"
            )
        )
        s.execute(
            text(
                "CREATE TABLE attribute_assertions (id INTEGER PRIMARY KEY, "
                "source_record_id INTEGER, canonical_entity_type TEXT, "
                "canonical_entity_id INTEGER, attribute_name TEXT, value_json TEXT)"
            )
        )
        yield s
    engine.dispose()


def _loader(session, advisorship_ids):
    loader = ProjectLoader.__new__(ProjectLoader)
    loader.controller = SimpleNamespace(
        _service=SimpleNamespace(_repository=SimpleNamespace(_session=session))
    )
    loader.adv_controller = SimpleNamespace(
        get_by_id=lambda i: object() if i in advisorship_ids else None
    )
    return loader


def _assert(session, sr_id, system, entity_id, name, value, payload=None):
    session.execute(
        text("INSERT OR IGNORE INTO source_records VALUES (:i, :s, :p)"),
        {"i": sr_id, "s": system, "p": json.dumps(payload) if payload else None},
    )
    session.execute(
        text(
            "INSERT INTO attribute_assertions (source_record_id, canonical_entity_type, "
            "canonical_entity_id, attribute_name, value_json) "
            "VALUES (:sr, 'advisorship', :e, :n, :v)"
        ),
        {"sr": sr_id, "e": entity_id, "n": name, "v": json.dumps(value)},
    )


def test_the_advisorship_gets_the_rebuild_title(session):
    session.execute(text("INSERT INTO initiatives VALUES (5, 'Lodo de curtume')"))
    _assert(session, 1, "lattes_advisorships", 5, "student_names", ["Ana Souza"])
    _assert(session, 1, "lattes_advisorships", 5, "start_date", "2015-03-01 00:00:00")
    by_name = {"Lodo de curtume": SimpleNamespace(id=5, name="Lodo de curtume")}
    _loader(session, {5})._free_name_held_by_advisorship("Lodo de curtume", by_name, {})
    expected = AdvisorshipHandler._build_disambiguated_advisorship_title(
        None,
        "Lodo de curtume",
        {"student_names": ["Ana Souza"], "start_date": datetime(2015, 3, 1)},
    )
    assert expected == "Lodo de curtume | Orientacao Ana Souza | 2015"
    assert (
        session.execute(text("SELECT name FROM initiatives WHERE id = 5")).scalar()
        == expected
    )
    assert "Lodo de curtume" not in by_name and expected in by_name


def test_a_sigpesq_workplan_keeps_its_id_in_the_title(session):
    session.execute(text("INSERT INTO initiatives VALUES (6, 'Mudas')"))
    _assert(
        session, 2, "sigpesq_advisorships", 6, "student_names", ["Bia"], {"Id": 4882}
    )
    _loader(session, {6})._free_name_held_by_advisorship("Mudas", {}, {})
    assert (
        session.execute(text("SELECT name FROM initiatives WHERE id = 6")).scalar()
        == "Mudas | Orientacao Bia | sigpesq 4882"
    )


def test_the_latest_assertion_wins(session):
    session.execute(text("INSERT INTO initiatives VALUES (7, 'T')"))
    _assert(session, 1, "lattes_advisorships", 7, "student_names", ["Old"])
    _assert(session, 9, "lattes_advisorships", 7, "student_names", ["New"])
    _loader(session, {7})._free_name_held_by_advisorship("T", {}, {})
    assert session.execute(
        text("SELECT name FROM initiatives WHERE id = 7")
    ).scalar() == ("T | Orientacao New")


def test_a_name_held_by_a_project_is_left_alone(session):
    session.execute(text("INSERT INTO initiatives VALUES (8, 'P')"))
    _loader(session, set())._free_name_held_by_advisorship("P", {}, {})
    assert (
        session.execute(text("SELECT name FROM initiatives WHERE id = 8")).scalar()
        == "P"
    )


def test_a_free_name_does_nothing(session):
    _loader(session, set())._free_name_held_by_advisorship("Nothing", {}, {})
    assert session.execute(text("SELECT COUNT(*) FROM initiatives")).scalar() == 0
