from typing import Any, Dict, List

import pandas as pd
from loguru import logger

from src.core.logic.initiative_identity import (
    build_identity_key,
    normalize_sigpesq_code,
)

from .base import ProjectMappingStrategy


class SigPesqProjectMappingStrategy(ProjectMappingStrategy):
    """
    Strategy for mapping SigPesq Project Excel data to canonical domain models.

    This strategy handles the specific column names and formats found in the SigPesq
    research project exports, including multi-value name parsing and date handling.
    """

    # The name lists the portal returns in another order between downloads.
    UNORDERED_NAME_COLUMNS = ("Pesquisadores", "Estudantes")

    def change_content(self, row: dict) -> Dict[str, Any]:
        """The content compared to decide whether a row changed (branch 036).

        The portal reorders "Pesquisadores" and "Estudantes" between downloads,
        which made an unchanged row look changed. Both lists are compared as
        sorted names; a name added or removed is still a change. The row
        itself, and the payload stored for tracking, stay as read.
        """
        content = dict(row)
        for column in self.UNORDERED_NAME_COLUMNS:
            content[column] = sorted(self._parse_names(row.get(column)))
        return content

    def map_row(self, row: dict) -> Dict[str, Any]:
        """
        Maps a Single SigPesq Excel row to a standardized dictionary of initiative attributes.

        Args:
            row (dict): A dictionary representing a row from the Excel file.

        Returns:
            Dict[str, Any]: Standardized project data with keys like 'title', 'coordinator_name', etc.
        """
        # Calculate status based on ParecerDiretoria and dates
        parecer = row.get("ParecerDiretoria", "Unknown")
        end_date = self._parse_date(row.get("Fim"))

        status = parecer
        if parecer == "Aprovado":
            from datetime import datetime

            if end_date and end_date < datetime.now():
                status = "Concluded"
            else:
                status = "Active"

        project_code = normalize_sigpesq_code(row.get("Id"))
        identity_parts = (
            ["sigpesq_project", project_code]
            if project_code
            else [
                "sigpesq_project",
                row.get("Id"),
                row.get("Titulo", row.get("Título")),
                row.get("Coordenador"),
                row.get("Inicio"),
            ]
        )

        return {
            "title": row.get("Titulo", row.get("Título")),
            "status": status,
            "start_date": self._parse_date(row.get("Inicio")),
            "end_date": end_date,
            "description": row.get("Resumo"),
            "value": row.get("Valor Aprovado"),
            "coordinator_name": row.get("Coordenador"),
            "researcher_names": self._parse_names(row.get("Pesquisadores")),
            "student_names": self._parse_names(row.get("Estudantes")),
            "research_group_name": row.get("GrupoPesquisa"),
            "metadata": {
                "external_partner": row.get("ParceiroDemandante"),
                "external_research_group": row.get("GrupoPesquisaExterno"),
                "knowledge_area": row.get("AreaConhecimento"),
                "keywords": row.get("PalavraChave"),
                "sigpesq_project_code": project_code,
                "source_system": "sigpesq_projects",
            },
            "campus_name": row.get("CampusExecucao"),
            "identity_key": build_identity_key(identity_parts),
        }

    def _parse_names(self, names_str: Any) -> List[str]:
        """
        Parses a semicolon-separated string of names into a trimmed list.

        Args:
            names_str (Any): The input string or NaN value.

        Returns:
            List[str]: A list of non-empty name strings.
        """
        if not names_str or pd.isna(names_str):
            return []
        return [name.strip() for name in str(names_str).split(";") if name.strip()]

    def _parse_date(self, date_val: Any):
        """
        Attempts to parse a date from various types and string formats.

        Args:
            date_val (Any): Input date value (datetime, string, or NaN).

        Returns:
            Optional[datetime]: The parsed datetime object, or None if parsing fails.
        """
        if pd.isna(date_val) or not date_val:
            return None

        from datetime import datetime

        # If already datetime
        if isinstance(date_val, datetime):
            return date_val

        str_val = str(date_val).strip()
        formats = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"]

        for fmt in formats:
            try:
                return datetime.strptime(str_val, fmt)
            except ValueError:
                continue

        logger.warning(f"Could not parse date: {str_val}")
        return None
