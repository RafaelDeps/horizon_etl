"""run_weekly finalizes the SQLite file after the last phase (spec 018, US2)."""

from unittest.mock import MagicMock, call, patch

import pytest

import src.flows.pipelines.weekly_orchestrator as wo

_DB_URL = "sqlite:///db/horizon.db"


def _result(name, ok=True, critical=False):
    return {"name": name, "ok": ok, "rc": 0 if ok else 1, "critical": critical}


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    m = MagicMock()
    m.finalize.return_value = {"finalized": True, "journal_mode": "delete"}
    return m


def _run(manager, phase_results):
    manager.run_phase.side_effect = phase_results
    with (
        patch.object(wo, "_run_phase", manager.run_phase),
        patch.object(wo, "_notify", manager.notify),
        patch.object(wo, "finalize_sqlite_database", manager.finalize),
    ):
        return wo.run_weekly()


def test_finalize_runs_once_after_every_phase(manager):
    results = [_result(name) for name, *_ in wo._PHASES]

    rc = _run(manager, results)

    assert rc == 0
    assert manager.finalize.call_args_list == [call(_DB_URL)]
    names = [c[0] for c in manager.mock_calls]
    assert names.index("finalize") == len(wo._PHASES)
    assert names.count("run_phase") == len(wo._PHASES)


def test_finalize_still_runs_when_a_critical_phase_fails(manager):
    results = [_result(name) for name, *_ in wo._PHASES]
    results[0] = _result(results[0]["name"], ok=False, critical=True)

    rc = _run(manager, results)

    assert rc == 1
    manager.finalize.assert_called_once_with(_DB_URL)


def test_failed_finalize_does_not_change_the_exit_code(manager):
    manager.finalize.return_value = {
        "finalized": False,
        "reason": "database is locked",
    }
    results = [_result(name) for name, *_ in wo._PHASES]

    rc = _run(manager, results)

    assert rc == 0


def test_failed_finalize_reaches_the_telegram_summary(manager):
    failed = {"finalized": False, "reason": "database is locked"}
    manager.finalize.return_value = failed
    results = [_result(name) for name, *_ in wo._PHASES]

    _run(manager, results)

    assert manager.notify.call_args.kwargs.get("finalize") == failed


def test_notify_adds_a_line_only_for_a_real_finalize_failure():
    results = [_result("sigpesq")]
    with patch("src.notifications.telegram.send_telegram_message") as send:
        wo._notify(results, [], finalize={"finalized": False, "reason": "locked"})
        wo._notify(
            results,
            [],
            finalize={
                "finalized": False,
                "reason": "not a SQLite database",
                "skipped": True,
            },
        )
        wo._notify(results, [], finalize={"finalized": True})

    texts = [c.args[0] for c in send.call_args_list]
    assert "SQLite finalize falhou: locked" in texts[0]
    assert "SQLite finalize" not in texts[1]
    assert "SQLite finalize" not in texts[2]
