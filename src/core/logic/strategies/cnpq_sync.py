from datetime import date, datetime
from typing import Any, Dict, List

from loguru import logger
from research_domain import (
    KnowledgeAreaController,
    ResearcherController,
    ResearchGroupController,
    RoleController,
)

from src.core.logic.researcher_resolution import resolve_or_create_researcher
from src.tracking.recorder import tracking_recorder


class CnpqSyncLogic:
    """
    Business logic for synchronizing CNPq data with the local database.
    """

    def __init__(self):
        self.rg_ctrl = ResearchGroupController()
        self.res_ctrl = ResearcherController()
        self.role_ctrl = RoleController()
        self.ka_ctrl = KnowledgeAreaController()
        self._leader_role_id = None

    def _get_leader_role_id(self):
        if not self._leader_role_id:
            role = self.role_ctrl.get_or_create_leader_role()
            self._leader_role_id = role.id
        return self._leader_role_id

    def _parse_date(self, date_str: str) -> date:
        """Parses date from 'DD/MM/YYYY' format or 'Anterior a...' text, or returns None if invalid."""
        if not date_str:
            return None

        lower_str = date_str.lower().strip()
        if lower_str in ["não informada", "não informado", "n/a", ""]:
            return None

        try:
            # Standard Format
            return datetime.strptime(date_str, "%d/%m/%Y").date()
        except ValueError:
            # Handle "Anterior a <month> de <year>"
            # Example: "Anterior a abril de 2014"
            if "anterior a" in lower_str:
                try:
                    parts = lower_str.replace("anterior a", "").strip().split(" de ")
                    if len(parts) == 2:
                        month_str = parts[0]
                        year_str = parts[1]

                        months = {
                            "janeiro": 1,
                            "fevereiro": 2,
                            "março": 3,
                            "abril": 4,
                            "maio": 5,
                            "junho": 6,
                            "julho": 7,
                            "agosto": 8,
                            "setembro": 9,
                            "outubro": 10,
                            "novembro": 11,
                            "dezembro": 12,
                        }

                        month = months.get(
                            month_str, 1
                        )  # Default to Jan if mapping fails
                        year = int(year_str)
                        return date(year, month, 1)
                except Exception as e:
                    logger.warning(
                        f"Failed to parse 'Anterior a' date: {date_str} - {e}"
                    )

            # Additional format handling or Fallback
            logger.warning(f"Date parse failed for '{date_str}', returning None.")
            return None

    def _coerce_text_field(self, value: Any) -> str | None:
        """Normalizes heterogeneous crawler payloads into plain text."""
        if value is None:
            return None

        if isinstance(value, str):
            text = value.strip()
            return text or None

        if isinstance(value, dict):
            for key in ("descricao", "descrição", "texto", "value"):
                nested = self._coerce_text_field(value.get(key))
                if nested:
                    return nested

            parts = [self._coerce_text_field(item) for item in value.values()]
            parts = [part for part in parts if part]
            return "\n".join(parts) if parts else None

        if isinstance(value, (list, tuple, set)):
            parts = [self._coerce_text_field(item) for item in value]
            parts = [part for part in parts if part]
            return "\n".join(parts) if parts else None

        return str(value).strip() or None

    def sync_group(
        self,
        group_id: Any,
        cnpq_data: Dict[str, Any],
        *,
        source_record_id: int | None = None,
    ):
        """
        Updates group basic info (name, description, start_date) from CNPq data.
        """
        try:
            from sqlalchemy import text

            session = self.rg_ctrl._service._repository._session

            # 1. Update Name and Description in 'teams' table
            nome_cnpq = self._coerce_text_field(cnpq_data.get("nome_grupo"))
            repercussoes = self._coerce_text_field(cnpq_data.get("repercussoes"))

            # Patch: ignore 'CNPq' which is a header branding in some mirrors
            if nome_cnpq and nome_cnpq.upper() == "CNPQ":
                nome_cnpq = None

            # Check and Update Teams table
            if nome_cnpq or repercussoes:
                check_query = text(
                    "SELECT name, description FROM teams WHERE id = :gid"
                )
                current = session.execute(check_query, {"gid": group_id}).fetchone()

                if current:
                    curr_name, curr_desc = current[0], current[1]
                    updates = {}
                    if nome_cnpq and curr_name != nome_cnpq:
                        updates["name"] = nome_cnpq
                    if repercussoes and curr_desc != repercussoes:
                        updates["description"] = repercussoes

                    if updates:
                        before_payload = {"name": curr_name, "description": curr_desc}
                        logger.info(
                            f"Updating team {group_id} metadata: {list(updates.keys())}"
                        )
                        set_clause = ", ".join([f"{k} = :{k}" for k in updates])
                        updates["gid"] = group_id
                        upd_query = text(
                            f"UPDATE teams SET {set_clause} WHERE id = :gid"
                        )
                        session.execute(upd_query, updates)
                        session.commit()
                        tracking_recorder.record_entity_match(
                            source_record_id=source_record_id,
                            canonical_entity_type="research_group",
                            canonical_entity_id=group_id,
                            match_strategy="cnpq_group_id",
                            match_confidence=1.0,
                        )
                        tracking_recorder.record_attribute_assertions(
                            source_record_id=source_record_id,
                            canonical_entity_type="research_group",
                            canonical_entity_id=group_id,
                            selected_attributes={
                                "name": updates.get("name", curr_name),
                                "description": updates.get("description", curr_desc),
                            },
                            selection_reason="cnpq_group_metadata_selected_values",
                        )
                        tracking_recorder.record_change(
                            source_record_id=source_record_id,
                            canonical_entity_type="research_group",
                            canonical_entity_id=group_id,
                            operation="update",
                            changed_fields=list(updates.keys()),
                            before=before_payload,
                            after={
                                "name": updates.get("name", curr_name),
                                "description": updates.get("description", curr_desc),
                            },
                            reason="Updated from CNPq group metadata",
                        )

            # 2. Update Start Date in 'research_groups' table
            ident = cnpq_data.get("identificacao", {})
            ano_formacao = ident.get("ano_de_formacao") or ident.get("data_de_formacao")

            if ano_formacao:
                # Handle year only or full date
                if (
                    isinstance(ano_formacao, str)
                    and len(ano_formacao) == 4
                    and ano_formacao.isdigit()
                ):
                    start_date = date(int(ano_formacao), 1, 1)
                else:
                    start_date = self._parse_date(str(ano_formacao))

                if start_date:
                    current_start_date = session.execute(
                        text("SELECT start_date FROM research_groups WHERE id = :gid"),
                        {"gid": group_id},
                    ).scalar()
                    logger.info(f"Updating group {group_id} start_date: {start_date}")
                    upd_rg = text(
                        "UPDATE research_groups SET start_date = :sd WHERE id = :gid"
                    )
                    session.execute(upd_rg, {"sd": start_date, "gid": group_id})
                    session.commit()
                    tracking_recorder.record_change(
                        source_record_id=source_record_id,
                        canonical_entity_type="research_group",
                        canonical_entity_id=group_id,
                        operation="update",
                        changed_fields=["start_date"],
                        before={"start_date": current_start_date},
                        after={"start_date": start_date},
                        reason="Updated group start_date from CNPq identification data",
                    )

        except Exception as e:
            logger.error(f"Failed to sync group {group_id}: {e}")
            try:
                if hasattr(self, "rg_ctrl"):
                    self.rg_ctrl._service._repository._session.rollback()
            except Exception:
                pass

    def sync_members(
        self,
        group_id: Any,
        members_data: List[Dict[str, Any]],
        *,
        source_file: str | None = None,
        researcher_index: List[Any],
    ):
        """
        Synchronizes members of a research group.

        ``researcher_index`` is built once per weekly run by the caller (see
        ``src/flows/cnpq/groups.py:sync_cnpq_groups_flow``) and shared across
        every group -- this method used to call ``self.res_ctrl.get_all()``
        here, once per group (351 times per run, ~8.8s each against the
        current data). See specs/011-cnpq-sync-index-reuse/.
        """
        from sqlalchemy import text

        all_res = researcher_index
        # Read once per group, not once per member: the roles table has ~11
        # rows and rarely changes, so a fresh read at the top of each group
        # is both cheap and current. See specs/011-cnpq-sync-index-reuse/.
        all_roles = self.role_ctrl.get_all()

        for m_data in members_data:
            name = m_data.get("name")
            if not name:
                continue
            source_record = tracking_recorder.record_source_record(
                source_entity_type="cnpq_group_member",
                payload=m_data,
                source_record_id=f"{group_id}|{name}|{m_data.get('role')}",
                source_file=source_file,
                source_path=source_file,
            )

            try:
                # 1. Ensure Researcher exists.
                # identification_id must stay None: it is a CPF-like identity
                # column, and storing a name hash there poisons future matching.
                researcher = resolve_or_create_researcher(
                    self.res_ctrl,
                    all_res,
                    name=name,
                )

                if researcher:
                    logger.debug(
                        f"Researcher '{name}' already exists (ID: {researcher.id}). Using existing."
                    )
                    tracking_recorder.record_entity_match(
                        source_record_id=getattr(source_record, "id", None),
                        canonical_entity_type="researcher",
                        canonical_entity_id=researcher.id,
                        match_strategy="resolve_or_create_researcher",
                        match_confidence=0.9,
                    )
                    tracking_recorder.record_attribute_assertions(
                        source_record_id=getattr(source_record, "id", None),
                        canonical_entity_type="researcher",
                        canonical_entity_id=researcher.id,
                        selected_attributes={
                            "name": name,
                            "role": m_data.get("role"),
                            "data_inicio": m_data.get("data_inicio"),
                            "data_fim": m_data.get("data_fim"),
                        },
                        selection_reason="cnpq_member_selected_values",
                    )
                else:
                    logger.error(
                        f"Could not create nor find researcher {name}. Skipping."
                    )
                    continue

                # SELF-HEALING: Ensure it exists in 'researchers' table (Joined Inheritance fix)
                # The library might only be inserting into 'persons' if mapping is partial.
                try:
                    session = self.rg_ctrl._service._repository._session
                    # Check if exists in researchers
                    chk_res = text("SELECT 1 FROM researchers WHERE id = :rid")
                    is_researcher = session.execute(
                        chk_res, {"rid": researcher.id}
                    ).scalar()

                    if not is_researcher:
                        logger.info(
                            f"Fixing missing 'researchers' row for ID {researcher.id}"
                        )
                        # Insert with just ID (other cols are URLs, nullable)
                        ins_res = text("INSERT INTO researchers (id) VALUES (:rid)")
                        session.execute(ins_res, {"rid": researcher.id})
                        session.commit()
                except Exception as e:
                    logger.warning(f"Failed to fix researchers table for {name}: {e}")
                    # Don't block flow
                    pass

                # 2. Get/Create Role
                role_name = m_data.get("role", "Pesquisador")
                # Try to find existing role
                role = None
                for r in all_roles:
                    if r.name.lower() == role_name.lower():
                        role = r
                        break

                if not role:
                    logger.info(f"Creating new role: {role_name}")
                    role = self.role_ctrl.create_role(name=role_name)
                    # `all_roles` is now read once per group instead of once
                    # per member: without this append, a second member in
                    # the same group needing the same new role would create
                    # it a second time, since the local snapshot would still
                    # be missing it.
                    all_roles.append(role)

                # 3. Associate with group using the service's add_member
                start_date = self._parse_date(m_data.get("data_inicio"))
                end_date = (
                    self._parse_date(m_data.get("data_fim"))
                    if m_data.get("data_fim")
                    else None
                )

                try:
                    # Accessing service directly as controller doesn't expose generic add_member
                    # Check for existing membership to avoid duplicates
                    existing_members = self.rg_ctrl._service.get_members(group_id)
                    already_associated = False
                    for em in existing_members:
                        if em.person_id == researcher.id:
                            # Already associated. We could check role/dates here if needed.
                            # For now, let's just skip to avoid duplicates.
                            already_associated = True
                            break

                    if not already_associated:
                        self.rg_ctrl._service.add_member(
                            team_id=group_id,
                            person_id=researcher.id,
                            role_id=role.id,
                            start_date=start_date,
                            end_date=end_date,
                        )
                        logger.info(
                            f"Member {name} ({role_name}) associated to group {group_id}"
                        )
                        tracking_recorder.record_change(
                            source_record_id=getattr(source_record, "id", None),
                            canonical_entity_type="research_group",
                            canonical_entity_id=group_id,
                            operation="update",
                            changed_fields=["member_association"],
                            after={
                                "person_id": researcher.id,
                                "role_id": role.id,
                                "start_date": start_date,
                                "end_date": end_date,
                            },
                            reason="Associated member from CNPq sync",
                        )
                    else:
                        # UPDATE LOGIC for Egressos
                        # If the member is already associated, check if we need to update the end_date
                        # This handles Active -> Egresso transition
                        try:
                            # We need to find the specific association to check dates
                            target_member = next(
                                (
                                    em
                                    for em in existing_members
                                    if em.person_id == researcher.id
                                ),
                                None,
                            )

                            if target_member:
                                current_end_date = target_member.end_date
                                # Check if end_date provided by CNPq is 'new' (we have it, DB doesn't)
                                # or different (CNPq has date, DB has different date)

                                should_update = False
                                if end_date and current_end_date != end_date:
                                    should_update = True

                                if should_update:
                                    before_end_date = current_end_date
                                    logger.info(
                                        f"Updating member {name} dates: End {current_end_date} -> {end_date}"
                                    )

                                    # Use direct SQL update for safety and to avoid ORM complexity with composite keys/relationships
                                    upd_query = text(
                                        """
                                        UPDATE team_members 
                                        SET end_date = :end_dt 
                                        WHERE team_id = :gid AND person_id = :pid
                                    """
                                    )
                                    session = self.rg_ctrl._service._repository._session
                                    session.execute(
                                        upd_query,
                                        {
                                            "end_dt": end_date,
                                            "gid": group_id,
                                            "pid": researcher.id,
                                        },
                                    )
                                    session.commit()
                                    tracking_recorder.record_change(
                                        source_record_id=getattr(
                                            source_record, "id", None
                                        ),
                                        canonical_entity_type="research_group",
                                        canonical_entity_id=group_id,
                                        operation="update",
                                        changed_fields=["member_end_date"],
                                        before={
                                            "person_id": researcher.id,
                                            "end_date": before_end_date,
                                        },
                                        after={
                                            "person_id": researcher.id,
                                            "end_date": end_date,
                                        },
                                        reason="Updated group member end_date from CNPq sync",
                                    )
                                else:
                                    logger.debug(f"Member {name} up to date.")

                        except Exception as inner_e:
                            logger.warning(f"Failed to update member {name}: {inner_e}")

                except Exception as e:
                    logger.warning(f"Could not associate member {name}: {e}")
                    # Rollback for this specific association failure
                    try:
                        self.rg_ctrl._service._repository._session.rollback()
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Error syncing member {name}: {e}")
                try:
                    self.rg_ctrl._service._repository._session.rollback()
                except Exception:
                    pass

        # Final commit for the whole group batch to be extra sure
        try:
            self.rg_ctrl._service._repository._session.commit()
        except Exception:
            pass

    def sync_knowledge_areas(
        self,
        group_id: Any,
        lines_data: List[Dict[str, Any]],
        *,
        source_file: str | None = None,
    ):
        """
        Syncs research lines as Knowledge Areas and associates them to the group.
        """
        import unicodedata

        from sqlalchemy import text

        def normalize(text):
            if not text:
                return ""
            return unicodedata.normalize("NFC", str(text).strip())

        if not lines_data:
            return

        try:
            # 1. Fetch/Create Knowledge Areas
            ka_map = {}
            all_kas = self.ka_ctrl.get_all()
            for ka in all_kas:
                if ka.name:
                    ka_map[normalize(ka.name).lower()] = ka

            processed_kas = []
            source_records_by_name = {}
            for line in lines_data:
                raw_name = line.get("nome_da_linha_de_pesquisa")
                if not raw_name:
                    continue

                norm_name = normalize(raw_name)
                key = norm_name.lower()
                source_record = tracking_recorder.record_source_record(
                    source_entity_type="cnpq_research_line",
                    payload=line,
                    source_record_id=f"{group_id}|{norm_name}",
                    source_file=source_file,
                    source_path=source_file,
                )
                source_records_by_name[key] = source_record

                ka = ka_map.get(key)
                if not ka:
                    logger.info(f"Creating new Knowledge Area: {norm_name}")
                    try:
                        ka = self.ka_ctrl.create_knowledge_area(name=norm_name)
                        ka_map[key] = ka  # Update map
                        tracking_recorder.record_change(
                            source_record_id=getattr(source_record, "id", None),
                            canonical_entity_type="knowledge_area",
                            canonical_entity_id=ka.id,
                            operation="create",
                            changed_fields=["name"],
                            after={"name": norm_name},
                            reason="Created knowledge area from CNPq research line",
                        )
                    except Exception as e:
                        logger.error(f"Failed to create KA {norm_name}: {e}")
                        continue
                else:
                    logger.debug(f"Using existing KA: {ka.name}")

                if ka:
                    processed_kas.append(ka)

            # 2. Associate with Group (Direct SQL for safety/performance)
            session = self.rg_ctrl._service._repository._session

            pending_tracking_associations = []

            for ka in processed_kas:
                try:
                    # Check existence
                    check_query = text(
                        "SELECT 1 FROM group_knowledge_areas WHERE group_id = :gid AND area_id = :aid"
                    )
                    exists = session.execute(
                        check_query, {"gid": group_id, "aid": ka.id}
                    ).fetchone()

                    if not exists:
                        logger.info(f"Associating KA '{ka.name}' to Group {group_id}")
                        ins_query = text(
                            "INSERT INTO group_knowledge_areas (group_id, area_id) VALUES (:gid, :aid)"
                        )
                        session.execute(ins_query, {"gid": group_id, "aid": ka.id})
                        pending_tracking_associations.append(
                            {
                                "source_record": source_records_by_name.get(
                                    normalize(ka.name).lower()
                                ),
                                "knowledge_area_id": ka.id,
                                "knowledge_area_name": ka.name,
                            }
                        )
                    else:
                        logger.debug(
                            f"KA '{ka.name}' already associated to Group {group_id}"
                        )

                except Exception as e:
                    logger.error(
                        f"Failed to associate KA {ka.id} to Group {group_id}: {e}"
                    )
                    # Don't rollback whole transaction, just skip this association?
                    # Actually, if auto-commit isn't on, we might need to rollback sub-transaction if using Postgres
                    # But here likely wrapping inside outer transaction or session management.
                    # Safe pattern:
                    try:
                        session.rollback()
                    except:
                        pass

            session.commit()

            for association in pending_tracking_associations:
                source_record = association["source_record"]
                knowledge_area_id = association["knowledge_area_id"]
                knowledge_area_name = association["knowledge_area_name"]
                tracking_recorder.record_entity_match(
                    source_record_id=getattr(source_record, "id", None),
                    canonical_entity_type="knowledge_area",
                    canonical_entity_id=knowledge_area_id,
                    match_strategy="normalized_name",
                    match_confidence=1.0,
                )
                tracking_recorder.record_attribute_assertions(
                    source_record_id=getattr(source_record, "id", None),
                    canonical_entity_type="knowledge_area",
                    canonical_entity_id=knowledge_area_id,
                    selected_attributes={
                        "name": knowledge_area_name,
                        "group_id": group_id,
                    },
                    selection_reason="cnpq_research_line_selected_values",
                )
                tracking_recorder.record_change(
                    source_record_id=getattr(source_record, "id", None),
                    canonical_entity_type="research_group",
                    canonical_entity_id=group_id,
                    operation="update",
                    changed_fields=["knowledge_area_association"],
                    after={
                        "knowledge_area_id": knowledge_area_id,
                        "knowledge_area_name": knowledge_area_name,
                    },
                    reason="Associated knowledge area from CNPq research line",
                )
            logger.info(
                f"Synced {len(processed_kas)} research lines/KAs for group {group_id}"
            )

        except Exception as e:
            logger.error(f"Failed to sync knowledge areas for {group_id}: {e}")
            try:
                self.rg_ctrl._service._repository._session.rollback()
            except:
                pass
