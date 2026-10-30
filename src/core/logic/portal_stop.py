"""When to stop downloading from a portal that blocks (spec 024, research R1–R4).

A run gives a portal up when it fails a number of requests in a row with no
success between them, or, for CNPq, when its downloads run past a time
budget. After that no new request starts, and the run finishes from the raw
copies kept by spec 023 (older data is better than none).

Pure logic: no file or network access. The download threads share one
``PortalStop`` per source and ask it before each request.
"""

import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional

from loguru import logger

ENABLED_ENV = "HORIZON_PORTAL_EARLY_STOP"
CNPQ_FAILURES_ENV = "HORIZON_CNPQ_STOP_AFTER_FAILURES"
CNPQ_BUDGET_ENV = "HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN"
LATTES_FAILURES_ENV = "HORIZON_LATTES_STOP_AFTER_FAILURES"

# R1: a CNPq attempt already holds the library's 3 tries (~95 s on a hung
# portal); 8 in a row stopped run 40966298828 about 5 min in. R3: 5 access
# check pages in a row. R2: a full healthy download took 15–25 min.
DEFAULT_CNPQ_FAILURES = 8
DEFAULT_CNPQ_BUDGET_MIN = 45.0
DEFAULT_LATTES_FAILURES = 5

FAILURES_IN_A_ROW = "failures_in_a_row"
TIME_BUDGET = "time_budget"


class PortalStop:
    """The stop decision of one source in one run; thread safe."""

    def __init__(
        self,
        source: str,
        max_failures: int = 0,
        budget_s: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.source = source
        self.max_failures = max_failures
        self.budget_s = budget_s
        self._clock = clock
        self._lock = threading.Lock()
        self._event = threading.Event()
        self.started_at: Optional[float] = None
        self.failures_in_a_row = 0
        self.failures_total = 0
        self.successes_total = 0
        self.reason: Optional[str] = None
        self.stopped_at: Optional[str] = None
        self.elapsed_s: Optional[float] = None

    @property
    def stopped(self) -> bool:
        return self._event.is_set()

    def start(self) -> None:
        with self._lock:
            if self.started_at is None:
                self.started_at = self._clock()

    def should_stop(self) -> bool:
        if self._event.is_set():
            return True
        with self._lock:
            if (
                self.budget_s > 0
                and self.started_at is not None
                and self._clock() - self.started_at >= self.budget_s
            ):
                self._stop(TIME_BUDGET)
        return self._event.is_set()

    def record(self, success: bool) -> None:
        with self._lock:
            if success:
                self.successes_total += 1
                self.failures_in_a_row = 0
                return
            self.failures_total += 1
            self.failures_in_a_row += 1
            if self.max_failures > 0 and self.failures_in_a_row >= self.max_failures:
                self._stop(FAILURES_IN_A_ROW)

    def wait(self, seconds: float) -> bool:
        """Waits up to ``seconds``, or until the stop; True when stopped."""
        return self._event.wait(timeout=max(0.0, seconds))

    def summary(self) -> dict:
        with self._lock:
            return {
                "source": self.source,
                "reason": self.reason,
                "limit": self.max_failures,
                "budget_s": self.budget_s,
                "stopped_at": self.stopped_at,
                "elapsed_s": self.elapsed_s,
                "failures_total": self.failures_total,
                "successes_total": self.successes_total,
            }

    def _stop(self, reason: str) -> None:
        # Caller holds the lock.
        if self._event.is_set():
            return
        self.reason = reason
        self.stopped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        started = self.started_at if self.started_at is not None else self._clock()
        self.elapsed_s = round(self._clock() - started, 1)
        self._event.set()
        limit = (
            f"{self.max_failures} failures"
            if reason == FAILURES_IN_A_ROW
            else f"{self.budget_s:g} s"
        )
        logger.warning(
            "portal given up: {} reason={} limit={} after={}s failures={} "
            "successes={}",
            self.source,
            reason,
            limit,
            self.elapsed_s,
            self.failures_total,
            self.successes_total,
        )


@dataclass(frozen=True)
class PortalStopSettings:
    enabled: bool = True
    cnpq_failures: int = DEFAULT_CNPQ_FAILURES
    cnpq_budget_s: float = DEFAULT_CNPQ_BUDGET_MIN * 60
    lattes_failures: int = DEFAULT_LATTES_FAILURES

    def for_source(
        self, source: str, clock: Callable[[], float] = time.monotonic
    ) -> Optional[PortalStop]:
        """The stop of ``source``, or ``None`` (today's behaviour) when the
        feature is off or every rule of the source is 0."""
        if not self.enabled:
            return None
        if source == "cnpq":
            failures, budget = self.cnpq_failures, self.cnpq_budget_s
        elif source == "lattes":
            failures, budget = self.lattes_failures, 0.0
        else:
            raise ValueError(f"unknown portal source: {source}")
        if failures <= 0 and budget <= 0:
            return None
        return PortalStop(source, failures, budget, clock=clock)


def _number(env: Mapping[str, str], name: str, default: float, integer: bool):
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


def portal_stop_settings(env: Optional[Mapping[str, str]] = None) -> PortalStopSettings:
    """The four ``HORIZON_*`` variables (research R6); blank means the
    default, an invalid value is logged and replaced by the default, and 0
    turns a rule off. Never raises."""
    env = os.environ if env is None else env
    raw = (env.get(ENABLED_ENV) or "").strip().lower()
    enabled = True
    if raw in {"0", "false", "no"}:
        enabled = False
    elif raw not in {"", "1", "true", "yes"}:
        logger.warning("Invalid {}={!r}; early stop stays on", ENABLED_ENV, raw)
    return PortalStopSettings(
        enabled=enabled,
        cnpq_failures=_number(env, CNPQ_FAILURES_ENV, DEFAULT_CNPQ_FAILURES, True),
        cnpq_budget_s=_number(env, CNPQ_BUDGET_ENV, DEFAULT_CNPQ_BUDGET_MIN, False)
        * 60,
        lattes_failures=_number(
            env, LATTES_FAILURES_ENV, DEFAULT_LATTES_FAILURES, True
        ),
    )
