"""Acquisition of the SigPesq project documents (the ``PJ_*.json`` corpus).

Two stages, both talking to external systems:

  1. download  -- Playwright against the SigPesq portal, one PDF per project
  2. extract   -- Mistral (local PDF text first, OCR only when needed) turning
                  each PDF into the structured JSON that ``enrich_projects``
                  consumes from ``data/exports/project_sigpesq_files_json/``

Both stages are RESUMABLE and skip what already exists. That is the whole point:
extraction costs money per document, so a re-run must only pay for what is new.
Pass ``force=True`` to re-extract everything.

This closes a gap called out in ADR-002: the documents used to be produced by an
undocumented manual process outside the repository, which is why they went
missing and the enrichment phase silently processed nothing.
"""

import glob
import json
import os
import time

from loguru import logger

from src.adapters.sources.sigpesq.adapter import (
    _SIGPESQ_429_WAIT_SECONDS,
    _SIGPESQ_MAX_RETRIES,
    SigPesqAdapter,
)

DEFAULT_PDF_ROOT = "data/raw/sigpesq_project_files"
DEFAULT_JSON_DIR = "data/exports/project_sigpesq_files_json"


class SigPesqProjectFilesAdapter(SigPesqAdapter):
    """Downloads the per-project PDFs and extracts them into structured JSON.

    Inherits credential validation and the macOS browser workaround from
    ``SigPesqAdapter``; everything else is specific to the document corpus.
    """

    def __init__(
        self, pdf_root: str = DEFAULT_PDF_ROOT, json_dir: str = DEFAULT_JSON_DIR
    ):
        super().__init__(download_dir=pdf_root)
        self.json_dir = json_dir
        os.makedirs(self.json_dir, exist_ok=True)

    @property
    def pdf_dir(self) -> str:
        """Where the strategy actually drops the files (it appends the subdir)."""
        return os.path.join(self.download_dir, "project_files")

    # ------------------------------------------------------------------ stage 1
    def download_pdfs(self, limit=None) -> dict:
        """Downloads every project PDF, skipping those already on disk.

        Unlike ``SigPesqAdapter.extract``, the download directory is NOT cleaned
        between runs. Clearing it would throw away work the portal rate-limits us
        for re-fetching, and the strategy is resumable by design.
        """
        import asyncio

        from agent_sigpesq.services.reports_service import SigpesqReportService

        from src.adapters.sources.sigpesq.project_files_strategy import (
            build_resilient_strategy,
        )

        self._validate_environment()
        before = self._count_pdfs()
        logger.info(
            "Downloading project PDFs into {} ({} already present)",
            self.pdf_dir,
            before,
        )

        # Resilient discovery instead of the library's fixed id fragment, which
        # stopped matching the portal. See project_files_strategy.py for why.
        strategy = build_resilient_strategy(limit=limit)

        for attempt in range(1, _SIGPESQ_MAX_RETRIES + 1):
            rate_limited = {"seen": False}

            async def run_agent():
                self._patch_browser_factory()
                service = SigpesqReportService(
                    headless=True,
                    download_dir=self.download_dir,
                    strategies=[strategy],
                )
                self._attach_http_429_logging(service, rate_limited)
                return await service.run()

            if asyncio.run(run_agent()):
                break

            if rate_limited["seen"] and attempt < _SIGPESQ_MAX_RETRIES:
                wait = _SIGPESQ_429_WAIT_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "HTTP 429 on attempt {}/{}. Waiting {}s (keeping downloaded "
                    "PDFs — the strategy resumes from them)",
                    attempt,
                    _SIGPESQ_MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
                continue

            # A partial download is still progress: the next run resumes from it.
            logger.warning(
                "Project PDF download reported failure on attempt {}; keeping "
                "whatever landed on disk",
                attempt,
            )
            break

        after = self._count_pdfs()
        stats = {"pdfs_before": before, "pdfs_after": after, "new": after - before}
        # Per-outcome counts: they are what tells "this project has no attachment"
        # apart from "the portal changed and we could not read the page".
        stats["outcomes"] = strategy.summary()
        logger.info("PDF download finished: {}", stats)
        return stats

    # ------------------------------------------------------------------ stage 2
    def extract_json(self, force: bool = False, limit=None) -> dict:
        """Extracts each PDF into ``PJ_<code>.json``, skipping existing ones.

        Skipping is what keeps this affordable: only documents without a JSON
        cost an API call. ``force=True`` re-extracts everything.
        """
        pdfs = sorted(glob.glob(os.path.join(self.pdf_dir, "*.pdf")))
        if limit is not None:
            pdfs = pdfs[:limit]

        stats = {"pdfs": len(pdfs), "extracted": 0, "skipped": 0, "errors": 0}
        if not pdfs:
            logger.warning("No PDFs in {} — run the download stage first", self.pdf_dir)
            return stats

        pending = [
            p
            for p in pdfs
            if force
            or not os.path.exists(
                os.path.join(
                    self.json_dir, os.path.splitext(os.path.basename(p))[0] + ".json"
                )
            )
        ]
        stats["skipped"] = len(pdfs) - len(pending)
        logger.info(
            "{} PDFs | {} already extracted (skipped) | {} to extract",
            len(pdfs),
            stats["skipped"],
            len(pending),
        )
        if not pending:
            return stats

        # Imported only when there is work to do, for two reasons: it pulls the
        # optional [extract] dependencies, and it raises without MISTRAL_KEY. A
        # machine with neither can still run this phase as a no-op.
        try:
            from agent_sigpesq.extraction import ProjectExtractor
        except ImportError as exc:
            from src.adapters.sources.sigpesq.project_files_strategy import (
                MISSING_EXTRACTION_DEPS_HELP,
            )

            logger.error(MISSING_EXTRACTION_DEPS_HELP)
            raise ImportError(MISSING_EXTRACTION_DEPS_HELP) from exc

        extractor = ProjectExtractor()

        for index, pdf in enumerate(pending, 1):
            stem = os.path.splitext(os.path.basename(pdf))[0]
            out_path = os.path.join(self.json_dir, f"{stem}.json")
            try:
                projeto = extractor.extract_project(pdf)
            except Exception as exc:  # one bad PDF must not sink the batch
                logger.warning("[{}/{}] {} FAILED: {}", index, len(pending), stem, exc)
                stats["errors"] += 1
                continue
            data = projeto.model_dump(by_alias=True)
            with open(out_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            stats["extracted"] += 1
            missing = (data.get("_meta") or {}).get("campos_ausentes") or []
            logger.info(
                "[{}/{}] {} -> {}{}",
                index,
                len(pending),
                stem,
                os.path.basename(out_path),
                f" (campos ausentes: {', '.join(missing)})" if missing else "",
            )

        logger.info("Extraction finished: {}", stats)
        return stats

    # ------------------------------------------------------------------ helpers
    def _count_pdfs(self) -> int:
        return len(glob.glob(os.path.join(self.pdf_dir, "*.pdf")))

    def count_documents(self) -> int:
        """How many ``PJ_*.json`` the enrichment phase will find."""
        return len(glob.glob(os.path.join(self.json_dir, "PJ_*.json")))

    # ------------------------------------------------------------------ ISource
    def extract(self, download_strategies: list = None) -> dict:
        """Runs both stages. Signature kept compatible with the parent adapter."""
        stats = {"download": self.download_pdfs(), "extraction": self.extract_json()}
        return stats
