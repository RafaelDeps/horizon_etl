"""Shared fixtures for the campus-resolution tests.

The resolver and the loader both talk to real tables, so the cheapest honest
test is a real (in-memory) SQLite database with just the tables they touch.
Nothing here reads ``db/horizon.db`` — the tests must stay independent of
whatever the last ingestion happened to leave behind.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Only the tables the campus resolution path actually reads. Kept deliberately
# narrow: a wider schema would drift from research_domain without ever being
# exercised.
CAMPUS_SCHEMA = """
CREATE TABLE organizational_units (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    organization_id INTEGER
);
CREATE TABLE teams (
    id INTEGER PRIMARY KEY,
    name VARCHAR
);
CREATE TABLE research_groups (
    id INTEGER PRIMARY KEY,
    campus_id INTEGER
);
CREATE TABLE team_members (
    id INTEGER PRIMARY KEY,
    team_id INTEGER,
    person_id INTEGER
);
CREATE TABLE initiatives (
    id INTEGER PRIMARY KEY,
    name VARCHAR,
    parent_id INTEGER
);
CREATE TABLE initiative_teams (
    initiative_id INTEGER,
    team_id INTEGER
);
CREATE TABLE advisorships (
    id INTEGER PRIMARY KEY
);
CREATE TABLE advisorship_members (
    id INTEGER PRIMARY KEY,
    advisorship_id INTEGER,
    person_id INTEGER,
    role_name VARCHAR
);
CREATE TABLE article_authors (
    article_id INTEGER,
    researcher_id INTEGER
);
CREATE TABLE group_knowledge_areas (
    group_id INTEGER,
    area_id INTEGER
);
CREATE TABLE attribute_assertions (
    id INTEGER PRIMARY KEY,
    source_record_id INTEGER,
    canonical_entity_type VARCHAR,
    canonical_entity_id INTEGER,
    attribute_name VARCHAR,
    value_json JSON,
    is_selected BOOLEAN
);
CREATE TABLE entity_matches (
    source_record_id INTEGER,
    canonical_entity_type VARCHAR,
    canonical_entity_id INTEGER
);
CREATE TABLE entity_change_logs (
    source_record_id INTEGER,
    canonical_entity_type VARCHAR,
    canonical_entity_id INTEGER
);
CREATE TABLE source_records (
    id INTEGER PRIMARY KEY,
    ingestion_run_id INTEGER
);
"""


class FakeCampus:
    """Stands in for the research_domain campus entity."""

    def __init__(self, id: int, name: str, organization_id: Optional[int] = 1):
        self.id = id
        self.name = name
        self.organization_id = organization_id


class FakeCampusController:
    """Duck-typed stand-in for research_domain's CampusController.

    Implements only what ``ExportCampusResolver._load_campuses`` and
    ``SigPesqCampusStrategy.ensure`` call: ``get_all`` and ``create_campus``.
    """

    def __init__(self, session: Session, raise_on_get_all: bool = False):
        self._session = session
        self._raise_on_get_all = raise_on_get_all
        self.created: list[str] = []

    def get_all(self) -> list[FakeCampus]:
        if self._raise_on_get_all:
            raise RuntimeError("campus lookup unavailable")
        rows = self._session.execute(
            text(
                "SELECT id, name, organization_id FROM organizational_units ORDER BY id"
            )
        ).fetchall()
        return [FakeCampus(row[0], row[1], row[2]) for row in rows]

    def create_campus(self, name: str, organization_id: int) -> FakeCampus:
        next_id = (
            self._session.execute(
                text("SELECT COALESCE(MAX(id), 0) + 1 FROM organizational_units")
            ).scalar()
            or 1
        )
        self._session.execute(
            text(
                "INSERT INTO organizational_units (id, name, organization_id) "
                "VALUES (:id, :name, :org)"
            ),
            {"id": next_id, "name": name, "org": organization_id},
        )
        self._session.commit()
        self.created.append(name)
        return FakeCampus(next_id, name, organization_id)


class CampusDB:
    """Small builder so tests read as data, not as INSERT statements."""

    def __init__(self, session: Session):
        self.session = session
        self._ids: dict[str, int] = {}

    def _next(self, kind: str) -> int:
        self._ids[kind] = self._ids.get(kind, 0) + 1
        return self._ids[kind]

    def campus(self, name: str, organization_id: int = 1) -> int:
        campus_id = self._next("campus")
        self.session.execute(
            text(
                "INSERT INTO organizational_units (id, name, organization_id) "
                "VALUES (:id, :name, :org)"
            ),
            {"id": campus_id, "name": name, "org": organization_id},
        )
        return campus_id

    def research_group(self, campus_id: Optional[int] = None) -> int:
        group_id = self._next("team")
        self.session.execute(
            text("INSERT INTO teams (id, name) VALUES (:id, :name)"),
            {"id": group_id, "name": f"group-{group_id}"},
        )
        self.session.execute(
            text("INSERT INTO research_groups (id, campus_id) VALUES (:id, :campus)"),
            {"id": group_id, "campus": campus_id},
        )
        return group_id

    def plain_team(self) -> int:
        team_id = self._next("team")
        self.session.execute(
            text("INSERT INTO teams (id, name) VALUES (:id, :name)"),
            {"id": team_id, "name": f"team-{team_id}"},
        )
        return team_id

    def member(self, team_id: int, person_id: int) -> None:
        self.session.execute(
            text(
                "INSERT INTO team_members (id, team_id, person_id) "
                "VALUES (:id, :team, :person)"
            ),
            {"id": self._next("member"), "team": team_id, "person": person_id},
        )

    def initiative(self, team_ids: Optional[list[int]] = None) -> int:
        initiative_id = self._next("initiative")
        self.session.execute(
            text("INSERT INTO initiatives (id, name) VALUES (:id, :name)"),
            {"id": initiative_id, "name": f"initiative-{initiative_id}"},
        )
        for team_id in team_ids or []:
            self.session.execute(
                text(
                    "INSERT INTO initiative_teams (initiative_id, team_id) "
                    "VALUES (:initiative, :team)"
                ),
                {"initiative": initiative_id, "team": team_id},
            )
        return initiative_id

    def advisorship(self, supervisors: list[int], students: list[int]) -> int:
        advisorship_id = self._next("advisorship")
        self.session.execute(
            text("INSERT INTO advisorships (id) VALUES (:id)"),
            {"id": advisorship_id},
        )
        for person_id in supervisors:
            self._advisorship_member(advisorship_id, person_id, "Supervisor")
        for person_id in students:
            self._advisorship_member(advisorship_id, person_id, "Student")
        return advisorship_id

    def _advisorship_member(
        self, advisorship_id: int, person_id: int, role_name: str
    ) -> None:
        self.session.execute(
            text(
                "INSERT INTO advisorship_members "
                "(id, advisorship_id, person_id, role_name) "
                "VALUES (:id, :advisorship, :person, :role)"
            ),
            {
                "id": self._next("advisorship_member"),
                "advisorship": advisorship_id,
                "person": person_id,
                "role": role_name,
            },
        )

    def execution_campus_assertion(
        self,
        entity_type: str,
        entity_id: int,
        value: Any,
        attribute_name: str = "execution_campus_id",
        is_selected: bool = True,
    ) -> None:
        self.session.execute(
            text(
                "INSERT INTO attribute_assertions "
                "(id, source_record_id, canonical_entity_type, canonical_entity_id, "
                " attribute_name, value_json, is_selected) "
                "VALUES (:id, :source, :type, :entity, :attr, :value, :selected)"
            ),
            {
                "id": self._next("assertion"),
                "source": None,
                "type": entity_type,
                "entity": entity_id,
                "attr": attribute_name,
                "value": json.dumps(value),
                "selected": is_selected,
            },
        )

    def commit(self) -> None:
        self.session.commit()


@pytest.fixture
def campus_session() -> Session:
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        for statement in CAMPUS_SCHEMA.strip().split(";"):
            if statement.strip():
                connection.execute(text(statement))
        connection.commit()
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def campus_db(campus_session: Session) -> CampusDB:
    return CampusDB(campus_session)


@pytest.fixture
def campus_ctrl(campus_session: Session) -> FakeCampusController:
    return FakeCampusController(campus_session)
