"""Spec 031: the pure logic of the paced extraction retry."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
from loguru import logger

from src.core.logic.extraction_pacing import (
    MAX_WAIT_S,
    ExtractionPacingSettings,
    WaitBudget,
    backoff_s,
    extraction_pacing_settings,
    is_rate_limit,
    retry_after_s,
)

R = "HORIZON_EXTRACT_RETRIES"
P = "HORIZON_EXTRACT_PAUSE_S"
F = "HORIZON_EXTRACT_FIRST_WAIT_S"
B = "HORIZON_EXTRACT_WAIT_BUDGET_MIN"


class StatusError(Exception):
    def __init__(self, status_code, headers=None):
        super().__init__(f"API error occurred: Status {status_code}")
        self.status_code = status_code
        self.headers = headers or {}


class Response:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class RawOnlyError(Exception):
    def __init__(self, status_code, headers=None):
        super().__init__("refused")
        self.raw_response = Response(status_code, headers)


@pytest.fixture
def warnings():
    messages = []
    sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    yield messages
    logger.remove(sink)


# ------------------------------------------------------------------ settings
def test_defaults():
    assert extraction_pacing_settings({}) == ExtractionPacingSettings(
        retries=3, pause_s=2.0, first_wait_s=30.0, wait_budget_s=1200.0
    )


def test_blank_values_give_the_defaults():
    blank = {R: " ", P: "", F: "", B: " "}
    assert extraction_pacing_settings(blank) == ExtractionPacingSettings()


def test_zero_turns_each_knob_off():
    settings = extraction_pacing_settings({R: "0", P: "0", F: "0", B: "0"})
    assert settings == ExtractionPacingSettings(0, 0.0, 0.0, 0.0)


def test_decimal_values():
    settings = extraction_pacing_settings({P: "0.5", B: "0.5", F: "1.5"})
    assert settings.pause_s == 0.5
    assert settings.first_wait_s == 1.5
    assert settings.wait_budget_s == pytest.approx(30.0)


@pytest.mark.parametrize(
    "name, raw",
    [(R, "abc"), (R, "-1"), (R, "1.5"), (P, "abc"), (P, "-2"), (F, "inf"), (B, "nan")],
)
def test_an_invalid_value_is_logged_and_replaced(warnings, name, raw):
    assert extraction_pacing_settings({name: raw}) == ExtractionPacingSettings()
    assert any(f"Invalid {name}" in m for m in warnings)


def test_a_given_mapping_is_read_instead_of_the_environment(monkeypatch):
    monkeypatch.setenv(R, "7")
    assert extraction_pacing_settings({}).retries == 3
    assert extraction_pacing_settings().retries == 7


# ------------------------------------------------------------- is_rate_limit
def test_a_429_status_is_a_rate_limit():
    assert is_rate_limit(StatusError(429))
    assert is_rate_limit(RawOnlyError(429))


def test_a_429_in_the_cause_chain_is_a_rate_limit():
    try:
        try:
            raise StatusError(429)
        except StatusError as inner:
            raise RuntimeError("extraction failed") from inner
    except RuntimeError as outer:
        assert is_rate_limit(outer)


def test_other_failures_are_not_a_rate_limit():
    assert not is_rate_limit(StatusError(500))
    assert not is_rate_limit(RawOnlyError(400))
    assert not is_rate_limit(ValueError("bad pdf"))


def test_the_message_decides_only_when_no_status_is_found():
    assert is_rate_limit(Exception("API error occurred: Status 429. Body: {}"))
    # A real status wins over the text.
    error = StatusError(500)
    error.args = ("Status 429 mentioned",)
    assert not is_rate_limit(error)


# ------------------------------------------------------------- retry_after_s
def test_retry_after_in_seconds():
    assert retry_after_s(StatusError(429, {"retry-after": "12"})) == 12.0
    assert retry_after_s(RawOnlyError(429, {"Retry-After": "3"})) == 3.0


def test_retry_after_as_an_http_date():
    now = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)
    header = format_datetime(now + timedelta(seconds=30), usegmt=True)
    assert retry_after_s(StatusError(429, {"retry-after": header}), now) == 30.0


@pytest.mark.parametrize(
    "headers", [{}, {"retry-after": "soon"}, {"retry-after": "-5"}]
)
def test_an_absent_or_bad_retry_after_is_ignored(headers):
    assert retry_after_s(StatusError(429, headers)) is None


# ----------------------------------------------------------------- backoff_s
def test_the_wait_doubles_from_the_first_wait():
    settings = ExtractionPacingSettings()
    assert [backoff_s(n, settings, None) for n in (1, 2, 3)] == [30.0, 60.0, 120.0]


def test_a_longer_retry_after_wins():
    assert backoff_s(1, ExtractionPacingSettings(), 90.0) == 90.0
    assert backoff_s(2, ExtractionPacingSettings(), 10.0) == 60.0


def test_the_wait_is_capped():
    assert backoff_s(10, ExtractionPacingSettings(), None) == MAX_WAIT_S
    assert backoff_s(1, ExtractionPacingSettings(), 3600.0) == MAX_WAIT_S


# ---------------------------------------------------------------- WaitBudget
def test_the_budget_allows_up_to_its_edge():
    budget = WaitBudget(90.0)
    assert budget.allows(90.0)
    budget.spend(30.0)
    budget.spend(60.0)
    assert budget.spent_s == 90.0
    assert budget.allows(0.0)
    assert not budget.allows(0.1)


def test_a_zero_budget_allows_no_wait():
    assert not WaitBudget(0.0).allows(30.0)
