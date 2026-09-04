from unittest.mock import MagicMock, patch

from src.flows.lattes.projects import _resolve_sqlalchemy_engine, ingest_file_task


def test_resolve_sqlalchemy_engine_prefers_bound_session():
    init_ctrl = MagicMock()
    bound_engine = object()
    init_ctrl._service._repository._session.get_bind.return_value = bound_engine

    engine = _resolve_sqlalchemy_engine(init_ctrl)

    assert engine is bound_engine


@patch("src.flows.lattes.projects.resolve_or_create_researcher")
@patch("src.flows.lattes.projects.resolve_researcher_from_lattes")
@patch("src.flows.lattes.projects.load_researcher_index")
@patch("src.flows.lattes.projects.ResearcherController")
@patch("src.flows.lattes.projects.LattesParser")
def test_ingest_file_creates_researcher_when_lattes_match_is_missing(
    MockParser,
    MockResearcherController,
    mock_load_index,
    mock_resolve_from_lattes,
    mock_resolve_or_create,
):
    parser = MockParser.return_value
    parser.parse_personal_info.return_value = {
        "name": "Leonardo Azevedo Scardua",
        "lattes_id": "3651077981942079",
        "citation_names": None,
        "cnpq_url": None,
        "resume": None,
    }
    parser.parse_research_projects.return_value = []
    parser.parse_extension_projects.return_value = []
    parser.parse_development_projects.return_value = []
    parser.parse_articles.return_value = []
    parser.parse_conference_papers.return_value = []
    parser.parse_academic_education.return_value = []

    researcher_ctrl = MockResearcherController.return_value
    researcher_ctrl._service._repository._session = MagicMock()
    # O cadastro é lido uma vez, como índice — não uma vez por currículo.
    mock_load_index.return_value = []

    created_researcher = MagicMock()
    created_researcher.id = 77
    created_researcher.name = "Leonardo Azevedo Scardua"
    mock_resolve_from_lattes.return_value = None
    mock_resolve_or_create.return_value = created_researcher

    entity_manager = MagicMock()

    with (
        patch("builtins.open", new_callable=MagicMock),
        patch("json.load") as mock_json,
    ):
        mock_json.return_value = {"nome": "Leonardo Azevedo Scardua"}

        ingest_file_task.fn(
            "data/lattes_json/10_Leonardo-Azevedo-Scardua_3651077981942079.json",
            entity_manager,
        )

    mock_resolve_or_create.assert_called_once_with(
        researcher_ctrl,
        [],
        name="Leonardo Azevedo Scardua",
    )
    researcher_ctrl.get_all.assert_not_called()
