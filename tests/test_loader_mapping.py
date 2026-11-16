from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.core.logic.pii_anonymizer import anonymize_email
from src.core.logic.research_group_loader import ResearchGroupLoader
from src.core.logic.strategies.sigpesq_excel import (
    SigPesqCampusStrategy,
    SigPesqExcelMappingStrategy,
    SigPesqKnowledgeAreaStrategy,
    SigPesqOrganizationStrategy,
    SigPesqResearcherStrategy,
    SigPesqRoleStrategy,
)


def test_research_group_loader_mapping():
    # Setup
    loader = ResearchGroupLoader(
        mapping_strategy=SigPesqExcelMappingStrategy(),
        org_strategy=SigPesqOrganizationStrategy(),
        campus_strategy=SigPesqCampusStrategy(),
        area_strategy=SigPesqKnowledgeAreaStrategy(),
        researcher_strategy=SigPesqResearcherStrategy(),
        role_strategy=SigPesqRoleStrategy(),
    )
    loader.uni_ctrl = MagicMock()
    loader.campus_ctrl = MagicMock()
    loader.rg_ctrl = MagicMock()
    loader.area_ctrl = MagicMock()
    loader.researcher_ctrl = MagicMock()
    loader.role_ctrl = MagicMock()

    # Mock return values
    loader.ensure_organization = MagicMock(return_value=1)
    loader.ensure_campus = MagicMock(return_value=1)
    loader.ensure_knowledge_area = MagicMock(return_value=1)

    mock_research_group = MagicMock()
    mock_research_group.id = 100
    mock_research_group.name = "Grupo Teste"
    loader.rg_ctrl.create_research_group.return_value = mock_research_group

    loader.researcher_ctrl.get_all.return_value = []
    mock_researcher = MagicMock()
    mock_researcher.id = 50
    loader.researcher_ctrl.create_researcher.return_value = mock_researcher

    # Create invalid/dummy dataframe
    data = {
        "Nome": ["Grupo Teste"],
        "Sigla": ["GT"],
        "Unidade": ["Campus X"],
        "AreaConhecimento": ["Area Y"],
        "Column1": ["http://cnpq.br/grupo"],
        "Lideres": ["Carlos Campos (carlos@ifes.edu.br)"],
    }
    df = pd.DataFrame(data)

    # Save to tmp excel
    tmp_path = "test_mapping.xlsx"
    df.to_excel(tmp_path, index=False)

    # Execute
    loader.process_file(tmp_path)

    # Verify
    loader.rg_ctrl.create_research_group.assert_called_with(
        name="Grupo Teste",
        campus_id=1,
        organization_id=1,
        short_name="GT",
        cnpq_url="http://cnpq.br/grupo",
        knowledge_area_ids=[1],
    )

    # SigPesq e-mails are pseudonymized before they reach the database (LGPD).
    loader.researcher_ctrl.create_researcher.assert_called_with(
        name="Carlos Campos",
        emails=[anonymize_email("carlos@ifes.edu.br")],
        identification_id=None,
    )
    loader.rg_ctrl.add_leader.assert_called()

    import os

    if os.path.exists(tmp_path):
        os.remove(tmp_path)


def test_research_group_loader_skips_duplicate_name_in_same_file():
    loader = ResearchGroupLoader(
        mapping_strategy=SigPesqExcelMappingStrategy(),
        org_strategy=SigPesqOrganizationStrategy(),
        campus_strategy=SigPesqCampusStrategy(),
        area_strategy=SigPesqKnowledgeAreaStrategy(),
        researcher_strategy=SigPesqResearcherStrategy(),
        role_strategy=SigPesqRoleStrategy(),
    )
    loader.uni_ctrl = MagicMock()
    loader.campus_ctrl = MagicMock()
    loader.rg_ctrl = MagicMock()
    loader.area_ctrl = MagicMock()
    loader.researcher_ctrl = MagicMock()
    loader.role_ctrl = MagicMock()

    loader.ensure_organization = MagicMock(return_value=1)
    loader.ensure_campus = MagicMock(return_value=1)
    loader.ensure_knowledge_area = MagicMock(return_value=1)
    loader.ensure_leader_role = MagicMock()

    mock_research_group = MagicMock()
    mock_research_group.id = 100
    mock_research_group.name = "Grupo Duplicado"
    loader.rg_ctrl.get_all.return_value = []
    loader.rg_ctrl.create_research_group.return_value = mock_research_group

    data = {
        "Nome": ["Grupo Duplicado", "Grupo Duplicado"],
        "Sigla": ["GD", "GD"],
        "Unidade": ["Campus X", "Campus X"],
        "AreaConhecimento": ["Area Y", "Area Y"],
        "Column1": ["http://cnpq.br/grupo", "http://cnpq.br/grupo"],
        "Lideres": [None, None],
    }
    df = pd.DataFrame(data)

    tmp_path = "test_mapping_duplicates.xlsx"
    df.to_excel(tmp_path, index=False)

    loader.process_file(tmp_path)

    assert loader.rg_ctrl.create_research_group.call_count == 1

    import os

    if os.path.exists(tmp_path):
        os.remove(tmp_path)


if __name__ == "__main__":
    test_research_group_loader_mapping()
    print("Test Passed!")
