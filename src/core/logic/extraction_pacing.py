"""Paced retry of the project PDF extraction (spec 031, research R2-R5).

The extraction service (Mistral) refuses calls with HTTP 429 when they come
too fast. A refused document is asked again in the same run after a growing
wait, calls are spaced by a pause, and a wait budget bounds the whole stage
so a long outage cannot hold the weekly run.

Pure logic: no file, network or clock access, and no import of ``mistralai``
(an optional dependency): errors are read by duck typing.
"""

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Mapping, Optional

from loguru import logger

RETRIES_ENV = "HORIZON_EXTRACT_RETRIES"
PAUSE_ENV = "HORIZON_EXTRACT_PAUSE_S"
FIRST_WAIT_ENV = "HORIZON_EXTRACT_FIRST_WAIT_S"
BUDGET_ENV = "HORIZON_EXTRACT_WAIT_BUDGET_MIN"

# R3: on 2026-11-09 the 26 calls of a fork run came within about 40 s and 25
# got HTTP 429, so the limit is per short period: tens of seconds of wait,
# doubling, recover it; 20 min bound a real outage well inside the 2 h phase.
DEFAULT_RETRIES = 3
DEFAULT_PAUSE_S = 2.0
DEFAULT_FIRST_WAIT_S = 30.0
DEFAULT_BUDGET_MIN = 20.0
# A wrong Retry-After must not stall the stage.
MAX_WAIT_S = 300.0

_RATE_LIMIT_STATUS = 429
_CHAIN_DEPTH = 5


@dataclass(frozen=True)
class ExtractionPacingSettings:
    retries: int = DEFAULT_RETRIES
    pause_s: float = DEFAULT_PAUSE_S
    first_wait_s: float = DEFAULT_FIRST_WAIT_S
    wait_budget_s: float = DEFAULT_BUDGET_MIN * 60


def _read(env: Mapping[str, str], name: str, default, integer: bool):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw) if integer else float(raw)
    except ValueError:
        value = -1
    if value < 0 or (not integer and not math.isfinite(value)):
        logger.warning("Invalid {}={!r}; using {}", name, raw, default)
        return default
    return value


def extraction_pacing_settings(
    env: Optional[Mapping[str, str]] = None,
) -> ExtractionPacingSettings:
    """``HORIZON_EXTRACT_RETRIES`` (default 3; 0 turns the retry off),
    ``HORIZON_EXTRACT_PAUSE_S`` (default 2; 0 means no pause),
    ``HORIZON_EXTRACT_FIRST_WAIT_S`` (default 30, doubling on each retry) and
    ``HORIZON_EXTRACT_WAIT_BUDGET_MIN`` (default 20; 0 stops at the first
    refusal). Blank means the default; an invalid value is logged and replaced
    by the default. Never raises."""
    env = os.environ if env is None else env
    return ExtractionPacingSettings(
        retries=_read(env, RETRIES_ENV, DEFAULT_RETRIES, True),
        pause_s=_read(env, PAUSE_ENV, DEFAULT_PAUSE_S, False),
        first_wait_s=_read(env, FIRST_WAIT_ENV, DEFAULT_FIRST_WAIT_S, False),
        wait_budget_s=_read(env, BUDGET_ENV, DEFAULT_BUDGET_MIN, False) * 60,
    )


def _chain(exc: BaseException):
    """``exc`` and the exceptions it was raised from, at most 5."""
    seen = []
    current: Optional[BaseException] = exc
    while current is not None and len(seen) < _CHAIN_DEPTH and current not in seen:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def _status(exc: BaseException) -> Optional[int]:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "raw_response", None), "status_code", None)
    return status if isinstance(status, int) else None


def is_rate_limit(exc: BaseException) -> bool:
    """R2: true when ``exc`` or one it was raised from carries HTTP 429. Only
    when no status is found anywhere, the SDK's message text decides."""
    statuses = [s for s in (_status(e) for e in _chain(exc)) if s is not None]
    if statuses:
        return _RATE_LIMIT_STATUS in statuses
    return f"Status {_RATE_LIMIT_STATUS}" in str(exc)


def _headers(exc: BaseException):
    headers = getattr(exc, "headers", None)
    if headers is None:
        headers = getattr(getattr(exc, "raw_response", None), "headers", None)
    return headers


def retry_after_s(
    exc: BaseException, now: Optional[datetime] = None
) -> Optional[float]:
    """The ``Retry-After`` the service sent, in seconds (delta or HTTP date);
    ``None`` when absent, unreadable or negative."""
    for error in _chain(exc):
        headers = _headers(error)
        if not headers:
            continue
        try:
            raw = headers.get("retry-after") or headers.get("Retry-After")
        except Exception:
            continue
        if not raw:
            continue
        raw = str(raw).strip()
        try:
            seconds = float(raw)
        except ValueError:
            try:
                when = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                return None
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - (now or datetime.now(timezone.utc))).total_seconds()
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return seconds
    return None


def backoff_s(
    retry: int, settings: ExtractionPacingSettings, retry_after: Optional[float]
) -> float:
    """R3: wait before retry ``retry`` (1-based): the growing wait or the
    service's own Retry-After, whichever is longer, capped at 5 min."""
    growing = settings.first_wait_s * 2 ** (retry - 1)
    return min(MAX_WAIT_S, max(growing, retry_after or 0.0))


class WaitBudget:
    """R5: the backoff waits one run may spend; the pauses do not count."""

    def __init__(self, total_s: float):
        self.total_s = total_s
        self.spent_s = 0.0

    def allows(self, wait_s: float) -> bool:
        return self.spent_s + wait_s <= self.total_s

    def spend(self, wait_s: float) -> None:
        self.spent_s += wait_s
