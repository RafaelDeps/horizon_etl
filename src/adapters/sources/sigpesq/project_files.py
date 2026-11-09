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
import zipfile
from typing import Callable, Optional

from loguru import logger

from src.adapters.sources.sigpesq.adapter import (
    _SIGPESQ_429_WAIT_SECONDS,
    _SIGPESQ_MAX_RETRIES,
    SigPesqAdapter,
)
from src.core.logic.extraction_pacing import (
    ExtractionPacingSettings,
    WaitBudget,
    backoff_s,
    extraction_pacing_settings,
    is_rate_limit,
    retry_after_s,
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
    def extract_json(
        self,
        force: bool = False,
        limit=None,
        *,
        settings: Optional[ExtractionPacingSettings] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> dict:
        """Extracts each PDF into ``PJ_<code>.json``, skipping existing ones.

        Skipping is what keeps this affordable: only documents without a JSON
        cost an API call. Before paying, each pending document is looked up in
        the previous run's ``exports_canonical.zip`` (living next to the
        corpus): an archived copy is restored locally instead of re-extracting.
        ``force=True`` re-extracts everything, bypassing both the local skip
        and the archive reuse.

        Spec 031: the calls are paced, and a document refused by the service's
        rate limit (HTTP 429) is tried again after a growing wait, within a
        wait budget for the whole stage (``settings``, read from the
        environment when ``None``). ``sleep`` and ``clock`` are test seams.
        """
        pdfs = sorted(glob.glob(os.path.join(self.pdf_dir, "*.pdf")))
        if limit is not None:
            pdfs = pdfs[:limit]

        stats = {
            "pdfs": len(pdfs),
            "present": 0,
            "skipped": 0,  # same as "present", kept for older readers
            "reused": 0,
            "to_extract": 0,
            "extracted": 0,
            "recovered": 0,
            "retried": 0,
            "retries": 0,
            "failed_rate_limit": 0,
            "failed_other": 0,
            "errors": 0,
            "left": 0,
            "waited_s": 0.0,
        }
        self.pacing_settings = None
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
        stats["present"] = stats["skipped"] = len(pdfs) - len(pending)
        logger.info(
            "{} PDFs | {} already present | {} pending",
            len(pdfs),
            stats["present"],
            len(pending),
        )
        if not pending:
            return stats

        # Reuse pass (feature 013): the previous run's archive may already
        # hold the extracted document. Restoring it costs nothing, so it runs
        # BEFORE the extractor is imported or built — a fully-reused run makes
        # zero extraction calls and never needs the API key.
        still_pending = pending
        if not force:
            archive = self._open_previous_archive()
            if archive is not None:
                try:
                    still_pending = self._reuse_from_archive(archive, pending, stats)
                finally:
                    archive.close()

        stats["to_extract"] = len(still_pending)
        logger.info(
            "{} restored from the archive | {} to extract",
            stats["reused"],
            len(still_pending),
        )
        if not still_pending:
            logger.info("Extraction finished: {}", stats)
            return stats

        # Imported only when there is work to do, for two reasons: it pulls the
        # optional [extract] dependencies, and it raises without MISTRAL_KEY. A
        # machine with neither can still run this phase as a no-op.
        extractor = self._build_extractor()
        settings = settings or extraction_pacing_settings()
        self.pacing_settings = settings

        self._extract_paced(extractor, still_pending, stats, settings, sleep, clock)
        stats["errors"] = stats["failed_rate_limit"] + stats["failed_other"]
        logger.info("Extraction finished: {}", stats)
        return stats

    def _extract_paced(self, extractor, queue, stats, settings, sleep, clock) -> None:
        """Spec 031 (contracts A2-A7): one document after the other, spaced by
        ``pause_s``; a rate limit refusal waits and tries again, other failures
        do not; once the wait budget is spent the rest is left for next run."""
        budget = WaitBudget(settings.wait_budget_s)
        last_end = None
        total = len(queue)
        for index, pdf in enumerate(queue, 1):
            stem = os.path.splitext(os.path.basename(pdf))[0]
            tries = 0
            while True:
                if tries == 0 and last_end is not None and settings.pause_s > 0:
                    gap = settings.pause_s - (clock() - last_end)
                    if gap > 0:
                        sleep(gap)
                tries += 1
                try:
                    projeto = extractor.extract_project(pdf)
                except Exception as exc:  # one bad PDF must not sink the batch
                    last_end = clock()
                    if not is_rate_limit(exc):
                        logger.warning("[{}/{}] {} FAILED: {}", index, total, stem, exc)
                        stats["failed_other"] += 1
                        break
                    if tries > settings.retries:
                        logger.warning("[{}/{}] {} FAILED: {}", index, total, stem, exc)
                        stats["failed_rate_limit"] += 1
                        break
                    wait = backoff_s(tries, settings, retry_after_s(exc))
                    if not budget.allows(wait):
                        logger.warning("[{}/{}] {} FAILED: {}", index, total, stem, exc)
                        stats["failed_rate_limit"] += 1
                        stats["left"] = total - index
                        logger.warning(
                            "Wait budget of {:g} min used up; {} PDF(s) left for "
                            "the next run",
                            settings.wait_budget_s / 60,
                            stats["left"],
                        )
                        return
                    if tries == 1:
                        stats["retried"] += 1
                    stats["retries"] += 1
                    logger.warning(
                        "[{}/{}] {} rate limited (try {}/{}); waiting {:g} s",
                        index,
                        total,
                        stem,
                        tries,
                        settings.retries + 1,
                        wait,
                    )
                    budget.spend(wait)
                    stats["waited_s"] += wait
                    sleep(wait)
                    continue
                last_end = clock()
                self._write_document(projeto, stem, index, total, tries, stats)
                break

    def _write_document(self, projeto, stem, index, total, tries, stats) -> None:
        out_path = os.path.join(self.json_dir, f"{stem}.json")
        data = projeto.model_dump(by_alias=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        stats["extracted"] += 1
        if tries > 1:
            stats["recovered"] += 1
        missing = (data.get("_meta") or {}).get("campos_ausentes") or []
        logger.info(
            "[{}/{}] {} -> {}{}{}",
            index,
            total,
            stem,
            os.path.basename(out_path),
            f" (after {tries} tries)" if tries > 1 else "",
            f" (campos ausentes: {', '.join(missing)})" if missing else "",
        )

    # --------------------------------------------------- archive reuse helpers
    def _open_previous_archive(self):
        """Opens ``exports_canonical.zip`` from the export folder, if readable.

        The archive lives next to the corpus (it is written by
        ``zip_exports_task`` into the same ``OUTPUT_DIR``). Any doubt — absent,
        stale-corrupt, unreadable — degrades to normal extraction.
        """
        archive_path = os.path.join(
            os.path.dirname(self.json_dir), "exports_canonical.zip"
        )
        if not os.path.exists(archive_path):
            return None
        try:
            return zipfile.ZipFile(archive_path)
        except (zipfile.BadZipFile, OSError) as exc:
            logger.warning(
                "Export archive unreadable ({}); extracting all pending documents",
                exc,
            )
            return None

    def _reuse_from_archive(self, archive, pending, stats):
        """Restores archived documents for pending stems; returns the rest.

        Matching is exactly ``project_sigpesq_files_json/<stem>.json`` — the
        same folder the zip ships and the same stem the pipeline uses. A
        malformed archived copy is not trusted: that PDF falls back to a real
        extraction.
        """
        by_name = {
            os.path.basename(name): name
            for name in archive.namelist()
            if os.path.dirname(name) == "project_sigpesq_files_json"
        }
        still_pending = []
        for pdf in pending:
            stem = os.path.splitext(os.path.basename(pdf))[0]
            entry = by_name.get(f"{stem}.json")
            if entry is None:
                still_pending.append(pdf)
                continue
            try:
                document = json.loads(archive.read(entry))
            except (ValueError, zipfile.BadZipFile) as exc:
                logger.warning(
                    "Archived document {} unusable ({}); extracting instead",
                    entry,
                    exc,
                )
                still_pending.append(pdf)
                continue
            out_path = os.path.join(self.json_dir, f"{stem}.json")
            with open(out_path, "w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2)
            stats["reused"] += 1
            logger.info("Reused archived document for {} (no extraction call)", stem)
        if stats["reused"]:
            logger.info(
                "{} documents restored from the export archive",
                stats["reused"],
            )
        return still_pending

    def _build_extractor(self):
        """Builds the Mistral-backed extractor, with actionable import errors."""
        try:
            from agent_sigpesq.extraction import ProjectExtractor
        except ImportError as exc:
            from src.adapters.sources.sigpesq.project_files_strategy import (
                MISSING_EXTRACTION_DEPS_HELP,
            )

            logger.error(MISSING_EXTRACTION_DEPS_HELP)
            raise ImportError(MISSING_EXTRACTION_DEPS_HELP) from exc

        # Defensive: patch finalize so 'financiamento.moeda: None' doesn't fail Pydantic
        if hasattr(ProjectExtractor, "finalize"):
            orig_finalize = ProjectExtractor.finalize

            def _safe_finalize(this, codigo, raw, arquivo, num_pages, source):
                fin = raw.get("financiamento")
                if isinstance(fin, dict) and not fin.get("moeda"):
                    fin["moeda"] = "BRL"
                return orig_finalize(this, codigo, raw, arquivo, num_pages, source)

            ProjectExtractor.finalize = _safe_finalize

        chat_model = os.getenv("MISTRAL_CHAT_MODEL", "ministral-8b-latest")
        try:
            return ProjectExtractor(chat_model=chat_model)
        except TypeError:
            return ProjectExtractor()

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
