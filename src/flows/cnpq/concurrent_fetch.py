"""Concurrent fetching of CNPq group pages (spec 017).

Pure orchestration: worker threads only call the adapter's ``get_group_data``,
which talks to the DGP portal through dgp_cnpq_lib (each call opens its own
browser, as the library always did). Nothing here touches the database —
SQLite allows one writer, so the flow writes every group itself, in order.
"""

import random
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

DEFAULT_WORKERS = 4

# dgp_cnpq_lib already retries a page 3 times, 1-10 s apart; that is too short
# for the reset bursts the portal produced (85 groups in 8 minutes on
# 2026-10-22). These ETL-level attempts wait longer, outside the gate.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (30.0, 90.0)
BACKOFF_JITTER = 0.2

# Failure-burst rule: this many failures within the window halve the limit;
# a quiet period without failures restores it one step at a time.
BURST_FAILURES = 4
BURST_WINDOW_SECONDS = 60.0
RESTORE_AFTER_SECONDS = 120.0


@dataclass
class FetchOutcome:
    index: int
    group_info: Dict[str, Any]
    data: Optional[Dict[str, Any]]
    attempts: int


def resolve_workers(value: Optional[str], default: int = DEFAULT_WORKERS) -> int:
    """HORIZON_CNPQ_WORKERS: a positive integer; anything else falls back."""
    if value is None or str(value).strip() == "":
        return default
    try:
        workers = int(str(value).strip())
    except ValueError:
        workers = 0
    if workers < 1:
        logger.warning(
            f"Invalid HORIZON_CNPQ_WORKERS={value!r}; using {default} workers."
        )
        return default
    return workers


class AdaptiveGate:
    """Bounds the page fetches in flight to ``limit`` (<= ``max_workers``).

    Clustered failures halve ``limit`` (never below 1) so the phase backs off
    instead of hammering the portal; after a quiet period it climbs back by one.
    """

    def __init__(self, max_workers: int, clock: Callable[[], float] = time.monotonic):
        self.max_workers = max_workers
        self.limit = max_workers
        self.in_flight = 0
        self.reductions = 0
        self._clock = clock
        self._cond = threading.Condition()
        self._failures: deque = deque()
        self._last_change: Optional[float] = None

    def record_failure(self) -> None:
        with self._cond:
            now = self._clock()
            self._failures.append(now)
            while self._failures and now - self._failures[0] > BURST_WINDOW_SECONDS:
                self._failures.popleft()
            self._last_change = now
            if len(self._failures) >= BURST_FAILURES and self.limit > 1:
                old = self.limit
                self.limit = max(1, self.limit // 2)
                self.reductions += 1
                self._failures.clear()
                logger.warning(
                    f"CNPq fetch: failures clustering, concurrency {old} → {self.limit}"
                )

    def _maybe_restore(self) -> None:
        if self._last_change is None or self.limit >= self.max_workers:
            return
        now = self._clock()
        if now - self._last_change >= RESTORE_AFTER_SECONDS:
            old = self.limit
            self.limit += 1
            self._last_change = now
            logger.info(f"CNPq fetch: portal calm, concurrency {old} → {self.limit}")

    @contextmanager
    def slot(self):
        with self._cond:
            self._maybe_restore()
            while self.in_flight >= self.limit:
                self._cond.wait(timeout=1.0)
            self.in_flight += 1
        try:
            yield
        finally:
            with self._cond:
                self.in_flight -= 1
                self._cond.notify_all()


class FetchBatch:
    """Fetches started up front; the writer consumes them by index, in order."""

    def __init__(self, executor: ThreadPoolExecutor, futures: List[Future], gate):
        self._executor = executor
        self._futures = futures
        self.gate = gate

    def outcome(self, index: int) -> FetchOutcome:
        return self._futures[index].result()

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)


def fetch_with_retries(
    index: int,
    group_info: Dict[str, Any],
    adapter_factory: Callable[[], Any],
    gate: AdaptiveGate,
    sleep: Callable[[float], None],
    rng: random.Random,
) -> FetchOutcome:
    """Up to MAX_ATTEMPTS fetches; "no data" is the retry signal (the adapter
    swallows the cause). The back-off sleep happens outside the gate."""
    data = None
    attempt = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        with gate.slot():
            data = adapter_factory().get_group_data(group_info["url"])
        if data:
            break
        gate.record_failure()
        if attempt < MAX_ATTEMPTS:
            base = BACKOFF_SECONDS[attempt - 1]
            sleep(base * rng.uniform(1 - BACKOFF_JITTER, 1 + BACKOFF_JITTER))
    return FetchOutcome(index=index, group_info=group_info, data=data, attempts=attempt)


def fetch_all(
    groups: List[Dict[str, Any]],
    adapter_factory: Callable[[], Any],
    max_workers: int,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    rng: Optional[random.Random] = None,
) -> FetchBatch:
    gate = AdaptiveGate(max_workers, clock=clock)
    rng = rng or random.Random()
    # A few extra threads beyond the gate, so groups waiting out a retry
    # back-off never hold the slots other fetches need.
    executor = ThreadPoolExecutor(
        max_workers=max_workers + 4, thread_name_prefix="cnpq-fetch"
    )
    futures = [
        executor.submit(fetch_with_retries, i, g, adapter_factory, gate, sleep, rng)
        for i, g in enumerate(groups)
    ]
    return FetchBatch(executor, futures, gate)
