"""Resilient discovery of the "Arquivos" attachment inside a SigPesq project modal.

WHY THIS EXISTS
---------------
``agent_sigpesq``'s ProjectFilesDownloadStrategy finds the attachment by a fixed
id fragment (``rptArquivo_Download``). That fragment no longer exists on the
portal: a document-wide search with the modal open found nothing, in five
projects, and waiting did not change it. The phase therefore reported every
project as "no files (likely a draft)" and downloaded nothing -- while claiming
success.

The library cannot be patched: it lives in another repository and is installed
from requirements.txt, so any local edit would be lost on reinstall and would not
reproduce for anyone cloning this project. So the adaptation lives here, as a
subclass. Login, navigation, grid pagination and resume-from-disk stay with the
library; only the "find the attachment in this modal" step is replaced.

TWO INDEPENDENT SIGNALS
-----------------------
A control is a candidate when EITHER its id carries a download-ish verb, OR its
visible text ends in a document extension. The first survives a container rename
(ASP.NET tends to keep the verb in the control name); the second survives a total
rename, because the file name is what the user reads.

TELLING "EMPTY" FROM "UNREADABLE"
---------------------------------
The defect stayed invisible for weeks because "this project has no attachment"
and "I could not recognise the attachments area" produced the same message. They
are now separate outcomes: if no candidate is found, we look for an attachments
area at all. Area present and empty -> the project genuinely has none. No area
-> the page changed and we say so, loudly.
"""

from typing import Optional

from loguru import logger

# Outcome labels. Kept as plain strings so they travel through logs and stats
# without any import of this module.
DOWNLOADED = "downloaded"
SKIPPED_EXISTING = "skipped_existing"
NO_ATTACHMENT = "no_attachment"
UNRECOGNIZED = "unrecognized"
MODAL_FAILED = "modal_failed"

OUTCOMES = (DOWNLOADED, SKIPPED_EXISTING, NO_ATTACHMENT, UNRECOGNIZED, MODAL_FAILED)

# Runs in the page. Returns the chosen control's id plus the outcome, so the
# Python side never depends on a specific portal id.
_DISCOVER_JS = """(args) => {
  const label = args.label;
  const textOf = (e) => ((e.innerText || e.value || '').trim());
  const DOWNLOADISH = /download|baixar|arquiv/i;
  const DOCEXT = /\\.(pdf|docx?|odt|rtf)$/i;

  // Scope everything to the modal. Searching the whole page is what makes the
  // "is there an attachments area?" question meaningless: a portal menu item or
  // a grid column header called "Arquivos" would answer yes for every project,
  // turning every unreadable page into a false "no attachment".
  // Match on ID ONLY, never className. The close button sits inside a footer
  // whose CLASS says "modal" but which holds nothing -- testing className made
  // the walk stop at level 1 on a 0-character container, so every project came
  // back "unrecognized". The real panel is a few levels up and carries the id.
  let region = null;
  const anchor = args.anchorId ? document.getElementById(args.anchorId) : null;
  if (anchor) {
    let node = anchor;
    for (let i = 0; i < 8 && node.parentElement; i++) {
      node = node.parentElement;
      if (node.id && /modal|dialog|popup/i.test(node.id)) { region = node; break; }
    }
  }
  if (!region) {
    return {outcome: 'unrecognized', id: null, text: null, total: 0,
            by_label: false, scoped: false};
  }

  const candidates = Array.from(
      region.querySelectorAll('a[id], input[type=submit][id], button[id]'))
    .filter(e => DOWNLOADISH.test(e.id) || DOCEXT.test(textOf(e)));

  if (candidates.length === 0) {
    // Attachments area inside the modal? If yes the project simply has none;
    // if no, this modal is not the shape we know how to read.
    const hasArea = Array.from(region.querySelectorAll(
        'h1,h2,h3,h4,h5,h6,table,fieldset,legend,div,span,td,th'))
      .some(e => /arquivos?\\b/i.test((e.innerText || '').slice(0, 120)));
    return {outcome: hasArea ? 'no_attachment' : 'unrecognized',
            id: null, text: null, total: 0, by_label: false, scoped: true};
  }

  const exact = candidates.find(
      e => textOf(e).toLowerCase() === String(label).toLowerCase());
  const chosen = exact || candidates[0];
  return {outcome: 'found', id: chosen.id, text: textOf(chosen),
          total: candidates.length, by_label: !!exact, scoped: true};
}"""


def _build_strategy_class():
    """Builds the subclass lazily so importing this module never needs the lib."""
    from agent_sigpesq.strategies.project_files_strategy import (  # noqa: WPS433
        MODAL_CLOSE,
        RESUMO_BTN,
        ProjectFilesDownloadStrategy,
    )

    class ResilientProjectFilesStrategy(ProjectFilesDownloadStrategy):
        """Same download flow as the library, with attachment discovery replaced."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.counters = {name: 0 for name in OUTCOMES}
            self.counters["examined"] = 0

        # ---------------------------------------------------------- discovery
        async def discover(self, page) -> dict:
            """Finds the attachment control. Pure inspection -- clicks nothing.

            The modal's close button anchors the search region: the container id
            the library assumes no longer exists, but the close button does.
            """
            return await page.evaluate(
                _DISCOVER_JS,
                {"label": self.file_label, "anchorId": MODAL_CLOSE.lstrip("#")},
            )

        # ---------------------------------------------------- one project row
        async def _download_one(self, page, i, code, target_subdir) -> bool:
            import os

            from agent_sigpesq.strategies.project_files_strategy import _safe_name

            self.counters["examined"] += 1
            try:
                await page.click(RESUMO_BTN.format(i=i))
                await page.wait_for_selector(
                    MODAL_CLOSE, state="visible", timeout=12000
                )
            except Exception as exc:
                logger.warning("[{}] project window did not open: {}", code, exc)
                self.counters[MODAL_FAILED] += 1
                await self._close_modal(page)
                return False

            try:
                found = await self.discover(page)
            except Exception as exc:
                logger.warning("[{}] could not inspect the page: {}", code, exc)
                self.counters[UNRECOGNIZED] += 1
                await self._close_modal(page)
                return False

            outcome = found.get("outcome")
            if outcome == NO_ATTACHMENT:
                logger.info("[{}] no attachment on this project (legitimate)", code)
                self.counters[NO_ATTACHMENT] += 1
                await self._close_modal(page)
                return False
            if outcome != "found":
                # The loud one: the page is not shaped the way we know.
                logger.error(
                    "[{}] ATTACHMENTS AREA NOT RECOGNISED — the portal markup "
                    "probably changed; this is NOT the same as 'no attachment'",
                    code,
                )
                self.counters[UNRECOGNIZED] += 1
                await self._close_modal(page)
                return False

            if not found.get("by_label"):
                logger.warning(
                    "[{}] no attachment labelled '{}' among {} found; falling back "
                    "to '{}' — verify this is the intended document",
                    code,
                    self.file_label,
                    found.get("total"),
                    found.get("text"),
                )

            try:
                link = page.locator(f"[id='{found['id']}']").first
                async with page.expect_download(timeout=60000) as dl_info:
                    await link.click()
                download = await dl_info.value
                suggested = download.suggested_filename or "projeto.pdf"
                ext = os.path.splitext(suggested)[1] or ".pdf"
                dest = os.path.join(target_subdir, f"{_safe_name(code)}{ext}")
                if os.path.exists(dest):
                    os.remove(dest)
                await download.save_as(dest)
                logger.info("[{}] saved -> {}", code, dest)
                self.counters[DOWNLOADED] += 1
                return True
            except Exception as exc:
                logger.warning("[{}] download failed: {}", code, exc)
                self.counters[MODAL_FAILED] += 1
                return False
            finally:
                await self._close_modal(page)

        # ------------------------------------------------------------ summary
        async def download(self, page, reports_dir) -> bool:
            result = await super().download(page, reports_dir)
            logger.info("Project attachment summary: {}", self.summary())
            unrecognized = self.counters[UNRECOGNIZED]
            if unrecognized:
                logger.error(
                    "{} project page(s) could not be read. The portal markup "
                    "likely changed — the discovery rules in "
                    "src/adapters/sources/sigpesq/project_files_strategy.py "
                    "need updating.",
                    unrecognized,
                )
            return result

        def summary(self) -> dict:
            return dict(self.counters)

    return ResilientProjectFilesStrategy


def build_resilient_strategy(
    file_label: str = "Projeto",
    limit: Optional[int] = None,
    skip_existing: bool = True,
):
    """Returns a configured resilient strategy instance."""
    cls = _build_strategy_class()
    return cls(file_label=file_label, limit=limit, skip_existing=skip_existing)
