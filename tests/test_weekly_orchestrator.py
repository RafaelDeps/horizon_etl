"""Tests for the process-isolated weekly orchestrator.

Verifies the property that motivated it: one phase crashing (segfault,
non-zero exit, or timeout) must not stop later phases, while a failure in a
critical phase must still make the whole run exit non-zero.
"""

import subprocess
from unittest.mock import MagicMock, patch

import src.flows.pipelines.weekly_orchestrator as wo


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
