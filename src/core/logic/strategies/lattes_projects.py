from typing import Any, Dict, List
from datetime import datetime

from .base import ProjectMappingStrategy
from src.adapters.sources.lattes_parser import LattesParser
from src.core.logic.initiative_identity import build_identity_key
from src.core.logic.person_name_rules import is_name_fragment


class LattesProjectMappingStrategy(ProjectMappingStrategy):
    """
    Strategy for mapping Lattes JSON project data to canonical domain models.
    """

    def __init__(self, target_researcher_name: str, researcher_roles: Dict[str, str] = None):
        super().__init__()
        self.parser = LattesParser()
        self.target_researcher_name = target_researcher_name
        self.target_researcher_name_normalized = self.parser.normalize_title(
            target_researcher_name
        )
        # Roles from raw_members
        self.researcher_roles = researcher_roles or {}

    def map_row(self, row: dict) -> Dict[str, Any]:
        """
        Maps a Single Lattes parsed dictionary to a standardized dictionary.
        """
        start_year = row.get("start_year")
        end_year = row.get("end_year")
        
        start_date = None
        if start_year:
            try:
                start_date = datetime.strptime(f"{start_year}-01-01", "%Y-%m-%d")
            except ValueError:
                pass
                
        end_date = None
        if end_year:
            try:
                end_date = datetime.strptime(f"{end_year}-12-31", "%Y-%m-%d")
            except ValueError:
                pass

        # Identify roles from raw members
        raw_members = row.get("raw_members", [])
        
        coordinator_name = None
        student_names = []
        researcher_names = []
        
        for m in raw_members:
            m_name = m.get("nome", "")
            # Branch 041: "D", "J" or "-" in the member list are not people.
            if is_name_fragment(m_name):
                continue
            m_role = m.get("papel", "Integrante").lower()
            
            if "coordenador" in m_role:
                if not coordinator_name: 
                    coordinator_name = m_name
                else:
                    researcher_names.append(m_name)
            elif "estudante" in m_role or "bolsista" in m_role:
                student_names.append(m_name)
            else:
                researcher_names.append(m_name)
                
        # If no coordinator found but target researcher is marked as coordinator in Lattes
        if not coordinator_name and (row.get("role") == "Coordenador" or self.researcher_roles.get(row.get("name")) == "Coordenador"):
            coordinator_name = self.target_researcher_name
            # remove from researchers if present
            researcher_names = [
                n
                for n in researcher_names
                if self.parser.normalize_title(n)
                != self.target_researcher_name_normalized
            ]

        # Ensure the target researcher is included if they are not the coordinator or a student
        if coordinator_name and (
            self.parser.normalize_title(coordinator_name)
            != self.target_researcher_name_normalized
        ):
             if not any(
                 self.parser.normalize_title(n)
                 == self.target_researcher_name_normalized
                 for n in researcher_names + student_names
             ):
                 researcher_names.append(self.target_researcher_name)

        # Extract sponsors
        raw_sponsors = row.get("raw_sponsors", [])
        sponsor_name = None
        if raw_sponsors:
             sponsor_name = raw_sponsors[0].get("nome")

        return {
            "title": row.get("name"),
            "status": row.get("status"), # Lattes parser standardizes this
            "start_date": start_date,
            "end_date": end_date,
            "description": row.get("description"),
            "value": 0.0, # Lattes doesn't reliably provide project value
            "coordinator_name": coordinator_name,
            "researcher_names": researcher_names,
            "student_names": student_names,
            "research_group_name": None, # Lattes doesn't link projects to research groups reliably
            "metadata": {
                "external_partner": sponsor_name,
                "project_nature": row.get("nature"),
                "initiative_type_name": row.get("initiative_type_name"),
                "source_system": "lattes_projects",
            },
            "campus_name": None, # Lattes doesn't provide campus
            "identity_key": build_identity_key(
                [
                    "lattes_project",
                    row.get("name"),
                    coordinator_name or self.target_researcher_name,
                    start_year,
                    row.get("initiative_type_name"),
                ]
            ),
        }
