from prefect import flow, get_run_logger

from src.core.logic.step_timer import StepTimer
from src.flows.lattes.advisorships import ingest_lattes_advisorships_flow
from src.flows.lattes.download import download_lattes_flow
from src.flows.lattes.projects import ingest_lattes_projects_flow
from src.notifications.telegram import telegram_flow_state_handlers


@flow(name="Lattes Complete Pipeline", **telegram_flow_state_handlers())
def lattes_complete_flow():
    """
    Coordinates the full Lattes pipeline:
    1. Downloads Lattes curricula (JSON) using scriptLattes.
    2. Ingests the downloaded JSON data into the database (Projects, Articles).
    3. Ingests Advisorships.
    """
    logger = get_run_logger()
    logger.info("Starting Lattes Complete Pipeline...")

    timer = StepTimer("Lattes Complete Pipeline")
    timer.start()

    with timer.track("download_lattes"):
        download_lattes_flow()

    with timer.track("ingest_projects"):
        ingest_lattes_projects_flow()

    with timer.track("ingest_advisorships"):
        ingest_lattes_advisorships_flow()

    logger.info("Lattes Complete Pipeline finished successfully.")
    timer.summary()


if __name__ == "__main__":
    lattes_complete_flow()
