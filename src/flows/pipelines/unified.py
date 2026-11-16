import os
from typing import Optional

from prefect import flow, get_run_logger

from src.core.logic.etl_flow_reporter import (
    ETLFlowReporter,
    probe_cnpq_sync,
    probe_lattes_advisorships,
    probe_lattes_projects,
    probe_sigpesq_advisorships,
    probe_sigpesq_groups,
    probe_sigpesq_projects,
)
from src.core.logic.prefect_runtime import configure_local_prefect_runtime
from src.flows.cnpq.groups import sync_cnpq_groups_flow
from src.flows.exports.canonical_data import export_canonical_data_flow
from src.flows.exports.initiatives_analytics_mart import (
    export_initiatives_analytics_mart_flow,
)
from src.flows.exports.knowledge_areas_mart import export_knowledge_areas_mart_flow
from src.flows.lattes.advisorships import ingest_lattes_advisorships_flow
from src.flows.lattes.projects import ingest_lattes_projects_flow
from src.flows.maintenance.parent_projects import recalculate_parent_projects_flow
from src.flows.sigpesq.advisorships import persist_advisorships
from src.flows.sigpesq.all import download_all_sigpesq_reports
from src.flows.sigpesq.enrich_projects import enrich_projects_flow
from src.flows.sigpesq.groups import persist_research_groups
from src.flows.sigpesq.projects import persist_projects
from src.notifications.telegram import telegram_flow_state_handlers

configure_local_prefect_runtime()


@flow(name="Horizon Full Pipeline", **telegram_flow_state_handlers())
def full_ingestion_pipeline(
    campus_name: Optional[str] = None,
    output_dir: str = "data/exports",
    generate_etl_report: bool = True,
):
    """
    Orchestrates the complete data pipeline:
    1. SigPesq ingestion
    2. Lattes complete ingestion
    3. CNPq synchronization
    4. Canonical data export
    5. Knowledge Area mart generation
    6. Initiative analytics mart generation
    """
    logger = get_run_logger()
    logger.info("Starting Unified Ingestion Pipeline...")
    reporter = (
        ETLFlowReporter(output_dir="data/reports", run_name="etl_flow_run")
        if generate_etl_report
        else None
    )

    try:
        logger.info("Step 1/8: Downloading all SigPesq reports (single login)...")
        download_all_sigpesq_reports()

        logger.info("Step 2/8: Persisting SigPesq research groups...")
        if reporter:
            reporter.run_step(
                step_name="sigpesq_research_groups",
                runner=persist_research_groups,
                source_probe=probe_sigpesq_groups,
            )
        else:
            persist_research_groups()

        logger.info("Step 3/8: Persisting SigPesq projects...")
        if reporter:
            reporter.run_step(
                step_name="sigpesq_projects",
                runner=persist_projects,
                source_probe=probe_sigpesq_projects,
            )
        else:
            persist_projects()

        logger.info("Step 4/8: Persisting SigPesq advisorships...")
        if reporter:
            reporter.run_step(
                step_name="sigpesq_advisorships",
                runner=persist_advisorships,
                source_probe=probe_sigpesq_advisorships,
            )
        else:
            persist_advisorships()

        logger.info(
            f"Step 5/9: Syncing CNPq groups (Filter: {campus_name or 'None'})..."
        )
        if reporter:
            reporter.run_step(
                step_name="cnpq_sync",
                runner=lambda: sync_cnpq_groups_flow(campus_name=campus_name),
                source_probe=lambda: probe_cnpq_sync(campus_name),
            )
        else:
            sync_cnpq_groups_flow(campus_name=campus_name)

        logger.info("Step 6/9: Ingesting Lattes projects/articles/education...")
        if reporter:
            reporter.run_step(
                step_name="lattes_projects",
                runner=ingest_lattes_projects_flow,
                source_probe=probe_lattes_projects,
            )
        else:
            ingest_lattes_projects_flow()

        logger.info("Step 7/10: Ingesting Lattes advisorships...")
        if reporter:
            reporter.run_step(
                step_name="lattes_advisorships",
                runner=ingest_lattes_advisorships_flow,
                source_probe=probe_lattes_advisorships,
            )
        else:
            ingest_lattes_advisorships_flow()

        # Runs AFTER SigPesq + Lattes project ingestion: it matches PJ document
        # files against initiatives from both sources (by SigPesq code, then
        # title). Must precede the export so enrichment reaches the canonical
        # output. Best-effort: a no-op when no PJ files are present.
        logger.info("Step 8/10: Enriching projects from SigPesq document files...")
        enrich_projects_flow()
        # Parent projects span all their advisorships, so after every source.
        recalculate_parent_projects_flow()

        logger.info(f"Step 9/10: Exporting canonical data to {output_dir}...")
        export_canonical_data_flow(output_dir=output_dir, campus=campus_name)

        ka_mart_path = os.path.join(output_dir, "knowledge_areas_mart.json")
        logger.info(f"Step 10/10: Generating marts at {output_dir}...")
        export_knowledge_areas_mart_flow(output_path=ka_mart_path, campus=campus_name)

        analytics_mart_path = os.path.join(
            output_dir, "initiatives_analytics_mart.json"
        )
        export_initiatives_analytics_mart_flow(output_path=analytics_mart_path)
        logger.info("Unified Ingestion Pipeline completed successfully.")
    finally:
        if reporter:
            json_path, md_path = reporter.write()
            logger.info(
                f"ETL execution report written to {json_path} and {md_path}. "
                "Latest aliases updated in data/reports/etl_flow_run.json and "
                "data/reports/etl_flow_run.md"
            )


if __name__ == "__main__":
    full_ingestion_pipeline()
