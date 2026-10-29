from typing import Optional

from dotenv import load_dotenv
from prefect import flow, get_run_logger, task

from src.adapters.sources.sigpesq.adapter import SigPesqAdapter
from src.core.logic.research_group_loader import ResearchGroupLoader
from src.core.logic.strategies.sigpesq_excel import (
    SigPesqCampusStrategy,
    SigPesqExcelMappingStrategy,
    SigPesqKnowledgeAreaStrategy,
    SigPesqOrganizationStrategy,
    SigPesqResearcherStrategy,
    SigPesqRoleStrategy,
)
from src.flows.document_phase import document_phase, finish_report_listing
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import tracking_recorder

load_dotenv()


@task
def persist_research_groups():
    """
    Finds the latest Research Group Excel file and loads it into the database.
    """
    logger = get_run_logger()
    import glob
    import os

    # Find latest file
    files = glob.glob("data/raw/sigpesq/research_group/*.xlsx")
    if not files:
        logger.warning("No Research Group Excel files found.")
        return

    # Sort by mtime
    latest_file = max(files, key=os.path.getmtime)
    logger.info(f"Loading Research Groups from {latest_file}")

    # Each report row is one source document (spec 021); the phase is opened
    # before the loader so its controllers bind to the shared connection.
    with document_phase("sigpesq_group") as skip:
        loader = ResearchGroupLoader(
            mapping_strategy=SigPesqExcelMappingStrategy(),
            org_strategy=SigPesqOrganizationStrategy(),
            campus_strategy=SigPesqCampusStrategy(),
            area_strategy=SigPesqKnowledgeAreaStrategy(),
            researcher_strategy=SigPesqResearcherStrategy(),
            role_strategy=SigPesqRoleStrategy(),
        )
        loader.document_skip = skip
        skip.on_rollback = loader.reset_caches
        # A trilha de auditoria mora aqui, e não no orquestrador: assim ela vale
        # igual no `make weekly-flows` (subprocessos), no `make pipeline` e numa
        # execução isolada da fase. O envelope é reentrante, então conviver com o
        # ETLFlowReporter do pipeline unificado não cria run duplicada.
        with tracking_recorder.run_context(
            source_system="sigpesq_research_group",
            flow_name="sigpesq_research_groups",
        ):
            loader.process_file(latest_file)
            finish_report_listing(skip, loader)


@flow(name="Ingest SigPesq Research Groups", **telegram_flow_state_handlers())
def ingest_research_groups_flow() -> None:
    """
    Flow specifically for ingesting Research Groups.
    """
    logger = get_run_logger()
    logger.info("Initializing SigPesq Research Groups Ingestion Flow")

    # Import strategies
    from agent_sigpesq.strategies import ResearchGroupsDownloadStrategy

    adapter = SigPesqAdapter()

    # 1. Extract Only Groups
    logger.info("Extracting Research Groups...")
    # We ignore the returned raw_data for now as the Loader reads from disk
    adapter.extract(download_strategies=[ResearchGroupsDownloadStrategy()])

    # 2. Persist Groups
    persist_research_groups()

    logger.info("Research Groups Ingestion finished successfully.")


if __name__ == "__main__":
    ingest_research_groups_flow()
