"""Spec 024, US1: the CNPq phase stops requesting pages once the portal fails
a number of attempts in a row (or runs past its time budget), and processes
every group left from its stored page."""

import contextlib
import json
import logging
import threading

import pytest

import src.flows.portal_stops as portal_stops
from src.core.logic.document_skip import DocumentSkip
from src.core.logic.portal_stop import PortalStop
from src.flows.cnpq import groups as flow
from src.flows.cnpq.concurrent_fetch import fetch_all
from tests.conftest import _MemoryDocumentStore

# --- fetch level ----------------------------------------------------------


def _groups(n):
    return [
        {"id": i, "name": f"G{i}", "url": f"http://dgp/espelhogrupo/{i:016d}"}
        for i in range(n)
    ]


class Portal:
    """A fake adapter; ``fail_first`` attempts fail, then it answers."""

    lock = threading.Lock()
    calls = 0
    fail_first = 10**9

    @classmethod
    def reset(cls, fail_first=10**9):
        cls.calls = 0
        cls.fail_first = fail_first

    def get_group_data(self, url):
        cls = type(self)
        with cls.lock:
            cls.calls += 1
            n = cls.calls
        return None if n <= cls.fail_first else {"nome": url}


def _collect(groups, stop, workers=4):
    batch = fetch_all(groups, Portal, workers, sleep=lambda _s: None, stop=stop)
    try:
        return [batch.outcome(i) for i in range(len(groups))]
    finally:
        batch.close()


def test_a_down_portal_gets_no_request_after_the_limit():
    Portal.reset()
    stop = PortalStop("cnpq", max_failures=8)
    # back-offs wait on the stop: a short real wait keeps the test fast
    outcomes = _collect(_groups(40), stop)
    assert stop.stopped and stop.reason == "failures_in_a_row"
    # the attempts already in flight when the 8th failed are counted too
    assert 8 <= Portal.calls <= 8 + 4
    assert all(o.data is None for o in outcomes)
    assert all(o.stopped for o in outcomes if o.attempts < 3)
    not_tried = [o for o in outcomes if o.attempts == 0]
    assert len(not_tried) >= 40 - Portal.calls


def test_back_offs_end_at_the_stop(monkeypatch):
    import time

    import src.flows.cnpq.concurrent_fetch as module

    monkeypatch.setattr(module, "BACKOFF_SECONDS", (3600.0, 3600.0))
    Portal.reset()
    stop = PortalStop("cnpq", max_failures=8)
    done = []

    def collect():
        # the real sleep: the back-offs wait on the stop
        batch = fetch_all(_groups(12), Portal, 4, sleep=time.sleep, stop=stop)
        try:
            done.append([batch.outcome(i) for i in range(12)])
        finally:
            batch.close()

    t = threading.Thread(target=collect)
    t.start()
    t.join(timeout=30)
    assert done, "a back-off kept waiting after the stop"
    assert stop.stopped


def test_a_portal_that_recovers_is_not_given_up():
    # 2 failures, then answers: no group can use up its 3 attempts
    Portal.reset(fail_first=2)
    stop = PortalStop("cnpq", max_failures=2 + 1)
    outcomes = _collect(_groups(20), stop)
    assert not stop.stopped
    assert all(o.data for o in outcomes)


def test_the_time_budget_stops_new_attempts():
    now = [0.0]
    stop = PortalStop("cnpq", max_failures=8, budget_s=2700, clock=lambda: now[0])
    Portal.reset(fail_first=0)
    groups = _groups(10)
    stop.start()
    now[0] = 2700.0  # the budget is spent before the downloads start
    outcomes = _collect(groups, stop)
    assert stop.reason == "time_budget"
    assert Portal.calls == 0
    assert all(o.stopped and o.attempts == 0 for o in outcomes)


def test_a_healthy_portal_gives_the_same_outcomes_with_a_stop():
    Portal.reset(fail_first=0)
    without = _collect(_groups(10), None)
    Portal.reset(fail_first=0)
    with_stop = _collect(_groups(10), PortalStop("cnpq", max_failures=8))
    assert [(o.data, o.attempts, o.stopped) for o in with_stop] == [
        (o.data, o.attempts, o.stopped) for o in without
    ]


# --- phase level ------------------------------------------------------------

IDS = [f"{i:016d}" for i in range(1, 41)]
URL = "http://dgp.cnpq.br/dgp/espelhogrupo/{}"


class Crawler:
    lock = threading.Lock()
    asked = []
    down = False

    def get_group_data(self, url):
        with Crawler.lock:
            Crawler.asked.append(url)
        group_id = url.rsplit("/", 1)[-1]
        if Crawler.down:
            return None
        return {"nome": f"Grupo {group_id}", "linhas": [group_id]}


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    groups = [
        {"id": n + 1, "name": f"G{n}", "url": URL.format(i)} for n, i in enumerate(IDS)
    ]
    monkeypatch.setattr(
        flow,
        "get_groups_to_sync",
        lambda campus_name=None: {"valid": groups, "invalid": []},
    )
    monkeypatch.setattr(flow, "_active_in_sigpesq", lambda g, skip, logger: g)
    monkeypatch.setattr(flow, "CnpqCrawlerAdapter", Crawler)
    monkeypatch.setattr(flow, "ResearcherController", lambda: None)
    monkeypatch.setattr(flow, "load_researcher_index", lambda session: [])
    monkeypatch.setattr(flow, "_SLEEP", lambda *_a, **_k: None)
    monkeypatch.setattr(
        flow.tracking_recorder, "run_context", lambda **_k: contextlib.nullcontext()
    )
    import src.flows.cnpq.concurrent_fetch as fetch_module

    monkeypatch.setattr(fetch_module, "BACKOFF_SECONDS", (0.01, 0.01))
    written = []

    def fake_document(skip, g_info, outcome, index, downloaded_at=None):
        written.append((g_info["url"].rsplit("/", 1)[-1], outcome.data, downloaded_at))
        return {"success": bool(outcome.data), "group_id": g_info["id"]}

    monkeypatch.setattr(flow, "_sync_group_document", fake_document)
    clock = iter(f"2026-11-{day:02d}T02:00:00Z" for day in range(1, 29))
    monkeypatch.setattr(flow, "_now", lambda: next(clock))

    def go(env=None, down=False):
        for key in (
            "HORIZON_REFRESH_SHARE",
            "HORIZON_FULL_REFRESH",
            "HORIZON_PORTAL_EARLY_STOP",
            "HORIZON_CNPQ_STOP_AFTER_FAILURES",
            "HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in (env or {}).items():
            monkeypatch.setenv(key, value)
        Crawler.asked = []
        Crawler.down = down
        written.clear()
        skip = DocumentSkip(_MemoryDocumentStore(), "cnpq_group")
        flow._sync_cnpq_groups(None, skip, logging.getLogger("test"))
        return len(Crawler.asked), list(written), skip

    return go


def test_an_outage_uses_every_stored_page(run):
    _, first, _ = run()  # every page stored
    stored_dates = {w[0]: w[2] for w in first}
    asked, written, skip = run({"HORIZON_FULL_REFRESH": "1"}, down=True)
    assert asked <= 8 + 4  # the limit plus the attempts in flight
    assert [w[0] for w in written] == IDS
    assert all(w[1] for w in written)  # every group keeps its data
    assert {w[0]: w[2] for w in written} == stored_dates
    counts = skip.downloads
    assert counts["stopped"] + counts["failed"] == len(IDS)
    assert counts["stopped"] >= len(IDS) - asked
    assert counts["reused_after_failure"] == counts["failed"]
    entry = json.load(open(portal_stops.PORTAL_STOPS_PATH))["stops"]["cnpq"]
    assert entry["reason"] == "failures_in_a_row" and entry["limit"] == 8
    assert entry["counts"]["stopped"] == counts["stopped"]


def test_untried_groups_are_processed_from_their_stored_page(run):
    run()
    asked, written, skip = run({"HORIZON_FULL_REFRESH": "1"}, down=True)
    counts = skip.downloads
    # only the groups actually requested are failed downloads
    assert counts["failed"] <= asked and counts["failed"] < len(IDS)
    assert counts["refreshed"] == 0 and counts["reused"] == counts["stopped"]
    assert all(w[1] for w in written)


def test_without_stored_pages_the_untried_groups_fail_as_today(run):
    asked, written, skip = run(down=True)  # first run: nothing stored
    assert asked <= 8 + 4
    # no page to process: each is a failed download of the writer (FR-004)
    assert all(w[1] is None and w[2] is None for w in written)
    assert skip.downloads["new"] == 0
    assert skip.downloads["failed"] + skip.downloads["stopped"] == len(IDS)


def test_a_healthy_portal_gives_the_same_result_with_the_stop_off(run):
    _, on, skip_on = run()
    _, off, skip_off = run(
        {"HORIZON_FULL_REFRESH": "1", "HORIZON_PORTAL_EARLY_STOP": "0"}
    )
    _, on_again, skip_again = run({"HORIZON_FULL_REFRESH": "1"})
    assert [w[:2] for w in on_again] == [w[:2] for w in off]
    assert skip_again.downloads == skip_off.downloads
    assert "stopped" not in skip_on.downloads
    assert portal_stops.read_portal_stops() == {}


def test_the_stop_can_be_turned_off(run):
    run()
    asked, _, skip = run(
        {"HORIZON_FULL_REFRESH": "1", "HORIZON_PORTAL_EARLY_STOP": "0"}, down=True
    )
    assert asked == len(IDS) * 3  # every page with all its attempts
    assert skip.downloads["failed"] == len(IDS)
