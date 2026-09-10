import re
from typing import List, Optional, Tuple

import pandas as pd
from loguru import logger

from src.core.logic.initiative_identity import normalize_text
from src.core.logic.researcher_resolution import resolve_or_create_researcher

from .base import (
    CampusStrategy,
    KnowledgeAreaStrategy,
    OrganizationStrategy,
    ResearcherStrategy,
    ResearchGroupMappingStrategy,
    RoleStrategy,
)


class SigPesqOrganizationStrategy(OrganizationStrategy):
    def ensure(self, uni_ctrl) -> int:
        """Ensures IFES exists."""
        try:
            all_orgs = uni_ctrl.get_all()
            for org in all_orgs:
                if normalize_text(org.name) in {
                    normalize_text("IFES"),
                    normalize_text("Instituto Federal do Espirito Santo"),
                    normalize_text("Instituto Federal do Espírito Santo"),
                }:
                    logger.info(f"Organization found: {org.name} (ID: {org.id})")
                    return org.id
        except Exception as e:
            logger.error(f"Error fetching organizations: {e}")

        try:
            ufsc = uni_ctrl.create_university(
                name="IFES", short_name="Instituto Federal do Espirito Santo"
            )
            logger.info(f"Organization created: {ufsc.name} (ID: {ufsc.id})")
            return ufsc.id
        except Exception as e:
            logger.error(f"Failed to create organization: {e}")
            return None


class SigPesqCampusStrategy(CampusStrategy):
    # O relatório de orientações traz o campus escrito à mão: "Serra",
    # "Campus Serra", "serra", "Serra ". O normalize_text já resolve caixa,
    # acento e espaço, mas não a palavra "campus" na frente — e como o caminho
    # de falha aqui é criar o campus, a variante prefixada nasceria como uma
    # unidade organizacional nova. Por isso o prefixo sai antes da comparação.
    _CAMPUS_PREFIX = re.compile(r"^campus\s+", re.IGNORECASE)

    @classmethod
    def _strip_campus_prefix(cls, normalized_name: str) -> str:
        """Remove o "campus " inicial, desde que sobre algum nome."""
        stripped = cls._CAMPUS_PREFIX.sub("", normalized_name).strip()
        return stripped or normalized_name

    def ensure(self, campus_ctrl, campus_name: str, org_id: int) -> int:
        """Ensures Campus exists."""
        try:
            all_campuses = campus_ctrl.get_all()
            target_name = self._strip_campus_prefix(normalize_text(campus_name))
            for campus in all_campuses:
                c_org = getattr(campus, "organization_id", None)
                existing_name = self._strip_campus_prefix(normalize_text(campus.name))
                if existing_name == target_name and (c_org is None or c_org == org_id):
                    logger.debug(f"Campus found: {campus.name}")
                    return campus.id
        except Exception as e:
            logger.error(f"Error fetching campuses: {e}")

        try:
            campus = campus_ctrl.create_campus(name=campus_name, organization_id=org_id)
            logger.info(f"Campus created: {campus.name} (ID: {campus.id})")
            return campus.id
        except Exception as e:
            logger.error(f"Error creating campus '{campus_name}': {e}")
            return None


class SigPesqKnowledgeAreaStrategy(KnowledgeAreaStrategy):
    def ensure(self, area_ctrl, area_name: str) -> Optional[int]:
        """Ensures Knowledge Area exists."""
        if not area_name or pd.isna(area_name):
            return None

        try:
            all_areas = area_ctrl.get_all()
            target_name = normalize_text(area_name)
            for area in all_areas:
                if normalize_text(area.name) == target_name:
                    return area.id
        except Exception as e:
            logger.error(f"Error fetching areas: {e}")

        try:
            area = area_ctrl.create_knowledge_area(name=area_name)
            logger.info(f"Knowledge Area created: {area.name}")
            return area.id
        except Exception as e:
            logger.error(f"Error creating area '{area_name}': {e}")
            return None


class SigPesqResearcherStrategy(ResearcherStrategy):
    def ensure(self, researcher_ctrl, name: str, email: str = None):
        """Ensures a researcher exists using strict idempotency."""
        try:
            all_res = researcher_ctrl.get_all()
            # Email belongs only in `emails`; identification_id is a CPF-like
            # identity column and an email hash there poisons future matching.
            res = resolve_or_create_researcher(
                researcher_ctrl,
                all_res,
                name=name,
                emails=[email] if email else None,
            )
            if res:
                return res
        except Exception as e:
            logger.error(f"Error fetching researchers: {e}")
        return None


class SigPesqRoleStrategy(RoleStrategy):
    def ensure_leader(self, role_ctrl):
        """Ensures the Leader role exists."""
        try:
            role = role_ctrl.get_or_create_leader_role()
            logger.info(f"Role 'Leader' ensured (ID: {role.id})")
            return role
        except Exception as e:
            logger.error(f"Error ensuring leader role: {e}")
            return None


class SigPesqExcelMappingStrategy(ResearchGroupMappingStrategy):
    """Concrete strategy for mapping SigPesq Excel data."""

    def map_row(self, row: dict) -> dict:
        """Maps SigPesq Excel columns to standardized keys."""
        return {
            "name": row.get("Nome"),
            "short_name": row.get("Sigla"),
            "campus_name": row.get("Unidade"),
            "area_name": row.get("AreaConhecimento"),
            "site_url": row.get("Column1"),
            "leaders_raw": row.get("Lideres"),
        }

    def parse_leaders(self, leaders_str: str) -> List[Tuple[str, Optional[str]]]:
        """Parses leaders string in 'Name (email)' format."""
        if not leaders_str or pd.isna(leaders_str):
            return []

        parts = re.split(r"[,;]", str(leaders_str))
        leaders = []
        for part in parts:
            part = part.strip()
            if not part:
                continue

            match = re.match(r"^(.*?)\s*\((.*?)\)$", part)
            if match:
                name = match.group(1).strip()
                email = match.group(2).strip()
                leaders.append((name, email))
            else:
                leaders.append((part, None))
        return leaders
