"""Spec 041: members of a Lattes project whose name is a fragment ("D", "J")
are not people (research R3, contracts/dashboard-fixes.md section 1)."""

from src.core.logic.strategies.lattes_projects import LattesProjectMappingStrategy

OWNER = "Anderson Mathias Holtz"


def _row(members):
    return {
        "name": "Projeto de Pesquisa X",
        "start_year": 2020,
        "end_year": 2022,
        "status": "Concluded",
        "description": "",
        "initiative_type_name": "Research Project",
        "raw_members": members,
        "raw_sponsors": [],
    }


def _everyone(mapped):
    return (
        [mapped["coordinator_name"]]
        + mapped["researcher_names"]
        + mapped["student_names"]
    )


def test_fragment_members_are_skipped():
    mapped = LattesProjectMappingStrategy(OWNER).map_row(
        _row(
            [
                {"nome": OWNER, "papel": "Coordenador"},
                {"nome": "D", "papel": "Integrante"},
                {"nome": "J", "papel": "Estudante"},
                {"nome": "Graciela", "papel": "Integrante"},
            ]
        )
    )

    assert mapped["coordinator_name"] == OWNER
    assert "D" not in _everyone(mapped)
    assert "J" not in _everyone(mapped)
    assert mapped["researcher_names"] == ["Graciela"]
    assert mapped["student_names"] == []


def test_a_fragment_coordinator_does_not_hide_the_real_one():
    mapped = LattesProjectMappingStrategy(OWNER).map_row(
        _row(
            [
                {"nome": "-", "papel": "Coordenador"},
                {"nome": OWNER, "papel": "Coordenador"},
            ]
        )
    )

    assert mapped["coordinator_name"] == OWNER


def test_without_fragments_the_output_is_unchanged():
    members = [
        {"nome": OWNER, "papel": "Coordenador"},
        {"nome": "Maria da Silva", "papel": "Integrante"},
        {"nome": "João Lima", "papel": "Estudante"},
    ]
    mapped = LattesProjectMappingStrategy(OWNER).map_row(_row(members))

    assert mapped["coordinator_name"] == OWNER
    assert mapped["researcher_names"] == ["Maria da Silva"]
    assert mapped["student_names"] == ["João Lima"]
