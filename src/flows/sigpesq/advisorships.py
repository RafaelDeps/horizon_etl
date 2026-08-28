import glob
import os

from dotenv import load_dotenv
from prefect import flow, get_run_logger, task

from src.adapters.sources.sigpesq.adapter import SigPesqAdapter
from src.core.logic.project_loader import ProjectLoader
from src.core.logic.strategies.sigpesq_advisorships import (
    SigPesqAdvisorshipMappingStrategy,
)
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import tracking_recorder

load_dotenv()


@task
def persist_advisorships():
    """
    Finds the latest Advisorships Excel file and loads it into the database.
    """
    logger = get_run_logger()

    # SigPesqAdapter typically downloads to data/raw/sigpesq/
    # The AdvisorshipsDownloadStrategy might save to a specific subfolder.
    # Looking at SigPesqFileLoader.load_files logic would help,
    # but we follow the pattern in ingest_sigpesq_projects.py

    files = glob.glob("data/raw/sigpesq/advisorships/**/*.xlsx", recursive=True)
    if not files:
        # Try generic sigpesq folder if specific one doesn't exist
        files = glob.glob("data/raw/sigpesq/*.xlsx")

    if not files:
        logger.warning("No Advisorship Excel files found.")
        return

    # Sort by mtime (optional, but good for logs)
    files.sort(key=os.path.getmtime)

    loader = ProjectLoader(mapping_strategy=SigPesqAdvisorshipMappingStrategy())

    # Ensure "Advisorship" initiative type exists once
    existing_types = loader.controller.list_initiative_types()
    raw_type = next(
        (
            t
            for t in existing_types
            if (t.get("name") if isinstance(t, dict) else getattr(t, "name", ""))
            == "Advisorship"
        ),
        None,
    )

    if not raw_type:
        logger.info("Creating 'Advisorship' initiative type...")
        raw_type = loader.controller.create_initiative_type(
            name="Advisorship", description="Bolsas e Orientações importadas do SigPesq"
        )

    # Wrap in object if it's a dict (ProjectLoader expects .id)
    if isinstance(raw_type, dict):

        class Obj:
            pass

        loader.initiative_type = Obj()
        loader.initiative_type.id = raw_type.get("id")
        loader.initiative_type.name = raw_type.get("name")
    else:
        loader.initiative_type = raw_type

    with tracking_recorder.run_context(
        source_system="sigpesq_advisorships",
        flow_name="sigpesq_advisorships",
    ):
        for file_path in files:
            logger.info(f"Loading Advisorships from {file_path}")
            loader.process_file(file_path)

        # Final pass: Recalculate parent project dates and status from DB
        loader.recalculate_all_parent_statuses()


@flow(name="Ingest SigPesq Advisorships", **telegram_flow_state_handlers())
def ingest_advisorships_flow() -> None:
    """
    Prefect flow for ingesting Advisorships (Bolsistas) from SigPesq.
    """
    logger = get_run_logger()
    logger.info("Initializing SigPesq Advisorships Ingestion Flow")

    from agent_sigpesq.strategies import AdvisorshipsDownloadStrategy

    adapter = SigPesqAdapter()

    # 1. Extract Advisorships
    logger.info("Extracting Advisorships...")
    adapter.extract(download_strategies=[AdvisorshipsDownloadStrategy()])

    # 2. Persist Advisorships
    persist_advisorships()

    logger.info("Advisorships Ingestion finished successfully.")


if __name__ == "__main__":
    ingest_advisorships_flow()
