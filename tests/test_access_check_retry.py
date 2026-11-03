"""Spec 025: the settings of the second try for the Lattes access check pages."""

import pytest
from loguru import logger

from src.core.logic.access_check_retry import (
    AccessCheckRetrySettings,
    access_check_retry_settings,
)

W = "HORIZON_LATTES_RETRY_WORKERS"
P = "HORIZON_LATTES_RETRY_PAUSE_MIN"


@pytest.fixture
def warnings():
    messages = []
    sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    yield messages
    logger.remove(sink)


def test_defaults_are_one_worker_after_five_minutes():
    settings = access_check_retry_settings({})
    assert settings == AccessCheckRetrySettings(workers=1, pause_s=300.0)
    assert settings.enabled


def test_blank_values_give_the_defaults():
    assert access_check_retry_settings({W: " ", P: ""}) == AccessCheckRetrySettings()


def test_zero_workers_turns_it_off_and_a_zero_pause_means_no_wait():
    settings = access_check_retry_settings({W: "0", P: "0"})
    assert not settings.enabled
    assert settings.pause_s == 0


def test_the_pause_takes_decimal_minutes():
    assert access_check_retry_settings({P: "0.1"}).pause_s == pytest.approx(6.0)
    assert access_check_retry_settings({W: "3"}).workers == 3


@pytest.mark.parametrize(
    "name, raw", [(W, "abc"), (W, "-1"), (W, "1.5"), (P, "abc"), (P, "-2"), (P, "inf")]
)
def test_an_invalid_value_is_logged_and_replaced_by_the_default(warnings, name, raw):
    settings = access_check_retry_settings({name: raw})
    assert settings == AccessCheckRetrySettings()
    assert any(f"Invalid {name}" in m for m in warnings)


def test_the_given_mapping_is_read_instead_of_the_environment(monkeypatch):
    monkeypatch.setenv(W, "4")
    assert access_check_retry_settings({}).workers == 1
    assert access_check_retry_settings().workers == 4
