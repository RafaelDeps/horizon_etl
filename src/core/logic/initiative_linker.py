import unicodedata
from typing import Any, Dict, List, Optional
from loguru import logger
from sqlalchemy import text

from research_domain import (
    ResearchGroupController,
)


class InitiativeLinker:
    """
    Handles associations between Initiatives and other domain entities like
    Research Groups and Knowledge Areas.
    """

    def __init__(
        self,
        initiative_controller,
        rg_controller: ResearchGroupController,
        team_controller,
        person_matcher,
        team_synchronizer,
        entity_manager,
    ):
        self.initiative_controller = initiative_controller
        self.rg_controller = rg_controller
        self.team_controller = team_controller
        self.person_matcher = person_matcher
        self.team_synchronizer = team_synchronizer
        self.entity_manager = entity_manager

    def create_initiative_team(self, initiative: Any, project_data: Dict[str, Any]) -> None:
        """Creates a team for the given initiative and synchronizes its members."""
        team_name = initiative.name[:200]
        team = self.team_synchronizer.ensure_team(
            team_name=team_name,
            description=f"Equipe do projeto: {initiative.name[:100]}",
        )

        if not team:
            return

        members_to_sync = []
        strict = True
        start_date = project_data.get("start_date")

        # Coordinator
        coord_name = project_data.get("coordinator_name")
        coord_email = project_data.get("coordinator_email")
        if coord_name or coord_email:
            p = self.person_matcher.match_or_create(coord_name, email=coord_email, strict_match=strict)
            if p:
                members_to_sync.append((p, "Coordinator", start_date))

        # Researchers
        res_names = project_data.get("researcher_names", [])
        res_emails = project_data.get("researcher_emails", [None] * len(res_names))
        for name, email in zip(res_names, res_emails):
            p = self.person_matcher.match_or_create(name, email=email, strict_match=strict)
            if p:
                members_to_sync.append((p, "Researcher", start_date))

        # Students
        stu_names = project_data.get("student_names", [])
        stu_emails = project_data.get("student_emails", [None] * len(stu_names))
        for name, email in zip(stu_names, stu_emails):
            p = self.person_matcher.match_or_create(name, email=email, strict_match=strict)
            if p:
                members_to_sync.append((p, "Student", start_date))

        # 2. Delegate synchronization to TeamSynchronizer
        # The row's tracking key names the document (spec 020): membership
        # becomes the union of what each document says about the team.
        self.team_synchronizer.synchronize_members(
            team.id, members_to_sync, document_key=project_data.get("_document_key")
        )

        # 3. Link team to initiative
        try:
            self.initiative_controller.assign_team(initiative.id, team.id)
        except Exception as e:
            logger.warning(f"Failed to assign team to initiative: {e}")

    def add_members_to_initiative_team(self, initiative: Any, project_data: Dict[str, Any]) -> None:
        """Adds members (Supervisor/Student) to the initiative's team without removing existing ones."""
        team_name = initiative.name[:200]
        team = self.team_synchronizer.ensure_team(
            team_name=team_name,
            description=f"Equipe do projeto: {initiative.name[:100]}",
        )

        if not team:
            return

        members_to_add = []
        strict = True
        start_date = project_data.get("start_date")

        # 1. Supervisor (Coordinator in project_data) -> Role: Researcher
        # We add them as Researcher to the parent project to avoid multiple Coordinators.
        coord_name = project_data.get("coordinator_name")
        coord_email = project_data.get("coordinator_email")
        if coord_name or coord_email:
            p = self.person_matcher.match_or_create(coord_name, email=coord_email, strict_match=strict)
            if p:
                members_to_add.append((p, "Researcher", start_date))

        # 2. Student -> Role: Student
        stu_names = project_data.get("student_names", [])
        stu_emails = project_data.get("student_emails", [None] * len(stu_names))
        for name, email in zip(stu_names, stu_emails):
            p = self.person_matcher.match_or_create(name, email=email, strict_match=strict)
            if p:
                members_to_add.append((p, "Student", start_date))

        # 3. Add members (Additive)
        self.team_synchronizer.add_members(
            team.id, members_to_add, document_key=project_data.get("_document_key")
        )

        # 4. Link team to initiative (Ensure assigned)
        try:
            self.initiative_controller.assign_team(initiative.id, team.id)
        except Exception as e:
            logger.warning(f"Failed to assign team to parent initiative: {e}")

    def link_research_group(
        self,
        initiative: Any,
        rg_name: str,
        project_data: Dict[str, Any],
        campus_name: Optional[str],
        org_id: Optional[int],
    ) -> None:
        """Links an initiative to a Research Group, creating it if missing."""
        try:
            all_groups = self.rg_controller.get_all()
            target_group = None

            def normalize(s):
                return (
                    unicodedata.normalize("NFD", s)
                    .encode("ascii", "ignore")
                    .decode("utf-8")
                    .upper()
                    .strip()
                )

            target_norm = normalize(rg_name)

            for group in all_groups:
                g_name = group.name if hasattr(group, "name") else group.get("name")
                if g_name and normalize(g_name) == target_norm:
                    target_group = group
                    break

            if not target_group:
                logger.info(f"Research Group '{rg_name}' not found. Creating new group...")
                campus_id = self.entity_manager.resolve_campus(campus_name, org_id)

                if not campus_id:
                    logger.warning(f"Could not resolve campus for RG '{rg_name}'. Cannot create.")
                    return

                try:
                    target_group = self.rg_controller.create_research_group(
                        name=rg_name,
                        description=f"Grupo de Pesquisa importado do SigPesq: {rg_name}",
                        organization_id=org_id,
                        campus_id=campus_id,
                    )
                    logger.info(f"Created new Research Group: {rg_name} (Campus ID: {campus_id})")
                    
                    # RF-15: Auto-populate members for newly created groups
                    self._populate_group_members(target_group, initiative, project_data)
                except Exception as e:
                    logger.error(f"Failed to create Research Group '{rg_name}': {e}")
                    return

            if target_group:
                self._link_initiative_to_group_team(initiative, target_group, rg_name)

        except Exception as e:
            logger.warning(f"Failed to link Research Group '{rg_name}': {e}")

    def _link_initiative_to_group_team(self, initiative: Any, target_group: Any, rg_name: str) -> None:
        """Helper to link initiative to the underlying Team of a Research Group."""
        try:
            tg_id = target_group.id if hasattr(target_group, "id") else target_group.get("id")
            team_proxy = self.team_controller.get_by_id(tg_id)
            
            if not team_proxy:
                logger.warning(f"Could not find base Team for Research Group {tg_id}")
                return

            is_linked = False
            if hasattr(team_proxy, "initiatives"):
                for init in team_proxy.initiatives:
                    if init.id == initiative.id:
                        is_linked = True
                        break

            if not is_linked:
                if hasattr(team_proxy, "initiatives"):
                    team_proxy.initiatives.append(initiative)
                    self.team_controller.update(team_proxy)
                    logger.info(f"Linked Initiative to Research Group '{rg_name}' (via Team)")
                else:
                    initiative.teams.append(team_proxy)
                    # Note: Need access to initiative controller or session to update
                    # For now we assume the session will be committed by the caller
                    logger.info(f"Linked Initiative to Research Group '{rg_name}' (via Initiative.teams)")
        except Exception as e:
            logger.warning(f"Failed to link Team proxy for RG: {e}")

    def _populate_group_members(self, group: Any, initiative: Any, project_data: Dict[str, Any]) -> None:
        """Populates a newly created Research Group with members from the project."""
        try:
            gid = group.id if hasattr(group, "id") else group.get("id")
            start_date = project_data.get("start_date")
            members_to_sync = []
            strict = True

            # 1. Coordinator & Researchers -> Role: Researcher
            res_names = []
            res_emails = []
            if project_data.get("coordinator_name"):
                res_names.append(project_data.get("coordinator_name"))
                res_emails.append(project_data.get("coordinator_email"))
            
            res_names.extend(project_data.get("researcher_names", []))
            res_emails.extend(project_data.get("researcher_emails", [None] * len(project_data.get("researcher_names", []))))

            for name, email in zip(res_names, res_emails):
                p = self.person_matcher.match_or_create(name, email=email, strict_match=strict)
                if p:
                    members_to_sync.append((p, "Researcher", start_date))

            # 2. Students -> Role: Student
            stu_names = project_data.get("student_names", [])
            stu_emails = project_data.get("student_emails", [None] * len(stu_names))
            for name, email in zip(stu_names, stu_emails):
                p = self.person_matcher.match_or_create(name, email=email, strict_match=strict)
                if p:
                    members_to_sync.append((p, "Student", start_date))

            if members_to_sync:
                self.team_synchronizer.synchronize_members(gid, members_to_sync)
        except Exception as e:
            logger.warning(f"Failed to populate members for Group: {e}")

    def associate_keyword_knowledge_areas(self, initiative: Any, project_data: Dict[str, Any], rg_name: str) -> None:
        """Parses keywords and links them as Knowledge Areas to initiative, group, and researchers."""
        metadata = project_data.get("metadata", {})
        keywords_str = metadata.get("keywords")
        if not keywords_str:
            return

        if ";" in str(keywords_str):
            keywords = [k.strip() for k in str(keywords_str).split(";") if k.strip()]
        else:
            keywords = [k.strip() for k in str(keywords_str).split(",") if k.strip()]

        ka_ids = []
        for kw in keywords:
            kid = self.entity_manager.ensure_knowledge_area(kw)
            if kid:
                ka_ids.append(kid)

        if not ka_ids:
            return

        if initiative:
            self._link_kas_to_initiative(initiative.id, ka_ids)
        if rg_name:
            self._link_kas_to_group(rg_name, ka_ids)

        member_names = []
        if project_data.get("coordinator_name"):
            member_names.append(project_data.get("coordinator_name"))
        member_names.extend(project_data.get("researcher_names", []))

        for name in member_names:
            person = self.person_matcher.match_or_create(name, strict_match=True)
            if person:
                self._link_kas_to_researcher(person.id, ka_ids)

    def _link_kas_to_initiative(self, initiative_id: Any, ka_ids: List[int]) -> None:
        session = self.rg_controller._service._repository._session
        for aid in ka_ids:
            try:
                check = text("SELECT 1 FROM initiative_knowledge_areas WHERE initiative_id = :iid AND area_id = :aid")
                exists = session.execute(check, {"iid": initiative_id, "aid": aid}).scalar()
                if not exists:
                    ins = text("INSERT INTO initiative_knowledge_areas (initiative_id, area_id) VALUES (:iid, :aid)")
                    session.execute(ins, {"iid": initiative_id, "aid": aid})
            except Exception as e:
                logger.warning(f"Failed handling KA {aid} for Initiative {initiative_id}: {e}")
        try:
            session.commit()
        except Exception:
            session.rollback()

    def _link_kas_to_group(self, rg_name: str, ka_ids: List[int]) -> None:
        try:
            all_groups = self.rg_controller.get_all()
            target_group = None
            def normalize(s):
                return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("utf-8").upper().strip()
            target_norm = normalize(rg_name)
            for group in all_groups:
                g_name = group.name if hasattr(group, "name") else group.get("name")
                if g_name and normalize(g_name) == target_norm:
                    target_group = group
                    break
            if not target_group:
                return
            gid = target_group.id if hasattr(target_group, "id") else target_group.get("id")
            session = self.rg_controller._service._repository._session
            for aid in ka_ids:
                try:
                    check = text("SELECT 1 FROM group_knowledge_areas WHERE group_id = :gid AND area_id = :aid")
                    exists = session.execute(check, {"gid": gid, "aid": aid}).scalar()
                    if not exists:
                        ins = text("INSERT INTO group_knowledge_areas (group_id, area_id) VALUES (:gid, :aid)")
                        session.execute(ins, {"gid": gid, "aid": aid})
                except Exception as e:
                    logger.warning(f"Failed handling KA {aid} for Group {gid}: {e}")
            try:
                session.commit()
            except Exception:
                session.rollback()
        except Exception as e:
            logger.warning(f"Failed to link KAs to Group {rg_name}: {e}")

    def _link_kas_to_researcher(self, person_id: Any, ka_ids: List[int]) -> None:
        try:
            session = self.rg_controller._service._repository._session
            chk_res = text("SELECT 1 FROM researchers WHERE id = :rid")
            is_res = session.execute(chk_res, {"rid": person_id}).scalar()
            if not is_res:
                try:
                    ins_res = text("INSERT INTO researchers (id) VALUES (:rid)")
                    session.execute(ins_res, {"rid": person_id})
                    session.commit()
                except Exception:
                    session.rollback()
            for aid in ka_ids:
                try:
                    check = text("SELECT 1 FROM researcher_knowledge_areas WHERE researcher_id = :rid AND area_id = :aid")
                    exists = session.execute(check, {"rid": person_id, "aid": aid}).scalar()
                    if not exists:
                        ins = text("INSERT INTO researcher_knowledge_areas (researcher_id, area_id) VALUES (:rid, :aid)")
                        session.execute(ins, {"rid": person_id, "aid": aid})
                except Exception as e:
                    logger.warning(f"Failed handling KA {aid} for Researcher {person_id}: {e}")
            try:
                session.commit()
            except Exception:
                session.rollback()
        except Exception as e:
            logger.warning(f"Failed to link KAs to Researcher {person_id}: {e}")
