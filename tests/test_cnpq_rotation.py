"""Spec 023, US2: CNPq group pages are stored with their download date; a run
fetches the new groups plus a rotating share of the stored ones, and uses the
stored page for the rest and after a failed fetch.

``_sync_cnpq_groups`` runs in-process with a fake crawler, a recording
document writer and a memory document store: no database, no network."""

import contextlib
import logging
import os

import pytest

from src.adapters.sources import raw_store
from src.core.logic.document_skip import DocumentSkip
from src.flows.cnpq import groups as flow
from tests.conftest import _MemoryDocumentStore

IDS = [f"{i:016d}" for i in range(1, 9)]
URL = "http://dgp.cnpq.br/dgp/espelhogrupo/{}"


class FakeCrawler:
    asked = []
    failing = set()

    def get_group_data(self, url):
        FakeCrawler.asked.append(url)
        group_id = url.rsplit("/", 1)[-1]
        if group_id in FakeCrawler.failing:
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
    monkeypatch.setattr(flow, "CnpqCrawlerAdapter", FakeCrawler)
    monkeypatch.setattr(flow, "ResearcherController", lambda: None)
    monkeypatch.setattr(flow, "load_researcher_index", lambda session: [])
    monkeypatch.setattr(flow, "_SLEEP", lambda *_a, **_k: None)
    monkeypatch.setattr(
        flow.tracking_recorder, "run_context", lambda **_k: contextlib.nullcontext()
    )
    written = []

    def fake_document(skip, g_info, outcome, index, downloaded_at=None):
        written.append((g_info["url"].rsplit("/", 1)[-1], outcome.data, downloaded_at))
        return {"success": bool(outcome.data), "group_id": g_info["id"]}

    monkeypatch.setattr(flow, "_sync_group_document", fake_document)

    clock = iter(f"2026-11-{day:02d}T02:00:00Z" for day in range(1, 29))
    monkeypatch.setattr(flow, "_now", lambda: next(clock))  # one run per week

    def go(env=None, campus=None):
        for key in ("HORIZON_REFRESH_SHARE", "HORIZON_FULL_REFRESH"):
            monkeypatch.delenv(key, raising=False)
        for key, value in (env or {}).items():
            monkeypatch.setenv(key, value)
        FakeCrawler.asked = []
        written.clear()
        skip = DocumentSkip(_MemoryDocumentStore(), "cnpq_group")
        flow._sync_cnpq_groups(campus, skip, logging.getLogger("test"))
        return [u.rsplit("/", 1)[-1] for u in FakeCrawler.asked], list(written), skip

    return go


def test_first_run_fetches_and_stores_every_page(run, tmp_path):
    asked, written, skip = run()
    assert sorted(asked) == IDS
    assert [w[0] for w in written] == IDS  # writer order = group list order
    assert all(w[1] and w[2] for w in written)
    stored = sorted(os.listdir(raw_store.CNPQ_PAGES))
    assert stored == [f"{i}.json" for i in IDS]
    assert skip.downloads["new"] == 8


def test_later_runs_fetch_a_quarter_and_reuse_the_rest(run):
    run()
    asked, written, skip = run()
    assert len(asked) == 2  # ceil(0.25 * 8)
    assert [w[0] for w in written] == IDS
    assert all(w[1] for w in written)  # reused pages are processed too
    assert skip.downloads["refreshed"] == 2 and skip.downloads["reused"] == 6
    third, _, _ = run()
    assert set(third).isdisjoint(asked)  # the next oldest quarter


def test_a_failed_fetch_uses_the_stored_page(run):
    _, first, _ = run()
    stored_dates = {w[0]: w[2] for w in first}
    FakeCrawler.failing = set(IDS)  # the portal is down
    try:
        asked, written, skip = run({"HORIZON_FULL_REFRESH": "1"})
    finally:
        FakeCrawler.failing = set()
    assert sorted(set(asked)) == IDS  # each tried (with its retries)
    assert all(w[1] for w in written)  # every group keeps its data
    assert {w[0]: w[2] for w in written} == stored_dates  # dates of the stored copies
    assert skip.downloads["failed"] == 8
    assert skip.downloads["reused_after_failure"] == 8


def test_a_failed_fetch_without_a_stored_page_is_a_failed_download(run):
    FakeCrawler.failing = {IDS[0]}
    try:
        _, written, skip = run()
    finally:
        FakeCrawler.failing = set()
    assert written[0] == (IDS[0], None, None)
    assert skip.downloads["failed"] == 1 and skip.downloads["new"] == 7


def test_a_campus_filtered_run_never_does_a_full_refresh(run):
    run()
    asked, _, _ = run({"HORIZON_FULL_REFRESH": "1"}, campus="Serra")
    assert len(asked) == 2
