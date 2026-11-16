"""lattes_advisorships builds one ProjectLoader per run (spec 015, FR-008)."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from prefect.utilities.annotations import quote

from src.core.logic.strategies.lattes_advisorships import (
    LattesAdvisorshipMappingStrategy,
)
from src.flows.lattes import advisorships as module

SUPERVISORS = {
    "1111111111111111": "Ana Supervisora",
    "2222222222222222": "Bruno Orientador",
    "3333333333333333": "Carla Docente",
}


def _write_cvs(tmp_path):
    cv_dir = tmp_path / "data" / "lattes_json"
    cv_dir.mkdir(parents=True)
    for n, (lattes_id, name) in enumerate(SUPERVISORS.items()):
        path = cv_dir / f"{n}_{name.replace(' ', '-')}_{lattes_id}.json"
        path.write_text(json.dumps({"nome": name}), encoding="utf-8")


def _resolve(index, lattes_id, json_name, session):
    return SimpleNamespace(id=int(lattes_id[0]), name=SUPERVISORS[lattes_id])


_TASK_FN = module.ingest_advisorships_file_task.fn


def _task_body(*args):
    return _TASK_FN(*(a.unquote() if isinstance(a, quote) else a for a in args))


def _patches():
    return (
        patch.object(module, "ProjectLoader"),
        patch.object(module, "load_researcher_index", return_value=[]),
        patch.object(module, "resolve_researcher_from_lattes", side_effect=_resolve),
        patch.object(module, "ResearcherController"),
        patch.object(module, "LattesParser"),
        patch.object(module, "get_run_logger", return_value=MagicMock()),
        patch.object(
            module.tracking_recorder, "run_context", return_value=nullcontext()
        ),
        # Run the task body directly, without the Prefect engine, unwrapping
        # quote()d arguments the way Prefect does before calling the task.
        patch.object(module, "ingest_advisorships_file_task", _task_body),
    )


def test_flow_builds_one_loader_and_swaps_strategy_per_cv(tmp_path, monkeypatch):
    _write_cvs(tmp_path)
    monkeypatch.chdir(tmp_path)
    p_loader, p_index, p_resolve, p_ctrl, p_parser, p_log, p_ctx, p_task = _patches()
    with p_loader as MockLoader, p_index, p_resolve, p_ctrl, p_parser as MockParser:
        with p_log, p_ctx, p_task:
            MockParser.return_value.parse_advisorships.return_value = [{"title": "T"}]
            loader = MockLoader.return_value
            seen = []
            loader.process_records.side_effect = (
                lambda records, source_file: seen.append(loader.mapping_strategy)
            )

            module.ingest_lattes_advisorships_flow.fn()

    assert MockLoader.call_count == 1
    assert loader.process_records.call_count == 3
    assert all(isinstance(s, LattesAdvisorshipMappingStrategy) for s in seen)
    assert sorted(s.advisor_name for s in seen) == sorted(SUPERVISORS.values())
    loader.team_synchronizer.log_lookup_summary.assert_called_once_with(
        "lattes_advisorships"
    )


def test_task_called_alone_builds_its_own_loader(tmp_path, monkeypatch):
    _write_cvs(tmp_path)
    monkeypatch.chdir(tmp_path)
    cv = next((tmp_path / "data" / "lattes_json").glob("*.json"))
    p_loader, _, p_resolve, p_ctrl, p_parser, p_log, _, _ = _patches()
    with p_loader as MockLoader, p_resolve, p_ctrl, p_parser as MockParser, p_log:
        MockParser.return_value.parse_advisorships.return_value = [{"title": "T"}]

        module.ingest_advisorships_file_task.fn(str(cv), [])

    assert MockLoader.call_count == 1
    strategy = MockLoader.call_args.kwargs["mapping_strategy"]
    assert isinstance(strategy, LattesAdvisorshipMappingStrategy)
    MockLoader.return_value.process_records.assert_called_once()


# --- Spec 036: student names ---


def test_an_item_without_a_student_maps_to_no_student_names():
    mapped = LattesAdvisorshipMappingStrategy("Ana Supervisora").map_row(
        {"title": "Iniciação Científica", "student_name": None, "start_year": 2020}
    )

    assert mapped["student_names"] == []
    assert mapped["identity_key"]
    assert mapped["coordinator_name"] == "Ana Supervisora"


def test_the_student_name_summary_reports_every_kind_and_starts_again():
    logger = MagicMock()
    module.log_student_name_summary(MagicMock())  # empty the counts
    module.count_student_names(
        [
            {"student_name_kinds": ("work_title",)},
            {"student_name_kinds": ("link", "several")},
            {"student_name_kinds": ("title", "not_a_name")},
            {"student_name_kinds": ()},
            {"title": "row parsed before branch 036"},
        ]
    )

    line = module.log_student_name_summary(logger)

    assert line == (
        "student names: title 1, link 1, work title 1, footnote 0, "
        "not a name 1, several 1, uncut 0"
    )
    logger.info.assert_called_once_with(line)
    assert module.log_student_name_summary(MagicMock()).endswith("uncut 0")
    assert "work title 0" in module.log_student_name_summary(MagicMock())
