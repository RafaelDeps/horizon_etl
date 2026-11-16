"""Spec 024: the rule that gives a portal up (failures in a row, time budget)."""

import threading
import time

import pytest

from src.core.logic.portal_stop import (
    FAILURES_IN_A_ROW,
    TIME_BUDGET,
    PortalStop,
    PortalStopSettings,
    portal_stop_settings,
)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_stops_at_exactly_n_failures_in_a_row():
    stop = PortalStop("cnpq", max_failures=3)
    stop.start()
    stop.record(False)
    stop.record(False)
    assert not stop.should_stop()
    stop.record(False)
    assert stop.should_stop() and stop.reason == FAILURES_IN_A_ROW
    assert stop.stopped_at.endswith("Z")


def test_a_success_resets_the_count():
    stop = PortalStop("cnpq", max_failures=3)
    for success in (False, False, True, False, False, True, False, False):
        stop.record(success)
    assert not stop.should_stop()
    assert stop.failures_total == 6 and stop.successes_total == 2


def test_time_budget_with_a_fake_clock():
    clock = Clock()
    stop = PortalStop("cnpq", max_failures=8, budget_s=60, clock=clock)
    assert not stop.should_stop()  # not started: no budget yet
    stop.start()
    clock.now += 59
    assert not stop.should_stop()
    clock.now += 1
    assert stop.should_stop() and stop.reason == TIME_BUDGET
    assert stop.elapsed_s == 60


def test_zero_turns_a_rule_off():
    clock = Clock()
    stop = PortalStop("cnpq", max_failures=0, budget_s=0, clock=clock)
    stop.start()
    for _ in range(100):
        stop.record(False)
    clock.now += 10**6
    assert not stop.should_stop()


def test_stays_stopped_and_only_counts_afterwards():
    stop = PortalStop("lattes", max_failures=1)
    stop.record(False)
    reason, at = stop.reason, stop.stopped_at
    stop.record(True)
    stop.record(False)
    assert stop.stopped and stop.reason == reason and stop.stopped_at == at
    assert stop.successes_total == 1 and stop.failures_total == 2


def test_wait_returns_at_once_when_stopped():
    stop = PortalStop("cnpq", max_failures=1)
    started = time.monotonic()
    assert stop.wait(0.05) is False
    threading.Timer(0.05, stop.record, args=(False,)).start()
    assert stop.wait(30) is True
    assert time.monotonic() - started < 5


def test_summary_fields():
    stop = PortalStop("cnpq", max_failures=1, budget_s=2700)
    stop.start()
    stop.record(False)
    summary = stop.summary()
    assert summary["source"] == "cnpq" and summary["reason"] == FAILURES_IN_A_ROW
    assert summary["limit"] == 1 and summary["budget_s"] == 2700
    assert summary["failures_total"] == 1 and summary["successes_total"] == 0


def test_threads_give_exact_counters_and_one_stop():
    stop = PortalStop("cnpq", max_failures=10**6)

    def work():
        for i in range(1000):
            stop.record(i % 2 == 0)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert stop.failures_total == 4000 and stop.successes_total == 4000
    assert not stop.stopped


def test_one_stop_among_threads(monkeypatch):
    warnings = []
    import src.core.logic.portal_stop as module

    monkeypatch.setattr(module.logger, "warning", lambda *a, **k: warnings.append(a))
    stop = PortalStop("cnpq", max_failures=5)
    threads = [
        threading.Thread(target=lambda: [stop.record(False) for _ in range(50)])
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert stop.stopped and len(warnings) == 1


def test_default_settings():
    settings = portal_stop_settings({})
    assert settings == PortalStopSettings()
    assert settings.cnpq_failures == 8 and settings.cnpq_budget_s == 2700
    assert settings.lattes_failures == 5 and settings.enabled


def test_settings_from_the_environment():
    settings = portal_stop_settings(
        {
            "HORIZON_CNPQ_STOP_AFTER_FAILURES": "2",
            "HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN": "0.5",
            "HORIZON_LATTES_STOP_AFTER_FAILURES": " 0 ",
        }
    )
    assert settings.cnpq_failures == 2 and settings.cnpq_budget_s == 30
    assert settings.lattes_failures == 0
    assert settings.for_source("lattes") is None
    assert settings.for_source("cnpq").max_failures == 2


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "nan"])
def test_invalid_values_fall_back_to_the_default(value, monkeypatch):
    warnings = []
    import src.core.logic.portal_stop as module

    monkeypatch.setattr(module.logger, "warning", lambda *a, **k: warnings.append(a))
    settings = portal_stop_settings(
        {
            "HORIZON_CNPQ_STOP_AFTER_FAILURES": value,
            "HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN": value if value != "1.5" else "x",
        }
    )
    assert settings.cnpq_failures == 8 and settings.cnpq_budget_s == 2700
    assert len(warnings) == 2


@pytest.mark.parametrize("value", ["0", "false", "No", "FALSE"])
def test_the_switch_turns_everything_off(value):
    settings = portal_stop_settings({"HORIZON_PORTAL_EARLY_STOP": value})
    assert not settings.enabled
    assert settings.for_source("cnpq") is None
    assert settings.for_source("lattes") is None


@pytest.mark.parametrize("value", ["", "1", "true", "yes", "maybe"])
def test_the_switch_stays_on(value):
    assert portal_stop_settings({"HORIZON_PORTAL_EARLY_STOP": value}).enabled


def test_lattes_has_no_budget():
    stop = PortalStopSettings(cnpq_budget_s=1).for_source("lattes")
    assert stop.budget_s == 0 and stop.max_failures == 5
