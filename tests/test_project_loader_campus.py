"""The execution campus stated by SigPesq must survive ingestion.

Before this feature the value was read from the report and then used only to
give a campus to the row's research group — so a project or advisorship with no
registered group silently lost the one authoritative campus the source had
given it. These tests pin the two halves of the fix: the name resolves to a
campus id, and the pair is recorded as tracking attributes regardless of any
research group.
"""

import pytest

from src.core.logic.project_loader import ProjectLoader
from tests.conftest import FakeCampusController


class RecordingStrategy:
    """Counts calls so the caching behaviour is observable."""

    def __init__(self, result=7, raises=False):
        self.result = result
        self.raises = raises
        self.calls = []

    def ensure(self, campus_ctrl, campus_name, org_id):
        self.calls.append((campus_name, org_id))
        if self.raises:
            raise RuntimeError("campus backend unavailable")
        return self.result


@pytest.fixture
def loader(campus_session):
    """A ProjectLoader without its heavy __init__.

    ProjectLoader's constructor builds half a dozen live controllers against
    the real database. The campus logic under test needs none of that, so the
    instance is assembled directly with just the collaborators it touches.
    """
    instance = ProjectLoader.__new__(ProjectLoader)
    instance.campus_strategy = RecordingStrategy()
    instance.campus_ctrl = FakeCampusController(campus_session)
    instance.org_id = 1
    instance._campus_cache = {}
    return instance


def test_stated_campus_resolves_to_an_id(loader):
    assert loader._resolve_execution_campus_id("Serra") == 7
    assert loader.campus_strategy.calls == [("Serra", 1)]


def test_repeated_names_hit_the_cache(loader):
    for name in ("Serra", "serra", "Serra ", "Serra"):
        assert loader._resolve_execution_campus_id(name) == 7

    assert len(loader.campus_strategy.calls) == 1, "campus lookup was not cached"


@pytest.mark.parametrize("empty", [None, "", "   ", float("nan")])
def test_missing_campus_name_resolves_to_none(loader, empty):
    assert loader._resolve_execution_campus_id(empty) is None
    assert loader.campus_strategy.calls == []


def test_backend_failure_does_not_abort_the_row(loader):
    """FR-004 / I-03: an unresolvable campus must not break ingestion."""
    loader.campus_strategy = RecordingStrategy(raises=True)

    assert loader._resolve_execution_campus_id("Serra") is None


def test_attributes_are_recorded_without_a_research_group(loader):
    """I-01: the assertion does not depend on GrupoPesquisa being present."""
    attrs = loader._execution_campus_attrs(
        {"campus_name": "Presidente Kennedy", "research_group_name": None}
    )

    assert attrs == {
        "execution_campus_name": "Presidente Kennedy",
        "execution_campus_id": 7,
    }


def test_unresolved_name_is_still_auditable(loader):
    """The raw name is kept even when it resolved to nothing."""
    loader.campus_strategy = RecordingStrategy(result=None)

    attrs = loader._execution_campus_attrs({"campus_name": "Campus Fantasma"})

    assert attrs == {"execution_campus_name": "Campus Fantasma"}


def test_row_without_a_campus_adds_no_attributes(loader):
    """Lattes rows carry campus_name=None; they must add nothing."""
    assert loader._execution_campus_attrs({"campus_name": None}) == {}


def test_tracked_attributes_carry_the_execution_campus(loader):
    """The wiring: what the loader records must include the campus.

    `_execution_campus_attrs` being correct is worthless if `_process_row`
    stops merging it into the recorded attributes, which is precisely the
    regression this feature exists to prevent.
    """
    attrs = loader._tracked_attrs(
        "Projeto X",
        {
            "campus_name": "Serra",
            "status": "Em andamento",
            "coordinator_name": "Fulana",
        },
    )

    assert attrs["execution_campus_name"] == "Serra"
    assert attrs["execution_campus_id"] == 7
    # The pre-existing attributes must survive the merge untouched.
    assert attrs["name"] == "Projeto X"
    assert attrs["status"] == "Em andamento"
    assert attrs["coordinator_name"] == "Fulana"


def test_tracked_attributes_are_unchanged_for_sources_without_campus(loader):
    """Lattes rows must record exactly what they recorded before."""
    attrs = loader._tracked_attrs("Projeto Lattes", {"campus_name": None})

    assert "execution_campus_id" not in attrs
    assert "execution_campus_name" not in attrs
    assert set(attrs) == {
        "name",
        "status",
        "description",
        "start_date",
        "end_date",
        "coordinator_name",
        "student_names",
        "researcher_names",
    }
