from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from eo_lib import TeamController
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.logic.initiative_identity import normalize_text

_ALL_TEAMS_SQL = text("SELECT id, name FROM teams ORDER BY id")
_TEAMS_AFTER_SQL = text("SELECT id, name FROM teams WHERE id > :max_id ORDER BY id")


@dataclass(frozen=True)
class TeamRef:
    """What ensure_team returns: the team's id and stored name, nothing else.

    Callers only use ``id`` (InitiativeLinker, synchronize_members). Holding ORM
    Team entities for ~11k teams would keep them, and their eagerly joined
    members, alive in the session's identity map.
    """

    id: int
    name: str


def _team_name(team: Any) -> str:
    if hasattr(team, "name"):
        return team.name or ""
    if isinstance(team, dict):
        return team.get("name") or ""
    return ""


def _day(value: Any) -> str:
    """A start date as ``YYYY-MM-DD`` text ('' when absent), whatever its type."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    return str(value)[:10]


def _team_id(team: Any) -> Any:
    return team.get("id") if isinstance(team, dict) else getattr(team, "id", None)


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

        # Team lookup (spec 015), built on the first ensure_team call. It used
        # to call team_controller.get_all() per record: eo_lib joins every
        # team's members, persons and roles eagerly, ~3.7M objects and 1.5-1.9 s
        # per call at ~10.6k teams, which made the Lattes phases quadratic.
        self._by_key: Dict[str, TeamRef] = {}
        self._max_id = 0
        self._loaded = False
        self._mode: Optional[str] = None  # "sql" or "controller"
        self._stats = {
            "loaded": 0,
            "hits": 0,
            "created": 0,
            "refreshes": 0,
            "refresh_found": 0,
            "failed": 0,
        }

    def _session(self) -> Optional[Session]:
        try:
            session = self.team_controller._service._repository._session
        except AttributeError:
            return None
        # A MagicMock controller (tests) answers any attribute chain; only a
        # real session can run SQL.
        return session if isinstance(session, Session) else None

    def _merge(self, rows: Iterable[Tuple[int, Optional[str]]]) -> int:
        """Merges (id, name) rows in ascending id; the lowest id keeps its key."""
        merged = 0
        for team_id, name in rows:
            ref = TeamRef(team_id, name or "")
            self._by_key.setdefault(normalize_text(ref.name), ref)
            self._max_id = max(self._max_id, team_id)
            merged += 1
        return merged

    def _load(self) -> None:
        session = self._session()
        if session is not None:
            self._mode = "sql"
            rows = session.execute(_ALL_TEAMS_SQL).fetchall()
        else:
            self._mode = "controller"
            teams = [
                t for t in self.team_controller.get_all() if _team_id(t) is not None
            ]
            rows = sorted(
                ((_team_id(t), _team_name(t)) for t in teams), key=lambda r: r[0]
            )
        self._stats["loaded"] = self._merge(rows)
        self._loaded = True

    def reset_lookup(self) -> None:
        """Forgets the team lookup (spec 021): after a rolled-back document it
        may hold teams that no longer exist; it is rebuilt on next use."""
        self._by_key = {}
        self._max_id = 0
        self._loaded = False

    def _refresh(self) -> int:
        """Merges teams created since the last read (by any code in this process)."""
        if self._mode != "sql":
            return 0
        self._stats["refreshes"] += 1
        rows = (
            self._session()
            .execute(_TEAMS_AFTER_SQL, {"max_id": self._max_id})
            .fetchall()
        )
        return self._merge(rows)

    def ensure_team(self, team_name: str, description: str) -> Optional[TeamRef]:
        """
        Ensures a team exists with the given name. If not, creates it.

        Matches the lowest-id team whose normalized name equals the requested
        one, the same answer the old full scan gave.

        Args:
            team_name (str): The name of the team.
            description (str): Description for the team if creation is needed.

        Returns:
            Optional[TeamRef]: The existing or newly created team, or None if error.
        """
        try:
            if not self._loaded:
                self._load()

            key = normalize_text(team_name)
            ref = self._by_key.get(key)
            if ref is not None:
                self._stats["hits"] += 1
                return ref

            if self._refresh():
                ref = self._by_key.get(key)
                if ref is not None:
                    self._stats["refresh_found"] += 1
                    return ref

            team = self.team_controller.create_team(
                name=team_name, description=description
            )
            logger.info(f"Created team: {team_name[:50]}...")
            ref = TeamRef(team.id, _team_name(team))
            self._by_key.setdefault(key, ref)
            self._max_id = max(self._max_id, ref.id)
            self._stats["created"] += 1
            return ref
        except Exception as e:
            self._stats["failed"] += 1
            logger.warning(f"Failed to manage team '{team_name[:50]}': {e}")
            return None

    def log_lookup_summary(self, label: str) -> None:
        s = self._stats
        logger.info(
            f"Team lookup [{label}]: loaded={s['loaded']} hits={s['hits']} "
            f"created={s['created']} refreshes={s['refreshes']} "
            f"refresh_found={s['refresh_found']} failed={s['failed']}"
        )

    def synchronize_members(
        self,
        team_id: int,
        members_to_sync: List[Tuple[Any, str, Optional[Any]]],
        document_key: Optional[str] = None,
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

        With a ``document_key`` (spec 020), membership is the union of what
        every document says instead; see ``_sync_contributions``.
        """
        if document_key and self._sync_contributions(
            team_id, members_to_sync, document_key
        ):
            return
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
        self,
        team_id: int,
        members_to_add: List[Tuple[Any, str, Optional[Any]]],
        document_key: Optional[str] = None,
    ):
        """
        Adds members to the team without removing existing ones.
        Idempotent: only adds if (person, role, start_date) is missing.
        """
        if document_key and self._sync_contributions(
            team_id, members_to_add, document_key
        ):
            return
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

    def _role(self, role_name: str) -> Tuple[Any, Optional[int]]:
        role_obj = self.roles_cache.get(role_name)
        role_id = getattr(role_obj, "id", None) or (
            role_obj.get("id") if isinstance(role_obj, dict) else None
        )
        return role_obj, role_id

    def _sync_contributions(
        self,
        team_id: int,
        members: List[Tuple[Any, str, Optional[Any]]],
        document_key: str,
    ) -> bool:
        """Membership as the union of the documents' contributions (spec 020,
        research R9.2/R9.3).

        Each call replaces what ``document_key`` says about the team in
        ``team_member_contributions``. A ``team_members`` row (person, role,
        start date) is added when some document contributes it and removed
        only when no document does any more. Several CVs listing the same
        project, or two projects sharing a team by name, therefore no longer
        overwrite each other, and a rerun over the same input writes nothing.
        Returns False (caller falls back to the old behaviour) without a SQL
        session.
        """
        session = self._session()
        if session is None:
            return False
        # Spec 021: what this row says about the team is an item of the source
        # document being processed (a CV or a report row).
        from src.core.logic.document_skip import carry

        carry("team_contribution", f"{team_id}|{document_key}")

        new: Dict[Tuple[int, int, str], Tuple[Any, Any, str, Optional[Any]]] = {}
        for person, role_name, start_date in members:
            role_obj, role_id = self._role(role_name)
            if not person or not role_id:
                continue
            key = (person.id, role_id, _day(start_date))
            new.setdefault(key, (person, role_obj, role_name, start_date))

        old = {
            (row[0], row[1], row[2] or "")
            for row in session.execute(
                text(
                    "SELECT person_id, role_id, start_date FROM "
                    "team_member_contributions WHERE team_id = :t AND document_key = :d"
                ),
                {"t": team_id, "d": document_key},
            )
        }
        dropped = old - set(new)
        for person_id, role_id, start in dropped:
            session.execute(
                text(
                    "DELETE FROM team_member_contributions WHERE team_id = :t "
                    "AND document_key = :d AND person_id = :p AND role_id = :r "
                    "AND COALESCE(start_date, '') = :s"
                ),
                {
                    "t": team_id,
                    "d": document_key,
                    "p": person_id,
                    "r": role_id,
                    "s": start,
                },
            )
        for person_id, role_id, start in set(new) - old:
            session.execute(
                text(
                    "INSERT OR IGNORE INTO team_member_contributions (team_id, "
                    "person_id, role_id, document_key, start_date) "
                    "VALUES (:t, :p, :r, :d, :s)"
                ),
                {
                    "t": team_id,
                    "p": person_id,
                    "r": role_id,
                    "d": document_key,
                    "s": start,
                },
            )
        still_contributed = {
            (row[0], row[1], row[2] or "")
            for row in session.execute(
                text(
                    "SELECT DISTINCT person_id, role_id, start_date FROM "
                    "team_member_contributions WHERE team_id = :t"
                ),
                {"t": team_id},
            )
        }
        session.commit()

        try:
            current = self.team_controller.get_members(team_id)
        except Exception as e:
            logger.warning(f"Failed to read members of team {team_id}: {e}")
            return True
        present = {
            (
                getattr(m, "person_id", None),
                getattr(m, "role_id", None),
                _day(getattr(m, "start_date", None)),
            )
            for m in current
        }
        for key, (person, role_obj, role_name, start_date) in new.items():
            if key in present:
                continue
            try:
                self.team_controller.add_member(
                    team_id=team_id,
                    person_id=person.id,
                    role=role_obj or role_name,
                    start_date=start_date,
                )
            except Exception as e:
                logger.warning(f"Failed to add {role_name} '{person.name}': {e}")
        for m in current:
            key = (
                getattr(m, "person_id", None),
                getattr(m, "role_id", None),
                _day(getattr(m, "start_date", None)),
            )
            if key in dropped and key not in still_contributed:
                try:
                    self.team_controller.remove_member(m.id)
                except Exception as e:
                    logger.warning(f"Failed to remove obsolete member: {e}")
        return True

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
