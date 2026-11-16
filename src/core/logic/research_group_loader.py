from contextlib import nullcontext

import pandas as pd
from loguru import logger
from research_domain import (
    CampusController,
    KnowledgeAreaController,
    ResearcherController,
    ResearchGroupController,
    RoleController,
    UniversityController,
)

from src.core.logic.document_skip import file_download_date, mark_partial
from src.core.logic.initiative_identity import normalize_text
from src.core.logic.pii_anonymizer import anonymize_person_data
from src.tracking.recorder import tracking_recorder

from .strategies.base import (
    CampusStrategy,
    KnowledgeAreaStrategy,
    OrganizationStrategy,
    ResearcherStrategy,
    ResearchGroupMappingStrategy,
    RoleStrategy,
)


class ResearchGroupLoader:
    def __init__(
        self,
        mapping_strategy: ResearchGroupMappingStrategy,
        org_strategy: OrganizationStrategy,
        campus_strategy: CampusStrategy,
        area_strategy: KnowledgeAreaStrategy,
        researcher_strategy: ResearcherStrategy,
        role_strategy: RoleStrategy,
    ):
        self.mapping_strategy = mapping_strategy
        self.org_strategy = org_strategy
        self.campus_strategy = campus_strategy
        self.area_strategy = area_strategy
        self.researcher_strategy = researcher_strategy
        self.role_strategy = role_strategy

        self.uni_ctrl = UniversityController()
        self.campus_ctrl = CampusController()
        self.rg_ctrl = ResearchGroupController()
        self.area_ctrl = KnowledgeAreaController()
        self.researcher_ctrl = ResearcherController()
        self.role_ctrl = RoleController()

        # Cache to avoid repeated DB hits
        self._org_id = None
        self._campus_cache = {}
        self._area_cache = {}
        self._role_cache = {}
        self._researcher_cache = {}
        # Spec 021: when set (SigPesq flow), each report row is one source
        # document, skipped when unchanged and written in one transaction.
        self.document_skip = None
        self._existing_groups_map = {}

    def ensure_organization(self):
        """Ensures organization exists using strategy."""
        if self._org_id:
            return self._org_id

        self._org_id = self.org_strategy.ensure(self.uni_ctrl)
        return self._org_id

    def ensure_campus(self, campus_name: str, org_id: int):
        """Ensures Campus exists using strategy."""
        campus_key = normalize_text(campus_name)
        if campus_key in self._campus_cache:
            return self._campus_cache[campus_key]

        campus_id = self.campus_strategy.ensure(self.campus_ctrl, campus_name, org_id)
        if campus_id:
            self._campus_cache[campus_key] = campus_id
        return campus_id

    def reset_caches(self) -> None:
        """After a rolled-back row (spec 021): the caches may hold rows that no
        longer exist; reload the group index, drop the rest."""
        self._org_id = None
        self._campus_cache.clear()
        self._area_cache.clear()
        self._role_cache.clear()
        self._researcher_cache.clear()
        self._load_existing_groups()

    def _load_existing_groups(self) -> None:
        self._existing_groups_map.clear()
        try:
            for g in self.rg_ctrl.get_all():
                if g.name:
                    self._existing_groups_map[normalize_text(g.name)] = g
            logger.info(
                f"Pre-fetched {len(self._existing_groups_map)} existing groups."
            )
        except Exception as e:
            logger.warning(f"Could not pre-fetch groups: {e}")

    def _row_document(self, row: dict):
        """The row as a source document, keyed by the normalized group name,
        or a null context when no DocumentSkip is attached."""
        if self.document_skip is None:
            return nullcontext(None)
        name = self.mapping_strategy.map_row(dict(row)).get("name")
        key = normalize_text(name) if isinstance(name, str) else str(name)
        return self.document_skip.document(
            key, downloaded_at=getattr(self, "_report_date", None)
        )

    def _try_rollback(self, controller):
        """Attempts to rollback session via private attributes."""
        try:
            if (
                hasattr(controller, "_service")
                and hasattr(controller._service, "_repository")
                and hasattr(controller._service._repository, "_session")
            ):
                controller._service._repository._session.rollback()
                logger.debug("Session rolled back successfully.")
        except:
            pass

    def ensure_leader_role(self):
        """Ensures the Leader role exists using strategy."""
        if "leader" in self._role_cache:
            return self._role_cache["leader"]

        role = self.role_strategy.ensure_leader(self.role_ctrl)
        if role:
            self._role_cache["leader"] = role
        return role

    def ensure_researcher(self, name: str, email: str = None):
        """Ensures a researcher exists."""
        cache_key = f"{normalize_text(name)}|{(email or '').strip().lower()}"
        if cache_key in self._researcher_cache:
            return self._researcher_cache[cache_key]

        email = anonymize_person_data({"email": email})["email"]
        researcher = self.researcher_strategy.ensure(self.researcher_ctrl, name, email)
        if researcher:
            self._researcher_cache[cache_key] = researcher
        return researcher

    def ensure_knowledge_area(self, area_name: str):
        """Ensures Knowledge Area exists."""
        if not area_name or pd.isna(area_name):
            return None

        area_key = normalize_text(area_name)
        if area_key in self._area_cache:
            return self._area_cache[area_key]

        area_id = self.area_strategy.ensure(self.area_ctrl, area_name)
        if area_id:
            self._area_cache[area_key] = area_id
        return area_id

    def process_file(self, file_path: str):
        logger.info(f"Processing Research Groups from: {file_path}")
        # Spec 023: the rows date from the report, downloaded whole each run.
        self._report_date = file_download_date(file_path)

        try:
            df = pd.read_excel(file_path)
        except Exception as e:
            logger.error(f"Failed to read Excel: {e}")
            # The report is then not a complete listing (spec 021, R8).
            self.read_failures = getattr(self, "read_failures", 0) + 1
            return

        self.ensure_leader_role()
        org_id = self.ensure_organization()
        if not org_id:
            logger.error("Organization ID not available. Aborting.")
            self.read_failures = getattr(self, "read_failures", 0) + 1
            return

        self._load_existing_groups()
        existing_groups_map = self._existing_groups_map

        count = 0
        updated = 0
        skipped = 0
        for _, row_raw in df.iterrows():
            row = row_raw.to_dict()
            if self.document_skip is not None and pd.isna(
                self.mapping_strategy.map_row(dict(row)).get("name")
            ):
                continue
            with self._row_document(row) as doc:
                if doc is not None:
                    if doc.unchanged(row):
                        continue
                    doc.begin()
                try:
                    # Delegate mapping to strategy
                    data = self.mapping_strategy.map_row(row_raw.to_dict())

                    name = data.get("name")
                    sigla = data.get("short_name")
                    unidade = data.get("campus_name")
                    area_name = data.get("area_name")
                    site_url = data.get("site_url")
                    leaders_raw = data.get("leaders_raw")

                    if pd.isna(name):
                        continue
                    name_key = normalize_text(name)
                    source_record = tracking_recorder.record_source_record(
                        source_entity_type="research_group",
                        payload=row_raw.to_dict(),
                        source_record_id=name_key or str(name),
                        source_file=file_path,
                        source_path=file_path,
                    )

                    area_ids = []
                    if pd.notna(area_name):
                        aid = self.ensure_knowledge_area(str(area_name).strip())
                        if aid:
                            area_ids.append(aid)

                    # Delegate parsing to strategy
                    leaders_data = self.mapping_strategy.parse_leaders(leaders_raw)

                    group = None
                    group_already_existed = name_key in existing_groups_map
                    if group_already_existed:
                        group = existing_groups_map[name_key]
                        if (
                            pd.notna(site_url)
                            and getattr(group, "cnpq_url", None) != site_url
                        ):
                            group.cnpq_url = site_url
                            try:
                                self.rg_ctrl.update(group)
                                updated += 1
                                tracking_recorder.record_change(
                                    source_record_id=getattr(source_record, "id", None),
                                    canonical_entity_type="research_group",
                                    canonical_entity_id=group.id,
                                    operation="update",
                                    changed_fields=["cnpq_url"],
                                    before={
                                        "cnpq_url": getattr(group, "cnpq_url", None)
                                    },
                                    after={"cnpq_url": site_url},
                                    reason="Updated CNPq URL from source file",
                                )
                            except Exception as e:
                                logger.warning(f"Failed to update group {name}: {e}")
                                mark_partial(f"update of group {name} failed")
                        skipped += 1
                    else:
                        campus_name = (
                            unidade if pd.notna(unidade) else "Campus Desconhecido"
                        )
                        campus_id = self.ensure_campus(campus_name, org_id)

                        if not campus_id:
                            continue

                        try:
                            group = self.rg_ctrl.create_research_group(
                                name=name,
                                campus_id=campus_id,
                                organization_id=org_id,
                                short_name=sigla if pd.notna(sigla) else None,
                                cnpq_url=site_url if pd.notna(site_url) else None,
                                knowledge_area_ids=area_ids if area_ids else None,
                            )
                            existing_groups_map[name_key] = group
                            count += 1
                            tracking_recorder.record_entity_match(
                                source_record_id=getattr(source_record, "id", None),
                                canonical_entity_type="research_group",
                                canonical_entity_id=group.id,
                                match_strategy="canonical_name",
                                match_confidence=1.0,
                            )
                            tracking_recorder.record_attribute_assertions(
                                source_record_id=getattr(source_record, "id", None),
                                canonical_entity_type="research_group",
                                canonical_entity_id=group.id,
                                selected_attributes={
                                    "name": name,
                                    "short_name": sigla if pd.notna(sigla) else None,
                                    "campus_name": campus_name,
                                    "site_url": (
                                        site_url if pd.notna(site_url) else None
                                    ),
                                    "area_name": (
                                        area_name if pd.notna(area_name) else None
                                    ),
                                },
                                selection_reason="research_group_loader_selected_values",
                            )
                            tracking_recorder.record_change(
                                source_record_id=getattr(source_record, "id", None),
                                canonical_entity_type="research_group",
                                canonical_entity_id=group.id,
                                operation="create",
                                changed_fields=[
                                    "name",
                                    "short_name",
                                    "campus_name",
                                    "site_url",
                                    "area_name",
                                ],
                                after={
                                    "name": name,
                                    "short_name": sigla if pd.notna(sigla) else None,
                                    "campus_name": campus_name,
                                    "site_url": (
                                        site_url if pd.notna(site_url) else None
                                    ),
                                    "area_name": (
                                        area_name if pd.notna(area_name) else None
                                    ),
                                },
                                reason=f"{self.mapping_strategy.__class__.__name__} applied",
                            )
                        except Exception as e:
                            logger.error(f"Failed to create group {name}: {e}")
                            mark_partial(f"creation of group {name} failed")
                            self._try_rollback(self.rg_ctrl)
                            continue

                    # Rule: "If research group exist do nothing" (except cnpq_url update)
                    # We only process leaders for NEW groups or if we want to ensure leader existence idempotently
                    # Based on ADR 001, we follow "Do Nothing" for existing entities.
                    if group_already_existed:
                        logger.debug(
                            f"Skipping leader association for existing group: {name}"
                        )
                    elif group and leaders_data:
                        from datetime import date

                        # Try to get existing members if possible, to avoid duplicates
                        existing_member_ids = []
                        try:
                            members = self.rg_ctrl._service.get_members(group.id)
                            existing_member_ids = [m.person_id for m in members]
                        except:
                            pass

                        for l_name, l_email in leaders_data:
                            researcher = self.ensure_researcher(l_name, l_email)
                            if researcher:
                                if researcher.id in existing_member_ids:
                                    logger.debug(
                                        f"Leader {l_name} already associated to group {name}. Skipping."
                                    )
                                    continue

                                try:
                                    self.rg_ctrl.add_leader(
                                        team_id=group.id,
                                        person_id=researcher.id,
                                        start_date=date.today(),
                                    )
                                    logger.debug(
                                        f"Leader {l_name} associated to group {name}"
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"Failed to associate leader {l_name} to unit {name}: {e}"
                                    )
                                    mark_partial(f"leader {l_name} of {name} failed")
                                    self._try_rollback(self.rg_ctrl)

                except Exception as e:
                    logger.error(f"Error processing row: {e}")
                    mark_partial(f"row failed: {e}")
                    self._try_rollback(self.rg_ctrl)

        logger.info(
            f"Loaded {count} New Research Groups. Skipped {skipped} existing (Updated {updated})."
        )
