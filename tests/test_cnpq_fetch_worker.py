from unittest.mock import patch

from src.flows.cnpq.fetch_worker import fetch_group


@patch("src.flows.cnpq.fetch_worker.CnpqCrawlerAdapter")
def test_fetch_group_returns_bundle_with_leaders_merged_into_members(mock_adapter_cls):
    adapter = mock_adapter_cls.return_value
    adapter.get_group_data.return_value = {"nome_grupo": "Grupo X"}
    adapter.extract_members.return_value = [
        {"name": "Alice", "role": "Pesquisador", "data_inicio": None, "data_fim": None}
    ]
    adapter.extract_leaders.return_value = ["Bob Leader"]
    adapter.extract_research_lines.return_value = [{"nome_da_linha_de_pesquisa": "IA"}]

    result = fetch_group.fn(
        {"id": 10, "name": "Grupo X", "url": "http://dgp.cnpq.br/x"}
    )

    assert result["success"] is True
    assert result["group_id"] == 10
    assert result["group_name"] == "Grupo X"
    assert result["url"] == "http://dgp.cnpq.br/x"
    assert result["data"] == {"nome_grupo": "Grupo X"}
    assert result["research_lines"] == [{"nome_da_linha_de_pesquisa": "IA"}]

    names_and_roles = [(m["name"], m["role"]) for m in result["members"]]
    assert ("Alice", "Pesquisador") in names_and_roles
    assert ("Bob Leader", "Líder") in names_and_roles
    assert len(result["members"]) == 2


@patch("src.flows.cnpq.fetch_worker.CnpqCrawlerAdapter")
def test_fetch_group_reports_failure_shape_when_portal_returns_nothing(
    mock_adapter_cls,
):
    adapter = mock_adapter_cls.return_value
    adapter.get_group_data.return_value = None

    result = fetch_group.fn(
        {"id": 7, "name": "Grupo Sem Dados", "url": "http://dgp.cnpq.br/nada"}
    )

    assert result == {
        "success": False,
        "group_id": 7,
        "group_name": "Grupo Sem Dados",
        "url": "http://dgp.cnpq.br/nada",
    }
    adapter.extract_members.assert_not_called()
