"""Lattes per-CV tasks get their large inputs quoted (spec 016, FR-008).

Prefect walks every task parameter before each call; the researcher index alone
cost ~0.85 s per CV. quote() makes Prefect pass the object through untouched.
"""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from prefect.utilities.annotations import quote

from src.flows.lattes import advisorships as adv_module
from src.flows.lattes import projects as proj_module


def _write_cvs(tmp_path, n=2):
    cv_dir = tmp_path / "data" / "lattes_json"
    cv_dir.mkdir(parents=True)
    for i in range(n):
        lattes_id = str(i + 1) * 16
        (cv_dir / f"{i}_Pessoa-{i}_{lattes_id}.json").write_text(
            json.dumps({"nome": f"Pessoa {i}"}), encoding="utf-8"
        )


def _assert_quoted(value, expected):
    assert isinstance(value, quote)
    assert value.unquote() is expected


def test_projects_flow_quotes_large_task_parameters(tmp_path, monkeypatch):
    _write_cvs(tmp_path)
    monkeypatch.chdir(tmp_path)
    index = [SimpleNamespace(id=1, name="x")]
    with (
        patch.object(proj_module, "ingest_researcher_data") as task,
        patch.object(proj_module, "InitiativeController"),
        patch.object(proj_module, "PersonController"),
        patch.object(proj_module, "EntityManager") as MockEM,
        patch.object(proj_module, "LattesParser") as MockParser,
        patch.object(proj_module, "ResearcherController"),
        patch.object(proj_module, "load_researcher_index", return_value=index),
        patch.object(proj_module, "_resolve_sqlalchemy_engine"),
        patch.object(proj_module, "_expire_lattes_sessions"),
        patch.object(proj_module, "log_researcher_resolution_summary") as res_summary,
        patch.object(
            proj_module.tracking_recorder, "run_context", return_value=nullcontext()
        ),
        patch("src.core.logic.project_loader.ProjectLoader") as MockLoader,
        patch("eo_lib.domain.base.Base.metadata.create_all"),
    ):
        proj_module.ingest_lattes_projects_flow.fn()

    assert task.call_count == 2
    for call in task.call_args_list:
        json_file, entity_manager, parser, researcher_index, loader = call.args
        assert json_file.endswith(".json")
        _assert_quoted(entity_manager, MockEM.return_value)
        _assert_quoted(parser, MockParser.return_value)
        _assert_quoted(researcher_index, index)
        _assert_quoted(loader, MockLoader.return_value)
    MockLoader.return_value.person_matcher.log_match_summary.assert_called_once_with(
        "lattes_projects"
    )
    res_summary.assert_called_once_with("lattes_projects")


def test_advisorships_flow_quotes_large_task_parameters(tmp_path, monkeypatch):
    _write_cvs(tmp_path)
    monkeypatch.chdir(tmp_path)
    index = [SimpleNamespace(id=1, name="x")]
    with (
        patch.object(adv_module, "ingest_advisorships_file_task") as task,
        patch.object(adv_module, "ProjectLoader") as MockLoader,
        patch.object(adv_module, "load_researcher_index", return_value=index),
        patch.object(adv_module, "ResearcherController"),
        patch.object(adv_module, "get_run_logger", return_value=MagicMock()),
        patch.object(adv_module, "log_researcher_resolution_summary") as res_summary,
        patch.object(
            adv_module.tracking_recorder, "run_context", return_value=nullcontext()
        ),
    ):
        adv_module.ingest_lattes_advisorships_flow.fn()

    assert task.call_count == 2
    for call in task.call_args_list:
        json_file, researcher_index, loader = call.args
        assert json_file.endswith(".json")
        _assert_quoted(researcher_index, index)
        _assert_quoted(loader, MockLoader.return_value)
    MockLoader.return_value.person_matcher.log_match_summary.assert_called_once_with(
        "lattes_advisorships"
    )
    res_summary.assert_called_once_with("lattes_advisorships")
