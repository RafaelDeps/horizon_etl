import glob
import json
import os

from loguru import logger as fallback_logger
from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE
from research_domain.controllers import ResearcherController

from src.adapters.sources.lattes_parser import LattesParser
from src.core.logic.project_loader import ProjectLoader
from src.core.logic.researcher_resolution import resolve_researcher_from_lattes
from src.core.logic.strategies.lattes_advisorships import (
    LattesAdvisorshipMappingStrategy,
)
from src.notifications.telegram import telegram_flow_state_handlers


@task(name="Ingest Lattes Advisorships for File", cache_policy=NO_CACHE)
def ingest_advisorships_file_task(file_path: str, loader: ProjectLoader):
    try:
        logger = get_run_logger()
    except Exception:
        logger = fallback_logger

    filename = os.path.basename(file_path)
    lattes_id = filename.replace(".json", "").split("_")[-1]

    if not lattes_id or not lattes_id.isdigit():
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON {file_path}: {e}")
        return

    # 1. Identify Supervisor (Owner of CV)
    researcher_ctrl = ResearcherController()
    all_researchers = researcher_ctrl.get_all()

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
        all_researchers,
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

    # 2. Parse Advisorships
    parser = LattesParser()
    advisorships = parser.parse_advisorships(data)

    if not advisorships:
        return

    logger.info(f"Processing {len(advisorships)} advisorships for {json_name}...")

    # 3. Ingest with shared loader (avoids re-creating 5 controllers per researcher)
    loader.mapping_strategy = LattesAdvisorshipMappingStrategy(json_name)
    loader.process_records(advisorships, source_file=file_path)


@flow(name="Ingest Lattes Advisorships Flow", **telegram_flow_state_handlers())
def ingest_lattes_advisorships_flow():
    base_dir = "data/lattes_json"
    if not os.path.isabs(base_dir):
        base_dir = os.path.join(os.getcwd(), base_dir)

    json_files = glob.glob(os.path.join(base_dir, "*.json"))

    logger = get_run_logger()
    if not json_files:
        logger.warning(f"No JSON files found in {base_dir}")
        return

    mapping_strategy = LattesAdvisorshipMappingStrategy("")
    loader = ProjectLoader(mapping_strategy=mapping_strategy)

    for json_file in json_files:
        ingest_advisorships_file_task(json_file, loader)


if __name__ == "__main__":
    ingest_lattes_advisorships_flow()
