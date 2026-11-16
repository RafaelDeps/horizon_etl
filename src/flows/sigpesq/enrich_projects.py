from dotenv import load_dotenv
from prefect import flow, get_run_logger

from src.adapters.database.field_claim_store import (
    SqliteFieldClaimStore,
    SqliteFieldWriter,
)
from src.core.logic.field_merge import FieldMergeApplier, FieldMergeStats
from src.core.logic.project_enrichment import ProjectEnrichmentLoader
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import tracking_recorder

load_dotenv()

DEFAULT_PJ_DIR = "data/exports/project_sigpesq_files_json"


@flow(name="Enrich SigPesq Projects", **telegram_flow_state_handlers())
def enrich_projects_flow(
    pj_dir: str = DEFAULT_PJ_DIR,
    overwrite: bool = False,
    dry_run: bool = False,
    ingest_new: bool = True,
) -> dict:
    """
    Enriches Research Project initiatives with content extracted from the SigPesq
    project document files (``PJ_*.json``).

    Fills empty descriptions and stores the richer document fields (objectives,
    schedule, research line, keywords) in ``initiatives.enrichment_json``.

    ``ingest_new`` (default True): rich documents that match no existing
    initiative are created as new Research Projects, flagged ``needs_review`` in
    their enrichment payload. This is idempotent — on later runs those documents
    match by title and are not recreated — so the automated pipeline reproduces
    the same set instead of relying on a manual one-off run.
    """
    logger = get_run_logger()
    logger.info("Initializing SigPesq Project Enrichment Flow")

    loader = ProjectEnrichmentLoader(overwrite=overwrite, dry_run=dry_run)
    if not dry_run:
        # Branch 030: the PDF description is ranked with the other documents'.
        store = SqliteFieldClaimStore(lambda: loader._session)
        loader.field_merge = FieldMergeApplier(
            store, SqliteFieldWriter(lambda: loader._session), FieldMergeStats()
        )

    if dry_run:
        stats = loader.run(pj_dir, ingest_new=ingest_new)
    else:
        with tracking_recorder.run_context(
            source_system=ProjectEnrichmentLoader.SOURCE_SYSTEM,
            flow_name="Enrich SigPesq Projects",
        ):
            stats = loader.run(pj_dir, ingest_new=ingest_new)

    if loader.field_merge is not None:
        loader.field_merge.stats.log(ProjectEnrichmentLoader.SOURCE_SYSTEM)
    logger.info(f"Enrichment finished: {stats}")
    return stats


if __name__ == "__main__":
    enrich_projects_flow()
