"""Spec 023: which raw items a run downloads (research R3)."""

from src.core.logic.raw_rotation import (
    counts_line,
    download_counts,
    plan_downloads,
    refresh_settings,
)

IDS = [f"{i:016d}" for i in range(1, 9)]


def test_new_items_are_downloaded_and_the_oldest_quarter_refreshed():
    dates = {i: f"2026-10-{10 + n:02d}T00:00:00Z" for n, i in enumerate(IDS[:6])}
    plan = plan_downloads(IDS, dates, share=0.25)
    assert plan.new == IDS[6:]
    assert plan.refresh == IDS[:2]  # ceil(0.25 * 6) = 2 oldest
    assert plan.reuse == IDS[2:6]
    assert plan.to_download == IDS[6:] + IDS[:2]


def test_undated_items_count_as_the_oldest_and_ties_go_by_id():
    dates = {IDS[0]: "2026-10-01T00:00:00Z", IDS[3]: None, IDS[1]: None}
    plan = plan_downloads(IDS[:4], dates, share=0.5)
    assert plan.refresh == [IDS[1], IDS[3]]  # both undated, by id
    assert plan.reuse == [IDS[0]]
    assert plan.new == [IDS[2]]


def test_every_item_is_refreshed_within_four_runs():
    dates = {i: None for i in IDS}
    refreshed = set()
    for run in range(4):
        plan = plan_downloads(IDS, dates, share=0.25)
        for item in plan.refresh:
            dates[item] = f"2026-11-{run + 1:02d}T00:00:00Z"
            refreshed.add(item)
    assert refreshed == set(IDS)


def test_full_refresh_and_determinism():
    dates = {i: "2026-10-01T00:00:00Z" for i in IDS}
    assert plan_downloads(IDS, dates, full=True).refresh == IDS
    assert plan_downloads(IDS, dates) == plan_downloads(list(IDS), dict(dates))
    assert plan_downloads(IDS + IDS[:2], dates).refresh == IDS[:2]  # duplicates once


def test_settings():
    assert refresh_settings({}) == (0.25, False)
    assert refresh_settings({"HORIZON_REFRESH_SHARE": "0.5"}) == (0.5, False)
    assert refresh_settings({"HORIZON_REFRESH_SHARE": "1"}) == (1.0, False)
    for bad in ("0", "-1", "2", "abc"):
        assert refresh_settings({"HORIZON_REFRESH_SHARE": bad})[0] == 0.25
    assert refresh_settings({"HORIZON_FULL_REFRESH": "true"})[1] is True
    assert refresh_settings({"HORIZON_FULL_REFRESH": "0"})[1] is False


def test_counts():
    dates = {IDS[0]: None, IDS[1]: None, IDS[2]: "2026-10-01T00:00:00Z"}
    plan = plan_downloads(IDS[:4], dates, share=0.5)  # new 3, refresh 0 1
    counts = download_counts(plan, failed=[IDS[1], IDS[3]])
    assert counts == {
        "new": 0,
        "refreshed": 1,
        "reused": 1,
        "failed": 2,
        "reused_after_failure": 1,
        "failed_ids": [IDS[1], IDS[3]],
    }
    assert counts_line("cnpq", counts).startswith("downloads cnpq: new=0 refreshed=1")


def test_counts_with_items_not_tried_after_a_portal_stop():
    # Spec 024: new 3; refresh 0 and 1. 1 failed; 0 and 3 never tried.
    dates = {IDS[0]: None, IDS[1]: None, IDS[2]: "2026-10-01T00:00:00Z"}
    plan = plan_downloads(IDS[:4], dates, share=0.5)
    counts = download_counts(plan, failed=[IDS[1]], stopped=[IDS[0], IDS[3]])
    assert counts == {
        "new": 0,
        "refreshed": 0,
        "reused": 2,  # 2 as planned, 0 from its stored copy
        "failed": 1,
        "reused_after_failure": 1,
        "failed_ids": [IDS[1]],
        "stopped": 2,
        "stopped_ids": [IDS[0], IDS[3]],
    }
    assert counts_line("lattes", counts).endswith("reused_after_failure=1 stopped=2")


def test_a_stopped_id_is_not_also_a_failure():
    plan = plan_downloads(IDS[:2], {}, share=0.25)  # both new
    counts = download_counts(plan, failed=[IDS[0]], stopped=[IDS[0]])
    assert counts["failed"] == 0 and counts["stopped"] == 1 and counts["new"] == 1
