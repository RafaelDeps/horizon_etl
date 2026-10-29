"""Which raw items to download in a run (spec 023, research R3).

Lattes curricula and CNPq group pages are kept between runs. A run downloads
the items it has no copy of, plus a share of the stored ones with the oldest
download dates, and reuses the stored copy for the rest. With the default
share of one quarter, every stored item is downloaded again at least once in
any four runs: each run takes the oldest quarter, and a downloaded item moves
to the newest end.

Pure logic: no file or network access; the flows read the dates from the raw
stores and pass them here.
"""

import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

from loguru import logger

DEFAULT_SHARE = 0.25
SHARE_ENV = "HORIZON_REFRESH_SHARE"
FULL_REFRESH_ENV = "HORIZON_FULL_REFRESH"


@dataclass
class RotationPlan:
    new: List[str] = field(default_factory=list)
    refresh: List[str] = field(default_factory=list)
    reuse: List[str] = field(default_factory=list)

    @property
    def to_download(self) -> List[str]:
        return self.new + self.refresh


def plan_downloads(
    listed: List[str],
    dates: Mapping[str, Optional[str]],
    share: float = DEFAULT_SHARE,
    full: bool = False,
) -> RotationPlan:
    """``listed``: the ids to process, in source order. ``dates``: stored id ->
    download date (ISO-8601, ``None`` when unknown). Undated items count as
    the oldest; ties are broken by id, so the same inputs give the same plan
    (FR-010). Each list keeps the listed order."""
    seen = set()
    order: List[str] = []
    for item in listed:
        if item not in seen:
            seen.add(item)
            order.append(item)
    stored = [i for i in order if i in dates]
    if full:
        chosen = set(stored)
    else:
        count = math.ceil(share * len(stored)) if stored else 0
        oldest = sorted(stored, key=lambda i: (dates[i] is not None, dates[i] or "", i))
        chosen = set(oldest[:count])
    return RotationPlan(
        new=[i for i in order if i not in dates],
        refresh=[i for i in order if i in chosen],
        reuse=[i for i in stored if i not in chosen],
    )


def refresh_settings(env: Optional[Mapping[str, str]] = None) -> Tuple[float, bool]:
    """``HORIZON_REFRESH_SHARE`` (a fraction in (0, 1], default one quarter;
    anything else is logged and replaced by the default) and
    ``HORIZON_FULL_REFRESH`` (1/true/yes)."""
    env = os.environ if env is None else env
    raw = (env.get(SHARE_ENV) or "").strip()
    share = DEFAULT_SHARE
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = -1.0
        if 0 < value <= 1:
            share = value
        else:
            logger.warning("Invalid {}={!r}; using {}", SHARE_ENV, raw, DEFAULT_SHARE)
    full = (env.get(FULL_REFRESH_ENV) or "").strip().lower() in {"1", "true", "yes"}
    return share, full


def download_counts(plan: RotationPlan, failed: List[str]) -> Dict[str, object]:
    """The counts of FR-011 for one source, from its plan and the ids whose
    download failed (a failed stored item is reused from its stored copy)."""
    failed_set = set(failed)
    refreshed = [i for i in plan.refresh if i not in failed_set]
    return {
        "new": sum(1 for i in plan.new if i not in failed_set),
        "refreshed": len(refreshed),
        "reused": len(plan.reuse),
        "failed": len(failed_set),
        "reused_after_failure": sum(1 for i in plan.refresh if i in failed_set),
        "failed_ids": sorted(failed_set),
    }


def counts_line(source: str, counts: Mapping[str, object]) -> str:
    return (
        f"downloads {source}: new={counts['new']} refreshed={counts['refreshed']} "
        f"reused={counts['reused']} failed={counts['failed']} "
        f"reused_after_failure={counts['reused_after_failure']}"
    )
