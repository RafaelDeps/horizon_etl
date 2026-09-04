from typing import Any, Dict, List, Optional, Set, Tuple

from eo_lib import TeamController
from loguru import logger

from src.core.logic.initiative_identity import normalize_text


class TeamSynchronizer:
    """
    Service responsible for team management and membership synchronization.

    This class handles identifying/creating teams and synchronizing their members
    based on the source data, ensuring that only current members are retained.
    """

    def __init__(self, team_controller: TeamController, roles_cache: Dict[str, Any]):
        """
        Initializes the TeamSynchronizer.

        Args:
            team_controller (TeamController): Controller used to interact with Team records.
            roles_cache (Dict[str, Any]): Cache of Role objects for quick lookup.
        """
        self.team_controller = team_controller
        self.roles_cache = roles_cache

    def ensure_team(self, team_name: str, description: str) -> Optional[Any]:
        """
        Ensures a team exists with the given name. If not, creates it.

        Args:
            team_name (str): The name of the team.
            description (str): Description for the team if creation is needed.

        Returns:
            Optional[Any]: The existing or newly created Team object, or None if error.
        """
        try:
            existing_teams = self.team_controller.get_all()
            team_name_key = normalize_text(team_name)
            for t in existing_teams:
                t_name = (
                    t.name
                    if hasattr(t, "name")
                    else (t.get("name") if isinstance(t, dict) else "")
                )
                if t_name == team_name or normalize_text(t_name) == team_name_key:
                    logger.debug(f"Team already exists: {team_name[:50]}...")
                    return t

            team = self.team_controller.create_team(
                name=team_name, description=description
            )
            logger.info(f"Created team: {team_name[:50]}...")
            return team
        except Exception as e:
            logger.warning(f"Failed to manage team '{team_name[:50]}': {e}")
            return None

    def synchronize_members(
        self, team_id: int, members_to_sync: List[Tuple[Any, str, Optional[Any]]]
    ):
        """
        Synchronizes team members: adds new ones and removes obsolete ones.

        Removal is scoped to the roles present in ``members_to_sync``. A source
        that only lists researchers/coordinators (e.g. a Lattes CV project
        roster) therefore never deletes members holding roles it does not
        provide -- most importantly the ``Student`` roster contributed by
        SigPesq. Without this scoping, the last project load to touch a team
        (Lattes runs after SigPesq in the weekly pipeline) would wipe every
        student from the project team, dropping their project memberships from
        the canonical export.
        """
        current_source_memberships: Set[Tuple[int, int]] = set()

        for person, role_name, start_date in members_to_sync:
            if not person:
                continue

            role_obj = self.roles_cache.get(role_name)
            role_id = getattr(role_obj, "id", None) or (
                role_obj.get("id") if isinstance(role_obj, dict) else None
            )

            if role_id:
                current_source_memberships.add((person.id, role_id))

            # Add member with idempotency check
            self._add_member_if_new(
                team_id, person, role_obj, role_name, role_id, start_date
            )

        # Remove obsolete members of the roles this source claims to manage.
        self._remove_obsolete_members(team_id, current_source_memberships)

    def add_members(
        self, team_id: int, members_to_add: List[Tuple[Any, str, Optional[Any]]]
    ):
        """
        Adds members to the team without removing existing ones.
        Idempotent: only adds if (person, role, start_date) is missing.
        """
        for person, role_name, start_date in members_to_add:
            if not person:
                continue

            role_obj = self.roles_cache.get(role_name)
            role_id = getattr(role_obj, "id", None) or (
                role_obj.get("id") if isinstance(role_obj, dict) else None
            )

            # Add member with idempotency check
            self._add_member_if_new(
                team_id, person, role_obj, role_name, role_id, start_date
            )

    def _add_member_if_new(
        self, team_id, person, role_obj, role_name, role_id, start_date
    ):
        """
        Adds a member to the team if they are not already present with the same role and start date.

        Args:
            team_id (int): ID of the team.
            person (Person): Person object to add.
            role_obj (Any): Role object for the membership.
            role_name (str): Name of the role (for logging).
            role_id (int): ID of the role.
            start_date (Optional[Any]): The start date of the membership.
        """
        try:
            current_members = self.team_controller.get_members(team_id)
            for m in current_members:
                m_person_id = getattr(m, "person_id", None)
                m_role_id = getattr(m, "role_id", None)
                m_start = getattr(m, "start_date", None)

                dates_match = True
                if m_start and start_date:
                    m_start_iso = (
                        m_start.isoformat()
                        if hasattr(m_start, "isoformat")
                        else str(m_start)
                    )
                    start_date_iso = (
                        start_date.isoformat()
                        if hasattr(start_date, "isoformat")
                        else str(start_date)
                    )
                    dates_match = m_start_iso == start_date_iso
                elif m_start or start_date:
                    dates_match = False

                if m_person_id == person.id and m_role_id == role_id and dates_match:
                    return
        except Exception as e:
            logger.warning(f"Failed to check member existence: {e}")

        try:
            self.team_controller.add_member(
                team_id=team_id,
                person_id=person.id,
                role=role_obj or role_name,
                start_date=start_date,
            )
        except Exception as e:
            logger.warning(f"Failed to add {role_name} '{person.name}': {e}")

    def _remove_obsolete_members(
        self, team_id: int, current_source_memberships: Set[Tuple[int, int]]
    ):
        """
        Removes members from the database that are not present in the current
        source data -- but only for roles the source actually carries.

        ``current_source_memberships`` is a set of (PersonID, RoleID) pairs
        present in the current source load. A member is only removed when the
        role of that membership is part of the source's own roster; members
        holding roles the source does not mention (e.g. ``Student`` from a
        source that only lists researchers) are never removed here. The roles
        effectively manage membership for those roles only.
        """
        source_roles = {role_id for _, role_id in current_source_memberships}
        try:
            db_members = self.team_controller.get_members(team_id)
            for m in db_members:
                m_person_id = getattr(m, "person_id", None)
                m_role_id = getattr(m, "role_id", None)

                if (
                    m_role_id in source_roles
                    and (m_person_id, m_role_id) not in current_source_memberships
                ):
                    logger.info(
                        f"Removing obsolete member (Person ID: {m_person_id}, Role ID: {m_role_id}) from team {team_id}"
                    )
                    try:
                        m_id = getattr(m, "id", None)
                        if m_id:
                            self.team_controller.remove_member(m_id)
                        else:
                            logger.warning(
                                f"Could not find member ID for obsolete membership (Person {m_person_id})"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to remove obsolete member: {e}")
        except Exception as e:
            logger.warning(f"Failed to synchronize team members: {e}")
