from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Dict, Optional

from eo_lib import Initiative, InitiativeController, Person
from eo_lib.domain import Role
from loguru import logger
from research_domain import (
    CampusController,
    KnowledgeAreaController,
    ResearcherController,
    ResearchGroupController,
    UniversityController,
)

# Workaround: Import directly from controllers module since not exported in __init__
from research_domain.controllers.controllers import (
    AdvisorshipController,
    FellowshipController,
)
from sqlalchemy import text

from src.research_domain_compat import (
    Advisorship,
    AdvisorshipRole,
    Fellowship,
    advisorship_supports_members_api,
)


class BaseInitiativeHandler(ABC):
    """Base class for handling specific initiative types during ingestion."""

    def __init__(self, initiative_controller: InitiativeController):
        self.initiative_controller = initiative_controller

    @abstractmethod
    def create_or_update(
        self,
        project_data: Dict[str, Any],
        existing_initiative: Optional[Any],
        initiative_type_name: str,
        initiative_type_id: int,
        organization_id: Optional[int],
        parent_id: Optional[int] = None,
    ) -> Any:
        """Creates or updates the initiative entity."""
        pass


class StandardProjectHandler(BaseInitiativeHandler):
    """Handler for standard research projects."""

    def create_or_update(
        self,
        project_data: Dict[str, Any],
        existing_initiative: Optional[Any],
        initiative_type_name: str,
        initiative_type_id: int,
        organization_id: Optional[int],
        parent_id: Optional[int] = None,
    ) -> Any:
        title = project_data["title"]
        metadata = project_data.get("metadata", {}).copy()
        if project_data.get("identity_key"):
            metadata["source_identity"] = project_data["identity_key"]

        if existing_initiative:
            logger.debug(f"Updating existing initiative: {title[:50]}...")
            self.initiative_controller.update_initiative(
                initiative_id=existing_initiative.id,
                name=title,
                status=project_data.get("status", "Unknown"),
                description=project_data.get("description"),
                start_date=project_data.get("start_date"),
                end_date=project_data.get("end_date"),
                initiative_type_name=initiative_type_name,
            )
            # Force organization and parent update if possible
            try:
                existing_initiative.organization_id = organization_id
                if parent_id is not None:
                    existing_initiative.parent_id = parent_id
                if metadata:
                    existing_initiative.metadata = metadata
                self.initiative_controller.update(existing_initiative)
            except Exception:
                pass
            return existing_initiative
        else:
            logger.debug(f"Creating new initiative: {title[:50]}...")
            initiative = Initiative(
                name=title,
                status=project_data.get("status", "Unknown"),
                start_date=project_data.get("start_date"),
                end_date=project_data.get("end_date"),
                description=project_data.get("description"),
                initiative_type_id=initiative_type_id,
                organization_id=organization_id,
                parent_id=parent_id,
            )
            if metadata:
                initiative.metadata = metadata

            self.initiative_controller.create(initiative)
            return initiative


class AdvisorshipHandler(BaseInitiativeHandler):
    """Handler for Advisorships and Fellowships."""

    def __init__(
        self,
        initiative_controller: InitiativeController,
        person_matcher,
        entity_manager,
    ):
        super().__init__(initiative_controller)
        self.adv_controller = AdvisorshipController()
        self.fel_controller = FellowshipController()
        self.person_matcher = person_matcher
        self.entity_manager = entity_manager
        self._fellowships_cache: Dict[str, Fellowship] = {}
        self._advisorship_roles_cache: Dict[str, Role] = {}
        self._preload_fellowships()

    def _preload_fellowships(self):
        """Preload fellowships into cache."""
        try:
            all_fels = self.fel_controller.get_all()
            for f in all_fels:
                name = self._get_fellowship_value(f, "name")
                if name:
                    fellowship_data = {"name": name}
                    sponsor_name = self._get_fellowship_sponsor_name(f)
                    sponsor_id = self._get_fellowship_value(f, "sponsor_id")
                    if sponsor_name:
                        fellowship_data["sponsor_name"] = sponsor_name
                    self._cache_fellowship(
                        f,
                        fellowship_data,
                        sponsor_id=sponsor_id,
                    )
        except Exception as e:
            logger.warning(f"Failed to preload fellowships: {e}")

    def create_or_update(
        self,
        project_data: Dict[str, Any],
        existing_initiative: Optional[Any],
        initiative_type_name: str,
        initiative_type_id: int,
        organization_id: Optional[int],
        parent_id: Optional[int] = None,
    ) -> Any:
        title = project_data["title"]
        metadata = project_data.get("metadata", {}).copy()
        if project_data.get("identity_key"):
            metadata["source_identity"] = project_data["identity_key"]
        persisted_title = self._resolve_persisted_title(
            title,
            project_data,
            current_id=getattr(existing_initiative, "id", None),
        )
        if not existing_initiative:
            existing_initiative = self._find_existing_advisorship_by_title(
                persisted_title
            )

        if existing_initiative:
            # Advisorship update logic (using standard initiative update as base)
            logger.debug(f"Updating existing advisorship: {title[:50]}...")
            self.initiative_controller.update_initiative(
                initiative_id=existing_initiative.id,
                name=persisted_title,
                status=project_data.get("status", "Unknown"),
                description=project_data.get("description"),
                start_date=project_data.get("start_date"),
                end_date=project_data.get("end_date"),
                initiative_type_name=initiative_type_name,
            )
            # Force organization and parent update if possible
            try:
                existing_initiative.organization_id = organization_id
                if parent_id is not None:
                    existing_initiative.parent_id = parent_id
                if metadata:
                    existing_initiative.metadata = metadata
                self.initiative_controller.update(existing_initiative)
            except Exception:
                pass

            # Update specialized fields
            # If it's a base Initiative, we MUST fetch it as Advisorship to access specialized fields
            target_adv = existing_initiative
            if not isinstance(existing_initiative, Advisorship):
                try:
                    # Fetch specialized record by ID
                    actual_adv = self.adv_controller.get_by_id(existing_initiative.id)
                    if actual_adv:
                        target_adv = actual_adv
                    else:
                        logger.warning(
                            f"Initiative {existing_initiative.id} is not an Advisorship in the DB."
                        )
                        return existing_initiative
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch Advisorship detail for {existing_initiative.id}: {e}"
                    )
                    return existing_initiative

            try:
                target_adv.organization_id = organization_id
                if parent_id is not None:
                    target_adv.parent_id = parent_id
                if metadata:
                    target_adv.metadata = metadata
                self._handle_advisorship_details(target_adv, project_data)
                self.adv_controller.update(target_adv)
            except Exception as e:
                logger.warning(
                    f"Could not update advisorship-specific details for {title}: {e}"
                )

            return target_adv
        else:
            logger.debug(f"Creating new advisorship: {title[:50]}...")
            student_person, supervisor_person = self._resolve_advisorship_people(
                project_data
            )
            fellowship = self._ensure_fellowship(project_data)

            initiative = Advisorship(
                name=persisted_title,
                fellowship_id=getattr(fellowship, "id", None),
                start_date=project_data.get("start_date"),
                end_date=project_data.get("end_date"),
                cancelled=project_data.get("cancelled", False),
                cancellation_date=project_data.get("cancellation_date"),
                description=project_data.get("description"),
                status=project_data.get("status", "Unknown"),
            )
            initiative.initiative_type_id = initiative_type_id
            initiative.organization_id = organization_id
            initiative.parent_id = parent_id
            if metadata:
                initiative.metadata = metadata

            self._handle_advisorship_details(
                initiative,
                project_data,
                student_person=student_person,
                supervisor_person=supervisor_person,
                fellowship=fellowship,
            )
            self.adv_controller.create(initiative)
            return initiative

    def _get_or_create_advisorship_role(self, role_name: str) -> Role:
        cached_role = self._advisorship_roles_cache.get(role_name)
        if cached_role:
            return cached_role

        for role in self.entity_manager.role_controller.get_all():
            candidate_name = role.name if hasattr(role, "name") else role.get("name")
            if candidate_name == role_name:
                self._advisorship_roles_cache[role_name] = role
                return role

        role = self.entity_manager.role_controller.create_role(
            name=role_name,
            description=f"Role: {role_name}",
        )
        self._advisorship_roles_cache[role_name] = role
        return role

    def _resolve_advisorship_people(
        self, project_data: Dict[str, Any]
    ) -> tuple[Optional[Any], Optional[Any]]:
        strict = True  # SigPesq requirement
        student_person = None
        supervisor_person = None

        student_names = project_data.get("student_names") or [None]
        student_emails = project_data.get("student_emails") or [None]
        student_name = student_names[0]
        student_email = student_emails[0]
        if student_name or student_email:
            student_person = self.person_matcher.match_or_create(
                student_name,
                email=student_email,
                strict_match=strict,
            )
            student_person = self._coerce_to_person(student_person)

        supervisor_name = project_data.get("coordinator_name")
        supervisor_email = project_data.get("coordinator_email")
        if supervisor_name or supervisor_email:
            supervisor_person = self.person_matcher.match_or_create(
                supervisor_name,
                email=supervisor_email,
                strict_match=strict,
            )
            supervisor_person = self._coerce_to_person(supervisor_person)

        return student_person, supervisor_person

    def _ensure_fellowship(self, project_data: Dict[str, Any]) -> Optional[Fellowship]:
        fellowship_data = project_data.get("fellowship_data")
        if not fellowship_data:
            return None

        fellowship_data = fellowship_data.copy()
        f_name = fellowship_data["name"]
        sponsor_name = self._clean_fellowship_sponsor_name(
            fellowship_data.get("sponsor_name")
        )
        if sponsor_name:
            fellowship_data["sponsor_name"] = sponsor_name
        else:
            fellowship_data.pop("sponsor_name", None)

        cache_key = self._fellowship_cache_key(fellowship_data)
        fellowship = self._fellowships_cache.get(cache_key)
        sponsor_id = None
        if not fellowship and sponsor_name:
            sponsor_id = self.entity_manager.ensure_organization(name=sponsor_name)
            sponsor_cache_key = self._fellowship_cache_key(
                fellowship_data,
                sponsor_id=sponsor_id,
            )
            fellowship = self._fellowships_cache.get(sponsor_cache_key)

        if not fellowship:
            if sponsor_name and sponsor_id is None:
                sponsor_id = self.entity_manager.ensure_organization(name=sponsor_name)

            fellowship = Fellowship(
                name=f_name,
                value=fellowship_data.get("value", 0.0),
                sponsor_id=sponsor_id,
                description=fellowship_data.get("description"),
            )
            self.fel_controller.create(fellowship)
            self._cache_fellowship(
                fellowship,
                fellowship_data,
                sponsor_id=sponsor_id,
            )
        else:
            updated = False
            new_value = fellowship_data.get("value", 0.0)
            if new_value and fellowship.value != new_value:
                logger.debug(
                    f"Updating fellowship '{f_name}' value: {fellowship.value} → {new_value}"
                )
                fellowship.value = new_value
                updated = True
            if sponsor_name and not fellowship.sponsor_id:
                sponsor_id = self.entity_manager.ensure_organization(name=sponsor_name)
                if sponsor_id:
                    fellowship.sponsor_id = sponsor_id
                    updated = True
            if updated:
                self.fel_controller.update(fellowship)
                self._cache_fellowship(
                    fellowship,
                    fellowship_data,
                    sponsor_id=sponsor_id or fellowship.sponsor_id,
                )

        return fellowship

    def _cache_fellowship(
        self,
        fellowship: Fellowship,
        fellowship_data: Dict[str, Any],
        *,
        sponsor_id: Optional[int] = None,
    ) -> None:
        self._fellowships_cache[self._fellowship_cache_key(fellowship_data)] = (
            fellowship
        )
        if sponsor_id is not None:
            self._fellowships_cache[
                self._fellowship_cache_key(
                    fellowship_data,
                    sponsor_id=sponsor_id,
                )
            ] = fellowship

    def _fellowship_cache_key(
        self,
        fellowship_data: Dict[str, Any],
        *,
        sponsor_id: Optional[int] = None,
    ) -> str:
        name_key = self._normalize_fellowship_cache_part(fellowship_data["name"])
        if sponsor_id is not None:
            sponsor_key = f"id:{sponsor_id}"
        else:
            sponsor_key = self._normalize_fellowship_cache_part(
                fellowship_data.get("sponsor_name")
            )
        return f"{name_key}::{sponsor_key}"

    @staticmethod
    def _clean_fellowship_sponsor_name(sponsor_name: Any) -> Optional[str]:
        if sponsor_name is None:
            return None
        cleaned = str(sponsor_name).strip()
        return cleaned or None

    @staticmethod
    def _normalize_fellowship_cache_part(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip().casefold()

    @staticmethod
    def _get_fellowship_value(fellowship: Any, key: str) -> Any:
        if isinstance(fellowship, dict):
            return fellowship.get(key)
        return getattr(fellowship, key, None)

    def _get_fellowship_sponsor_name(self, fellowship: Any) -> Optional[str]:
        sponsor = self._get_fellowship_value(fellowship, "sponsor")
        sponsor_name = self._get_fellowship_value(sponsor, "name") if sponsor else None
        return self._clean_fellowship_sponsor_name(sponsor_name)

    def _sync_advisorship_member(
        self,
        initiative: Advisorship,
        *,
        person: Optional[Any],
        role_name: str,
        start_date: Optional[Any],
    ) -> None:
        person = self._coerce_to_person(person)

        if advisorship_supports_members_api(initiative):
            members = list(getattr(initiative, "members", []) or [])
            retained_members = [
                member
                for member in members
                if getattr(member, "role_name", None) != role_name
            ]
            initiative.members = retained_members

            if not person:
                return

            role = self._get_or_create_advisorship_role(role_name)
            initiative.add_member(person=person, role=role, start_date=start_date)
            return

        if role_name == AdvisorshipRole.STUDENT.value:
            legacy_attr = "student"
        elif role_name == AdvisorshipRole.SUPERVISOR.value:
            legacy_attr = "supervisor"
        else:
            return

        setattr(initiative, legacy_attr, person)
        id_attr = f"{legacy_attr}_id"
        if hasattr(initiative, id_attr):
            setattr(
                initiative, id_attr, getattr(person, "id", None) if person else None
            )

    def _coerce_to_person(self, person: Optional[Any]) -> Optional[Person]:
        if not person:
            return None

        person_id = (
            person.get("id")
            if isinstance(person, dict)
            else getattr(person, "id", None)
        )
        if not person_id:
            return None

        session = self.person_matcher.person_controller._service._repository._session
        try:
            base_person = session.get(Person, person_id)
            if base_person:
                return base_person
        except Exception:
            pass

        try:
            return self.person_matcher.person_controller.get_by_id(person_id)
        except Exception:
            return person if isinstance(person, Person) else None

    def _resolve_persisted_title(
        self,
        title: str,
        project_data: Dict[str, Any],
        *,
        current_id: Optional[int] = None,
    ) -> str:
        if not self._initiative_name_in_use(title, current_id=current_id):
            return title

        return self._build_disambiguated_advisorship_title(title, project_data)

    def _initiative_name_in_use(
        self, title: str, *, current_id: Optional[int] = None
    ) -> bool:
        if not title:
            return False

        session = self.initiative_controller._service._repository._session
        params = {"name": title, "current_id": current_id or -1}
        result = session.execute(
            text(
                """
                SELECT id
                FROM initiatives
                WHERE name = :name
                  AND id != :current_id
                LIMIT 1
                """
            ),
            params,
        ).scalar()
        return result is not None

    def _build_disambiguated_advisorship_title(
        self, title: str, project_data: Dict[str, Any]
    ) -> str:
        student_names = project_data.get("student_names") or []
        student_name = next(
            (name for name in student_names if isinstance(name, str) and name.strip()),
            None,
        )

        start_date = project_data.get("start_date")
        year = None
        if isinstance(start_date, datetime):
            year = start_date.year
        elif isinstance(start_date, date):
            year = start_date.year

        metadata = project_data.get("metadata") or {}
        sigpesq_id = metadata.get("sigpesq_id")

        suffix_parts = []
        if student_name:
            suffix_parts.append(student_name)
        if year:
            suffix_parts.append(str(year))
        if sigpesq_id:
            suffix_parts.append(f"sigpesq {sigpesq_id}")
        if not suffix_parts and project_data.get("identity_key"):
            suffix_parts.append(str(project_data["identity_key"])[:24])

        return f"{title} | Orientacao {' | '.join(suffix_parts)}".strip()

    def _find_existing_advisorship_by_title(self, title: str) -> Optional[Advisorship]:
        if not title:
            return None

        session = self.initiative_controller._service._repository._session
        initiative_id = session.execute(
            text(
                """
                SELECT id
                FROM initiatives
                WHERE name = :name
                LIMIT 1
                """
            ),
            {"name": title},
        ).scalar()
        if not initiative_id:
            return None

        try:
            return self.adv_controller.get_by_id(initiative_id)
        except Exception:
            return None

    def _handle_advisorship_details(
        self,
        initiative: Advisorship,
        project_data: Dict[str, Any],
        *,
        student_person: Optional[Any] = None,
        supervisor_person: Optional[Any] = None,
        fellowship: Optional[Fellowship] = None,
    ) -> None:
        """Handles Student, Supervisor, and Fellowships for an Advisorship."""
        if student_person is None and supervisor_person is None:
            student_person, supervisor_person = self._resolve_advisorship_people(
                project_data
            )

        self._sync_advisorship_cancellation(initiative, project_data)

        program = project_data.get("program")
        if program is not None and hasattr(initiative, "program"):
            initiative.program = program

        start_date = project_data.get("start_date")

        if project_data.get("student_names") or project_data.get("student_emails"):
            self._sync_advisorship_member(
                initiative,
                person=student_person,
                role_name=AdvisorshipRole.STUDENT.value,
                start_date=start_date,
            )

        if project_data.get("coordinator_name") or project_data.get(
            "coordinator_email"
        ):
            self._sync_advisorship_member(
                initiative,
                person=supervisor_person,
                role_name=AdvisorshipRole.SUPERVISOR.value,
                start_date=start_date,
            )

        if fellowship is None:
            fellowship = self._ensure_fellowship(project_data)

        if fellowship:
            initiative.fellowship = fellowship
            initiative.fellowship_id = fellowship.id

    @staticmethod
    def _sync_advisorship_cancellation(
        initiative: Advisorship,
        project_data: Dict[str, Any],
    ) -> None:
        if "cancelled" in project_data and hasattr(initiative, "cancelled"):
            initiative.cancelled = bool(project_data["cancelled"])
        if "cancellation_date" in project_data and hasattr(
            initiative, "cancellation_date"
        ):
            initiative.cancellation_date = project_data["cancellation_date"]
