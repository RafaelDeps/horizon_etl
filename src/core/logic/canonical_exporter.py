import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, List, Optional

from eo_lib import InitiativeController, OrganizationController, PersonController
from loguru import logger
from research_domain import (
    CampusController,
    KnowledgeAreaController,
    ResearcherController,
    ResearchGroupController,
)
from sqlalchemy import text

from src.core.logic.advisorship_canonical_values import (
    load_advisorship_source_values,
    resolve_advisorship_canonical_values,
)
from src.core.logic.export_campus_resolver import ExportCampusResolver
from src.core.logic.pii_anonymizer import scrub_pii_deep, scrub_source_record_payload
from src.core.ports.export_sink import IExportSink
from src.research_domain_compat import AdvisorshipRole
from src.tracking.entities import (
    AttributeAssertion,
    EntityChangeLog,
    EntityMatch,
    IngestionRun,
    SourceRecord,
)

try:
    from research_domain.controllers import ArticleController
    from research_domain.domain.entities.article import ArticleType
except ImportError:

    class ArticleController:  # type: ignore[override]
        def __init__(self, *_args, **_kwargs):
            logger.warning(
                "ArticleController is unavailable in the current research_domain installation. "
                "Article exports will fall back to an empty controller."
            )

        def get_all(self) -> list[Any]:
            return []


ADVISORSHIP_STUDENT_ROLE = AdvisorshipRole.STUDENT.value
ADVISORSHIP_SUPERVISOR_ROLE = AdvisorshipRole.SUPERVISOR.value
IFES_STUDENT_ROLES = frozenset(
    {
        "Student",
        "Estudante",
        "Estudante (Egresso)",
    }
)
IFES_STAFF_ROLES = frozenset(
    {
        "Supervisor",
        "Coordinator",
        "Researcher",
        "Pesquisador",
        "Pesquisador (Egresso)",
        "Leader",
        "Líder",
    }
)
PROJECT_STAFF_ROLES = frozenset({"Coordinator", "Researcher"})
RESEARCHER_CLASSIFICATION_EXPORTS = (
    ("researcher", "researchers_only_canonical.json", "Researcher-only Researchers"),
    ("student", "students_canonical.json", "Students"),
    ("outside_ifes", "outside_ifes_canonical.json", "Outside Ifes Researchers"),
    (None, "null_researchers_canonical.json", "Null-classification Researchers"),
)


class CanonicalDataExporter:
    """
    Exports domain entities from the database to canonical JSON files.

    This class orchestrates the extraction of various entities (Organizations, Campuses,
    Knowledge Areas, Researchers, Initiatives) using their respective controllers
    and serializes them into a standardized format for external consumption.

    Attributes:
        sink (IExportSink): The destination for the exported data (e.g., File, S3).
        org_ctrl (OrganizationController): Controller for organizations.
        campus_ctrl (CampusController): Controller for campuses.
        ka_ctrl (KnowledgeAreaController): Controller for knowledge areas.
        researcher_ctrl (ResearcherController): Controller for researchers.
        initiative_ctrl (InitiativeController): Controller for initiatives.
    """

    def __init__(self, sink: IExportSink):
        """
        Initializes the CanonicalDataExporter.

        Args:
            sink (IExportSink): The strategy for exporting the data.
        """
        self.sink = sink
        self.org_ctrl = OrganizationController()
        self.campus_ctrl = CampusController()
        self.ka_ctrl = KnowledgeAreaController()
        self.researcher_ctrl = ResearcherController()
        self.initiative_ctrl = InitiativeController()
        self.article_ctrl = ArticleController()
        self._campus_resolver: Optional[ExportCampusResolver] = None

    def _get_session(self):
        try:
            return self.initiative_ctrl._service._repository._session
        except Exception:
            return None

    def _has_tracking_schema(self) -> bool:
        session = self._get_session()
        if session is None:
            return False

        required_tables = (
            "ingestion_runs",
            "source_records",
            "entity_matches",
            "attribute_assertions",
            "entity_change_logs",
        )
        try:
            for table in required_tables:
                exists = session.execute(
                    text(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table_name"
                    ),
                    {"table_name": table},
                ).fetchone()
                if exists is None:
                    return False
            return True
        except Exception:
            return False

    @staticmethod
    def _row_to_dict(row: Any) -> dict:
        if hasattr(row, "_mapping"):
            return dict(row._mapping)
        if isinstance(row, dict):
            return row
        return dict(row)

    @staticmethod
    def _item_to_export_dict(item: Any) -> dict:
        if isinstance(item, dict):
            return item
        if hasattr(item, "to_dict"):
            return item.to_dict()
        if hasattr(item, "__table__"):
            return {
                column.name: getattr(item, column.name)
                for column in item.__table__.columns
            }
        return {
            "id": getattr(item, "id", None),
            "name": getattr(item, "name", "Unknown"),
        }

    @staticmethod
    def _fetch_researcher_advisorship_rows(session: Any) -> list[Any]:
        members_query = text(
            """
            SELECT
                am_sup.supervisor_id,
                am_std.student_id AS person_id,
                a.id,
                i.name,
                i.status,
                i.start_date,
                i.end_date,
                it.name as type_name,
                a.type as advisorship_type,
                p.name as person_name
            FROM advisorships a
            JOIN initiatives i ON a.id = i.id
            LEFT JOIN initiative_types it ON i.initiative_type_id = it.id
            LEFT JOIN (
                SELECT advisorship_id, MIN(person_id) AS student_id
                FROM advisorship_members
                WHERE role_name = :student_role
                GROUP BY advisorship_id
            ) am_std ON am_std.advisorship_id = a.id
            LEFT JOIN persons p ON am_std.student_id = p.id
            JOIN (
                SELECT advisorship_id, MIN(person_id) AS supervisor_id
                FROM advisorship_members
                WHERE role_name = :supervisor_role
                GROUP BY advisorship_id
            ) am_sup ON am_sup.advisorship_id = a.id
            """
        )
        params = {
            "student_role": ADVISORSHIP_STUDENT_ROLE,
            "supervisor_role": ADVISORSHIP_SUPERVISOR_ROLE,
        }

        try:
            return session.execute(members_query, params).fetchall()
        except Exception as exc:
            logger.info(
                "Falling back to legacy advisorship columns for researcher export: {}",
                exc,
            )

        legacy_query = text(
            """
            SELECT
                a.supervisor_id AS supervisor_id,
                a.student_id AS person_id,
                a.id,
                i.name,
                i.status,
                i.start_date,
                i.end_date,
                it.name as type_name,
                a.type as advisorship_type,
                p.name as person_name
            FROM advisorships a
            JOIN initiatives i ON a.id = i.id
            LEFT JOIN initiative_types it ON i.initiative_type_id = it.id
            LEFT JOIN persons p ON a.student_id = p.id
            WHERE a.supervisor_id IS NOT NULL
            """
        )
        return session.execute(legacy_query).fetchall()

    @staticmethod
    def _fetch_advisorship_export_rows(session: Any) -> list[Any]:
        members_query = text(
            """
            SELECT
                a.id, i.name, i.status, i.description, i.start_date, i.end_date,
                a.type as advisorship_type,
                a.program as advisorship_program,
                it.name as initiative_type_name,
                am_std.student_id AS person_id, p_std.name as person_name,
                am_sup.supervisor_id, p_sup.name as supervisor_name,
                a.fellowship_id,
                f.name as fellowship_name,
                f.description as fellowship_description,
                f.value as fellowship_value,
                o.name as sponsor_name,
                i.parent_id,
                p_init.name as parent_name,
                p_init.status as parent_status,
                p_init.description as parent_description,
                p_init.start_date as parent_start_date,
                p_init.end_date as parent_end_date
            FROM advisorships a
            JOIN initiatives i ON a.id = i.id
            LEFT JOIN initiative_types it ON i.initiative_type_id = it.id
            LEFT JOIN (
                SELECT advisorship_id, MIN(person_id) AS student_id
                FROM advisorship_members
                WHERE role_name = :student_role
                GROUP BY advisorship_id
            ) am_std ON am_std.advisorship_id = a.id
            LEFT JOIN persons p_std ON am_std.student_id = p_std.id
            LEFT JOIN (
                SELECT advisorship_id, MIN(person_id) AS supervisor_id
                FROM advisorship_members
                WHERE role_name = :supervisor_role
                GROUP BY advisorship_id
            ) am_sup ON am_sup.advisorship_id = a.id
            LEFT JOIN persons p_sup ON am_sup.supervisor_id = p_sup.id
            LEFT JOIN initiatives p_init ON i.parent_id = p_init.id
            LEFT JOIN fellowships f ON a.fellowship_id = f.id
            LEFT JOIN organizations o ON f.sponsor_id = o.id
            """
        )
        params = {
            "student_role": ADVISORSHIP_STUDENT_ROLE,
            "supervisor_role": ADVISORSHIP_SUPERVISOR_ROLE,
        }

        try:
            return session.execute(members_query, params).fetchall()
        except Exception as exc:
            logger.info(
                "Falling back to legacy advisorship columns for canonical export: {}",
                exc,
            )

        legacy_query = text(
            """
            SELECT
                a.id, i.name, i.status, i.description, i.start_date, i.end_date,
                a.type as advisorship_type,
                a.program as advisorship_program,
                it.name as initiative_type_name,
                a.student_id AS person_id, p_std.name as person_name,
                a.supervisor_id, p_sup.name as supervisor_name,
                a.fellowship_id,
                f.name as fellowship_name,
                f.description as fellowship_description,
                f.value as fellowship_value,
                o.name as sponsor_name,
                i.parent_id,
                p_init.name as parent_name,
                p_init.status as parent_status,
                p_init.description as parent_description,
                p_init.start_date as parent_start_date,
                p_init.end_date as parent_end_date
            FROM advisorships a
            JOIN initiatives i ON a.id = i.id
            LEFT JOIN initiative_types it ON i.initiative_type_id = it.id
            LEFT JOIN persons p_std ON a.student_id = p_std.id
            LEFT JOIN persons p_sup ON a.supervisor_id = p_sup.id
            LEFT JOIN initiatives p_init ON i.parent_id = p_init.id
            LEFT JOIN fellowships f ON a.fellowship_id = f.id
            LEFT JOIN organizations o ON f.sponsor_id = o.id
            """
        )
        return session.execute(legacy_query).fetchall()

    @staticmethod
    def _normalize_person_id(person_id: Any) -> Any:
        if person_id is None:
            return None
        try:
            return int(person_id)
        except (TypeError, ValueError):
            return person_id

    @classmethod
    def _lookup_person_value(
        cls, values: dict[Any, Any], person_id: Any, default: Any
    ) -> Any:
        normalized_id = cls._normalize_person_id(person_id)
        if normalized_id in values:
            return values[normalized_id]
        if person_id in values:
            return values[person_id]
        return default

    @staticmethod
    def _build_researcher_base_export_dict(item: Any) -> dict[str, Any]:
        if hasattr(item, "to_dict"):
            raw_dict = item.to_dict()
        else:
            raw_dict = {
                "id": getattr(item, "id", None),
                "name": getattr(item, "name", "Unknown"),
                "identification_id": getattr(item, "identification_id", None),
                "birthday": getattr(item, "birthday", None),
            }

        export_dict = dict(raw_dict)
        export_dict.setdefault("id", None)
        export_dict.setdefault("name", "Unknown")
        export_dict.setdefault("identification_id", None)
        export_dict.setdefault("birthday", None)
        export_dict.setdefault("cnpq_url", None)
        export_dict.setdefault("google_scholar_url", None)
        export_dict.setdefault("resume", None)
        export_dict.setdefault("citation_names", None)
        return export_dict

    @classmethod
    def _collect_participant_person_ids(cls, *person_maps: dict[Any, Any]) -> set[Any]:
        participant_ids: set[Any] = set()
        for person_map in person_maps:
            for person_id in person_map.keys():
                normalized_id = cls._normalize_person_id(person_id)
                if normalized_id is not None:
                    participant_ids.add(normalized_id)
        return participant_ids

    @staticmethod
    def _person_sort_key(person_id: Any) -> tuple[bool, int, Any]:
        if person_id is None:
            return (True, 1, "")
        if isinstance(person_id, int):
            return (False, 0, person_id)
        return (False, 1, str(person_id))

    def _export_researcher_classification_views(
        self, export_data: list[dict[str, Any]], base_output_path: str
    ) -> None:
        output_dir = os.path.dirname(base_output_path)

        for classification, filename, label in RESEARCHER_CLASSIFICATION_EXPORTS:
            filtered_data = [
                item
                for item in export_data
                if item.get("classification") == classification
            ]
            output_path = os.path.join(output_dir, filename) if output_dir else filename
            logger.info("Exporting {} {}...", len(filtered_data), label)
            self.sink.export(filtered_data, output_path)
            logger.info("Successfully exported {} to {}", label, output_path)

    @classmethod
    def _append_person_role(
        cls, role_map: dict[Any, list[str]], person_id: Any, role_name: Optional[str]
    ) -> None:
        normalized_id = cls._normalize_person_id(person_id)
        if normalized_id is None or not role_name:
            return
        roles = role_map.setdefault(normalized_id, [])
        if role_name not in roles:
            roles.append(role_name)

    @staticmethod
    def _unique_roles(roles: Optional[List[str]]) -> List[str]:
        if not roles:
            return []
        return list(dict.fromkeys(role for role in roles if role))

    def _fetch_person_project_roles(self, session: Any) -> dict[Any, list[str]]:
        if session is None:
            return {}

        query = text(
            """
            SELECT tm.person_id, r.name AS role_name
            FROM initiative_teams it
            JOIN team_members tm ON tm.team_id = it.team_id
            JOIN roles r ON r.id = tm.role_id
            WHERE it.team_id NOT IN (SELECT id FROM research_groups)
            """
        )

        role_map: dict[Any, list[str]] = {}
        try:
            for row in session.execute(query).fetchall():
                row_data = self._row_to_dict(row)
                self._append_person_role(
                    role_map, row_data.get("person_id"), row_data.get("role_name")
                )
        except Exception as exc:
            logger.warning(
                "Failed to fetch project role evidence for researcher export: {}",
                exc,
            )
        return role_map

    def _fetch_person_research_group_roles(self, session: Any) -> dict[Any, list[str]]:
        if session is None:
            return {}

        query = text(
            """
            SELECT tm.person_id, r.name AS role_name
            FROM research_groups rg
            JOIN team_members tm ON tm.team_id = rg.id
            JOIN roles r ON r.id = tm.role_id
            """
        )

        role_map: dict[Any, list[str]] = {}
        try:
            for row in session.execute(query).fetchall():
                row_data = self._row_to_dict(row)
                self._append_person_role(
                    role_map, row_data.get("person_id"), row_data.get("role_name")
                )
        except Exception as exc:
            logger.warning(
                "Failed to fetch research-group role evidence for researcher export: {}",
                exc,
            )
        return role_map

    def _fetch_person_advisorship_roles(self, session: Any) -> dict[Any, list[str]]:
        if session is None:
            return {}

        members_query = text(
            """
            SELECT am.person_id, COALESCE(am.role_name, r.name) AS role_name
            FROM advisorship_members am
            LEFT JOIN roles r ON r.id = am.role_id
            """
        )

        role_map: dict[Any, list[str]] = {}
        try:
            rows = session.execute(members_query).fetchall()
        except Exception as exc:
            logger.info(
                "Falling back to legacy advisorship columns for researcher role evidence: {}",
                exc,
            )
            legacy_query = text(
                """
                SELECT a.student_id AS person_id, :student_role AS role_name
                FROM advisorships a
                WHERE a.student_id IS NOT NULL
                UNION ALL
                SELECT a.supervisor_id AS person_id, :supervisor_role AS role_name
                FROM advisorships a
                WHERE a.supervisor_id IS NOT NULL
                """
            )
            try:
                rows = session.execute(
                    legacy_query,
                    {
                        "student_role": ADVISORSHIP_STUDENT_ROLE,
                        "supervisor_role": ADVISORSHIP_SUPERVISOR_ROLE,
                    },
                ).fetchall()
            except Exception as legacy_exc:
                logger.warning(
                    "Failed to fetch advisorship role evidence for researcher export: {}",
                    legacy_exc,
                )
                return role_map

        for row in rows:
            row_data = self._row_to_dict(row)
            self._append_person_role(
                role_map, row_data.get("person_id"), row_data.get("role_name")
            )
        return role_map

    def _fetch_person_institutional_email_flags(self, session: Any) -> dict[Any, bool]:
        if session is None:
            return {}

        query = text(
            """
            SELECT
                p.id AS person_id,
                p.identification_id,
                pe.email
            FROM persons p
            LEFT JOIN person_emails pe ON pe.person_id = p.id
            """
        )

        flags: dict[Any, bool] = {}
        try:
            for row in session.execute(query).fetchall():
                row_data = self._row_to_dict(row)
                person_id = self._normalize_person_id(row_data.get("person_id"))
                if person_id is None:
                    continue

                values = [
                    row_data.get("identification_id"),
                    row_data.get("email"),
                ]
                has_institutional_email = any(
                    isinstance(value, str)
                    and value.strip().lower().endswith("@ifes.edu.br")
                    for value in values
                )
                if has_institutional_email:
                    flags[person_id] = True
                else:
                    flags.setdefault(person_id, False)
        except Exception as exc:
            logger.warning(
                "Failed to fetch Ifes email evidence for researcher export: {}",
                exc,
            )
        return flags

    def _fetch_person_academic_reference_counts(self, session: Any) -> dict[Any, int]:
        if session is None:
            return {}

        query = text(
            """
            SELECT ae.advisor_id AS person_id, COUNT(*) AS ref_count
            FROM academic_educations ae
            WHERE ae.advisor_id IS NOT NULL
            GROUP BY ae.advisor_id
            UNION ALL
            SELECT ae.co_advisor_id AS person_id, COUNT(*) AS ref_count
            FROM academic_educations ae
            WHERE ae.co_advisor_id IS NOT NULL
            GROUP BY ae.co_advisor_id
            """
        )

        counts: dict[Any, int] = {}
        try:
            for row in session.execute(query).fetchall():
                row_data = self._row_to_dict(row)
                person_id = self._normalize_person_id(row_data.get("person_id"))
                if person_id is None:
                    continue
                counts[person_id] = counts.get(person_id, 0) + int(
                    row_data.get("ref_count") or 0
                )
        except Exception as exc:
            logger.warning(
                "Failed to fetch academic-reference evidence for researcher export: {}",
                exc,
            )
        return counts

    @classmethod
    def _build_classification_payload(
        cls,
        project_roles: Optional[List[str]] = None,
        research_group_roles: Optional[List[str]] = None,
        advisorship_roles: Optional[List[str]] = None,
        has_institutional_email: bool = False,
        academic_reference_count: int = 0,
    ) -> dict[str, Any]:
        project_roles = cls._unique_roles(project_roles)
        research_group_roles = cls._unique_roles(research_group_roles)
        advisorship_roles = cls._unique_roles(advisorship_roles)

        project_roles_set = set(project_roles)
        group_roles_set = set(research_group_roles)
        advisorship_roles_set = set(advisorship_roles)

        has_project_student = bool(project_roles_set & IFES_STUDENT_ROLES)
        has_group_student = bool(group_roles_set & IFES_STUDENT_ROLES)
        has_advisorship_student = bool(advisorship_roles_set & IFES_STUDENT_ROLES)
        has_any_student = (
            has_project_student or has_group_student or has_advisorship_student
        )

        has_project_staff = bool(project_roles_set & PROJECT_STAFF_ROLES)
        has_group_staff = bool(group_roles_set & IFES_STAFF_ROLES)
        has_advisorship_staff = "Supervisor" in advisorship_roles_set
        has_strong_staff_signal = (
            has_group_staff
            or has_advisorship_staff
            or (has_project_staff and has_institutional_email)
        )
        has_strong_student = has_group_student or has_advisorship_student

        project_only_staff = (
            has_project_staff
            and not has_institutional_email
            and not research_group_roles
            and not advisorship_roles
        )

        classification = None
        confidence = "low"
        classification_note = None

        if has_strong_staff_signal:
            classification = "researcher"
            confidence = (
                "high" if (has_group_staff or has_advisorship_staff) else "medium"
            )
        elif (
            has_any_student
            and not has_project_staff
            and not has_group_staff
            and not has_advisorship_staff
        ):
            classification = "student"
            confidence = (
                "high" if (has_project_student or has_advisorship_student) else "medium"
            )
        elif has_any_student and has_strong_student and not has_strong_staff_signal:
            classification = "student"
            confidence = "medium"
            classification_note = "student_signal_overrides_project_staff_role"
        elif project_only_staff and not has_any_student:
            classification = "outside_ifes"
            confidence = "medium"
            classification_note = "project_only_staff_without_institutional_signals"
        elif (
            academic_reference_count > 0
            and not has_any_student
            and not has_strong_staff_signal
        ):
            classification_note = "academic_advisor_reference_only"

        return {
            "classification": classification,
            "classification_confidence": confidence,
            "classification_note": classification_note,
            "role_evidence": {
                "project_roles": project_roles,
                "research_group_roles": research_group_roles,
                "advisorship_roles": advisorship_roles,
                "has_institutional_email": has_institutional_email,
                "academic_reference_count": academic_reference_count,
            },
            "was_student": has_any_student,
            "was_staff": has_strong_staff_signal,
        }

    def _build_tracking_export(self, entity_type: str) -> List[dict]:
        if not self._has_tracking_schema():
            logger.info(
                "Tracking schema not available. Skipping {} tracking export.",
                entity_type,
            )
            return []

        session = self._get_session()
        if session is None:
            return []

        entity_ids_query = text(
            """
            SELECT canonical_entity_id AS entity_id
            FROM entity_matches
            WHERE canonical_entity_type = :entity_type
            UNION
            SELECT canonical_entity_id AS entity_id
            FROM attribute_assertions
            WHERE canonical_entity_type = :entity_type
            UNION
            SELECT canonical_entity_id AS entity_id
            FROM entity_change_logs
            WHERE canonical_entity_type = :entity_type
            ORDER BY entity_id
            """
        )
        source_rows_query = text(
            """
            SELECT
                em.canonical_entity_id AS entity_id,
                sr.source_system,
                sr.source_entity_type,
                sr.source_record_id,
                sr.source_file,
                sr.source_path,
                em.match_strategy,
                em.match_confidence,
                em.matched_at
            FROM entity_matches em
            JOIN source_records sr ON sr.id = em.source_record_id
            WHERE em.canonical_entity_type = :entity_type
            ORDER BY em.canonical_entity_id, em.matched_at, em.id
            """
        )
        assertion_rows_query = text(
            """
            SELECT
                aa.canonical_entity_id AS entity_id,
                aa.attribute_name,
                aa.value_json,
                aa.value_hash,
                aa.is_selected,
                aa.selection_reason,
                aa.asserted_at,
                sr.id AS source_record_pk,
                sr.source_system,
                sr.source_entity_type,
                sr.source_record_id,
                sr.source_file,
                sr.source_path
            FROM attribute_assertions aa
            JOIN source_records sr ON sr.id = aa.source_record_id
            WHERE aa.canonical_entity_type = :entity_type
            ORDER BY aa.canonical_entity_id, aa.attribute_name, aa.asserted_at DESC, aa.id DESC
            """
        )
        change_rows_query = text(
            """
            SELECT
                ecl.canonical_entity_id AS entity_id,
                ecl.operation,
                ecl.changed_fields_json,
                ecl.before_json,
                ecl.after_json,
                ecl.reason,
                ecl.changed_at,
                ir.id AS run_id,
                ir.source_system AS run_source_system,
                ir.flow_name,
                ir.status AS run_status,
                sr.id AS source_record_pk,
                sr.source_system AS source_record_system,
                sr.source_entity_type,
                sr.source_record_id,
                sr.source_file,
                sr.source_path
            FROM entity_change_logs ecl
            JOIN ingestion_runs ir ON ir.id = ecl.ingestion_run_id
            LEFT JOIN source_records sr ON sr.id = ecl.source_record_id
            WHERE ecl.canonical_entity_type = :entity_type
            ORDER BY ecl.canonical_entity_id, ecl.changed_at, ecl.id
            """
        )

        try:
            entity_ids = [
                self._row_to_dict(row)["entity_id"]
                for row in session.execute(
                    entity_ids_query, {"entity_type": entity_type}
                ).fetchall()
            ]
            if not entity_ids:
                return []

            items = {
                entity_id: {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "sources": [],
                    "created_by": None,
                    "last_updated_by": None,
                    "attributes": {},
                    "matches": [],
                    "changes": [],
                }
                for entity_id in entity_ids
            }

            source_sets: dict[int, set[str]] = defaultdict(set)

            for row in session.execute(
                source_rows_query, {"entity_type": entity_type}
            ).fetchall():
                record = self._row_to_dict(row)
                entity_id = record["entity_id"]
                source_system = record.get("source_system")
                if source_system:
                    source_sets[entity_id].add(source_system)
                items[entity_id]["matches"].append(
                    {
                        "source_system": source_system,
                        "source_entity_type": record.get("source_entity_type"),
                        "source_record_id": record.get("source_record_id"),
                        "source_file": record.get("source_file"),
                        "source_path": record.get("source_path"),
                        "match_strategy": record.get("match_strategy"),
                        "match_confidence": (
                            float(record["match_confidence"])
                            if record.get("match_confidence") is not None
                            else None
                        ),
                        "matched_at": record.get("matched_at"),
                    }
                )

            latest_selected: dict[tuple[int, str], dict] = {}
            for row in session.execute(
                assertion_rows_query, {"entity_type": entity_type}
            ).fetchall():
                record = self._row_to_dict(row)
                entity_id = record["entity_id"]
                source_system = record.get("source_system")
                if source_system:
                    source_sets[entity_id].add(source_system)

                if not record.get("is_selected"):
                    continue

                key = (entity_id, record["attribute_name"])
                if key in latest_selected:
                    continue
                latest_selected[key] = record

            for (entity_id, attribute_name), record in latest_selected.items():
                items[entity_id]["attributes"][attribute_name] = {
                    "selected_from": record.get("source_system"),
                    "source_entity_type": record.get("source_entity_type"),
                    "source_record_id": record.get("source_record_id"),
                    "source_file": record.get("source_file"),
                    "source_path": record.get("source_path"),
                    "source_record_pk": record.get("source_record_pk"),
                    "selection_reason": record.get("selection_reason"),
                    "asserted_at": record.get("asserted_at"),
                    "value": record.get("value_json"),
                    "value_hash": record.get("value_hash"),
                }

            for row in session.execute(
                change_rows_query, {"entity_type": entity_type}
            ).fetchall():
                record = self._row_to_dict(row)
                entity_id = record["entity_id"]
                source_system = record.get("source_record_system") or record.get(
                    "run_source_system"
                )
                if source_system:
                    source_sets[entity_id].add(source_system)

                change = {
                    "operation": record.get("operation"),
                    "source_system": source_system,
                    "flow_name": record.get("flow_name"),
                    "run_id": record.get("run_id"),
                    "run_status": record.get("run_status"),
                    "source_entity_type": record.get("source_entity_type"),
                    "source_record_id": record.get("source_record_id"),
                    "source_file": record.get("source_file"),
                    "source_path": record.get("source_path"),
                    "changed_at": record.get("changed_at"),
                    "changed_fields": record.get("changed_fields_json"),
                    "before": record.get("before_json"),
                    "after": record.get("after_json"),
                    "reason": record.get("reason"),
                }
                items[entity_id]["changes"].append(change)

            for entity_id, item in items.items():
                item["sources"] = sorted(source_sets.get(entity_id, set()))
                if item["changes"]:
                    item["created_by"] = item["changes"][0]
                    item["last_updated_by"] = item["changes"][-1]

            return list(items.values())
        except Exception as exc:
            logger.warning(f"Failed to build tracking export for {entity_type}: {exc}")
            return []

    def _get_campus_resolver(self) -> ExportCampusResolver:
        if self._campus_resolver is None:
            self._campus_resolver = ExportCampusResolver(
                self._get_session(), self.campus_ctrl
            )
        return self._campus_resolver

    def _resolve_record_campus(
        self, record: dict, entity_type: Optional[str] = None
    ) -> Optional[dict]:
        resolver = self._get_campus_resolver()

        if entity_type:
            return resolver.get_campus(entity_type, record.get("id"))

        if record.get("entity_type") and record.get("entity_id") is not None:
            return resolver.get_campus(record["entity_type"], record["entity_id"])

        if (
            record.get("canonical_entity_type")
            and record.get("canonical_entity_id") is not None
        ):
            return resolver.get_campus(
                record["canonical_entity_type"], record["canonical_entity_id"]
            )

        return None

    def _enrich_export_rows(
        self, rows: List[dict], entity_type: Optional[str] = None
    ) -> List[dict]:
        enriched = []
        for row in rows:
            item = dict(row)
            item.setdefault("campus", self._resolve_record_campus(item, entity_type))
            item = scrub_pii_deep(item)
            if entity_type == "source_record":
                payload = item.get("raw_payload_json")
                if payload is not None:
                    item["raw_payload_json"] = scrub_source_record_payload(payload)
            enriched.append(item)
        return enriched

    def _export_entities(
        self,
        data: List[Any],
        output_path: str,
        entity_name: str,
        entity_type: Optional[str] = None,
    ):
        """
        Helper to serialize and export a list of entities.
        """
        logger.info(f"Exporting {len(data)} {entity_name}...")
        try:
            export_data = [self._item_to_export_dict(item) for item in data]
            export_data = self._enrich_export_rows(export_data, entity_type=entity_type)

            self.sink.export(export_data, output_path)
            logger.info(f"Successfully exported {entity_name} to {output_path}")
        except Exception as e:
            logger.error(f"Failed to export {entity_name}: {e}")
            raise e

    def _load_tracking_entities(self, model: Any, label: str) -> Optional[List[Any]]:
        """Returns the entities, or None when tracking is unavailable.

        A query failure raises instead of returning an empty list: writing []
        to the canonical export would silently destroy the previous good file.
        """
        if not self._has_tracking_schema():
            logger.info(
                "Tracking schema not available. Skipping {} canonical export.",
                label,
            )
            return None

        session = self._get_session()
        if session is None:
            logger.info("Tracking session not available. Skipping {} export.", label)
            return None

        try:
            return session.query(model).order_by(model.id).all()
        except Exception as exc:
            logger.error(f"Failed to load {label} tracking entities: {exc}")
            raise

    def _export_tracking_entities(
        self,
        model: Any,
        output_path: str,
        entity_name: str,
        entity_type: Optional[str] = None,
    ) -> None:
        data = self._load_tracking_entities(model, entity_name)
        if data is None:
            return
        self._export_entities(data, output_path, entity_name, entity_type=entity_type)

    def export_organizations(self, output_path: str):
        """
        Exports all organizations to a JSON file.

        Args:
            output_path (str): The destination file path.
        """
        data = self.org_ctrl.get_all()
        self._export_entities(
            data, output_path, "Organizations", entity_type="organization"
        )

    def export_campuses(self, output_path: str, campus_filter: Optional[str] = None):
        """
        Exports campuses to a JSON file, optionally filtered by name.

        Args:
            output_path (str): The destination file path.
            campus_filter (Optional[str]): name of campus to filter.
        """
        data = self.campus_ctrl.get_all()
        if campus_filter:
            data = [c for c in data if c.name.lower() == campus_filter.lower()]
        self._export_entities(data, output_path, "Campuses", entity_type="campus")

    def export_knowledge_areas(self, output_path: str):
        """
        Exports all knowledge areas to a JSON file.

        Args:
            output_path (str): The destination file path.
        """
        data = self.ka_ctrl.get_all()
        self._export_entities(
            data, output_path, "Knowledge Areas", entity_type="knowledge_area"
        )

    def export_researchers(self, output_path: str):
        """
        Exports all researchers to a JSON file.

        Args:
            output_path (str): The destination file path.
        """
        resolver = self._get_campus_resolver()
        session = self._get_session()

        # Fetch raw list
        researchers = self.researcher_ctrl.get_all()

        # Enrichment Data
        # 1. Initiatives (Researcher -> [Initiatives])
        # We need to scan all initiatives' teams/members to map person_id -> initiative list
        # This is expensive but necessary without direct person->initiative DB queries available in current controllers
        person_initiatives_map = {}
        try:
            initiatives = self.initiative_ctrl.get_all()
            from eo_lib import TeamController

            team_ctrl = TeamController()

            # Pre-fetch initiative types
            raw_types = self.initiative_ctrl.list_initiative_types()
            types_map = {}
            for t in raw_types:
                t_id = t.get("id") if isinstance(t, dict) else getattr(t, "id", None)
                if t_id:
                    types_map[t_id] = t

            # Pre-fetch all Research Group IDs to identify "Group Teams" (non-project teams)
            rg_ids = set()
            if session is not None:
                try:
                    rg_ids = {
                        self._row_to_dict(row).get("id")
                        for row in session.execute(
                            text("SELECT id FROM research_groups")
                        ).fetchall()
                    }
                except Exception:
                    rg_ids = set()

            for init in initiatives:
                try:
                    teams = self.initiative_ctrl.get_teams(init.id)
                    for t in teams:
                        t_id = getattr(
                            t, "id", t.get("id") if isinstance(t, dict) else None
                        )

                        # FILTER: If the team is a Research Group, memberships in this team
                        # should not count as being PART OF the initiative in the Researchers canonical export.
                        if t_id in rg_ids:
                            continue

                        if t_id:
                            members = team_ctrl.get_members(t_id)
                            for m in members:
                                p_id = m.person_id
                                if p_id:
                                    if p_id not in person_initiatives_map:
                                        person_initiatives_map[p_id] = []

                                    # Consolidate roles if person is in multiple teams (unlikely now with filter, but safe)
                                    existing = next(
                                        (
                                            i
                                            for i in person_initiatives_map[p_id]
                                            if i["id"] == init.id
                                        ),
                                        None,
                                    )
                                    role_name = m.role.name if m.role else "Member"

                                    if not existing:
                                        # Get Initiative Type
                                        init_type = types_map.get(
                                            init.initiative_type_id
                                        )
                                        type_data = (
                                            {
                                                "id": (
                                                    init_type.get("id")
                                                    if isinstance(init_type, dict)
                                                    else getattr(init_type, "id", None)
                                                ),
                                                "name": (
                                                    init_type.get("name")
                                                    if isinstance(init_type, dict)
                                                    else getattr(
                                                        init_type, "name", None
                                                    )
                                                ),
                                            }
                                            if init_type
                                            else None
                                        )

                                        person_initiatives_map[p_id].append(
                                            {
                                                "id": init.id,
                                                "name": init.name,
                                                "status": init.status,
                                                "initiative_type": type_data,
                                                "demandante": (
                                                    {
                                                        "id": init.demandante.id,
                                                        "name": init.demandante.name,
                                                        "short_name": getattr(
                                                            init.demandante,
                                                            "short_name",
                                                            None,
                                                        ),
                                                    }
                                                    if getattr(init, "demandante", None)
                                                    else None
                                                ),
                                                "roles": [role_name],
                                            }
                                        )
                                    else:
                                        if role_name not in existing["roles"]:
                                            existing["roles"].append(role_name)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(
                f"Failed to fetch initiatives for researcher enrichment: {e}"
            )

        # 2. Research Groups (Researcher -> [Groups])
        # We can reuse the same logic if we know which teams are groups
        # OR we can use the Group members if exposed.
        # ResearchGroupController usually exposes `get_members`? No, it exposes `get_all` groups.
        # But groups are Teams.
        person_groups_map = {}
        try:
            rg_ctrl = ResearchGroupController()
            rg_ctrl.get_all()

            # Since RGs are teams, we might have already processed them in initiatives if they are linked there?
            # No, RGs are distinct entities in the domain lib, but they implement Team interface or are wrapped.
            # Usually RG has a mirrored Team.
            # If we don't have a direct "get members of group" in the controller, we rely on the DB or dgp_cnpq_lib.
            # Checking `ResearchGroupController` in `research_domain`...
            # Assuming we can access the underlying team or members.
            # If not easy, we might skip or do a best effort.
            # Strategy: Access the database session again to query group_members tables directly for speed.

            # Query group members (person_id -> group info)
            # Schema: research_groups.id matches teams.id (joined inheritance or logical link)
            # Members are in team_members table.
            # Query group members (person_id -> group info)
            # Schema: research_groups.id matches teams.id (joined inheritance or logical link)
            # Members are in team_members table.

            # Correct Query with 3-way join
            g_query = text(
                """
                SELECT tm.person_id, rg.id, t.name
                FROM team_members tm
                JOIN research_groups rg ON tm.team_id = rg.id
                JOIN teams t ON rg.id = t.id
            """
            )
            if session is not None:
                g_result = session.execute(g_query).fetchall()
                for row in g_result:
                    pid, gid, gname = row[0], row[1], row[2]
                    if pid not in person_groups_map:
                        person_groups_map[pid] = []
                    person_groups_map[pid].append({"id": gid, "name": gname})

        except Exception as e:
            logger.warning(
                f"Failed to fetch research groups for researcher enrichment: {e}"
            )

        # 3. Knowledge Areas (Researcher -> [KAs])
        person_kas_map = {}
        try:
            # Query researcher_knowledge_areas
            # uses researcher_id (which should map to person_id/researcher.id)
            k_query = text(
                """
                SELECT rka.researcher_id, ka.id, ka.name
                FROM researcher_knowledge_areas rka
                JOIN knowledge_areas ka ON rka.area_id = ka.id
            """
            )
            k_result = session.execute(k_query).fetchall()
            for row in k_result:
                pid, kid, kname = row[0], row[1], row[2]
                if pid not in person_kas_map:
                    person_kas_map[pid] = []
                person_kas_map[pid].append({"id": kid, "name": kname})

        except Exception as e:
            logger.warning(f"Failed to fetch KAs for researcher enrichment: {e}")

        # 4. Academic Education (Researcher -> [Education])
        person_education_map = {}
        try:
            # Query academic_educations with Joins for localized names
            # researcher_id, institution_name, degree_name, course_title, start, end, thesis_title, advisor_name
            # Note: We need to join organizations and education_types
            ae_query = text(
                """
                SELECT 
                    ae.researcher_id, 
                    org.name as institution, 
                    et.name as degree, 
                    ae.title as course_name, 
                    ae.start_year, 
                    ae.end_year, 
                    ae.thesis_title,
                    p_adv.name as advisor_name,
                    p_co.name as co_advisor_name
                FROM academic_educations ae
                LEFT JOIN organizations org ON ae.institution_id = org.id
                LEFT JOIN education_types et ON ae.education_type_id = et.id
                LEFT JOIN researchers adv ON ae.advisor_id = adv.id
                LEFT JOIN persons p_adv ON adv.id = p_adv.id
                LEFT JOIN researchers co ON ae.co_advisor_id = co.id
                LEFT JOIN persons p_co ON co.id = p_co.id
            """
            )

            try:
                ae_result = session.execute(ae_query).fetchall()
                for row in ae_result:
                    rid = row[0]
                    edu_item = {
                        "institution": row[1],
                        "degree": row[2],
                        "course_name": row[3],  # Mapped to title
                        "start_year": row[4],
                        "end_year": row[5],
                        "thesis_title": row[6],
                        "advisor_name": row[7],
                        "co_advisor_name": row[8],
                    }
                    if rid not in person_education_map:
                        person_education_map[rid] = []

                    # Deduplication: Check if item already exists in the list
                    # Using a subset of keys for uniqueness check
                    is_duplicate = False
                    duplicate_index = -1

                    for idx, existing in enumerate(person_education_map[rid]):
                        if (
                            existing.get("institution") == edu_item.get("institution")
                            and existing.get("degree") == edu_item.get("degree")
                            and existing.get("course_name")
                            == edu_item.get("course_name")
                            and existing.get("start_year") == edu_item.get("start_year")
                        ):
                            is_duplicate = True
                            duplicate_index = idx
                            break

                    if not is_duplicate:
                        person_education_map[rid].append(edu_item)
                    else:
                        # If duplicate, assume the one with MORE info is better
                        existing = person_education_map[rid][duplicate_index]

                        better_advisor = not existing.get(
                            "advisor_name"
                        ) and edu_item.get("advisor_name")
                        better_co_advisor = not existing.get(
                            "co_advisor_name"
                        ) and edu_item.get("co_advisor_name")

                        if better_advisor or better_co_advisor:
                            person_education_map[rid][duplicate_index] = edu_item
            except Exception as e:
                logger.warning(
                    f"Failed to export Education data (Schema mismatch?): {e}"
                )
        except Exception as e:
            logger.warning(
                f"Failed to fetch Academic Education for researcher enrichment: {e}"
            )

        # 5. Articles (Researcher -> [Articles])
        person_articles_map = {}
        try:
            a_query = text(
                """
                SELECT aa.researcher_id, a.id, a.title, a.year, a.type, a.doi, a.journal_conference
                FROM article_authors aa
                JOIN articles a ON aa.article_id = a.id
            """
            )
            a_result = session.execute(a_query).fetchall()
            for row in a_result:
                rid, aid, atitle, ayear, atype, adoi, j_c = (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                )
                if rid not in person_articles_map:
                    person_articles_map[rid] = []
                person_articles_map[rid].append(
                    {
                        "id": aid,
                        "title": atitle,
                        "year": ayear,
                        "type": atype,
                        "doi": adoi,
                        "journal_conference": j_c,
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to fetch Articles for researcher enrichment: {e}")

        # 6. Advisorships (Researcher -> [Advisorships])
        person_advisorships_map = {}
        try:
            adv_result = self._fetch_researcher_advisorship_rows(session)

            for row in adv_result:
                row_data = self._row_to_dict(row)
                sup_id = row_data["supervisor_id"]
                adv_data = {
                    "id": row_data["id"],
                    "name": row_data["name"],
                    "status": row_data["status"],
                    "start_year": (
                        row_data["start_date"].year
                        if hasattr(row_data["start_date"], "year")
                        else (
                            int(str(row_data["start_date"])[:4])
                            if row_data["start_date"]
                            else None
                        )
                    ),
                    "end_year": (
                        row_data["end_date"].year
                        if hasattr(row_data["end_date"], "year")
                        else (
                            int(str(row_data["end_date"])[:4])
                            if row_data["end_date"]
                            else None
                        )
                    ),
                    "type": row_data["advisorship_type"],
                    "initiative_type": row_data["type_name"],
                    "person_id": row_data.get("person_id"),
                    "person_name": row_data["person_name"],
                }

                if sup_id not in person_advisorships_map:
                    person_advisorships_map[sup_id] = []
                person_advisorships_map[sup_id].append(adv_data)

        except Exception as e:
            logger.warning(
                f"Failed to fetch Advisorships for researcher enrichment: {e}"
            )

        person_project_roles_map = self._fetch_person_project_roles(session)
        person_research_group_roles_map = self._fetch_person_research_group_roles(
            session
        )
        person_advisorship_roles_map = self._fetch_person_advisorship_roles(session)
        person_institutional_email_flags = self._fetch_person_institutional_email_flags(
            session
        )
        person_academic_reference_counts = self._fetch_person_academic_reference_counts(
            session
        )

        researchers_by_id: dict[Any, dict[str, Any]] = {}
        for researcher in researchers:
            researcher_dict = self._build_researcher_base_export_dict(researcher)
            researcher_id = self._normalize_person_id(researcher_dict.get("id"))
            if researcher_id is None:
                continue
            researchers_by_id[researcher_id] = researcher_dict

        original_researcher_count = len(researchers_by_id)
        participant_person_ids = self._collect_participant_person_ids(
            person_initiatives_map,
            person_groups_map,
            person_advisorships_map,
            person_project_roles_map,
            person_research_group_roles_map,
            person_advisorship_roles_map,
        )
        missing_participant_ids = sorted(
            participant_person_ids - set(researchers_by_id.keys()),
            key=self._person_sort_key,
        )

        added_participant_count = 0
        if missing_participant_ids:
            try:
                person_ctrl = PersonController()
                people_by_id = {}
                for person in person_ctrl.get_all():
                    person_id = self._normalize_person_id(getattr(person, "id", None))
                    if person_id is not None:
                        people_by_id[person_id] = person

                for person_id in missing_participant_ids:
                    person = people_by_id.get(person_id)
                    if person is None:
                        logger.warning(
                            "Skipping researcher export backfill for missing person {} "
                            "because no Person record was found.",
                            person_id,
                        )
                        continue
                    researchers_by_id[person_id] = (
                        self._build_researcher_base_export_dict(person)
                    )
                    added_participant_count += 1
            except Exception as exc:
                logger.warning(
                    "Failed to load participant-only people for researcher export: {}",
                    exc,
                )

        ordered_researcher_ids = sorted(
            researchers_by_id.keys(),
            key=self._person_sort_key,
        )

        # Enrich and Export
        export_data = []
        for researcher_id in ordered_researcher_ids:
            r_dict = dict(researchers_by_id[researcher_id])

            p_id = r_dict.get("id")
            p_id_int = self._normalize_person_id(p_id)

            # Attach details
            initiatives_data = []
            init_list = self._lookup_person_value(person_initiatives_map, p_id, [])

            for init in init_list:
                # Standardize roles to English and pick primary if single string preferred
                # User previously had a single string, but let's provide the first one found
                # or join them if we want to be thorough.
                # To match previous structure but with correct data:
                role_map = {
                    "Coordenador": "Coordinator",
                    "Pesquisador": "Researcher",
                    "Estudante": "Student",
                    "Líder": "Leader",
                    "Membro": "Member",
                }
                translated_roles = [role_map.get(r, r) for r in init["roles"]]

                init_export = init.copy()
                init_export["role"] = translated_roles[0]  # Primary role
                del init_export["roles"]
                init_export["campus"] = resolver.get_campus(
                    "initiative", init_export["id"]
                )
                initiatives_data.append(init_export)

            r_dict["initiatives"] = initiatives_data

            raw_groups = self._lookup_person_value(person_groups_map, p_id, [])
            r_dict["research_groups"] = []
            for group in raw_groups:
                group_export = group.copy()
                group_export["campus"] = resolver.get_campus(
                    "research_group", group_export.get("id")
                )
                r_dict["research_groups"].append(group_export)
            r_dict["knowledge_areas"] = self._lookup_person_value(
                person_kas_map, p_id, []
            )
            r_dict["academic_education"] = self._lookup_person_value(
                person_education_map, p_id, []
            )
            r_dict["articles"] = self._lookup_person_value(
                person_articles_map, p_id, []
            )
            raw_advisorships = self._lookup_person_value(
                person_advisorships_map, p_id, []
            )
            r_dict["advisorships"] = []
            for advisorship in raw_advisorships:
                advisorship_export = advisorship.copy()
                advisorship_export["campus"] = resolver.get_campus(
                    "advisorship", advisorship_export.get("id")
                )
                r_dict["advisorships"].append(advisorship_export)

            r_dict.update(
                self._build_classification_payload(
                    project_roles=self._lookup_person_value(
                        person_project_roles_map, p_id, []
                    ),
                    research_group_roles=self._lookup_person_value(
                        person_research_group_roles_map, p_id, []
                    ),
                    advisorship_roles=self._lookup_person_value(
                        person_advisorship_roles_map, p_id, []
                    ),
                    has_institutional_email=self._lookup_person_value(
                        person_institutional_email_flags, p_id, False
                    ),
                    academic_reference_count=self._lookup_person_value(
                        person_academic_reference_counts, p_id, 0
                    ),
                )
            )
            r_dict["campus"] = resolver.get_campus("researcher", p_id_int or p_id)

            export_data.append(r_dict)

        logger.info(
            "Researcher export base: {} researchers from ResearcherController, "
            "{} participant-only people added, {} total exported.",
            original_researcher_count,
            added_participant_count,
            len(export_data),
        )
        logger.info(f"Exporting {len(export_data)} Researchers...")
        # This bespoke export path bypasses _enrich_export_rows, so scrub the
        # assembled rows here — resumes and free-text fields can carry e-mails
        # and phone numbers (LGPD). The classification views exported below
        # reuse this same (already scrubbed) list.
        export_data = scrub_pii_deep(export_data)
        self.sink.export(export_data, output_path)
        logger.info(f"Successfully exported enriched Researchers to {output_path}")
        self._export_researcher_classification_views(export_data, output_path)

    def export_initiatives(self, output_path: str):
        """
        Exports enriched initiatives (with types, organizations, and team members) to a JSON file.

        This method aggregates data from multiple controllers to provide a complete
        view of each initiative, including its team structure with roles.

        Args:
            output_path (str): The destination file path.
        """
        resolver = self._get_campus_resolver()
        from eo_lib import TeamController

        team_ctrl = TeamController()
        initiatives = self.initiative_ctrl.get_all()
        rg_ctrl = ResearchGroupController()
        # Pre-fetch all Research Groups for finding matches
        # Map <team_id> -> <ResearchGroup>
        rgs_by_team_id = {}
        try:
            all_rgs = rg_ctrl.get_all()
            for rg in all_rgs:
                rg_id = getattr(rg, "id", None)
                if rg_id:
                    rgs_by_team_id[rg_id] = rg
        except Exception as e:
            logger.warning(f"Failed to fetch Research Groups for export mapping: {e}")

        # Fetch Knowledge Areas mapping for Groups (Not used in Initiatives anymore, but keep if needed for other methods)
        group_kas_map = {}
        # Fetch Knowledge Areas mapping for Initiatives
        initiative_kas_map = {}

        try:
            from sqlalchemy import text

            session = rg_ctrl._service._repository._session

            # Group KAs (Optional enrichment if needed elsewhere)
            g_query = text(
                """
                SELECT gka.group_id, ka.id, ka.name
                FROM group_knowledge_areas gka
                JOIN knowledge_areas ka ON gka.area_id = ka.id
             """
            )
            g_result = session.execute(g_query).fetchall()
            for row in g_result:
                gid = row[0]
                if gid not in group_kas_map:
                    group_kas_map[gid] = []
                group_kas_map[gid].append({"id": row[1], "name": row[2]})

            # Initiative KAs
            i_query = text(
                """
                SELECT ika.initiative_id, ka.id, ka.name
                FROM initiative_knowledge_areas ika
                JOIN knowledge_areas ka ON ika.area_id = ka.id
             """
            )
            i_result = session.execute(i_query).fetchall()
            for row in i_result:
                iid = row[0]
                if iid not in initiative_kas_map:
                    initiative_kas_map[iid] = []
                initiative_kas_map[iid].append({"id": row[1], "name": row[2]})

        except Exception as e:
            logger.warning(f"Failed to fetch Knowledge Area mappings: {e}")

        # Initiative enrichment (SigPesq project document extraction). Stored in
        # the initiatives.enrichment_json column by ProjectEnrichmentLoader; the
        # column may not exist on older databases, so this is best-effort.
        initiative_enrichment_map = {}
        try:
            import json as _json

            e_result = session.execute(
                text(
                    "SELECT id, enrichment_json FROM initiatives WHERE enrichment_json IS NOT NULL"
                )
            ).fetchall()
            for row in e_result:
                try:
                    initiative_enrichment_map[row[0]] = _json.loads(row[1])
                except (TypeError, ValueError):
                    continue
        except Exception as e:
            logger.info(f"No initiative enrichment available: {e}")

        # Normalize types and orgs to handle both dicts and objects
        raw_types = self.initiative_ctrl.list_initiative_types()
        types = {}
        for t in raw_types:
            t_id = t.get("id") if isinstance(t, dict) else getattr(t, "id", None)
            if t_id:
                types[t_id] = t

        raw_orgs = self.org_ctrl.get_all()
        orgs = {}
        for o in raw_orgs:
            o_id = o.get("id") if isinstance(o, dict) else getattr(o, "id", None)
            if o_id:
                orgs[o_id] = o

        serialized_data = []
        for item in initiatives:
            # Enriched Initiative Type
            init_type = types.get(item.initiative_type_id)
            if init_type:
                type_data = {
                    "id": (
                        init_type.get("id")
                        if isinstance(init_type, dict)
                        else getattr(init_type, "id", None)
                    ),
                    "name": (
                        init_type.get("name")
                        if isinstance(init_type, dict)
                        else getattr(init_type, "name", None)
                    ),
                    "description": (
                        init_type.get("description")
                        if isinstance(init_type, dict)
                        else getattr(init_type, "description", None)
                    ),
                }
            else:
                type_data = None

            # Enriched Organization
            org = orgs.get(item.organization_id)
            if org:
                org_data = {
                    "id": (
                        org.get("id")
                        if isinstance(org, dict)
                        else getattr(org, "id", None)
                    ),
                    "name": (
                        org.get("name")
                        if isinstance(org, dict)
                        else getattr(org, "name", None)
                    ),
                    "short_name": (
                        org.get("short_name")
                        if isinstance(org, dict)
                        else getattr(org, "short_name", None)
                    ),
                }
            else:
                org_data = None

            # Enriched Team
            team_list = []

            # Identify Research Group
            research_group_data = None

            try:
                teams = self.initiative_ctrl.get_teams(item.id)
                for t_dict in teams:
                    t_id = t_dict.get("id")
                    if t_id:
                        # Check if this team is a Research Group
                        if t_id in rgs_by_team_id and not research_group_data:
                            rg_obj = rgs_by_team_id[t_id]
                            rg_id_val = getattr(rg_obj, "id", None)
                            research_group_data = {
                                "id": rg_id_val,
                                "name": getattr(rg_obj, "name", "Unknown"),
                                "campus": resolver.get_campus(
                                    "research_group", rg_id_val
                                ),
                            }

                        # FILTER: Skip adding members if the team is a Research Group
                        # These members are reported in the group's own context,
                        # not as direct initiative participants.
                        if t_id in rgs_by_team_id:
                            continue

                        members = team_ctrl.get_members(t_id)

                        # Aggregate roles by person
                        person_map = {}  # person_id -> member_data
                        for m in members:
                            p_id = m.person_id
                            if p_id not in person_map:
                                person_map[p_id] = {
                                    "person_id": p_id,
                                    "person_name": (
                                        m.person.name if m.person else "Unknown"
                                    ),
                                    "roles": [],  # Collect role names here
                                    "start_date": (
                                        m.start_date.isoformat()
                                        if m.start_date
                                        else None
                                    ),
                                    "end_date": (
                                        m.end_date.isoformat() if m.end_date else None
                                    ),
                                }

                            role_name = m.role.name if m.role else "Member"
                            if role_name not in person_map[p_id]["roles"]:
                                person_map[p_id]["roles"].append(role_name)

                        # Add aggregated members to team_list
                        for p_data in person_map.values():
                            team_list.append(p_data)
            except Exception as e:
                logger.warning(f"Could not fetch teams for initiative {item.id}: {e}")

            serialized_data.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "status": item.status,
                    "description": item.description,
                    "start_date": (
                        item.start_date.isoformat() if item.start_date else None
                    ),
                    "end_date": item.end_date.isoformat() if item.end_date else None,
                    "initiative_type_id": item.initiative_type_id,
                    "initiative_type": type_data,
                    "organization_id": item.organization_id,
                    "organization": org_data,
                    "parent_id": item.parent_id,
                    "team": team_list,
                    "demandante": (
                        {
                            "id": item.demandante.id,
                            "name": item.demandante.name,
                            "short_name": getattr(item.demandante, "short_name", None),
                        }
                        if getattr(item, "demandante", None)
                        else None
                    ),
                    "campus": resolver.get_campus("initiative", item.id),
                    "research_group": research_group_data,
                    "knowledge_areas": initiative_kas_map.get(item.id, []),
                    "enrichment": initiative_enrichment_map.get(item.id),
                    "external_partner": (
                        item.metadata.get("external_partner")
                        if item.metadata and isinstance(item.metadata, dict)
                        else (
                            getattr(item.metadata, "external_partner", None)
                            if item.metadata
                            else None
                        )
                    ),
                    "external_research_group": (
                        item.metadata.get("external_research_group")
                        if item.metadata and isinstance(item.metadata, dict)
                        else (
                            getattr(item.metadata, "external_research_group", None)
                            if item.metadata
                            else None
                        )
                    ),
                }
            )

        logger.info(f"Exporting {len(serialized_data)} enriched Initiatives...")
        self.sink.export(serialized_data, output_path)
        logger.info(f"Successfully exported enriched Initiatives to {output_path}")

    def export_initiative_types(self, output_path: str):
        """
        Exports all initiative types to a JSON file.

        Args:
            output_path (str): The destination file path.
        """
        data = self.initiative_ctrl.list_initiative_types()
        self._export_entities(
            data, output_path, "Initiative Types", entity_type="initiative_type"
        )

    def export_articles(self, output_path: str):
        """
        Exports all articles to a JSON file.

        Uses a column-only query instead of ``ArticleController.get_all()``:
        the controller's ``authors`` relationship is ``lazy="joined"`` and
        eagerly materializes the full researcher graph for every article,
        spiking resident memory (~2.6GB for a few thousand rows) and
        segfaulting with SIGSEGV on memory-constrained CI runners.

        Args:
            output_path (str): The destination file path.
        """
        session = self._get_session()
        if session is None:
            logger.info("No session available. Skipping Articles export.")
            return
        columns = (
            "id",
            "title",
            "doi",
            "year",
            "type",
            "journal_conference",
            "volume",
            "pages",
        )
        rows = session.execute(
            text(f"SELECT {', '.join(columns)} FROM articles ORDER BY id")
        ).fetchall()
        data = []
        for row in rows:
            item = {column: getattr(row, column) for column in columns}
            raw_type = item.get("type")
            if raw_type is not None:
                try:
                    item["type"] = ArticleType[raw_type].value
                except KeyError:
                    pass
            data.append(item)
        self._export_entities(data, output_path, "Articles", entity_type="article")

    def _export_via_orm(self, model, output_path, label, entity_type=None):
        """Exports every row of an ORM `model` (used for entities without a
        research_domain controller, e.g. awards/languages/proficiencies)."""
        session = self._get_session()
        if session is None:
            logger.info("No session available. Skipping {} export.", label)
            return
        data = session.query(model).order_by(model.id).all()
        self._export_entities(data, output_path, label, entity_type=entity_type)

    def export_awards(self, output_path: str):
        from research_domain.domain.entities.award import Award

        self._export_via_orm(Award, output_path, "Awards", entity_type="award")

    def export_languages(self, output_path: str):
        from research_domain.domain.entities.language import Language

        self._export_via_orm(Language, output_path, "Languages", entity_type="language")

    def export_proficiencies(self, output_path: str):
        from research_domain.domain.entities.proficiency import Proficiency

        self._export_via_orm(
            Proficiency, output_path, "Proficiencies", entity_type="proficiency"
        )

    def export_professional_activities(self, output_path: str):
        from research_domain.controllers import ProfessionalActivityController

        data = ProfessionalActivityController().get_all()
        self._export_entities(
            data,
            output_path,
            "Professional Activities",
            entity_type="professional_activity",
        )

    def export_production_types(self, output_path: str):
        from research_domain.controllers import ProductionTypeController

        data = ProductionTypeController().get_all()
        self._export_entities(
            data, output_path, "Production Types", entity_type="production_type"
        )

    def export_research_productions(self, output_path: str):
        from research_domain.controllers import ResearchProductionController

        data = ResearchProductionController().get_all()
        self._export_entities(
            data,
            output_path,
            "Research Productions",
            entity_type="research_production",
        )

    def export_production_authors(self, output_path: str):
        """Exports the production<->researcher association (no controller;
        raw association rows) so consumers can attribute productions."""
        session = self._get_session()
        if session is None:
            logger.info("No session available. Skipping Production Authors export.")
            return
        rows = session.execute(
            text("SELECT production_id, researcher_id FROM production_authors")
        ).fetchall()
        data = [{"production_id": row[0], "researcher_id": row[1]} for row in rows]
        logger.info(f"Exporting {len(data)} Production Authors...")
        self.sink.export(data, output_path)

    def export_researchers_tracking(self, output_path: str):
        data = self._build_tracking_export("researcher")
        self._export_entities(data, output_path, "Researchers Tracking")

    def export_initiatives_tracking(self, output_path: str):
        data = self._build_tracking_export("initiative")
        self._export_entities(data, output_path, "Initiatives Tracking")

    def export_advisorships_tracking(self, output_path: str):
        data = self._build_tracking_export("advisorship")
        self._export_entities(data, output_path, "Advisorships Tracking")

    def export_ingestion_runs(self, output_path: str):
        self._export_tracking_entities(
            IngestionRun,
            output_path,
            "Tracking Ingestion Runs",
            entity_type="ingestion_run",
        )

    def export_source_records(self, output_path: str):
        self._export_tracking_entities(
            SourceRecord,
            output_path,
            "Tracking Source Records",
            entity_type="source_record",
        )

    def export_entity_matches(self, output_path: str):
        self._export_tracking_entities(
            EntityMatch, output_path, "Tracking Entity Matches"
        )

    def export_attribute_assertions(self, output_path: str):
        self._export_tracking_entities(
            AttributeAssertion, output_path, "Tracking Attribute Assertions"
        )

    def export_entity_change_logs(self, output_path: str):
        self._export_tracking_entities(
            EntityChangeLog, output_path, "Tracking Entity Change Logs"
        )

    def export_tracking_entities(self, output_dir: str):
        self.export_ingestion_runs(
            os.path.join(output_dir, "ingestion_runs_canonical.json")
        )
        self.export_source_records(
            os.path.join(output_dir, "source_records_canonical.json")
        )
        self.export_entity_matches(
            os.path.join(output_dir, "entity_matches_canonical.json")
        )
        self.export_attribute_assertions(
            os.path.join(output_dir, "attribute_assertions_canonical.json")
        )
        self.export_entity_change_logs(
            os.path.join(output_dir, "entity_change_logs_canonical.json")
        )

    def export_all(self, output_dir: str):
        """
        Exports all canonical data to the specified directory.
        Generates: domain exports plus tracking canonical artifacts.
        """
        logger.info(f"Starting Canonical Data Export to {output_dir}")
        os.makedirs(output_dir, exist_ok=True)

        self.export_organizations(
            os.path.join(output_dir, "organizations_canonical.json")
        )
        self.export_campuses(os.path.join(output_dir, "campuses_canonical.json"))
        self.export_knowledge_areas(
            os.path.join(output_dir, "knowledge_areas_canonical.json")
        )
        self.export_researchers(os.path.join(output_dir, "researchers_canonical.json"))
        self.export_researchers_tracking(
            os.path.join(output_dir, "researchers_tracking.json")
        )
        self.export_initiatives(os.path.join(output_dir, "initiatives_canonical.json"))
        self.export_initiatives_tracking(
            os.path.join(output_dir, "initiatives_tracking.json")
        )
        self.export_initiative_types(
            os.path.join(output_dir, "initiative_types_canonical.json")
        )
        self.export_articles(os.path.join(output_dir, "articles_canonical.json"))
        self.export_awards(os.path.join(output_dir, "awards_canonical.json"))
        self.export_languages(os.path.join(output_dir, "languages_canonical.json"))
        self.export_proficiencies(
            os.path.join(output_dir, "proficiencies_canonical.json")
        )
        self.export_professional_activities(
            os.path.join(output_dir, "professional_activities_canonical.json")
        )
        self.export_production_types(
            os.path.join(output_dir, "production_types_canonical.json")
        )
        self.export_research_productions(
            os.path.join(output_dir, "research_productions_canonical.json")
        )
        self.export_production_authors(
            os.path.join(output_dir, "production_authors_canonical.json")
        )
        self.export_advisorships(
            os.path.join(output_dir, "advisorships_canonical.json")
        )
        self.export_advisorships_tracking(
            os.path.join(output_dir, "advisorships_tracking.json")
        )
        self.export_tracking_entities(output_dir)
        self.export_fellowships(os.path.join(output_dir, "fellowships_canonical.json"))

        logger.info("Canonical Data Export completed.")

    def export_advisorships(self, output_path: str):
        """
        Exports all advisorships to a JSON file.
        """
        resolver = self._get_campus_resolver()
        session = self.initiative_ctrl._service._repository._session
        result = self._fetch_advisorship_export_rows(session)
        source_values = load_advisorship_source_values(session)

        projects_map = {}
        orphans = []

        for row in result:
            row_data = self._row_to_dict(row)
            values = resolve_advisorship_canonical_values(
                source_values.get(row_data["id"], [])
            )
            adv_data = {
                "id": row_data["id"],
                "name": row_data["name"],
                "status": row_data["status"],
                "description": row_data["description"],
                "start_date": (
                    row_data["start_date"].isoformat()
                    if hasattr(row_data["start_date"], "isoformat")
                    else str(row_data["start_date"]) if row_data["start_date"] else None
                ),
                "end_date": (
                    row_data["end_date"].isoformat()
                    if hasattr(row_data["end_date"], "isoformat")
                    else str(row_data["end_date"]) if row_data["end_date"] else None
                ),
                "type": row_data["advisorship_type"],
                "initiative_type": row_data["initiative_type_name"],
                "person_id": row_data["person_id"],
                "person_name": row_data["person_name"],
                "supervisor_id": row_data["supervisor_id"],
                "supervisor_name": row_data["supervisor_name"],
                "campus": resolver.get_campus("advisorship", row_data["id"]),
                "year": values.year,
                "program": (
                    values.program
                    or row_data.get("advisorship_program")
                    or row_data.get("fellowship_name")
                ),
                "provider": values.provider or row_data.get("sponsor_name"),
                "fellowship": (
                    {
                        "id": row_data["fellowship_id"],
                        "name": row_data["fellowship_name"],
                        "description": row_data["fellowship_description"],
                        "value": row_data["fellowship_value"],
                        "sponsor_name": row_data["sponsor_name"],
                    }
                    if row_data["fellowship_id"]
                    else None
                ),
            }

            if row_data["parent_id"]:
                if row_data["parent_id"] not in projects_map:
                    projects_map[row_data["parent_id"]] = {
                        "id": row_data["parent_id"],
                        "name": row_data["parent_name"],
                        "status": row_data["parent_status"],
                        "description": row_data["parent_description"],
                        "start_date": (
                            row_data["parent_start_date"].isoformat()
                            if hasattr(row_data["parent_start_date"], "isoformat")
                            else (
                                str(row_data["parent_start_date"])
                                if row_data["parent_start_date"]
                                else None
                            )
                        ),
                        "end_date": (
                            row_data["parent_end_date"].isoformat()
                            if hasattr(row_data["parent_end_date"], "isoformat")
                            else (
                                str(row_data["parent_end_date"])
                                if row_data["parent_end_date"]
                                else None
                            )
                        ),
                        "campus": resolver.get_campus(
                            "initiative", row_data["parent_id"]
                        ),
                        "advisorships": [],
                    }
                projects_map[row_data["parent_id"]]["advisorships"].append(adv_data)
            else:
                orphans.append(adv_data)

        # 3. Fetch Team Members for all parent projects
        parent_ids = [pid for pid in projects_map.keys() if pid is not None]
        if parent_ids:
            # Format IDs for raw SQL IN clause
            ids_str = ",".join(str(pid) for pid in parent_ids)
            members_query = text(
                f"""
                SELECT 
                    it.initiative_id,
                    p.name as person_name,
                    r.name as role_name
                FROM initiative_teams it
                JOIN team_members tm ON it.team_id = tm.team_id
                JOIN persons p ON tm.person_id = p.id
                JOIN roles r ON tm.role_id = r.id
                WHERE it.initiative_id IN ({ids_str})
            """
            )
            try:
                members_result = session.execute(members_query).fetchall()

                logger.info(
                    f"Team fetch: Identified {len(parent_ids)} parents. Found {len(members_result)} members total."
                )

                for m_row in members_result:
                    pid = m_row[0]  # initiative_id
                    if pid in projects_map:
                        if "team" not in projects_map[pid]:
                            projects_map[pid]["team"] = []
                        projects_map[pid]["team"].append(
                            {
                                "name": m_row[1],  # person_name
                                "role": m_row[2],  # role_name
                            }
                        )
            except Exception as e:
                logger.warning(f"Failed to fetch team members for parent projects: {e}")

        # Ensure 'team' and 'advisorships' fields exist for all (even if empty)
        for p in projects_map.values():
            if "team" not in p:
                p["team"] = []
            if "advisorships" not in p:
                p["advisorships"] = []

        # Combine grouped projects, filtering out projects without advisorships
        final_data = [p for p in projects_map.values() if p.get("advisorships")]

        if orphans:
            final_data.append(
                {
                    "id": None,
                    "name": "Sem Projeto Associado",
                    "status": "N/A",
                    "campus": None,
                    "team": [],
                    "description": "Bolsistas sem vínculo direto com um projeto de pesquisa estruturado no SigPesq.",
                    "advisorships": orphans,
                }
            )

        logger.info(
            f"Filtered export: {len(final_data)} parent projects with advisorships (excluded {len(projects_map) - len([p for p in projects_map.values() if p.get('advisorships')])} projects without advisorships)"
        )
        self.sink.export(final_data, output_path)
        logger.info(
            f"Successfully exported {len(final_data)} parent projects with advisorships to {output_path}"
        )

    def export_fellowships(self, output_path: str):
        """
        Exports all fellowships to a JSON file.
        """
        session = self.initiative_ctrl._service._repository._session
        query = text("SELECT * FROM fellowships")
        result = session.execute(query).fetchall()
        data = []
        for row in result:
            data.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "description": row.description,
                    "value": row.value,
                }
            )

        self._export_entities(
            data, output_path, "Fellowships", entity_type="fellowship"
        )

    def generate_advisorship_mart(self, input_path: str, output_path: str):
        """
        Generates an analytical data mart from the hierarchical advisorship JSON.
        """
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                projects = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load canonical advisorships for mart: {e}")
            return

        mart_projects = []
        global_stats = {
            "total_projects": 0,
            "total_advisorships": 0,
            "total_active_advisorships": 0,
            "total_monthly_investment": 0.0,
            "program_distribution": Counter(),
            "investment_per_program": Counter(),
            "volunteer_count": 0,
        }

        supervisors_counter = Counter()
        campus_counter = Counter()

        for p in projects:
            # We also process "Sem Projeto Associado" if it has advisorships
            if not p.get("advisorships"):
                continue

            if p.get("id"):  # Real projects
                global_stats["total_projects"] += 1

            p_metrics = {
                "id": p.get("id"),
                "name": p.get("name"),
                "campus": p.get("campus"),
                "total_students": len(p["advisorships"]),
                "active_students": 0,
                "monthly_investment": 0.0,
                "main_program": "N/A",
                "team_size": len(p.get("team", [])),
            }

            project_campus = p.get("campus")
            if isinstance(project_campus, dict) and project_campus.get("name"):
                campus_counter[project_campus["name"]] += 1

            p_programs = Counter()

            for adv in p["advisorships"]:
                global_stats["total_advisorships"] += 1

                # Active Status
                if adv.get("status") == "Active":
                    p_metrics["active_students"] += 1
                    global_stats["total_active_advisorships"] += 1

                # Fellowship Info
                fell = adv.get("fellowship")
                if fell and isinstance(fell, dict):
                    prog_name = fell.get("name", "Unknown")
                    try:
                        val = float(fell.get("value", 0.0) or 0)
                    except (ValueError, TypeError):
                        val = 0.0

                    p_metrics["monthly_investment"] += val
                    global_stats["total_monthly_investment"] += val

                    p_programs[prog_name] += 1
                    global_stats["program_distribution"][prog_name] += 1
                    global_stats["investment_per_program"][prog_name] += val

                if (
                    not isinstance(fell, dict)
                    or float(fell.get("value", 0.0) or 0) == 0.0
                ):
                    global_stats["volunteer_count"] += 1

                # Supervisor Stats
                sup_name = adv.get("supervisor_name")
                if sup_name:
                    supervisors_counter[sup_name] += 1

            if p_programs:
                p_metrics["main_program"] = p_programs.most_common(1)[0][0]

            if p.get("id"):
                mart_projects.append(p_metrics)

        # Finalizing global stats
        participation_ratio = (
            global_stats["total_advisorships"] / global_stats["total_projects"]
            if global_stats["total_projects"] > 0
            else 0
        )
        volunteer_percentage = (
            (global_stats["volunteer_count"] / global_stats["total_advisorships"]) * 100
            if global_stats["total_advisorships"] > 0
            else 0
        )

        global_stats.update(
            {
                "program_distribution": dict(global_stats["program_distribution"]),
                "investment_per_program": dict(global_stats["investment_per_program"]),
                "participation_ratio": round(participation_ratio, 2),
                "volunteer_percentage": round(volunteer_percentage, 2),
                "total_monthly_investment": round(
                    global_stats["total_monthly_investment"], 2
                ),
            }
        )

        # Rankings
        rankings = {
            "top_supervisors": [
                {"name": name, "count": count}
                for name, count in supervisors_counter.most_common(10)
            ],
            "top_projects_by_investment": sorted(
                [
                    {"name": p["name"], "value": round(p["monthly_investment"], 2)}
                    for p in mart_projects
                ],
                key=lambda x: x["value"],
                reverse=True,
            )[:10],
        }

        final_mart = {
            "projects": mart_projects,
            "campus": (
                campus_counter.most_common(1)[0][0]
                if len(campus_counter) == 1
                else None
            ),
            "campuses": [
                {"name": name, "count": count}
                for name, count in campus_counter.most_common()
            ],
            "global_stats": global_stats,
            "rankings": rankings,
            "generated_at": datetime.now().isoformat(),
        }

        self.sink.export([final_mart], output_path)
        logger.info(
            f"Successfully generated Advisorship Analytics Mart to {output_path}"
        )
