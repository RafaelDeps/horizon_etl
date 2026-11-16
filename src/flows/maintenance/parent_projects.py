"""Recalculates the dates and status of parent research projects (spec 021).

A parent project spans its advisorships. The recalculation used to run at the
end of the SigPesq advisorships phase, so in a rebuild it saw only the SigPesq
advisorships, and the Lattes phases that came after overwrote the parents
again: the result depended on the order of the phases. On a persistent
database, where unchanged documents are skipped, the same inputs then gave
other parent dates than a rebuild. Run once after every source phase, it reads
all advisorships in the database, so a rebuild and an incremental run agree.
"""

from prefect import flow, get_run_logger

from src.core.logic.project_loader import ProjectLoader
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import tracking_recorder


@flow(name="Recalculate Parent Projects", **telegram_flow_state_handlers())
def recalculate_parent_projects_flow() -> None:
    logger = get_run_logger()
    logger.info("Recalculating parent research projects from all advisorships")
    loader = ProjectLoader(mapping_strategy=None)
    with tracking_recorder.run_context(
        source_system="parent_projects", flow_name="recalculate_parent_projects"
    ):
        loader.recalculate_all_parent_statuses()


if __name__ == "__main__":
    recalculate_parent_projects_flow()
