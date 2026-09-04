from pathlib import Path
from unittest.mock import MagicMock, patch


def test_weekly_pipeline_flow_runs_all_pipelines_and_sends_final_summary(tmp_path):
    from src.flows.pipelines.weekly import weekly_pipelines_flow

    executed_steps = []
    written_report = {
        "run_name": "weekly_pipeline_run",
        "steps": [],
        "final_tables": {},
        "final_duplicates": {},
    }

    class FakeReporter:
        def __init__(self, *, output_dir, run_name):
            assert output_dir == "data/reports"
            assert run_name == "weekly_pipeline_run"

        def run_step(self, *, step_name, runner, source_probe=None):
            assert source_probe is None
            executed_steps.append(step_name)
            return runner()

        def write(self):
            return tmp_path / "report.json", tmp_path / "report.md"

    with (
        patch("src.flows.pipelines.weekly.get_run_logger", return_value=MagicMock()),
        patch("src.flows.pipelines.weekly.ETLFlowReporter", FakeReporter),
        patch(
            "src.flows.pipelines.weekly.load_etl_report", return_value=written_report
        ),
        patch("src.flows.pipelines.weekly.send_telegram_etl_report_summary") as summary,
        patch("src.flows.pipelines.weekly.ingest_all_sources_flow") as all_sources,
        patch("src.flows.pipelines.weekly.run_person_dedup") as dedup,
        patch("src.flows.pipelines.weekly.export_canonical_data_flow") as canonical,
        patch("src.flows.pipelines.weekly.export_knowledge_areas_mart_flow") as ka_mart,
        patch(
            "src.flows.pipelines.weekly.export_initiatives_analytics_mart_flow"
        ) as analytics_mart,
        patch(
            "src.flows.pipelines.weekly.export_people_relationship_graph_flow"
        ) as graph,
    ):
        weekly_pipelines_flow.fn(campus_name="Serra", output_dir="out")

    assert executed_steps == [
        "all_sources",
        "consolidate_duplicates",
        "export_canonical",
        "knowledge_areas_mart",
        "initiatives_analytics_mart",
        "people_relationship_graph",
    ]
    all_sources.assert_called_once_with(campus_name="Serra")
    dedup.assert_called_once_with()
    canonical.assert_called_once_with(output_dir="out", campus="Serra")
    ka_mart.assert_called_once_with(
        output_path=str(Path("out") / "knowledge_areas_mart.json"), campus="Serra"
    )
    analytics_mart.assert_called_once_with(
        output_path=str(Path("out") / "initiatives_analytics_mart.json")
    )
    graph.assert_called_once_with(output_dir="out")
    summary.assert_called_once_with(written_report)
