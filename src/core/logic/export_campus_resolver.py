"""Campus attribution for the canonical exports.

Ninguém tem campus próprio no banco: a atribuição é derivada aqui, na hora do
export, a partir de duas camadas com autoridades diferentes.

1. **Evidência direta** — participação em grupo de pesquisa e o campus de
   execução que a fonte (SigPesq) afirmou para o projeto/orientação. Contam
   juntas, com peso, e decidem sozinhas.
2. **Inferência pelo orientador** — último recurso, só para quem não tem
   nenhuma evidência direta: a pessoa herda o campus dos membros "Supervisor"
   das orientações de que participa.

A camada 2 lê **exclusivamente** o mapa já congelado da camada 1. Isso não é
detalhe de implementação: é o que torna impossível uma inferência alimentar
outra (orientado de orientado herdando em cadeia) e o que garante que a ordem
das linhas do SQL não influencia o resultado. Se alguém um dia juntar as duas
camadas no mesmo contador, ambas as garantias caem.

Contrato completo em
``specs/010-campus-resolution-fallback/contracts/campus-resolution.md``.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any, Optional

from loguru import logger
from sqlalchemy import text

# Papel que confere autoridade de campus dentro de uma orientação. Comparado
# já normalizado, porque o valor vem de dados carregados por estratégias
# diferentes.
SUPERVISOR_ROLE = "supervisor"

# Peso da participação em grupo de pesquisa, quando a pessoa também tem campus
# de execução afirmado pela fonte.
#
# As duas evidências são diretas, mas dizem coisas diferentes: o grupo indica
# onde a pessoa está vinculada, o campus de execução indica onde um projeto de
# que ela participa acontece. Com peso igual, quem tem grupo em Presidente
# Kennedy e entra em dois projetos executados na Serra vira "Serra" — e numa
# ingestão restrita a um campus isso não é sinal, é viés da amostra.
#
# Com peso 3 o grupo só perde por dominância clara (mais de três vínculos de
# execução em outro campus contra um de grupo), que é o caso em que a mudança
# realmente descreve a pessoa e não o recorte da carga.
RESEARCH_GROUP_MEMBERSHIP_WEIGHT = 3


class ExportCampusResolver:
    """Best-effort campus resolver for export payloads."""

    def __init__(self, session: Any, campus_ctrl: Any):
        self.session = session
        self.campus_ctrl = campus_ctrl
        self._loaded = False
        self._campus_by_id: dict[int, dict[str, Any]] = {}
        self._primary_by_entity: dict[tuple[str, int], dict[str, Any]] = {}
        self._inferred_by_entity: dict[tuple[str, int], dict[str, Any]] = {}

    def get_campus(self, entity_type: str, entity_id: Any) -> Optional[dict[str, Any]]:
        self._ensure_loaded()
        key = self._normalize_key(entity_type, entity_id)
        if key is None:
            return None

        # Direto primeiro, sempre. A inferência só responde pelo silêncio.
        campus = self._primary_by_entity.get(key) or self._inferred_by_entity.get(key)
        return dict(campus) if campus else None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        self._loaded = True
        self._campus_by_id = self._load_campuses()
        if not self._campus_by_id:
            return

        campus_counts: dict[tuple[str, int], Counter[int]] = defaultdict(Counter)

        def add_campus(
            entity_type: str, entity_id: Any, campus_id: Any, weight: int = 1
        ):
            key = self._normalize_key(entity_type, entity_id)
            normalized_campus_id = self._normalize_int(campus_id)
            if key is None or normalized_campus_id is None:
                return
            if normalized_campus_id not in self._campus_by_id:
                return
            campus_counts[key][normalized_campus_id] += max(weight, 1)

        for campus_id in self._campus_by_id:
            add_campus("campus", campus_id, campus_id)

        for row in self._run_query(
            """
            SELECT id AS entity_id, campus_id, 1 AS weight
            FROM research_groups
            WHERE campus_id IS NOT NULL
            """
        ):
            add_campus(
                "research_group", row["entity_id"], row["campus_id"], row["weight"]
            )

        for row in self._run_query(
            """
            SELECT it.initiative_id AS entity_id, rg.campus_id, COUNT(*) AS weight
            FROM initiative_teams it
            JOIN research_groups rg ON rg.id = it.team_id
            WHERE rg.campus_id IS NOT NULL
            GROUP BY it.initiative_id, rg.campus_id
            """
        ):
            add_campus("initiative", row["entity_id"], row["campus_id"], row["weight"])

        for row in self._run_query(
            """
            SELECT a.id AS entity_id, rg.campus_id, COUNT(*) AS weight
            FROM advisorships a
            JOIN initiatives i ON i.id = a.id
            JOIN initiative_teams it ON it.initiative_id = COALESCE(i.parent_id, i.id)
            JOIN research_groups rg ON rg.id = it.team_id
            WHERE rg.campus_id IS NOT NULL
            GROUP BY a.id, rg.campus_id
            """
        ):
            add_campus("advisorship", row["entity_id"], row["campus_id"], row["weight"])

        for row in self._run_query(
            """
            SELECT tm.person_id AS entity_id, rg.campus_id, COUNT(*) AS weight
            FROM team_members tm
            JOIN research_groups rg ON rg.id = tm.team_id
            WHERE rg.campus_id IS NOT NULL
            GROUP BY tm.person_id, rg.campus_id
            """
        ):
            add_campus(
                "researcher",
                row["entity_id"],
                row["campus_id"],
                self._normalize_int(row["weight"]) * RESEARCH_GROUP_MEMBERSHIP_WEIGHT,
            )

        for row in self._run_query(
            """
            SELECT aa.article_id AS entity_id, rg.campus_id, COUNT(*) AS weight
            FROM article_authors aa
            JOIN team_members tm ON tm.person_id = aa.researcher_id
            JOIN research_groups rg ON rg.id = tm.team_id
            WHERE rg.campus_id IS NOT NULL
            GROUP BY aa.article_id, rg.campus_id
            """
        ):
            add_campus("article", row["entity_id"], row["campus_id"], row["weight"])

        for row in self._run_query(
            """
            SELECT gka.area_id AS entity_id, rg.campus_id, COUNT(*) AS weight
            FROM group_knowledge_areas gka
            JOIN research_groups rg ON rg.id = gka.group_id
            WHERE rg.campus_id IS NOT NULL
            GROUP BY gka.area_id, rg.campus_id
            """
        ):
            add_campus(
                "knowledge_area", row["entity_id"], row["campus_id"], row["weight"]
            )

        # Campus afirmado pela própria fonte (CampusExecucao do SigPesq),
        # gravado como assertion pelo ProjectLoader. Vale mesmo quando a linha
        # não tem grupo de pesquisa — que é exatamente o caso em que o campus
        # se perdia antes.
        execution_campus_by_entity: dict[str, dict[int, int]] = defaultdict(dict)
        for row in self._run_query(
            """
            SELECT canonical_entity_type, canonical_entity_id, value_json
            FROM attribute_assertions
            WHERE attribute_name = 'execution_campus_id'
              AND is_selected = 1
            """
        ):
            campus_id = self._campus_id_from_assertion(row["value_json"])
            entity_id = self._normalize_int(row["canonical_entity_id"])
            entity_type = row["canonical_entity_type"]
            if campus_id is None or entity_id is None or not entity_type:
                continue
            execution_campus_by_entity[str(entity_type)][entity_id] = campus_id
            add_campus(str(entity_type), entity_id, campus_id)

        # Quem participa do time de um projeto com campus afirmado herda esse
        # campus como evidência DIRETA — é o dado da fonte, não inferência.
        # O vínculo real é initiative_teams -> team_members; initiative_persons
        # existe no schema mas está vazia.
        initiative_campuses = execution_campus_by_entity.get("initiative", {})
        if initiative_campuses:
            for row in self._run_query(
                """
                SELECT it.initiative_id AS initiative_id, tm.person_id AS person_id
                FROM initiative_teams it
                JOIN team_members tm ON tm.team_id = it.team_id
                """
            ):
                campus_id = initiative_campuses.get(
                    self._normalize_int(row["initiative_id"])
                )
                if campus_id is not None:
                    add_campus("researcher", row["person_id"], campus_id)

        advisorship_campuses = execution_campus_by_entity.get("advisorship", {})
        if advisorship_campuses:
            for row in self._run_query(
                """
                SELECT advisorship_id, person_id
                FROM advisorship_members
                """
            ):
                campus_id = advisorship_campuses.get(
                    self._normalize_int(row["advisorship_id"])
                )
                if campus_id is not None:
                    add_campus("researcher", row["person_id"], campus_id)

        primary_from_direct = self._build_primary_map(campus_counts)

        for row in self._run_query(
            """
            SELECT source_record_id, canonical_entity_type, canonical_entity_id
            FROM entity_matches
            UNION ALL
            SELECT source_record_id, canonical_entity_type, canonical_entity_id
            FROM attribute_assertions
            UNION ALL
            SELECT source_record_id, canonical_entity_type, canonical_entity_id
            FROM entity_change_logs
            WHERE source_record_id IS NOT NULL
            """
        ):
            entity_key = self._normalize_key(
                row["canonical_entity_type"], row["canonical_entity_id"]
            )
            if entity_key is None:
                continue
            campus = primary_from_direct.get(entity_key)
            if campus:
                add_campus("source_record", row["source_record_id"], campus["id"])

        primary_with_sources = self._build_primary_map(campus_counts)

        for row in self._run_query(
            """
            SELECT ingestion_run_id AS entity_id, id AS source_record_id
            FROM source_records
            """
        ):
            source_record_key = self._normalize_key(
                "source_record", row["source_record_id"]
            )
            if source_record_key is None:
                continue
            campus = primary_with_sources.get(source_record_key)
            if campus:
                add_campus("ingestion_run", row["entity_id"], campus["id"])

        self._primary_by_entity = self._build_primary_map(campus_counts)
        self._inferred_by_entity = self._load_supervisor_inferences(
            self._primary_by_entity
        )

    def _load_supervisor_inferences(
        self, primary_direct: dict[tuple[str, int], dict[str, Any]]
    ) -> dict[tuple[str, int], dict[str, Any]]:
        """Deriva campus, por orientação, para quem não tem evidência direta.

        Recebe o mapa direto já pronto e só o consulta — nunca o mapa que está
        construindo. Por isso o resultado independe da ordem das linhas e não
        forma cadeia de inferência.
        """
        members_by_advisorship: dict[Any, list[tuple[Any, Any]]] = defaultdict(list)
        for row in self._run_query(
            """
            SELECT advisorship_id, person_id, role_name
            FROM advisorship_members
            """
        ):
            members_by_advisorship[row["advisorship_id"]].append(
                (row["person_id"], row["role_name"])
            )

        inferred_counts: dict[tuple[str, int], Counter[int]] = defaultdict(Counter)
        for members in members_by_advisorship.values():
            supervisor_campus_ids = []
            for person_id, role_name in members:
                if str(role_name or "").strip().lower() != SUPERVISOR_ROLE:
                    continue
                key = self._normalize_key("researcher", person_id)
                campus = primary_direct.get(key) if key else None
                if campus:
                    supervisor_campus_ids.append(campus["id"])

            if not supervisor_campus_ids:
                continue

            for person_id, _role_name in members:
                key = self._normalize_key("researcher", person_id)
                if key is None or key in primary_direct:
                    continue
                for campus_id in supervisor_campus_ids:
                    inferred_counts[key][campus_id] += 1

        inferred = self._build_primary_map(inferred_counts)
        if inferred:
            logger.debug(
                f"Campus export: {len(primary_direct)} entities resolved from direct "
                f"evidence, {len(inferred)} people from supervisor inference."
            )
        return inferred

    def _campus_id_from_assertion(self, value: Any) -> Optional[int]:
        """Lê o id de campus guardado em `value_json`.

        A coluna é JSON, então o mesmo id chega ora como inteiro, ora como
        string, dependendo de como o driver serializou. Nome de campus e lixo
        viram None em vez de erro.
        """
        campus_id = self._normalize_int(value)
        if campus_id is not None:
            return campus_id

        if isinstance(value, str):
            try:
                return self._normalize_int(json.loads(value))
            except (ValueError, TypeError):
                return None

        return None

    def _load_campuses(self) -> dict[int, dict[str, Any]]:
        try:
            campuses = self.campus_ctrl.get_all()
        except Exception as exc:
            logger.debug(f"Could not preload campuses for export resolution: {exc}")
            return {}

        campus_by_id: dict[int, dict[str, Any]] = {}
        for campus in campuses:
            campus_dict = None
            if isinstance(campus, dict):
                campus_dict = campus
            elif hasattr(campus, "to_dict"):
                try:
                    campus_dict = campus.to_dict()
                except Exception:
                    campus_dict = None

            campus_id = self._normalize_int(
                campus_dict.get("id") if campus_dict else getattr(campus, "id", None)
            )
            name = (
                campus_dict.get("name")
                if campus_dict
                else getattr(campus, "name", None)
            )
            if campus_id is None or not name:
                continue
            campus_by_id[campus_id] = {"id": campus_id, "name": name}

        return campus_by_id

    def _run_query(self, sql: str) -> list[dict[str, Any]]:
        if self.session is None:
            return []

        try:
            rows = self.session.execute(text(sql)).fetchall()
        except Exception as exc:
            logger.debug(f"Campus export query failed: {exc}")
            return []

        result = []
        for row in rows:
            if hasattr(row, "_mapping"):
                result.append(dict(row._mapping))
            elif isinstance(row, dict):
                result.append(row)
            else:
                try:
                    result.append(dict(row))
                except Exception:
                    continue
        return result

    def _build_primary_map(
        self, campus_counts: dict[tuple[str, int], Counter[int]]
    ) -> dict[tuple[str, int], dict[str, Any]]:
        primary: dict[tuple[str, int], dict[str, Any]] = {}
        for key, counter in campus_counts.items():
            if not counter:
                continue

            ordered = sorted(
                counter.items(),
                key=lambda item: (
                    -item[1],
                    self._campus_by_id[item[0]]["name"],
                    item[0],
                ),
            )
            primary[key] = dict(self._campus_by_id[ordered[0][0]])
        return primary

    @staticmethod
    def _normalize_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _normalize_key(
        self, entity_type: Any, entity_id: Any
    ) -> Optional[tuple[str, int]]:
        if not entity_type:
            return None

        normalized_id = self._normalize_int(entity_id)
        if normalized_id is None:
            return None

        return str(entity_type), normalized_id
