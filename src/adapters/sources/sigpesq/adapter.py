import asyncio
import os
import shutil
import time
from typing import Any, Dict, List

from loguru import logger

_SIGPESQ_429_WAIT_SECONDS = int(os.getenv("SIGPESQ_429_WAIT_SECONDS", "60"))
_SIGPESQ_MAX_RETRIES = int(os.getenv("SIGPESQ_MAX_RETRIES", "3"))

from src.core.logic.loaders import SigPesqFileLoader
from src.core.ports.source import ISource


class SigPesqAdapter(ISource):
    def __init__(self, download_dir: str = "data/raw/sigpesq"):
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def extract(self, download_strategies: list = None) -> List[Dict[str, Any]]:
        """
        Orchestrates the extraction:
        1. Validate environment (credentials).
        2. Trigger sigpesq_agent to download files.
        3. Read downloaded files from 'report' folder.
        """
        logger.info("Starting SigPesq extraction adapter...")

        self._validate_environment()

        # Step 1: Download
        self._clean_download_dir()
        self._trigger_download(download_strategies)

        # Step 2: Read
        loader = SigPesqFileLoader(self.download_dir)
        raw_data = loader.load_files()

        logger.info(f"Extraction finished. {len(raw_data)} items loaded.")
        return raw_data

    def _validate_environment(self):
        """
        Ensures necessary environment variables are set for sigpesq_agent.
        """
        # Support SIGPESQ_USER as alias for SIGPESQ_USERNAME and vice-versa
        if os.getenv("SIGPESQ_USER") and not os.getenv("SIGPESQ_USERNAME"):
            os.environ["SIGPESQ_USERNAME"] = os.getenv("SIGPESQ_USER")

        if os.getenv("SIGPESQ_USERNAME") and not os.getenv("SIGPESQ_USER"):
            os.environ["SIGPESQ_USER"] = os.getenv("SIGPESQ_USERNAME")

        required_vars = ["SIGPESQ_USERNAME", "SIGPESQ_PASSWORD"]
        missing = [v for v in required_vars if not os.getenv(v)]

        if missing:
            logger.error(
                f"Missing environment variables for SigPesq: {', '.join(missing)}"
            )
            # Try to be helpful if they used the wrong one
            if "SIGPESQ_USERNAME" in missing and os.getenv("SIGPESQ_USER"):
                logger.info("Found SIGPESQ_USER, mapped to SIGPESQ_USERNAME.")
            else:
                raise EnvironmentError(f"SigPesq Agent requires: {', '.join(missing)}")

        logger.debug("Environment variables for SigPesq verified.")

    def _clean_download_dir(self):
        """
        Removes stale SigPesq files before starting a new download batch.
        """
        os.makedirs(self.download_dir, exist_ok=True)
        for entry in os.scandir(self.download_dir):
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
        logger.info(f"Cleaned SigPesq download directory: {self.download_dir}")

    def _trigger_download(self, download_strategies: list = None):
        """
        Calls the external lib to download files.
        Retries up to _SIGPESQ_MAX_RETRIES times with exponential backoff when
        the download does not succeed. A failed login (HTTP 429 rate-limit OR a
        Page.goto timeout — RNP portal is intermittently slow from GitHub-hosted
        runners) previously aborted after a single attempt; the same transient
        slowness is often cleared by a later retry.
        """
        logger.info(f"Triggering sigpesq_agent in {self.download_dir}...")

        from agent_sigpesq.services.reports_service import SigpesqReportService
        from agent_sigpesq.strategies import ResearchGroupsDownloadStrategy

        strategies = (
            download_strategies
            if download_strategies
            else [ResearchGroupsDownloadStrategy()]
        )

        for attempt in range(1, _SIGPESQ_MAX_RETRIES + 1):
            rate_limited = {"seen": False}

            async def run_agent():
                self._patch_browser_factory()
                service = SigpesqReportService(
                    headless=True,
                    download_dir=self.download_dir,
                    strategies=strategies,
                )
                self._attach_http_429_logging(service, rate_limited)
                return await service.run()

            success = asyncio.run(run_agent())

            if success:
                return

            if attempt < _SIGPESQ_MAX_RETRIES:
                if rate_limited["seen"]:
                    wait = _SIGPESQ_429_WAIT_SECONDS * (2 ** (attempt - 1))
                    reason = f"HTTP 429 rate-limiting on attempt {attempt}/{_SIGPESQ_MAX_RETRIES}"
                else:
                    # Non-429 failure (e.g. Page.goto TimeoutError on login).
                    # RNP portal is intermittently slow from hosted runners; use
                    # a shorter wait and still allow the download to retry.
                    wait = min(5 * (2 ** (attempt - 1)), 60)
                    reason = (
                        f"Non-429 failure on attempt {attempt}/{_SIGPESQ_MAX_RETRIES}"
                    )
                logger.warning("{}. Waiting {}s before retry...", reason, wait)
                time.sleep(wait)
                self._clean_download_dir()
                continue

            # Non-429 failure or last attempt
            if os.path.exists(os.path.join(self.download_dir, "research_group")):
                logger.warning(
                    "SigpesqReportService failed to download all reports, but proceeding with existing files."
                )
                return
            raise RuntimeError(
                f"SigpesqReportService failed after {attempt} attempt(s). No fallback data found."
            )

    def _patch_browser_factory(self):
        """
        On macOS --disable-gpu blocks JS rendering and breaks login.
        On Linux (including Docker) the original BrowserFactory args are correct.
        Only apply the simplified launch on macOS.
        """
        import sys

        if sys.platform != "darwin":
            return
        try:
            from agent_sigpesq.core import browser_factory as _bf_mod
            from playwright.async_api import Playwright

            async def _safe_create_browser_context(
                playwright: Playwright, headless: bool = True
            ):
                browser = await playwright.chromium.launch(headless=headless)
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                return context

            _bf_mod.BrowserFactory.create_browser_context = staticmethod(
                _safe_create_browser_context
            )
        except Exception as exc:
            logger.warning(f"Could not patch BrowserFactory: {exc}")

    def _attach_http_429_logging(self, service, rate_limited: dict | None = None):
        """
        Wraps the agent login to detect HTTP 429 and signal callers via rate_limited dict.
        """
        original_login = getattr(service, "_login", None)
        if original_login is None:
            return

        async def login_with_http_429_logging(page):
            def log_rate_limit_response(response):
                if getattr(response, "status", None) != 429:
                    return
                if rate_limited is not None:
                    rate_limited["seen"] = True
                url = getattr(response, "url", "unknown URL")
                logger.error(
                    "SigPesq portal returned HTTP 429 while logging in at "
                    f"{url}. Rate limiting detected — will retry with backoff."
                )

            page.on("response", log_rate_limit_response)
            try:
                return await original_login(page)
            finally:
                page.remove_listener("response", log_rate_limit_response)

        service._login = login_with_http_429_logging
