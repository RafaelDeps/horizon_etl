from typing import Any, Dict, List
from datetime import datetime

from .base import ProjectMappingStrategy
from research_domain.domain.entities import Advisorship
from src.core.logic.initiative_identity import build_identity_key


class LattesAdvisorshipMappingStrategy(ProjectMappingStrategy):
    """
    Strategy for mapping Lattes JSON advisorship data to canonical domain models.
    """

    def __init__(self, advisor_name: str):
        super().__init__()
        self.advisor_name = advisor_name

    def map_row(self, row: dict) -> Dict[str, Any]:
        """
        Maps a Single Lattes parsed dictionary to a standardized dictionary for AdvisorshipHandler.
        Expected format matches what AdvisorshipHandler and ProjectLoader need:
        - title
        - status
        - start_date
        - end_date
        - description
        - initiative_type_name
        - model_class (Advisorship)
        - student_names (List[str])
        - coordinator_name (str) -> Supervisor
        - fellowship_data (dict) -> sponsor and fellowship name
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

        # Lattes specifies the student directly
        student_name = row.get("student_name")
        # Branch 041: a field split into several students gives them all; the
        # key keeps them joined by " / ", which normalizes like the source text.
        student_names = list(row.get("student_names") or []) or (
            [student_name] if student_name else []
        )
        key_student = (
            " / ".join(student_names) if len(student_names) > 1 else student_name
        )
        
        # Sponsorship / Fellowship
        fellowship_data = None
        sponsor_name = row.get("sponsor_name")
        fellowship_name = row.get("fellowship_name")
        
        if sponsor_name or fellowship_name:
            # Clean up default empty strings
            f_name = fellowship_name if fellowship_name else f"Bolsa - {row.get('type_name', 'Unknown')}"
            fellowship_data = {
                "name": f_name,
                "sponsor_name": sponsor_name,
                "value": 0.0,
                "description": row.get("type_name")
            }

        return {
            "title": row.get("title") or "Untitled Advisorship",
            "status": row.get("status"), # Lattes parser standardizes to Active/Concluded
            "start_date": start_date,
            "end_date": end_date,
            "description": row.get("type_name", ""),
            "coordinator_name": self.advisor_name, # Preserve original spelling for matching
            "student_names": student_names,
            "research_group_name": None,
            "metadata": {
                "lattes_nature": row.get("nature"),
                "advisorship_type": row.get("type_name"),
                "source_system": "lattes_advisorships",
            },
            "campus_name": None,
            "model_class": Advisorship,
            "initiative_type_name": "Advisorship", # Hardcoded type for the schema
            "fellowship_data": fellowship_data,
            "identity_key": build_identity_key(
                [
                    "lattes_advisorship",
                    row.get("title"),
                    self.advisor_name,
                    key_student,
                    start_year or end_year,
                    row.get("type_name"),
                ]
            ),
        }
