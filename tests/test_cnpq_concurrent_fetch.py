"""Concurrent CNPq fetch with a single ordered writer (spec 017)."""

import threading
import time
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from loguru import logger
from prefect.utilities.annotations import quote

from src.flows.cnpq import groups as groups_module
from src.flows.cnpq.concurrent_fetch import FetchOutcome, fetch_all, resolve_workers


def _groups(n):
    return [
        {"id": i, "name": f"G{i}", "url": f"http://dgp/espelhogrupo/{i:016d}"}
        for i in range(n)
    ]


class FakeAdapter:
    """Shared state across instances: delays make completions arrive out of order."""

    lock = threading.Lock()
    active = 0
    peak = 0
    delays = {}
    calls = {}
    fail_until = {}  # url -> number of initial calls returning None
    always_fail = set()

    @classmethod
    def reset(cls, delays=None):
        cls.active = 0
        cls.peak = 0
        cls.delays = delays or {}
        cls.calls = {}
        cls.fail_until = {}
        cls.always_fail = set()

    def get_group_data(self, url):
        cls = type(self)
        with cls.lock:
            cls.active += 1
            cls.peak = max(cls.peak, cls.active)
            cls.calls[url] = cls.calls.get(url, 0) + 1
            n = cls.calls[url]
        try:
            time.sleep(cls.delays.get(url, 0.01))
            if url in cls.always_fail or n <= cls.fail_until.get(url, 0):
                return None
            return {"nome_grupo": url}
        finally:
            with cls.lock:
                cls.active -= 1


def _no_sleep(_seconds):
    return None


def _capture(level="INFO"):
    lines = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level=level)
    return lines, sink


# --- User Story 1 -------------------------------------------------------


def test_fetch_all_bounds_in_flight_and_returns_outcomes_by_index():
    groups = _groups(12)
    # reverse delays: later groups finish first
    FakeAdapter.reset({g["url"]: 0.02 * (12 - g["id"]) for g in groups})
    batch = fetch_all(groups, FakeAdapter, max_workers=4, sleep=_no_sleep)
    try:
        outcomes = [batch.outcome(i) for i in range(len(groups))]
    finally:
        batch.close()

    assert FakeAdapter.peak == 4
    assert [o.index for o in outcomes] == list(range(12))
    assert all(isinstance(o, FetchOutcome) for o in outcomes)
    assert [o.data["nome_grupo"] for o in outcomes] == [g["url"] for g in groups]
    assert all(o.attempts == 1 for o in outcomes)


def test_one_worker_fetches_sequentially():
    groups = _groups(5)
    FakeAdapter.reset()
    batch = fetch_all(groups, FakeAdapter, max_workers=1, sleep=_no_sleep)
    try:
        [batch.outcome(i) for i in range(5)]
    finally:
        batch.close()
    assert FakeAdapter.peak == 1


def test_resolve_workers_defaults_and_warns_on_invalid_values():
    lines, sink = _capture("WARNING")
    try:
        assert resolve_workers(None) == 4
        assert resolve_workers("3") == 3
        assert resolve_workers("1") == 1
        for bad in ("0", "-2", "abc", ""):
            assert resolve_workers(bad) == 4
    finally:
        logger.remove(sink)
    assert sum("HORIZON_CNPQ_WORKERS" in line for line in lines) == 3  # "" == unset


def _run_flow(groups, record):
    with (
        patch.object(
            groups_module,
            "get_groups_to_sync",
            return_value={"valid": groups, "invalid": []},
        ),
        patch.object(groups_module, "CnpqCrawlerAdapter", FakeAdapter),
        patch.object(groups_module, "sync_single_group", side_effect=record),
        patch.object(groups_module, "get_run_logger", return_value=MagicMock()),
        patch.object(
            groups_module.tracking_recorder, "run_context", return_value=nullcontext()
        ),
        patch.object(groups_module, "load_researcher_index", return_value=[]),
        patch.object(groups_module, "ResearcherController"),
    ):
        return groups_module.sync_cnpq_groups_flow.fn()


def test_flow_writes_on_its_own_thread_in_original_order(monkeypatch):
    monkeypatch.setenv("HORIZON_CNPQ_WORKERS", "4")
    groups = _groups(6)
    FakeAdapter.reset({g["url"]: 0.02 * (6 - g["id"]) for g in groups})
    writes = []

    def record(group_info, data=None, researcher_index=None):
        data = data.unquote() if isinstance(data, quote) else data
        writes.append((threading.current_thread(), group_info["id"], data))
        return {
            "success": bool(data),
            "group_id": group_info["id"],
            "group_name": group_info["name"],
            "url": group_info["url"],
        }

    summary = _run_flow(groups, record)

    assert [w[1] for w in writes] == [g["id"] for g in groups]
    assert {w[0] for w in writes} == {threading.current_thread()}
    assert all(w[2] == {"nome_grupo": g["url"]} for w, g in zip(writes, groups))
    assert summary["success_count"] == 6
    assert FakeAdapter.peak <= 4


# --- User Story 3: retries and failure bursts ---------------------------------

import random  # noqa: E402

from src.flows.cnpq.concurrent_fetch import AdaptiveGate  # noqa: E402


def test_temporary_failures_are_retried_with_growing_waits():
    groups = _groups(3)
    FakeAdapter.reset()
    FakeAdapter.fail_until = {groups[0]["url"]: 1, groups[1]["url"]: 2}
    waits = []
    batch = fetch_all(
        groups, FakeAdapter, max_workers=2, sleep=waits.append, rng=random.Random(1)
    )
    try:
        outcomes = [batch.outcome(i) for i in range(3)]
    finally:
        batch.close()

    assert [o.attempts for o in outcomes] == [2, 3, 1]
    assert all(o.data is not None for o in outcomes)
    first = [w for w in waits if w < 60]
    second = [w for w in waits if w >= 60]
    assert len(first) == 2 and all(24 <= w <= 36 for w in first)
    assert len(second) == 1 and all(72 <= w <= 108 for w in second)


def test_permanent_failure_is_reported_and_others_continue():
    groups = _groups(4)
    FakeAdapter.reset()
    FakeAdapter.always_fail = {groups[1]["url"]}
    batch = fetch_all(groups, FakeAdapter, max_workers=2, sleep=_no_sleep)
    try:
        outcomes = [batch.outcome(i) for i in range(4)]
    finally:
        batch.close()

    assert outcomes[1].data is None and outcomes[1].attempts == 3
    assert [o.index for o in outcomes] == [0, 1, 2, 3]
    assert all(outcomes[i].data is not None for i in (0, 2, 3))


def test_backoff_wait_does_not_hold_a_fetch_slot():
    groups = _groups(2)
    FakeAdapter.reset({groups[1]["url"]: 0.05})
    FakeAdapter.fail_until = {groups[0]["url"]: 1}
    seen_other_done = []

    def sleep(_seconds):
        # group 1 must be able to fetch while group 0 waits (gate limit is 1)
        deadline = time.time() + 5
        while FakeAdapter.calls.get(groups[1]["url"], 0) == 0 or FakeAdapter.active:
            if time.time() > deadline:
                break
            time.sleep(0.01)
        seen_other_done.append(FakeAdapter.calls.get(groups[1]["url"], 0) == 1)

    batch = fetch_all(groups, FakeAdapter, max_workers=1, sleep=sleep)
    try:
        outcomes = [batch.outcome(i) for i in range(2)]
    finally:
        batch.close()

    assert seen_other_done == [True]
    assert outcomes[0].attempts == 2 and outcomes[1].attempts == 1


def test_failure_burst_halves_the_limit_and_quiet_period_restores_it():
    now = [0.0]
    gate = AdaptiveGate(4, clock=lambda: now[0])
    lines, sink = _capture("INFO")
    try:
        for t in (0, 10, 20, 30):
            now[0] = t
            gate.record_failure()
        assert gate.limit == 2 and gate.reductions == 1

        now[0] = 30 + 121
        with gate.slot():
            pass
        assert gate.limit == 3

        now[0] = 30 + 121 + 10  # not yet another quiet period
        with gate.slot():
            pass
        assert gate.limit == 3
    finally:
        logger.remove(sink)
    assert any("concurrency 4 → 2" in line for line in lines)


def test_limit_never_drops_below_one():
    now = [0.0]
    gate = AdaptiveGate(1, clock=lambda: now[0])
    for t in range(8):
        now[0] = t
        gate.record_failure()
    assert gate.limit == 1 and gate.reductions == 0


def test_flow_logs_one_fetch_summary_line(monkeypatch):
    monkeypatch.setenv("HORIZON_CNPQ_WORKERS", "2")
    groups = _groups(3)
    FakeAdapter.reset()
    FakeAdapter.always_fail = {groups[2]["url"]}
    monkeypatch.setattr(groups_module, "_SLEEP", _no_sleep)

    def record(group_info, data=None, researcher_index=None):
        data = data.unquote() if isinstance(data, quote) else data
        return {
            "success": bool(data),
            "group_id": group_info["id"],
            "group_name": group_info["name"],
            "url": group_info["url"],
        }

    lines, sink = _capture("INFO")
    try:
        summary = _run_flow(groups, record)
    finally:
        logger.remove(sink)

    fetch_lines = [line for line in lines if line.startswith("CNPq fetch:")]
    assert fetch_lines == [
        "CNPq fetch: workers=2 fetched=2 retries=2 failed_after_retries=1 "
        "concurrency_reductions=0 researcher_index_loaded=0 researcher_hits=0 "
        "researcher_created=0"
    ]
    assert summary["failed_count"] == 1
