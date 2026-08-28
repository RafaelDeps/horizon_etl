from datetime import datetime
from typing import Any, Dict

from research_domain.domain.entities import Advisorship

from src.core.logic.initiative_identity import (
    build_identity_key,
    normalize_sigpesq_code,
)

from .base import ProjectMappingStrategy


class SigPesqAdvisorshipMappingStrategy(ProjectMappingStrategy):
    """
    Strategy for mapping SigPesq Advisorship (Bolsistas) Excel data to canonical domain models.
    """

    def map_row(self, row: dict) -> Dict[str, Any]:
        """
        Maps a Single SigPesq Advisorship Excel row to a standardized dictionary.
        Returns data compatible with ProjectLoader.
        """
        # Student Mapping
        bolsista = str(row.get("Orientado", "")).strip()
        bolsista_email = str(row.get("OrientadoEmail", "")).strip()

        # Supervisor Mapping
        orientador = str(row.get("Orientador", "")).strip()
        orientador_email = str(row.get("OrientadorEmail", "")).strip()

        # Project Mapping
        project_title = str(row.get("TituloPT", "N/A")).strip()
        row_id = row.get("Id", "")
        workplan_code = normalize_sigpesq_code(row.get("CodPT"))
        project_code = normalize_sigpesq_code(row.get("CodPJ"))

        if not bolsista and not bolsista_email:
            return {}

        start_date = self._parse_date(row.get("Inicio"))
        end_date = self._parse_date(row.get("Fim"))
        cancelled = self._parse_cancelled(row.get("Cancelado"))
        cancellation_date = self._parse_date(
            row.get(
                "CanceladoData",
                row.get("DataCancelamento", row.get("DataCancelado")),
            )
        )

        # Determine status based on end_date
        status = "Active"
        if cancelled:
            status = "Cancelled"
        elif end_date and end_date < datetime.now():
            status = "Concluded"

        # Fellowship data
        programa = row.get("Programa")
        fellowship_data = None
        if programa:
            fellowship_data = {
                "name": str(programa).strip().upper(),
                "value": self.parse_currency(row.get("Valor")),
                "description": f"Programa: {programa}",
                "sigpesq_id": row_id,
                "sigpesq_workplan_code": workplan_code,
                "sigpesq_project_code": project_code,
                "sponsor_name": str(
                    row.get("AgFinanciadora", row.get("agFinanciadora", ""))
                ).strip(),
            }

        # O código do plano de trabalho (CodPT) identifica o PLANO, não a bolsa:
        # um mesmo plano pode ter bolsas consecutivas com bolsistas e períodos
        # diferentes. Usá-lo sozinho como identidade fazia duas bolsas colapsarem
        # na mesma chave, e a segunda tentava renomear a linha da primeira —
        # batendo na restrição de unicidade de `initiatives.name` e sendo
        # descartada. O `row_id` desempata sem perder o vínculo com o plano.
        identity_parts = (
            ["sigpesq_workplan", workplan_code, row_id]
            if workplan_code
            else [
                "sigpesq_advisorship",
                row_id,
                project_title,
                orientador_email or orientador,
                bolsista_email or bolsista,
                row.get("Inicio"),
            ]
        )
        parent_identity_key = (
            build_identity_key(["sigpesq_project", project_code])
            if project_code
            else None
        )

        return {
            "title": project_title,
            "parent_title": str(row.get("TituloPJ", "")).strip(),
            "parent_identity_key": parent_identity_key,
            "status": status,
            "start_date": start_date,
            "end_date": end_date,
            "cancelled": cancelled,
            "cancellation_date": cancellation_date,
            "description": f"Programa: {programa or 'N/A'}",
            "coordinator_name": orientador,
            "coordinator_email": orientador_email,
            "student_names": [bolsista] if bolsista else [],
            "student_emails": [bolsista_email] if bolsista_email else [],
            "researcher_names": [],
            "model_class": Advisorship,
            "fellowship_data": fellowship_data,
            "metadata": {
                "sigpesq_id": row_id,
                "sigpesq_workplan_code": workplan_code,
                "sigpesq_project_code": project_code,
                "original_program": programa,
                "cancelled": cancelled,
                "cancelled_by": self._clean_optional(row.get("CanceladoPor")),
                "parent_project_title": str(row.get("TituloPJ", "")).strip(),
                "source_system": "sigpesq_advisorships",
            },
            "campus_name": row.get("CampusExecucao", row.get("Campus")),
            "identity_key": build_identity_key(identity_parts),
        }

    @staticmethod
    def _parse_cancelled(value: Any) -> bool:
        try:
            import pandas as pd

            if pd.isna(value):
                return False
        except (ImportError, TypeError, ValueError):
            pass

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return value != 0

        normalized = str(value).strip().casefold()
        if normalized in {"", "0", "false", "f", "nao", "não", "n", "no"}:
            return False
        if normalized in {"1", "true", "t", "sim", "s", "yes", "y"}:
            return True
        return bool(normalized)

    @staticmethod
    def _clean_optional(value: Any) -> Any:
        try:
            import pandas as pd

            if pd.isna(value):
                return None
        except (ImportError, TypeError, ValueError):
            pass

        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None
