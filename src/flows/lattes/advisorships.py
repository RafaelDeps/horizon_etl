import glob
import json
import os
import time
from typing import List, Optional

from loguru import logger as fallback_logger
from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE
from prefect.utilities.annotations import quote
from research_domain.controllers import ResearcherController

from src.adapters.sources.lattes_parser import LattesParser
from src.core.logic.horizon_identity import (
    dedupe_same_document,
    join_normalized,
    lattes_id_from_cv_path,
)
from src.core.logic.document_skip import carry
from src.core.logic.project_loader import ProjectLoader
from src.core.logic.researcher_resolution import (
    ResearcherRef,
    load_researcher_index,
    log_researcher_resolution_summary,
    resolve_researcher_from_lattes,
)
from src.core.logic.strategies.lattes_advisorships import (
    LattesAdvisorshipMappingStrategy,
)
from src.flows.document_phase import document_phase
from src.flows.lattes.cv_document import finish_lattes_listing, read_cv
from src.flows.lattes.cv_timing import log_cv_duration
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import tracking_recorder


@task(name="Ingest Lattes Advisorships for File", cache_policy=NO_CACHE)
def ingest_advisorships_file_task(
    file_path: str,
    researcher_index: List[ResearcherRef],
    project_loader: Optional[ProjectLoader] = None,
    data: Optional[dict] = None,
):
    try:
        logger = get_run_logger()
    except Exception:
        logger = fallback_logger

    filename = os.path.basename(file_path)
    lattes_id = filename.replace(".json", "").split("_")[-1]

    if not lattes_id or not lattes_id.isdigit():
        return

    if data is None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load JSON {file_path}: {e}")
            return

    # 1. Identify Supervisor (Owner of CV)
    # O índice de correspondência chega pronto do flow: montá-lo aqui custaria
    # 7,8 s por currículo (112 vezes por execução) para reproduzir sempre a
    # mesma lista. O controller permanece apenas como porta de acesso à sessão,
    # usada no desempate por dados já vinculados.
    researcher_ctrl = ResearcherController()

    json_name = (
        data.get("nome")
        or data.get("name")
        or data.get("informacoes_pessoais", {}).get("nome_completo")
    )
    session = None
    try:
        session = researcher_ctrl._service._repository._session
    except Exception:
        pass

    supervisor = resolve_researcher_from_lattes(
        researcher_index,
        lattes_id=lattes_id,
        json_name=json_name,
        session=session,
    )

    if not supervisor:
        logger.debug(
            f"Skipping Advisorships for {lattes_id}: Supervisor not found in DB."
        )
        return

    json_name = getattr(supervisor, "name", "Unknown")
    # The CV's own subject (spec 021): left out of the total-loss count.
    carry("researcher", supervisor.id, is_subject=True)

    # 2. Parse Advisorships
    parser = LattesParser()
    # An advisorship entered twice in the same CV is processed once, always
    # the same version (spec 020, FR-020).
    advisorships, dropped = dedupe_same_document(
        parser.parse_advisorships(data),
        lambda row: join_normalized(
            row.get("title"),
            row.get("student_name"),
            row.get("start_year") or row.get("end_year") or row.get("year"),
            row.get("type"),
            row.get("institution"),
        ),
    )

    if not advisorships:
        return
    if dropped:
        logger.info(f"Dropped {dropped} duplicate advisorships for {lattes_id}")

    logger.info(f"Processing {len(advisorships)} advisorships for {json_name}...")

    # 3. Ingest with Strategy & ProjectLoader. The flow passes one loader for
    # the whole phase (its initiative/person caches and team lookup are built
    # once); only the per-supervisor strategy changes between CVs, as in
    # lattes/projects.py. Standalone callers still get a loader of their own.
    mapping_strategy = LattesAdvisorshipMappingStrategy(json_name)
    if project_loader is None:
        project_loader = ProjectLoader(mapping_strategy=mapping_strategy)
    else:
        project_loader.mapping_strategy = mapping_strategy

    project_loader.process_records(advisorships, source_file=file_path)


@flow(name="Ingest Lattes Advisorships Flow", **telegram_flow_state_handlers())
def ingest_lattes_advisorships_flow():
    base_dir = "data/lattes_json"
    if not os.path.isabs(base_dir):
        base_dir = os.path.join(os.getcwd(), base_dir)

    # Sorted: person resolution depends on who already exists, so the order
    # must not depend on the filesystem (spec 020, FR-002).
    json_files = sorted(glob.glob(os.path.join(base_dir, "*.json")))

    logger = get_run_logger()
    if not json_files:
        logger.warning(f"No JSON files found in {base_dir}")
        return

    # Opened before any controller: their sessions must bind to the shared
    # connection of the document transactions (spec 021).
    with document_phase("lattes_advisorships") as skip:
        _ingest_lattes_advisorships(json_files, skip, logger)


def _ingest_lattes_advisorships(json_files: List[str], skip, logger) -> None:
    # Uma leitura do cadastro por execução da fase, não por currículo.
    session = None
    try:
        session = ResearcherController()._service._repository._session
    except Exception:
        logger.warning("Could not reach the DB session; researcher index is empty.")
    researcher_index = load_researcher_index(session)
    logger.info(f"Researcher index loaded with {len(researcher_index)} entries")

    # Um loader por fase: montá-lo por currículo recarregava todas as
    # iniciativas e pessoas a cada um dos ~435 CVs (spec 015).
    project_loader = ProjectLoader(mapping_strategy=None)
    # One net change log for the whole phase (spec 020): an advisorship listed
    # in several CVs is logged once, by its real difference.
    project_loader.defer_change_log = True

    def reload_caches():
        # A rolled-back CV may have created rows the indexes still point at.
        researcher_index[:] = load_researcher_index(session)
        project_loader.reset_caches()

    skip.on_rollback = reload_caches

    with tracking_recorder.run_context(
        source_system="lattes_advisorships", flow_name="lattes_advisorships"
    ):
        for position, json_file in enumerate(json_files, start=1):
            started = time.perf_counter()
            key = lattes_id_from_cv_path(json_file) or os.path.basename(json_file)
            with skip.document(key) as doc:
                data = read_cv(json_file)
                if doc.unchanged(data):
                    continue
                doc.begin()
                ingest_advisorships_file_task(
                    json_file,
                    quote(researcher_index),
                    quote(project_loader),
                    quote(data),
                )
            log_cv_duration(
                "lattes_advisorships", position, len(json_files), json_file, started
            )
        project_loader.flush_change_log()
        finish_lattes_listing(skip, json_files)
    project_loader.team_synchronizer.log_lookup_summary("lattes_advisorships")
    project_loader.person_matcher.log_match_summary("lattes_advisorships")
    log_researcher_resolution_summary("lattes_advisorships")


if __name__ == "__main__":
    ingest_lattes_advisorships_flow()
