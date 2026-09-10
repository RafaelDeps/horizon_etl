"""Contract tests for ExportCampusResolver.

Reference: specs/010-campus-resolution-fallback/contracts/campus-resolution.md

The resolver attributes campus in two layers. Direct evidence (research group
membership, the execution campus stated by the source) always decides on its
own. Only when a person has no direct evidence at all does the supervisor
fallback speak, and it reads exclusively from the frozen direct layer — which is
what makes inference chains structurally impossible rather than merely unlikely.
"""

import pytest
from sqlalchemy import text

from src.core.logic.export_campus_resolver import ExportCampusResolver
from tests.conftest import FakeCampusController


def build_resolver(campus_session, campus_ctrl=None) -> ExportCampusResolver:
    return ExportCampusResolver(
        campus_session, campus_ctrl or FakeCampusController(campus_session)
    )


@pytest.fixture
def campi(campus_db):
    serra = campus_db.campus("Serra")
    vitoria = campus_db.campus("Vitória")
    alegre = campus_db.campus("Alegre")
    campus_db.commit()
    return {"serra": serra, "vitoria": vitoria, "alegre": alegre}


# --------------------------------------------------------------------------
# US1 — supervisor fallback
# --------------------------------------------------------------------------


def test_student_inherits_supervisor_campus(campus_db, campus_session, campi):
    """C-04: the student's only link is the advisorship; the supervisor decides."""
    supervisor, student = 100, 200
    group = campus_db.research_group(campus_id=campi["serra"])
    campus_db.member(group, supervisor)
    campus_db.advisorship(supervisors=[supervisor], students=[student])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", student)["name"] == "Serra"


def test_direct_evidence_beats_supervisor_inference(campus_db, campus_session, campi):
    """C-03 / FR-007: the student's own group membership outranks the supervisor."""
    supervisor, student = 100, 200
    serra_group = campus_db.research_group(campus_id=campi["serra"])
    vitoria_group = campus_db.research_group(campus_id=campi["vitoria"])
    campus_db.member(serra_group, supervisor)
    campus_db.member(vitoria_group, student)
    campus_db.advisorship(supervisors=[supervisor], students=[student])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", student)["name"] == "Vitória"


def test_advisorship_without_supervisor_leaves_student_null(
    campus_db, campus_session, campi
):
    """C-02: no evidence means None, never a default."""
    student = 200
    campus_db.advisorship(supervisors=[], students=[student])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", student) is None


def test_supervisor_without_campus_leaves_student_null(
    campus_db, campus_session, campi
):
    """FR-010: an uncampused supervisor contributes nothing."""
    supervisor, student = 100, 200
    campus_db.research_group(campus_id=None)
    campus_db.advisorship(supervisors=[supervisor], students=[student])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", student) is None


def test_inference_never_chains(campus_db, campus_session, campi):
    """C-05 / FR-008: an inferred campus is never the input of another inference.

    S has a real campus. A inherits it. B is supervised by A — and must stay
    null, because A's campus is inferred, not direct.
    """
    real_supervisor, person_a, person_b = 100, 200, 300
    group = campus_db.research_group(campus_id=campi["serra"])
    campus_db.member(group, real_supervisor)
    campus_db.advisorship(supervisors=[real_supervisor], students=[person_a])
    campus_db.advisorship(supervisors=[person_a], students=[person_b])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", person_a)["name"] == "Serra"
    assert resolver.get_campus("researcher", person_b) is None


def test_multiple_supervisors_resolve_by_weight(campus_db, campus_session, campi):
    """The dominant supervisor campus wins."""
    student = 200
    serra_group = campus_db.research_group(campus_id=campi["serra"])
    vitoria_group = campus_db.research_group(campus_id=campi["vitoria"])
    for supervisor in (101, 102):
        campus_db.member(serra_group, supervisor)
    campus_db.member(vitoria_group, 103)
    campus_db.advisorship(supervisors=[101], students=[student])
    campus_db.advisorship(supervisors=[102], students=[student])
    campus_db.advisorship(supervisors=[103], students=[student])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", student)["name"] == "Serra"


def test_tied_supervisors_resolve_identically_on_every_run(
    campus_db, campus_session, campi
):
    """C-01 / C-08: a 1-1 tie is broken by name then id, not by row order."""
    student = 200
    serra_group = campus_db.research_group(campus_id=campi["serra"])
    vitoria_group = campus_db.research_group(campus_id=campi["vitoria"])
    campus_db.member(serra_group, 101)
    campus_db.member(vitoria_group, 102)
    campus_db.advisorship(supervisors=[101], students=[student])
    campus_db.advisorship(supervisors=[102], students=[student])
    campus_db.commit()

    answers = {
        build_resolver(campus_session).get_campus("researcher", student)["name"]
        for _ in range(5)
    }

    assert answers == {"Serra"}


# --------------------------------------------------------------------------
# US2 — execution campus asserted by the source
# --------------------------------------------------------------------------


def test_initiative_resolves_from_asserted_execution_campus(
    campus_db, campus_session, campi
):
    """C-06: no research group involved at all."""
    initiative = campus_db.initiative()
    campus_db.execution_campus_assertion("initiative", initiative, campi["alegre"])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("initiative", initiative)["name"] == "Alegre"


def test_advisorship_resolves_from_asserted_execution_campus(
    campus_db, campus_session, campi
):
    advisorship = campus_db.advisorship(supervisors=[101], students=[201])
    campus_db.execution_campus_assertion("advisorship", advisorship, campi["alegre"])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("advisorship", advisorship)["name"] == "Alegre"


def test_team_member_of_asserted_initiative_gets_direct_evidence(
    campus_db, campus_session, campi
):
    """FR-005: participants of a group-less project stop being null."""
    person = 300
    team = campus_db.plain_team()
    campus_db.member(team, person)
    initiative = campus_db.initiative(team_ids=[team])
    campus_db.execution_campus_assertion("initiative", initiative, campi["alegre"])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", person)["name"] == "Alegre"


def test_asserted_initiative_campus_outranks_supervisor_inference(
    campus_db, campus_session, campi
):
    """The asserted campus is direct evidence, so inference must not touch it."""
    person, supervisor = 300, 100
    serra_group = campus_db.research_group(campus_id=campi["serra"])
    campus_db.member(serra_group, supervisor)
    team = campus_db.plain_team()
    campus_db.member(team, person)
    initiative = campus_db.initiative(team_ids=[team])
    campus_db.execution_campus_assertion("initiative", initiative, campi["alegre"])
    campus_db.advisorship(supervisors=[supervisor], students=[person])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", person)["name"] == "Alegre"


def test_advisorship_member_inherits_asserted_execution_campus(
    campus_db, campus_session, campi
):
    student = 201
    advisorship = campus_db.advisorship(supervisors=[101], students=[student])
    campus_db.execution_campus_assertion("advisorship", advisorship, campi["alegre"])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", student)["name"] == "Alegre"


@pytest.mark.parametrize("stored_value", [3, "3", 3.0])
def test_assertion_value_is_parsed_from_any_json_shape(
    campus_db, campus_session, campi, stored_value
):
    """value_json is JSON: the id may arrive as int, string, or float."""
    initiative = campus_db.initiative()
    campus_db.execution_campus_assertion("initiative", initiative, stored_value)
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("initiative", initiative)["name"] == "Alegre"


@pytest.mark.parametrize("bad_value", ["Serra", None, "", 999])
def test_unusable_assertion_values_are_ignored(
    campus_db, campus_session, campi, bad_value
):
    """C-09: a dangling or malformed campus id must not reach the export."""
    initiative = campus_db.initiative()
    campus_db.execution_campus_assertion("initiative", initiative, bad_value)
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("initiative", initiative) is None


def test_unselected_assertions_are_ignored(campus_db, campus_session, campi):
    initiative = campus_db.initiative()
    campus_db.execution_campus_assertion(
        "initiative", initiative, campi["alegre"], is_selected=False
    )
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("initiative", initiative) is None


# --------------------------------------------------------------------------
# US3 — precedence, determinism, resilience
# --------------------------------------------------------------------------


def test_group_membership_survives_a_narrow_execution_majority(
    campus_db, campus_session, campi
):
    """C-07: the group carries weight 3, so a bare majority does not unseat it.

    Two Alegre-executed projects against one Vitória group is exactly the shape
    a single-campus ingestion produces artificially — the person joined
    whatever happened to be loaded, not a different campus.
    """
    person = 300
    vitoria_group = campus_db.research_group(campus_id=campi["vitoria"])
    campus_db.member(vitoria_group, person)

    for _ in range(2):
        team = campus_db.plain_team()
        campus_db.member(team, person)
        initiative = campus_db.initiative(team_ids=[team])
        campus_db.execution_campus_assertion("initiative", initiative, campi["alegre"])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", person)["name"] == "Vitória"


def test_clear_execution_dominance_does_unseat_the_group(
    campus_db, campus_session, campi
):
    """Four executions against one group membership is dominance, not bias."""
    person = 300
    vitoria_group = campus_db.research_group(campus_id=campi["vitoria"])
    campus_db.member(vitoria_group, person)

    for _ in range(4):
        team = campus_db.plain_team()
        campus_db.member(team, person)
        initiative = campus_db.initiative(team_ids=[team])
        campus_db.execution_campus_assertion("initiative", initiative, campi["alegre"])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", person)["name"] == "Alegre"


def test_single_asserted_campus_loses_to_two_group_memberships(
    campus_db, campus_session, campi
):
    """Two group memberships (weight 6) against one execution (weight 1)."""
    person = 300
    for _ in range(2):
        group = campus_db.research_group(campus_id=campi["vitoria"])
        campus_db.member(group, person)
    team = campus_db.plain_team()
    campus_db.member(team, person)
    initiative = campus_db.initiative(team_ids=[team])
    campus_db.execution_campus_assertion("initiative", initiative, campi["alegre"])
    campus_db.commit()

    resolver = build_resolver(campus_session)

    assert resolver.get_campus("researcher", person)["name"] == "Vitória"


def test_tie_break_is_by_campus_name_then_id(campus_db, campus_session, campi):
    """C-08: pins the (-count, name, id) ordering against regressions.

    One Vitória group weighs 3; three Alegre executions weigh 3 as well. Alegre
    wins on name, not on insertion order — reordering the blocks below must not
    change the answer.
    """
    person = 300
    vitoria_group = campus_db.research_group(campus_id=campi["vitoria"])
    campus_db.member(vitoria_group, person)
    for _ in range(3):
        team = campus_db.plain_team()
        campus_db.member(team, person)
        initiative = campus_db.initiative(team_ids=[team])
        campus_db.execution_campus_assertion("initiative", initiative, campi["alegre"])
    campus_db.commit()

    assert (
        build_resolver(campus_session).get_campus("researcher", person)["name"]
        == "Alegre"
    )


def test_repeated_resolution_is_identical(campus_db, campus_session, campi):
    """C-01: the same database always yields the same attribution."""
    person, supervisor = 300, 100
    group = campus_db.research_group(campus_id=campi["serra"])
    campus_db.member(group, supervisor)
    campus_db.advisorship(supervisors=[supervisor], students=[person])
    campus_db.commit()

    answers = [
        build_resolver(campus_session).get_campus("researcher", person)["name"]
        for _ in range(10)
    ]

    assert len(set(answers)) == 1


def test_failing_query_degrades_instead_of_raising(campus_session, campi, campus_db):
    """C-10: a broken table costs its own evidence, not the whole export."""
    campus_db.commit()
    campus_session.execute(text("DROP TABLE advisorship_members"))
    campus_session.commit()

    resolver = build_resolver(campus_session)

    # The campus entities themselves still resolve; only the advisorship
    # evidence is missing.
    assert resolver.get_campus("campus", campi["serra"])["name"] == "Serra"
    assert resolver.get_campus("researcher", 999) is None


def test_unknown_entity_type_returns_none(campus_session, campi, campus_db):
    campus_db.commit()
    resolver = build_resolver(campus_session)

    assert resolver.get_campus("unicorn", 1) is None
    assert resolver.get_campus("researcher", None) is None
