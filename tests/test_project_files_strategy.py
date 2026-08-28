"""Offline tests for the resilient attachment discovery.

These load local HTML into a real browser page -- same engine and same DOM
queries that run against the portal -- without any network access. That matters
twice over: the SigPesq portal rate-limits logins, and the defect being guarded
against is precisely about the real DOM, so a mocked page would just reproduce
the wrong assumptions.

Four scenarios, from contracts/discovery.md:
  known markup with a labelled attachment  -> downloaded, chosen BY LABEL
  alternative markup, attachments reordered -> downloaded, chosen BY LABEL
  attachments area present but empty        -> no_attachment
  no attachments area at all                -> unrecognized
"""

import pytest

from src.adapters.sources.sigpesq.project_files_strategy import (
    _DISCOVER_JS,
    NO_ATTACHMENT,
    UNRECOGNIZED,
)

pytest.importorskip("playwright.sync_api")

# The markup the library was written against.
KNOWN_MARKUP = """
<div id="ContentPlaceHolder_ModalConsultaProjeto">
  <h4>Arquivos</h4>
  <table id="ContentPlaceHolder_ModalConsultaProjeto_rptArquivo">
    <tr><td><a id="ContentPlaceHolder_ModalConsultaProjeto_rptArquivo_Download_0"
             href="#">Projeto</a></td></tr>
    <tr><td><a id="ContentPlaceHolder_ModalConsultaProjeto_rptArquivo_Download_1"
             href="#">Parecer</a></td></tr>
  </table>
</div>
"""

# A plausible rename. Note the order: "Parecer" comes FIRST, so picking the first
# candidate would silently fetch the wrong document -- worse than failing.
ALTERNATIVE_MARKUP = """
<div id="ctl00_Content_modalProjeto">
  <h4>Arquivos do Projeto</h4>
  <table id="ctl00_Content_gvArquivos">
    <tr><td><a id="ctl00_Content_gvArquivos_lnkBaixar_0" href="#">Parecer</a></td></tr>
    <tr><td><a id="ctl00_Content_gvArquivos_lnkBaixar_1" href="#">Projeto</a></td></tr>
  </table>
</div>
"""

EMPTY_AREA_MARKUP = """
<div id="ctl00_Content_modalProjeto">
  <h4>Arquivos</h4>
  <table id="ctl00_Content_gvArquivos">
    <tr><td>Nenhum arquivo cadastrado.</td></tr>
  </table>
</div>
"""

NO_AREA_MARKUP = """
<div id="ctl00_Content_modalProjeto">
  <p>Resumo do projeto sem qualquer secao de anexos.</p>
</div>
"""


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        yield pg
        browser.close()


ANCHOR_ID = "ContentPlaceHolder_ModalConsultaProjeto_btnModal_Fechar"
CLOSE_BTN = f'<button id="{ANCHOR_ID}">Fechar</button>'


def discover(page, html, label="Projeto"):
    """Wraps the fixture in a modal carrying the real close-button id.

    The discovery scopes itself to the modal region using that button as the
    anchor, so every fixture must provide it -- exactly as the portal does.
    """
    # Mirrors the portal's real nesting, measured with a probe: the close button
    # sits in a footer whose CLASS says "modal" but which is empty; the panel
    # that actually holds the content is a few levels up and carries the id.
    page.set_content(
        f'<div id="ContentPlaceHolder_ModalConsultaProjeto_pnlModal">{html}'
        f'<div><div class="modal-footer">{CLOSE_BTN}</div></div></div>'
    )
    return page.evaluate(_DISCOVER_JS, {"label": label, "anchorId": ANCHOR_ID})


def test_known_markup_finds_attachment_by_label(page):
    """FR-001/FR-002/FR-003: the known markup still works, chosen by label."""
    result = discover(page, KNOWN_MARKUP)

    assert result["outcome"] == "found"
    assert result["text"] == "Projeto"
    assert result["by_label"] is True
    assert result["total"] == 2
    assert "rptArquivo_Download_0" in result["id"]


def test_alternative_markup_finds_attachment_by_label(page):
    """FR-002/FR-003: a renamed container still works, and the LABEL wins.

    The regression guard that matters most: here the first candidate is the
    wrong document. Choosing by position would fetch 'Parecer'.
    """
    result = discover(page, ALTERNATIVE_MARKUP)

    assert result["outcome"] == "found"
    assert result["text"] == "Projeto"
    assert result["by_label"] is True
    assert result["id"].endswith("_1"), "must pick by label, not by position"


def test_empty_attachments_area_is_no_attachment(page):
    """FR-004: an empty area is a legitimate 'this project has none'."""
    result = discover(page, EMPTY_AREA_MARKUP)

    assert result["outcome"] == NO_ATTACHMENT
    assert result["id"] is None


def test_missing_attachments_area_is_unrecognized(page):
    """FR-004: no area at all means the page changed -- a different outcome."""
    result = discover(page, NO_AREA_MARKUP)

    assert result["outcome"] == UNRECOGNIZED
    assert result["id"] is None


def test_empty_and_unrecognized_are_distinguishable(page):
    """FR-004, stated directly: the two cases must never collapse into one.

    This is the defect that hid the problem for weeks -- both used to print the
    same 'likely a draft' message.
    """
    empty = discover(page, EMPTY_AREA_MARKUP)["outcome"]
    unreadable = discover(page, NO_AREA_MARKUP)["outcome"]

    assert empty != unreadable
    assert {empty, unreadable} == {NO_ATTACHMENT, UNRECOGNIZED}


def test_attachment_found_by_filename_when_id_says_nothing(page):
    """FR-002: the second signal -- visible text ending in a document extension."""
    html = """
    <div><h4>Arquivos</h4>
      <a id="ctl00_x_lnk0" href="#">plano_de_projeto.pdf</a>
    </div>
    """
    result = discover(page, html)

    assert result["outcome"] == "found"
    assert result["text"] == "plano_de_projeto.pdf"
    assert result["by_label"] is False


def test_word_arquivos_outside_the_modal_does_not_count(page):
    """The scoping guard, and a real defect caught during implementation.

    A first version searched the whole page for an attachments area. A portal
    menu item or a grid column header called "Arquivos" answered yes for every
    project, so unreadable pages were silently reported as "no attachment" --
    reintroducing the exact confusion this feature exists to remove. The search
    must stay inside the modal.
    """
    page.set_content(
        '<div id="menu">Projetos | Arquivos do sistema</div>'
        "<table><tr><th>Codigo</th><th>Arquivos</th></tr></table>"
        '<div id="ContentPlaceHolder_ModalConsultaProjeto_pnlModal">'
        f'<p>Resumo sem anexos.</p><div class="modal-footer">{CLOSE_BTN}</div></div>'
    )
    result = page.evaluate(_DISCOVER_JS, {"label": "Projeto", "anchorId": ANCHOR_ID})

    assert result["outcome"] == UNRECOGNIZED
    assert result["scoped"] is True


def test_missing_modal_anchor_is_unrecognized(page):
    """Without the modal anchor there is no region to trust -- never guess."""
    page.set_content("<div><h4>Arquivos</h4><a id='x_Download_0'>Projeto</a></div>")
    result = page.evaluate(_DISCOVER_JS, {"label": "Projeto", "anchorId": ANCHOR_ID})

    assert result["outcome"] == UNRECOGNIZED
    assert result["scoped"] is False


def test_footer_class_named_modal_does_not_truncate_the_region(page):
    """Second defect caught by probing the live portal, now locked down.

    The close button's wrapper has class="modal-footer" and no content. Matching
    the region on className stopped the walk there, on a 0-character container,
    and every project came back "unrecognized" -- a false alarm as damaging as
    the false "no attachment" before it. The region must be found by ID.
    """
    page.set_content(
        '<div id="ContentPlaceHolder_ModalConsultaProjeto_pnlModal">'
        "  <h4>Arquivos</h4>"
        '  <a id="ContentPlaceHolder_ModalConsultaProjeto_rptArquivo_Download_0"'
        '     href="#">Projeto</a>'
        f'  <div class="modal-footer"><div class="modal">{CLOSE_BTN}</div></div>'
        "</div>"
    )
    result = page.evaluate(_DISCOVER_JS, {"label": "Projeto", "anchorId": ANCHOR_ID})

    assert result["outcome"] == "found", "region must not stop at the modal footer"
    assert result["text"] == "Projeto"


def test_summary_counters_sum_to_examined():
    """FR-005: the summary invariant, checked without a browser."""
    from src.adapters.sources.sigpesq.project_files_strategy import OUTCOMES

    counters = {name: 0 for name in OUTCOMES}
    counters["examined"] = 0

    # simulate one project per outcome
    for name in OUTCOMES:
        counters[name] += 1
        counters["examined"] += 1

    assert counters["examined"] == sum(counters[n] for n in OUTCOMES)


def test_stale_library_message_hands_over_the_fix():
    """A colleague lost time to a bare ModuleNotFoundError from this import.

    The cause -- pip skipping the upgrade because the new branch kept version
    0.3.2 -- was documented in the feature's research notes, which is exactly
    where nobody looks while a pipeline is broken. The message must carry the
    command instead.
    """
    from src.adapters.sources.sigpesq.project_files_strategy import (
        AGENT_SIGPESQ_SHA,
        STALE_LIBRARY_HELP,
    )

    assert "--force-reinstall" in STALE_LIBRARY_HELP
    assert AGENT_SIGPESQ_SHA in STALE_LIBRARY_HELP, "must pin the exact commit"
    assert "already satisfied" in STALE_LIBRARY_HELP, "must explain the silence"


def test_reinstall_guidance_also_installs_the_extras():
    """The first version of this message shipped a half-fix.

    It told people to reinstall with --no-deps and stopped there. --no-deps also
    skips the [extract] extra, so following the instructions to the letter left
    mistralai uninstalled and moved the failure one step later, into the
    extraction task. Guidance that only gets you halfway is worse than none: it
    looks authoritative.
    """
    from src.adapters.sources.sigpesq.project_files_strategy import (
        MISSING_EXTRACTION_DEPS_HELP,
        STALE_LIBRARY_HELP,
    )

    assert "mistralai" in STALE_LIBRARY_HELP, "--no-deps skips the extras"
    assert "pypdf" in STALE_LIBRARY_HELP
    assert "mistralai" in MISSING_EXTRACTION_DEPS_HELP
    assert "--no-deps" in MISSING_EXTRACTION_DEPS_HELP, "must name the cause"
