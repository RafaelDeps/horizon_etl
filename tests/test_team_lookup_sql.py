"""Team lookup in sql mode (spec 015): a real SQLAlchemy session over SQLite.

The controller doubles below expose ``_service._repository._session`` the way
eo_lib's TeamController does, so TeamSynchronizer reads ``teams(id, name)``
with plain SQL instead of ``get_all()``.
"""

from types import SimpleNamespace

import pytest
from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from src.core.logic.team_synchronizer import TeamRef, TeamSynchronizer


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT)"))
    with Session(engine) as s:
        yield s


def _insert(session, team_id, name):
    session.execute(
        text("INSERT INTO teams (id, name) VALUES (:id, :name)"),
        {"id": team_id, "name": name},
    )
    session.commit()


class SqlTeamController:
    def __init__(self, session):
        self._service = SimpleNamespace(_repository=SimpleNamespace(_session=session))
        self.session = session
        self.created = []

    def get_all(self):
        raise AssertionError("sql mode must not call get_all()")

    def create_team(self, name, description):
        row = self.session.execute(
            text("INSERT INTO teams (name) VALUES (:name) RETURNING id"),
            {"name": name},
        ).one()
        self.session.commit()
        self.created.append(name)
        return SimpleNamespace(id=row.id, name=name)


def _count_team_selects(session):
    statements = []

    @event.listens_for(session.get_bind(), "after_cursor_execute")
    def _record(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT") and "teams" in statement:
            statements.append(statement)

    return statements


def test_initial_load_reads_ids_and_names_once(session):
    _insert(session, 1, "Projeto Alfa")
    _insert(session, 2, "Projeto Beta")
    controller = SqlTeamController(session)
    synchronizer = TeamSynchronizer(controller, roles_cache={})
    selects = _count_team_selects(session)

    assert synchronizer.ensure_team("Projeto Alfa", "d") == TeamRef(1, "Projeto Alfa")
    assert synchronizer.ensure_team("PROJETO BETA", "d") == TeamRef(2, "Projeto Beta")

    assert len(selects) == 1
    assert controller.created == []


def test_team_created_elsewhere_is_found_by_incremental_refresh(session):
    _insert(session, 1, "Projeto Alfa")
    controller = SqlTeamController(session)
    synchronizer = TeamSynchronizer(controller, roles_cache={})
    synchronizer.ensure_team("Projeto Alfa", "d")

    # e.g. a research group created by another loader in the same process
    _insert(session, 2, "Grupo de Pesquisa Gama")

    team = synchronizer.ensure_team("grupo de pesquisa gama", "d")

    assert team == TeamRef(2, "Grupo de Pesquisa Gama")
    assert controller.created == []
    assert synchronizer._stats["refresh_found"] == 1


def test_created_team_is_a_hit_without_another_range_read(session):
    controller = SqlTeamController(session)
    synchronizer = TeamSynchronizer(controller, roles_cache={})

    created = synchronizer.ensure_team("Projeto Novo", "d")
    selects = _count_team_selects(session)
    again = synchronizer.ensure_team("projeto novo", "d")

    assert controller.created == ["Projeto Novo"]
    assert again == created
    assert selects == []


def test_log_lookup_summary_reports_counters(session):
    _insert(session, 1, "Projeto Alfa")
    controller = SqlTeamController(session)
    synchronizer = TeamSynchronizer(controller, roles_cache={})
    synchronizer.ensure_team("Projeto Alfa", "d")  # hit
    _insert(session, 2, "Grupo Gama")
    synchronizer.ensure_team("Grupo Gama", "d")  # refresh finds it
    synchronizer.ensure_team("Projeto Novo", "d")  # refresh misses, created

    lines = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        synchronizer.log_lookup_summary("x")
    finally:
        logger.remove(sink)

    assert lines == [
        "Team lookup [x]: loaded=1 hits=1 created=1 refreshes=2 "
        "refresh_found=1 failed=0"
    ]


def test_log_lookup_summary_before_any_lookup_is_all_zero():
    synchronizer = TeamSynchronizer(object(), roles_cache={})

    lines = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        synchronizer.log_lookup_summary("idle")
    finally:
        logger.remove(sink)

    assert lines == [
        "Team lookup [idle]: loaded=0 hits=0 created=0 refreshes=0 "
        "refresh_found=0 failed=0"
    ]
