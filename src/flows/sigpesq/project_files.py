"""Prefect flow that produces the SigPesq project documents (``PJ_*.json``).

Deliberately NOT part of the weekly pipeline. Downloading hundreds of PDFs and
sending them through an LLM is slow and costs money per document, while project
plans barely change — so this runs on demand (``make extract-project-files``)
when a new batch of projects lands. The weekly pipeline stays a pure consumer:
``enrich_projects`` just reads whatever JSON is on disk.

Both stages skip what already exists, so a re-run only pays for what is new.
"""

from typing import Optional

from dotenv import load_dotenv
from prefect import flow, get_run_logger, task

from src.adapters.sources.sigpesq.project_files import (
    DEFAULT_JSON_DIR,
    DEFAULT_PDF_ROOT,
    SigPesqProjectFilesAdapter,
)
from src.notifications.telegram import telegram_flow_state_handlers

load_dotenv()


@task(name="download_project_pdfs")
def download_project_pdfs_task(adapter: SigPesqProjectFilesAdapter, limit) -> dict:
    return adapter.download_pdfs(limit=limit)


@task(name="extract_project_json")
def extract_project_json_task(
    adapter: SigPesqProjectFilesAdapter, force: bool, limit
) -> dict:
    return adapter.extract_json(force=force, limit=limit)


@flow(name="Extract SigPesq Project Files", **telegram_flow_state_handlers())
def extract_project_files_flow(
    pdf_root: str = DEFAULT_PDF_ROOT,
    json_dir: str = DEFAULT_JSON_DIR,
    limit: Optional[int] = None,
    force: bool = False,
    skip_download: bool = False,
    skip_extract: bool = False,
) -> dict:
    """Downloads the project PDFs and extracts them into structured JSON.

    ``limit`` caps how many projects are processed (useful for a cheap smoke
    test). ``force`` re-extracts documents that already have JSON. ``skip_*``
    let each stage be exercised on its own.
    """
    logger = get_run_logger()
    adapter = SigPesqProjectFilesAdapter(pdf_root=pdf_root, json_dir=json_dir)

    stats = {"download": None, "extraction": None}

    if skip_download:
        logger.info("Download stage skipped by request")
    else:
        stats["download"] = download_project_pdfs_task(adapter, limit)

    if skip_extract:
        logger.info("Extraction stage skipped by request")
    else:
        stats["extraction"] = extract_project_json_task(adapter, force, limit)

    outcomes = (stats.get("download") or {}).get("outcomes")
    if outcomes:
        logger.info(f"Attachment outcomes per project: {outcomes}")
        if outcomes.get("unrecognized"):
            # Loud on purpose: this is the failure mode that used to masquerade
            # as a clean run and kept the phase broken for weeks.
            logger.error(
                f"{outcomes['unrecognized']} project page(s) could not be read — "
                "the portal markup likely changed. This is NOT 'no attachment'."
            )

    total = adapter.count_documents()
    logger.info(f"Project files ready: {total} PJ_*.json in {json_dir}")
    stats["documents_available"] = total
    return stats


if __name__ == "__main__":
    extract_project_files_flow()
