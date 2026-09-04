from unittest.mock import MagicMock, patch

import pytest
from research_domain.domain.entities.academic_education import AcademicEducation

from src.core.logic.researcher_resolution import ResearcherRef
from src.flows.lattes.projects import ingest_file_task


@pytest.fixture
def mock_entity_manager():
    manager = MagicMock()
    # Mock ensure methods if needed, though mostly used for projects
    manager.ensure_initiative_type.return_value = MagicMock(id=1)
    manager.ensure_organization.return_value = 1
    manager.ensure_education_type.return_value = 1
    manager.ensure_roles.return_value = {"Researcher": MagicMock(id=1)}
    return manager


@pytest.fixture
def mock_researcher_controller():
    with patch("src.flows.lattes.projects.ResearcherController") as mock:
        yield mock


@pytest.fixture
def mock_education_controller():
    with patch("src.flows.lattes.projects.AcademicEducationController") as mock:
        yield mock


@pytest.fixture
def mock_lattes_parser():
    with patch("src.flows.lattes.projects.LattesParser") as mock:
        yield mock


@pytest.fixture
def mock_researcher_index():
    with patch("src.flows.lattes.projects.load_researcher_index") as mock:
        yield mock


def test_ingest_academic_education(
    mock_entity_manager,
    mock_researcher_controller,
    mock_education_controller,
    mock_lattes_parser,
    mock_researcher_index,
):
    # Setup Mocks
    mock_edu_ctrl_instance = mock_education_controller.return_value
    mock_parser_instance = mock_lattes_parser.return_value

    # Link mocks
    mock_entity_manager.academic_edu_controller = mock_edu_ctrl_instance

    # Mock Researcher
    #
    # Este teste casava por `brand_id` — coluna que não existe em `persons` nem
    # em `researchers`, nem como atributo mapeado. Só um mock conseguia
    # satisfazer aquela regra; contra o banco real ela nunca disparou. Agora o
    # currículo casa por nome, como acontece de fato, e a entidade completa é
    # carregada por id, como o código faz para o vencedor da correspondência.
    mock_researcher = MagicMock()
    mock_researcher.id = 123
    mock_researcher.name = "Test Researcher"
    mock_session = MagicMock()
    mock_session.execute.return_value.fetchone.return_value = None
    mock_researcher_index.return_value = [ResearcherRef(id=123, name="Test Researcher")]
    mock_researcher_controller.return_value.get_by_id.return_value = mock_researcher
    mock_researcher_controller.return_value._service._repository._session = mock_session

    # Mock Parser Output
    mock_parser_instance.parse_research_projects.return_value = []
    mock_parser_instance.parse_extension_projects.return_value = []
    mock_parser_instance.parse_development_projects.return_value = []
    mock_parser_instance.parse_articles.return_value = []
    mock_parser_instance.parse_conference_papers.return_value = []
    mock_parser_instance.parse_personal_info.return_value = {}

    mock_education_data = [
        {
            "degree": "Doutorado",
            "institution": "UFES",
            "course_name": "Ciência da Computação",
            "start_year": 2018,
            "end_year": 2022,
        }
    ]
    mock_parser_instance.parse_academic_education.return_value = mock_education_data

    # Mock JSON loading (we need to patch built-in open/json.load or use a real file)
    # Easiest is to point to a dummy file and mock json.load
    with patch("builtins.open", new_callable=MagicMock) as mock_open:
        with patch("json.load") as mock_json_load:
            mock_json_load.return_value = {
                "nome": "Test Researcher",
                "idLattes": "1234567890",
            }

            # Execute
            ingest_file_task.fn("dummy_path/1234567890.json", mock_entity_manager)

            # Assert
            # Check if parse_academic_education was called
            mock_parser_instance.parse_academic_education.assert_called_once()

            # Check if create_academic_education was called on controller
            assert mock_edu_ctrl_instance.create_academic_education.call_count == 1
            call_args = mock_edu_ctrl_instance.create_academic_education.call_args[1]

            assert call_args["researcher_id"] == 123
            assert call_args["title"] == "Ciência da Computação"
            assert call_args["institution_id"] == 1
            assert call_args["start_year"] == 2018
            assert call_args["end_year"] == 2022
