"""Spec 041: a person is never linked to themselves in the collaboration
graphs (research R6). The curriculum owner listed as their own student stays
in the data; only the edge is left out."""

import json

import networkx as nx
import pytest

from src.core.logic.null_researchers_collaboration_graph_generator import (
    NullResearchersCollaborationGraphGenerator,
)
from src.core.logic.outside_ifes_collaboration_graph_generator import (
    OutsideIfesCollaborationGraphGenerator,
)
from src.core.logic.people_collaboration_graph_generator import (
    PeopleCollaborationGraphGenerator,
)
from src.core.logic.researchers_collaboration_graph_generator import (
    ResearchersCollaborationGraphGenerator,
)
from src.core.logic.students_collaboration_graph_generator import (
    StudentsCollaborationGraphGenerator,
)

SUBCLASSES = [
    ResearchersCollaborationGraphGenerator,
    StudentsCollaborationGraphGenerator,
    OutsideIfesCollaborationGraphGenerator,
    NullResearchersCollaborationGraphGenerator,
]


def test_add_evidence_never_adds_a_self_edge():
    G = nx.Graph()
    G.add_node(1)
    PeopleCollaborationGraphGenerator()._add_evidence(G, 1, 1, advisorship_count=1)
    assert G.number_of_edges() == 0


def test_add_evidence_leaves_an_existing_edge_alone_for_a_self_pair():
    G = nx.Graph()
    G.add_nodes_from([1, 2])
    gen = PeopleCollaborationGraphGenerator()
    gen._add_evidence(G, 1, 2, initiative_count=1)
    gen._add_evidence(G, 2, 2, initiative_count=5)
    assert list(G.edges(data="weight")) == [(1, 2, 1)]


def _person(pid, advisorships=(), classification="researcher"):
    return {
        "id": pid,
        "name": f"Pessoa {pid}",
        "classification": classification,
        "initiatives": [],
        "articles": [],
        "advisorships": [{"person_id": other} for other in advisorships],
        "campus": None,
    }


@pytest.mark.parametrize("cls", [PeopleCollaborationGraphGenerator] + SUBCLASSES)
def test_generate_has_no_self_edge_and_keeps_the_real_one(tmp_path, cls):
    assert issubclass(cls, PeopleCollaborationGraphGenerator)
    # Person 2 first: an advisorship edge is added when the other person is
    # already a node (the order of the export).
    people = [_person(2), _person(1, advisorships=[1, 2])]
    if cls is StudentsCollaborationGraphGenerator:
        people = [dict(p, was_student=True) for p in people]
    if cls is NullResearchersCollaborationGraphGenerator:
        people = [dict(p, classification=None) for p in people]
    source = tmp_path / "researchers.json"
    source.write_text(json.dumps(people))
    out = tmp_path / "graph.json"

    result = cls().generate(str(source), str(out))

    edges = result["graph"].get("edges") or result["graph"].get("links") or []
    assert all(e["source"] != e["target"] for e in edges)
    if result["graph_stats"]["nodes"] == 2:
        assert result["graph_stats"]["edges"] == 1
