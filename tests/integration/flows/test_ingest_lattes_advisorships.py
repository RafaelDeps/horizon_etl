import json
from unittest.mock import MagicMock, patch

import pytest

from src.flows.lattes.advisorships import ingest_advisorships_file_task


@pytest.fixture
def mock_lattes_data(tmp_path):
    data = {
        "informacoes_pessoais": {
            "nome_completo": "Test Researcher",
            "id_lattes": "1234567890123456",
        },
        "dados_complementares": {
            "orientacoes_concluidas": [
                {
                    "natureza": "Mestrado",
                    "tipo": "MESTRADO",
                    "titulo": "Test Master Thesis",
                    "nome_do_orientado": "Student A",
                    "ano": "2023",
                    "nome_instituicao": "Test Univ",
                }
            ]
        },
    }

    file_path = tmp_path / "1234567890123456.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    return str(file_path)


@patch("src.flows.lattes.advisorships.get_run_logger")
@patch("src.flows.lattes.advisorships.LattesAdvisorshipMappingStrategy")
@patch("src.flows.lattes.advisorships.LattesParser")
@patch("src.flows.lattes.advisorships.resolve_researcher_from_lattes")
@patch("src.flows.lattes.advisorships.ResearcherController")
def test_ingest_advisorships_file_task(
    MockResearcherCtrl,
    mock_resolve_researcher,
    MockParser,
    MockMappingStrategy,
    _mock_logger,
    mock_lattes_data,
):
    mock_res_ctrl = MockResearcherCtrl.return_value
    mock_res_ctrl.get_all.return_value = [MagicMock(name="candidate")]
    mock_session = MagicMock()
    mock_res_ctrl._service._repository._session = mock_session

    supervisor = MagicMock()
    supervisor.name = "Test Researcher"
    mock_resolve_researcher.return_value = supervisor

    parsed_advisorships = [
        {
            "name": "Test Master Thesis",
            "student_name": "Student A",
            "type": "MESTRADO",
        }
    ]
    mock_parser = MockParser.return_value
    mock_parser.parse_advisorships.return_value = parsed_advisorships

    mock_loader = MagicMock()

    ingest_advisorships_file_task.fn(mock_lattes_data, mock_loader)

    mock_resolve_researcher.assert_called_once_with(
        mock_res_ctrl.get_all.return_value,
        lattes_id="1234567890123456",
        json_name="Test Researcher",
        session=mock_session,
    )
    MockMappingStrategy.assert_called_once_with("Test Researcher")
    mock_loader.mapping_strategy = MockMappingStrategy.return_value
    mock_loader.process_records.assert_called_once_with(
        parsed_advisorships,
        source_file=mock_lattes_data,
    )
