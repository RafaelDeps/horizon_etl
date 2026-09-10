"""Tests for the campus coverage audit script.

This script exists to prove the success criteria, so a silent failure in it is
worse than no script at all: the first version forgot to set `row_factory` on
one of its two connections, every query came back empty, and it cheerfully
reported that all 6,608 people had lost their campus. These tests build a real
SQLite file and assert on the numbers.
"""

import json
import sqlite3

import pytest

from src.scripts.audit_campus_coverage import collect_coverage, find_regressions
from tests.conftest import CAMPUS_SCHEMA


@pytest.fixture
def audit_db(tmp_path):
    """A tiny but complete database: two campuses, four people.

    - 1 is in a Serra research group        -> direct
    - 2 is supervised by 1                  -> inferred
    - 3 is on the team of an Alegre project -> direct
    - 4 has nothing at all                  -> no campus
    """
    db_path = tmp_path / "audit.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(CAMPUS_SCHEMA)
    conn.executescript(
        """
        CREATE TABLE persons (id INTEGER PRIMARY KEY, name VARCHAR);
        INSERT INTO organizational_units (id, name, organization_id)
            VALUES (1, 'Serra', 1), (2, 'Alegre', 1);
        INSERT INTO persons (id, name)
            VALUES (1, 'A'), (2, 'B'), (3, 'C'), (4, 'D');

        INSERT INTO teams (id, name) VALUES (10, 'grupo'), (11, 'time');
        INSERT INTO research_groups (id, campus_id) VALUES (10, 1);
        INSERT INTO team_members (id, team_id, person_id)
            VALUES (1, 10, 1), (2, 11, 3);

        INSERT INTO advisorships (id) VALUES (100);
        INSERT INTO advisorship_members (id, advisorship_id, person_id, role_name)
            VALUES (1, 100, 1, 'Supervisor'), (2, 100, 2, 'Student');

        INSERT INTO initiatives (id, name) VALUES (50, 'projeto');
        INSERT INTO initiative_teams (initiative_id, team_id) VALUES (50, 11);
        INSERT INTO attribute_assertions
            (id, canonical_entity_type, canonical_entity_id, attribute_name,
             value_json, is_selected)
            VALUES (1, 'initiative', 50, 'execution_campus_id', '2', 1);
        """
    )
    conn.commit()
    conn.close()
    return str(db_path)


def test_coverage_splits_direct_from_inferred(audit_db):
    coverage = collect_coverage(audit_db)

    assert coverage["persons"] == 4
    assert coverage["direct"] == 2, "the group member and the project participant"
    assert coverage["inferred"] == 1, "the supervised student"
    assert coverage["without_campus"] == 1
    assert coverage["without_campus_share"] == pytest.approx(0.25)
    assert coverage["campuses"] == 2


def test_coverage_counts_people_per_campus(audit_db):
    coverage = collect_coverage(audit_db)

    assert coverage["by_campus"] == {"Serra": 2, "Alegre": 1}


def test_no_regression_when_everyone_keeps_their_campus(audit_db, tmp_path):
    previous = tmp_path / "previous.json"
    previous.write_text(
        json.dumps(
            [
                {"id": 1, "campus": {"id": 1, "name": "Serra"}},
                {"id": 2, "campus": {"id": 1, "name": "Serra"}},
                {"id": 4, "campus": None},
            ]
        ),
        encoding="utf-8",
    )

    assert find_regressions(audit_db, str(previous)) == []


def test_regression_is_reported_when_a_campus_disappears(audit_db, tmp_path):
    """Person 4 has no evidence, so a previous campus for them is a loss."""
    previous = tmp_path / "previous.json"
    previous.write_text(
        json.dumps([{"id": 4, "campus": {"id": 1, "name": "Serra"}}]),
        encoding="utf-8",
    )

    regressions = find_regressions(audit_db, str(previous))

    assert regressions == [{"person_id": 4, "was": "Serra", "now": None}]


def test_regression_check_reads_every_evidence_layer(audit_db, tmp_path):
    """Guards the row_factory bug: an inferred campus still counts as kept."""
    previous = tmp_path / "previous.json"
    previous.write_text(
        json.dumps([{"id": 2, "campus": {"id": 1, "name": "Serra"}}]),
        encoding="utf-8",
    )

    assert find_regressions(audit_db, str(previous)) == []


def test_previous_export_wrapped_in_an_object_is_accepted(audit_db, tmp_path):
    previous = tmp_path / "previous.json"
    previous.write_text(
        json.dumps({"data": [{"id": 1, "campus": {"id": 1, "name": "Serra"}}]}),
        encoding="utf-8",
    )

    assert find_regressions(audit_db, str(previous)) == []
