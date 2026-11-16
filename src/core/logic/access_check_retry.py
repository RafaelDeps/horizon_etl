"""A second try for the Lattes access check pages (spec 025, research R3, R6).

The Lattes portal sometimes serves its access check page (a reCAPTCHA)
instead of a curriculum, apparently at random per request. Such a request is
asked again once, at the end of the same download and after a pause, instead
of a week later. The access check is never answered or bypassed: the second
try is the same plain request, later.

Pure logic: no file or network access.
"""

import math
import os
from dataclasses import dataclass
from typing import Mapping, Optional

from loguru import logger

WORKERS_ENV = "HORIZON_LATTES_RETRY_WORKERS"
PAUSE_ENV = "HORIZON_LATTES_RETRY_PAUSE_MIN"

# R3: 38 of 435 requests were rejected on 2026-11-03, spread over 23 min with
# successes between them; one gentle worker after a short pause is the
# cheapest lever that leaves the CAPTCHA alone.
DEFAULT_WORKERS = 1
DEFAULT_PAUSE_MIN = 5.0


@dataclass(frozen=True)
class AccessCheckRetrySettings:
    workers: int = DEFAULT_WORKERS
    pause_s: float = DEFAULT_PAUSE_MIN * 60

    @property
    def enabled(self) -> bool:
        return self.workers > 0


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


def access_check_retry_settings(
    env: Optional[Mapping[str, str]] = None,
) -> AccessCheckRetrySettings:
    """``HORIZON_LATTES_RETRY_WORKERS`` (default 1; 0 turns the second try
    off) and ``HORIZON_LATTES_RETRY_PAUSE_MIN`` (default 5; 0 means no wait).
    Blank means the default; an invalid value is logged and replaced by the
    default. Never raises."""
    env = os.environ if env is None else env
    return AccessCheckRetrySettings(
        workers=_read(env, WORKERS_ENV, DEFAULT_WORKERS, True),
        pause_s=_read(env, PAUSE_ENV, DEFAULT_PAUSE_MIN, False) * 60,
    )
