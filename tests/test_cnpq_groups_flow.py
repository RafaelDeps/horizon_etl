import threading
import time
from unittest.mock import MagicMock, patch

from src.flows.cnpq.groups import (
    _write_group_result,
    build_cnpq_sync_summary,
    get_groups_to_sync,
    sync_cnpq_groups_flow,
)


def test_build_cnpq_sync_summary_reports_failed_groups():
    summary = build_cnpq_sync_summary(
        [
            {"success": True, "group_id": 1, "group_name": "Ok", "url": "http://ok"},
            {
                "success": False,
                "group_id": 2,
                "group_name": "Broken",
                "url": "http://broken",
            },
        ]
    )

    assert summary["total_groups"] == 2
    assert summary["success_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["warnings"] == [
        {
            "source": "cnpq",
            "severity": "warning",
            "code": "cnpq_group_sync_failed",
            "count": 1,
            "examples": [
                {
                    "group_id": 2,
                    "group_name": "Broken",
                    "url": "http://broken",
                }
            ],
            "message": "CNPq sync failed for 1 group(s); inspect URLs or portal availability.",
        }
    ]


def test_get_groups_to_sync_returns_valid_and_invalid_keys_when_no_campus_matches():
    # The flow does to_sync["valid"] / to_sync["invalid"]; when campus matches
    # nothing the task must still return that dict shape, not a bare list
    # (which crashed the weekly EtL with "TypeError: list indices must be
    # integers or slices, not str").
    fake_campus = MagicMock()
    fake_campus.get_all.return_value = [
        MagicMock(name="Vila Velha", id=1),
        MagicMock(name="Vitória", id=2),
    ]
    with (
        patch("src.flows.cnpq.groups.get_run_logger", return_value=MagicMock()),
        patch("src.flows.cnpq.groups.CampusController", return_value=fake_campus),
        patch("src.flows.cnpq.groups.ResearchGroupController"),
    ):
        result = get_groups_to_sync.fn(campus_name="Serra")

    assert result == {"valid": [], "invalid": []}


@patch("src.flows.cnpq.groups.tracking_recorder")
@patch("src.flows.cnpq.groups.CnpqSyncLogic")
@patch("src.flows.cnpq.groups.get_run_logger", return_value=MagicMock())
def test_write_group_result_forwards_shared_researcher_index(
    _mock_logger, mock_sync_logic_cls, mock_tracker
):
    """_write_group_result must forward the caller's researcher index
    unchanged into sync_members, and must not build or read a registry of
    its own -- the whole point of specs/011-cnpq-sync-index-reuse is that the
    index is built once in the flow and shared, not rebuilt per group."""
    sync_logic = mock_sync_logic_cls.return_value
    mock_tracker.record_source_record.return_value = MagicMock(id=1)

    shared_index = [MagicMock(name="pre-built index shared across groups")]

    fetch_result = {
        "group_id": 10,
        "group_name": "Grupo X",
        "url": "http://dgp.cnpq.br/x",
        "data": {"nome_grupo": "Grupo X"},
        "members": [{"name": "Alice", "role": "Pesquisador"}],
        "research_lines": [],
    }

    _write_group_result(fetch_result, sync_logic, shared_index)

    sync_logic.sync_members.assert_called_once()
    _, kwargs = sync_logic.sync_members.call_args
    assert kwargs["researcher_index"] is shared_index, (
        "_write_group_result did not forward the same researcher_index "
        "object it received -- a copy or a freshly-built index here would "
        "defeat the whole point of building it once in the flow"
    )


def test_fetches_are_all_submitted_before_any_result_is_consumed():
    """T011: proves the code shape that makes concurrent fetching possible.

    Actually observing network-level overlap needs a live run against the
    real portal (quickstart.md SS2), which needs a reachable Prefect API
    server this sandbox does not have -- an ephemeral Prefect server could
    not be reached even over loopback when tried directly here, and every
    other test in this module already avoids invoking Prefect orchestration
    in favor of calling `.fn()` directly. What a fast unit test can prove
    instead is the structural precondition for that overlap: every group's
    fetch_group.submit() must be issued before the loop starts blocking on
    any .result() -- submit-then-wait, not the old submit-wait-submit-wait
    shape sync_single_group had. If the loop ever regressed to fetching one
    group at a time, this would fail regardless of which task_runner is
    configured on the flow. Actual wall-clock concurrency and process
    isolation are verified live, per quickstart.md SS2-3, by the user.
    """
    events = []

    class _FakeFuture:
        def __init__(self, value):
            self._value = value

        def result(self):
            events.append(("result", self._value["group_id"]))
            return self._value

    def fake_submit(g_info):
        events.append(("submit", g_info["id"]))
        return _FakeFuture(
            {
                "success": True,
                "group_id": g_info["id"],
                "group_name": g_info["name"],
                "url": g_info["url"],
                "data": {},
                "members": [],
                "research_lines": [],
            }
        )

    groups = [{"id": i, "name": f"G{i}", "url": f"http://g{i}"} for i in (1, 2, 3)]

    with (
        patch(
            "src.flows.cnpq.groups.get_groups_to_sync",
            return_value={"valid": groups, "invalid": []},
        ),
        patch("src.flows.cnpq.groups.ResearcherController"),
        patch("src.flows.cnpq.groups.load_researcher_index", return_value=[]),
        patch("src.flows.cnpq.groups.CnpqSyncLogic"),
        patch("src.flows.cnpq.groups.tracking_recorder"),
        patch("src.flows.cnpq.groups.fetch_group") as mock_fetch_group,
        patch("src.flows.cnpq.groups.get_run_logger", return_value=MagicMock()),
        patch(
            "src.flows.cnpq.groups._write_group_result",
            side_effect=lambda fr, sl, ri: {
                "success": True,
                "group_id": fr["group_id"],
                "group_name": fr["group_name"],
                "url": fr["url"],
            },
        ),
    ):
        mock_fetch_group.submit.side_effect = fake_submit
        sync_cnpq_groups_flow.fn(campus_name=None)

    submit_indices = [i for i, (kind, _) in enumerate(events) if kind == "submit"]
    first_result_index = next(
        i for i, (kind, _) in enumerate(events) if kind == "result"
    )
    assert max(submit_indices) < first_result_index, (
        "a fetch was submitted after a result was already being consumed -- "
        "this is the fetch-wait-fetch-wait shape that defeats concurrency"
    )
    assert [gid for kind, gid in events if kind == "submit"] == [1, 2, 3]


def test_writes_never_overlap_even_if_fetches_finish_out_of_order():
    """T014 -- the critical test (see contracts/fetch_write_contract.md).

    Wraps the real write step with a non-reentrant guard: if the flow's loop
    were ever changed to submit _write_group_result() concurrently instead of
    calling it directly, one group at a time, this test fails on every run --
    not "sometimes", not "only under load" -- because the guard raises the
    instant a second write starts before the first one has finished. Group
    1's fetch is made the slowest to resolve, so its result becomes available
    last even though it was submitted first, proving the write loop still
    processes strictly in submission order regardless of arrival order.
    """
    fetch_payloads = {
        gid: {
            "success": True,
            "group_id": gid,
            "group_name": f"G{gid}",
            "url": f"http://g{gid}",
            "data": {},
            "members": [],
            "research_lines": [],
        }
        for gid in (1, 2, 3)
    }
    groups = [
        {"id": gid, "name": p["group_name"], "url": p["url"]}
        for gid, p in fetch_payloads.items()
    ]

    class _FakeFuture:
        def __init__(self, value, delay=0.0):
            self._value = value
            self._delay = delay

        def result(self):
            if self._delay:
                time.sleep(self._delay)
            return self._value

    def fake_submit(g_info):
        delay = 0.05 if g_info["id"] == 1 else 0.0
        return _FakeFuture(fetch_payloads[g_info["id"]], delay=delay)

    in_progress = 0
    max_in_progress = 0
    write_order = []
    lock = threading.Lock()

    def guarded_write(fetch_result, sync_logic, researcher_index):
        nonlocal in_progress, max_in_progress
        with lock:
            in_progress += 1
            max_in_progress = max(max_in_progress, in_progress)
        try:
            assert in_progress <= 1, "overlapping write detected"
            time.sleep(0.02)
            write_order.append(fetch_result["group_id"])
            return {
                "success": True,
                "group_id": fetch_result["group_id"],
                "group_name": fetch_result["group_name"],
                "url": fetch_result["url"],
            }
        finally:
            with lock:
                in_progress -= 1

    with (
        patch(
            "src.flows.cnpq.groups.get_groups_to_sync",
            return_value={"valid": groups, "invalid": []},
        ),
        patch("src.flows.cnpq.groups.ResearcherController"),
        patch("src.flows.cnpq.groups.load_researcher_index", return_value=[]),
        patch("src.flows.cnpq.groups.CnpqSyncLogic"),
        patch("src.flows.cnpq.groups.tracking_recorder"),
        patch("src.flows.cnpq.groups.fetch_group") as mock_fetch_group,
        patch("src.flows.cnpq.groups._write_group_result", side_effect=guarded_write),
        patch("src.flows.cnpq.groups.get_run_logger", return_value=MagicMock()),
    ):
        mock_fetch_group.submit.side_effect = fake_submit
        summary = sync_cnpq_groups_flow.fn(campus_name=None)

    assert max_in_progress <= 1, f"writes overlapped: max_in_progress={max_in_progress}"
    assert write_order == [1, 2, 3], (
        "writes did not happen in submission order even though every fetch "
        f"succeeded -- got {write_order}"
    )
    assert summary["success_count"] == 3
