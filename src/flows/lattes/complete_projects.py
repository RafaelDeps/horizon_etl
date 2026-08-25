from loguru import logger
from prefect import flow

from src.core.logic.step_timer import StepTimer
from src.flows.lattes.download import download_lattes_flow
from src.flows.lattes.projects import ingest_lattes_projects_flow
from src.notifications.telegram import telegram_flow_state_handlers


@flow(name="Lattes Complete Pipeline", **telegram_flow_state_handlers())
def lattes_complete_flow():
    """
    Unified flow that:
    1. Downloads Lattes XML/JSONs using scriptLattes
    2. Ingests the projects (Research, Extension, Development) into the database
    """
    logger.info(">>> Starting Lattes Complete Pipeline")

    timer = StepTimer("Lattes Complete Pipeline (projects)")
    timer.start()

    with timer.track("download_lattes"):
        download_lattes_flow()

    with timer.track("ingest_projects"):
        ingest_lattes_projects_flow()

    logger.info(">>> Lattes Complete Pipeline Finished successfully.")
    timer.summary()


if __name__ == "__main__":
    lattes_complete_flow()
