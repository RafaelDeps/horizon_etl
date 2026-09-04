import json
from pathlib import Path
from typing import Optional

from prefect import flow, get_run_logger

from src.core.logic.etl_flow_reporter import ETLFlowReporter
from src.flows.all import ingest_all_sources_flow
from src.flows.exports.canonical_data import export_canonical_data_flow
from src.flows.exports.initiatives_analytics_mart import (
    export_initiatives_analytics_mart_flow,
)
from src.flows.exports.knowledge_areas_mart import export_knowledge_areas_mart_flow
from src.flows.exports.people_relationship_graph import (
    export_people_relationship_graph_flow,
)
from src.notifications.telegram import (
    send_telegram_etl_report_summary,
    telegram_flow_state_handlers,
)
from src.scripts.consolidate_duplicates import run_person_dedup


def load_etl_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@flow(name="Horizon Weekly Pipelines", **telegram_flow_state_handlers())
def weekly_pipelines_flow(
    campus_name: Optional[str] = None,
    output_dir: str = "data/exports",
) -> None:
    campus_name = campus_name or None
    logger = get_run_logger()
    logger.info(
        "Starting weekly Horizon pipelines with campus filter: %s",
        campus_name or "all",
    )

    reporter = ETLFlowReporter(
        output_dir="data/reports",
        run_name="weekly_pipeline_run",
    )
    report_json_path = None

    try:
        reporter.run_step(
            step_name="all_sources",
            runner=lambda: ingest_all_sources_flow(campus_name=campus_name),
        )
        reporter.run_step(
            step_name="consolidate_duplicates",
            runner=lambda: run_person_dedup(),
        )
        reporter.run_step(
            step_name="export_canonical",
            runner=lambda: export_canonical_data_flow(
                output_dir=output_dir,
                campus=campus_name,
            ),
        )
        reporter.run_step(
            step_name="knowledge_areas_mart",
            runner=lambda: export_knowledge_areas_mart_flow(
                output_path=str(Path(output_dir) / "knowledge_areas_mart.json"),
                campus=campus_name,
            ),
        )
        reporter.run_step(
            step_name="initiatives_analytics_mart",
            runner=lambda: export_initiatives_analytics_mart_flow(
                output_path=str(Path(output_dir) / "initiatives_analytics_mart.json")
            ),
        )
        reporter.run_step(
            step_name="people_relationship_graph",
            runner=lambda: export_people_relationship_graph_flow(output_dir=output_dir),
        )
    finally:
        report_json_path, report_md_path = reporter.write()
        logger.info(
            "Weekly pipeline report written to %s and %s.",
            report_json_path,
            report_md_path,
        )
        report = load_etl_report(report_json_path)
        report["report_path"] = str(report_json_path)
        send_telegram_etl_report_summary(report)

    logger.info("Weekly Horizon pipelines finished successfully.")


if __name__ == "__main__":
    weekly_pipelines_flow()
