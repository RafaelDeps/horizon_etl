import json
import os
from datetime import datetime, timezone
from itertools import combinations
from typing import Any

import networkx as nx
from loguru import logger
from networkx.readwrite import json_graph

from src.core.logic.atomic_io import atomic_write_json


class PeopleCollaborationGraphGenerator:
    """
    Global people collaboration graph using NetworkX.

    Nodes: all people (researchers, students, external, null records).
    Edges: pairwise collaboration evidence.
    Edge weight: initiative_count + article_count + advisorship_count.
    """

    def generate(
        self,
        researchers_path: str,
        output_path: str,
        node_filter=None,
        node_filter_label: str | None = None,
    ) -> dict[str, Any]:
        logger.info("Building people collaboration graph from {}", researchers_path)

        with open(researchers_path) as f:
            raw = json.load(f)
        people = raw["data"] if "data" in raw else raw
        if node_filter is not None:
            before = len(people)
            people = [p for p in people if node_filter(p)]
            logger.info(
                "Node filter '{}': {} → {} people",
                node_filter_label or "custom",
                before,
                len(people),
            )

        G = nx.Graph()

        initiative_members: dict[int, list[int]] = {}
        article_authors: dict[int, list[int]] = {}

        for person in people:
            pid = person.get("id")
            if pid is None:
                continue

            campus = person.get("campus") or {}
            G.add_node(
                pid,
                name=person.get("name"),
                classification=person.get("classification"),
                classification_confidence=person.get("classification_confidence"),
                was_student=person.get("was_student", False),
                was_staff=person.get("was_staff", False),
                campus_name=campus.get("name") if isinstance(campus, dict) else campus,
            )

            for initiative in person.get("initiatives") or []:
                iid = initiative.get("id")
                if iid is not None:
                    initiative_members.setdefault(iid, []).append(pid)

            for article in person.get("articles") or []:
                aid = article.get("id")
                if aid is not None:
                    article_authors.setdefault(aid, []).append(pid)

            for adv in person.get("advisorships") or []:
                other_id = adv.get("person_id")
                if other_id is None:
                    continue
                self._add_evidence(G, pid, other_id, advisorship_count=1)

        for members in initiative_members.values():
            for a, b in combinations(set(members), 2):
                self._add_evidence(G, a, b, initiative_count=1)

        for authors in article_authors.values():
            for a, b in combinations(set(authors), 2):
                self._add_evidence(G, a, b, article_count=1)

        for node in G.nodes():
            G.nodes[node]["degree"] = G.degree(node)
            G.nodes[node]["weighted_degree"] = sum(
                d.get("weight", 0) for _, _, d in G.edges(node, data=True)
            )

        data = json_graph.node_link_data(G)

        result = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": researchers_path,
                **({"node_filter": node_filter_label} if node_filter_label else {}),
                "weight_definition": (
                    "Edge weight = initiative_count + article_count + advisorship_count. "
                    "Each shared initiative, co-authored article, or advisorship adds 1."
                ),
                "relation_types": {
                    "initiative": "People who appear together in the same initiative team.",
                    "article": "People who co-authored the same article.",
                    "advisorship": "Supervisor and student connected by an advisorship.",
                },
            },
            "graph_stats": {
                "nodes": G.number_of_nodes(),
                "edges": G.number_of_edges(),
                "connected_components": nx.number_connected_components(G),
                "relation_event_totals": {
                    "initiative": sum(
                        d.get("initiative_count", 0) for _, _, d in G.edges(data=True)
                    ),
                    "article": sum(
                        d.get("article_count", 0) for _, _, d in G.edges(data=True)
                    ),
                    "advisorship": sum(
                        d.get("advisorship_count", 0) for _, _, d in G.edges(data=True)
                    ),
                },
            },
            "graph": data,
        }

        atomic_write_json(output_path, result, ensure_ascii=False, indent=2)

        logger.info(
            "People collaboration graph: {} nodes, {} edges → {}",
            G.number_of_nodes(),
            G.number_of_edges(),
            output_path,
        )
        return result

    def _add_evidence(
        self,
        G: nx.Graph,
        a: int,
        b: int,
        initiative_count: int = 0,
        article_count: int = 0,
        advisorship_count: int = 0,
    ) -> None:
        # Spec 041 (research R6): a curriculum owner listed as their own
        # student is a source error; it never becomes an edge to themselves.
        if a == b:
            return
        if not G.has_node(a) or not G.has_node(b):
            return
        if G.has_edge(a, b):
            G[a][b]["initiative_count"] += initiative_count
            G[a][b]["article_count"] += article_count
            G[a][b]["advisorship_count"] += advisorship_count
            G[a][b]["weight"] = (
                G[a][b]["initiative_count"]
                + G[a][b]["article_count"]
                + G[a][b]["advisorship_count"]
            )
        else:
            weight = initiative_count + article_count + advisorship_count
            G.add_edge(
                a,
                b,
                weight=weight,
                initiative_count=initiative_count,
                article_count=article_count,
                advisorship_count=advisorship_count,
            )
