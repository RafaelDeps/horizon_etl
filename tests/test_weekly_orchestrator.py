"""Tests for the process-isolated weekly orchestrator.

Verifies the property that motivated it: one phase crashing (segfault,
non-zero exit, or timeout) must not stop later phases, while a failure in a
critical phase must still make the whole run exit non-zero.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

import src.flows.pipelines.weekly_orchestrator as wo


@pytest.fixture(autouse=True)
def _no_real_sqlite_finalize():
    """run_weekly finalizes DATABASE_URL after the phases; these tests fake the
    phases, so keep that step away from the real db/horizon.db."""
    with patch.object(
        wo, "finalize_sqlite_database", return_value={"finalized": True}
    ) as finalize:
        yield finalize


def test_extract_project_files_is_a_fixed_phase_before_enrich_projects():
    names = [p[0] for p in wo._PHASES]
    assert "extract_project_files" in names
    assert "enrich_projects" in names
    assert names.index("extract_project_files") < names.index("enrich_projects")


def test_consolidate_duplicates_phase_runs_before_canonical_export():
    names = [p[0] for p in wo._PHASES]
    assert "consolidate_duplicates" in names
    assert "export_canonical" in names
    assert names.index("consolidate_duplicates") < names.index("export_canonical")
    entry = next(phase for phase in wo._PHASES if phase[0] == "consolidate_duplicates")
    assert (
        entry[4] == "app"
    ), "the dedup phase writes to the DB; it must run under app.py"


def _fake_run_factory(fail_cmd=None, rc=1, timeout_cmd=None, seen=None):
    def fake_run(argv, timeout=None):
        cmd = argv[2]
        if seen is not None:
            seen.append(cmd)
        if timeout_cmd and cmd == timeout_cmd:
            raise subprocess.TimeoutExpired(argv, timeout)
        m = MagicMock()
        m.returncode = rc if cmd == fail_cmd else 0
        return m

    return fake_run


def test_describe_rc_signal_and_exit():
    assert wo._describe_rc(139) == "killed by signal 11"
    assert wo._describe_rc(-11) == "killed by signal 11"
    assert wo._describe_rc(0) == "exit 0"
    assert wo._describe_rc(None) == "timeout"


def test_signal_death_retries_once_and_self_heals():
    codes = iter([-11, 0])  # SIGSEGV on first attempt, success on retry
    calls = []

    def fake_run(argv, timeout=None):
        calls.append(1)
        return MagicMock(returncode=next(codes))

    with patch.object(wo.subprocess, "run", side_effect=fake_run):
        rc = wo._run_phase_subprocess(["python", "-m", "x"], 60, "t")
    assert rc == 0
    assert len(calls) == 2


def test_signal_death_retries_once_then_keeps_signal():
    codes = iter([-11, -11])
    calls = []

    def fake_run(argv, timeout=None):
        calls.append(1)
        return MagicMock(returncode=next(codes))

    with patch.object(wo.subprocess, "run", side_effect=fake_run):
        rc = wo._run_phase_subprocess(["python", "-m", "x"], 60, "t")
    assert rc == -11
    assert len(calls) == 2


def test_ordinary_nonzero_exit_is_not_retried():
    calls = []

    def fake_run(argv, timeout=None):
        calls.append(1)
        return MagicMock(returncode=1)

    with patch.object(wo.subprocess, "run", side_effect=fake_run):
        rc = wo._run_phase_subprocess(["python", "-m", "x"], 60, "t")
    assert rc == 1
    assert len(calls) == 1  # deterministic errors must not be masked by a retry


def test_timeout_is_not_retried():
    calls = []

    def fake_run(argv, timeout=None):
        calls.append(1)
        raise subprocess.TimeoutExpired(argv, timeout)

    with patch.object(wo.subprocess, "run", side_effect=fake_run):
        rc = wo._run_phase_subprocess(["python", "-m", "x"], 60, "t")
    assert rc is None
    assert len(calls) == 1


def test_noncritical_segfault_does_not_stop_later_phases():
    seen = []
    fake = _fake_run_factory(fail_cmd="ingest_lattes_projects", rc=139, seen=seen)
    with (
        patch("src.notifications.telegram.send_telegram_message", return_value=True),
        patch.object(wo.subprocess, "run", side_effect=fake),
    ):
        rc = wo.run_weekly()
    # non-critical crash -> overall success, and everything after it still ran
    assert rc == 0
    after = seen[seen.index("ingest_lattes_projects") + 1 :]
    assert "export_canonical" in after
    assert "anonymize_backfill" in after


def test_critical_export_failure_fails_run():
    with (
        patch("src.notifications.telegram.send_telegram_message", return_value=True),
        patch.object(
            wo.subprocess,
            "run",
            side_effect=_fake_run_factory(fail_cmd="export_canonical"),
        ),
    ):
        assert wo.run_weekly() == 1


def test_all_ok_returns_zero():
    with (
        patch("src.notifications.telegram.send_telegram_message", return_value=True),
        patch.object(wo.subprocess, "run", side_effect=_fake_run_factory()),
    ):
        assert wo.run_weekly() == 0


def test_critical_timeout_fails_but_later_phases_still_run():
    seen = []
    with (
        patch("src.notifications.telegram.send_telegram_message", return_value=True),
        patch.object(
            wo.subprocess,
            "run",
            side_effect=_fake_run_factory(timeout_cmd="sigpesq", seen=seen),
        ),
    ):
        rc = wo.run_weekly()
    assert rc == 1
    assert "export_canonical" in seen  # isolation: sigpesq timeout didn't abort the run


def test_telegram_failure_never_changes_outcome():
    with (
        patch(
            "src.notifications.telegram.send_telegram_message",
            side_effect=RuntimeError("boom"),
        ),
        patch.object(wo.subprocess, "run", side_effect=_fake_run_factory()),
    ):
        assert wo.run_weekly() == 0


def test_campus_is_forwarded_to_cnpq_sync_and_export_canonical():
    captured = []

    def fake_run(argv, timeout=None):
        captured.append(argv)
        m = MagicMock()
        m.returncode = 0
        return m

    with (
        patch("src.notifications.telegram.send_telegram_message", return_value=True),
        patch.object(wo.subprocess, "run", side_effect=fake_run),
    ):
        assert wo.run_weekly(campus_name="Serra", output_dir="data/exports") == 0

    cnpq = next(a for a in captured if "cnpq_sync" in a)
    export = next(
        a for a in captured if a[-1] == "export_canonical" or "export_canonical" in a
    )
    # cnpq_sync receives campus as trailing arg
    assert cnpq[-1] == "Serra"
    # export_canonical receives output_dir then campus
    assert export[-1] == "Serra"
    assert export[-2] == "data/exports"


# --- Spec 024: portals given up ------------------------------------------


def _cnpq_stop_entry():
    return {
        "source": "cnpq",
        "reason": "failures_in_a_row",
        "limit": 8,
        "budget_s": 2700,
        "stopped_at": "2026-10-29T22:38:21Z",
        "elapsed_s": 289.4,
        "failures_total": 8,
        "successes_total": 0,
        "counts": {
            "new": 0,
            "refreshed": 0,
            "reused": 344,
            "failed": 6,
            "reused_after_failure": 6,
            "stopped": 81,
        },
    }


def _run_with_telegram(side_effect):
    sent = []
    with (
        patch(
            "src.notifications.telegram.send_telegram_message",
            side_effect=lambda text: sent.append(text) or True,
        ),
        patch.object(wo.subprocess, "run", side_effect=side_effect),
    ):
        rc = wo.run_weekly()
    return rc, sent


def test_a_stale_portal_stop_report_is_cleared_before_the_phases():
    import src.flows.portal_stops as portal_stops

    portal_stops.record_portal_stop(
        "cnpq", MagicMock(summary=lambda: {"reason": "x"}), {}
    )
    seen = []

    def fake(cmd, **kwargs):
        seen.append(portal_stops.read_portal_stops())
        return _fake_run_factory()(cmd, **kwargs)

    rc, sent = _run_with_telegram(fake)
    assert rc == 0 and seen[0] == {}
    assert "portal abandonado" not in sent[0]


def test_a_portal_given_up_shows_in_the_summary_and_keeps_the_exit_code():
    import src.flows.portal_stops as portal_stops
    from src.core.logic.atomic_io import atomic_write_json

    def fake(cmd, **kwargs):
        if "cnpq_sync" in cmd:
            atomic_write_json(
                portal_stops.PORTAL_STOPS_PATH,
                {"version": 1, "stops": {"cnpq": _cnpq_stop_entry()}},
            )
        return _fake_run_factory()(cmd, **kwargs)

    lines = []
    from loguru import logger

    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        rc, sent = _run_with_telegram(fake)
    finally:
        logger.remove(sink)
    assert rc == 0
    expected = (
        "⚠ cnpq: portal given up (failures_in_a_row, limit 8) after 289 s; "
        "81 not tried, 350 from stored copies, 6 failed"
    )
    assert any(expected in line for line in lines)
    assert (
        "⚠️ cnpq: portal abandonado (8 falhas seguidas) após 289 s; "
        "81 não tentados, 350 das cópias guardadas, 6 falhas"
    ) in sent[0]


def test_an_access_check_retry_shows_in_the_summary_and_keeps_the_exit_code():
    # Spec 025: one line after the stop lines, in the log and in Telegram.
    import src.flows.portal_stops as portal_stops

    def fake(cmd, **kwargs):
        if "lattes_download" in cmd:
            portal_stops.record_access_check_retry(
                "lattes",
                {
                    "source": "lattes",
                    "pause_s": 300.0,
                    "workers": 1,
                    "retried": 38,
                    "recovered": 35,
                    "not_tried": 0,
                },
            )
        return _fake_run_factory()(cmd, **kwargs)

    lines = []
    from loguru import logger

    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        rc, sent = _run_with_telegram(fake)
    finally:
        logger.remove(sink)
    assert rc == 0
    expected = (
        "↻ lattes: 38 access check pages asked again after 5 min; "
        "35 recovered, 3 still missing"
    )
    assert any(expected in line for line in lines)
    assert (
        "🔁 lattes: 38 páginas de captcha pedidas de novo após 5 min; "
        "35 recuperadas, 3 ainda faltando"
    ) in sent[0]


def test_no_access_check_retry_means_no_retry_line():
    rc, sent = _run_with_telegram(_fake_run_factory())
    assert rc == 0 and "captcha" not in sent[0]
    assert wo._access_check_retry_lines({}) == []


def test_a_time_budget_line():
    entry = dict(_cnpq_stop_entry(), reason="time_budget")
    line = wo._portal_stop_lines({"cnpq": entry})[0]
    assert "(time_budget, 45 min)" in line
    assert "(limite de 45 min)" in wo._portal_stop_lines({"cnpq": entry}, True)[0]


def test_no_report_means_no_extra_line():
    rc, sent = _run_with_telegram(_fake_run_factory())
    assert rc == 0 and "⚠️" not in sent[0]


# --- Spec 029: the archive is its own critical phase, gated on earlier ones ---


def _run_weekly_with(fail=(), timeout=(), seen=None):
    """Runs the weekly with these phase commands failing (exit 1) or timing out."""

    def fake(argv, timeout=None):
        cmd = argv[2]
        if seen is not None:
            seen.append(cmd)
        if cmd in timeout_cmds:
            raise subprocess.TimeoutExpired(argv, timeout)
        return MagicMock(returncode=1 if cmd in fail else 0)

    timeout_cmds = set(timeout)
    with (
        patch("src.notifications.telegram.send_telegram_message", return_value=True),
        patch.object(wo.subprocess, "run", side_effect=fake),
    ):
        return wo.run_weekly()


def test_zip_exports_phase_follows_the_graph_and_is_critical():
    names = [p[0] for p in wo._PHASES]
    assert names.index("zip_exports") == names.index("people_relationship_graph") + 1
    entry = next(p for p in wo._PHASES if p[0] == "zip_exports")
    assert entry[1] == ["zip_exports"]
    assert entry[2] == 900
    assert entry[3] is True
    assert entry[4] == "app"


def test_zip_exports_receives_the_output_folder():
    captured = []

    def fake(argv, timeout=None):
        captured.append(argv)
        return MagicMock(returncode=0)

    with (
        patch("src.notifications.telegram.send_telegram_message", return_value=True),
        patch.object(wo.subprocess, "run", side_effect=fake),
    ):
        assert wo.run_weekly(output_dir="somewhere") == 0

    zip_call = next(a for a in captured if a[2] == "zip_exports")
    assert zip_call[-1] == "somewhere"


def test_zip_exports_runs_when_everything_before_it_passed():
    seen = []
    assert _run_weekly_with(seen=seen) == 0
    assert "zip_exports" in seen


@pytest.mark.parametrize(
    "failing",
    ["knowledge_areas_mart", "initiatives_analytics_mart", "people_relationship_graph"],
)
def test_a_failed_mart_or_graph_skips_the_archive_but_the_run_stays_green(failing):
    command = {
        "knowledge_areas_mart": "ka_mart",
        "initiatives_analytics_mart": "analytics_mart",
        "people_relationship_graph": "people_graph",
    }[failing]
    seen = []

    rc = _run_weekly_with(fail=[command], seen=seen)

    assert rc == 0
    assert "zip_exports" not in seen
    assert "anonymize_backfill" in seen  # later phases still run


def test_a_failed_export_canonical_skips_the_archive_and_fails_the_run():
    seen = []

    rc = _run_weekly_with(fail=["export_canonical"], seen=seen)

    assert rc == 1
    assert "zip_exports" not in seen


def test_an_earlier_critical_failure_skips_the_archive():
    seen = []

    rc = _run_weekly_with(timeout=["sigpesq"], seen=seen)

    assert rc == 1
    assert "zip_exports" not in seen


def test_a_failed_archive_fails_the_run():
    assert _run_weekly_with(fail=["zip_exports"]) == 1


def test_a_noncritical_failure_after_the_archive_leaves_exit_zero():
    seen = []

    rc = _run_weekly_with(fail=["src.scripts.analyze_venues"], seen=seen)

    assert rc == 0
    assert "zip_exports" in seen


def test_a_portal_early_stop_does_not_block_the_archive():
    seen = []
    stop = {"lattes": {"reason": "failures_in_a_row", "counts": {}}}
    with patch.object(wo, "read_portal_stops", return_value=stop):
        rc = _run_weekly_with(seen=seen)

    assert rc == 0
    assert "zip_exports" in seen


def test_the_skipped_archive_is_reported_as_skipped():
    from loguru import logger

    messages = []
    sink = logger.add(lambda m: messages.append(str(m)))
    try:
        _run_weekly_with(fail=["ka_mart"])
    finally:
        logger.remove(sink)

    assert any("zip_exports" in m and "skipped" in m for m in messages)
