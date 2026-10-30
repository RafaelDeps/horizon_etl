"""The portals given up in this weekly (spec 024, research R5).

Each phase that stops downloading from a portal adds its entry to
``data/reports/portal_stops.json``; the weekly orchestrator clears the file
before the first phase and reads it for its summary. A report, never an
input: no phase reads it.
"""

import json
import os
from typing import Mapping, Optional

from loguru import logger

from src.core.logic.atomic_io import atomic_write_json
from src.core.logic.portal_stop import PortalStop

PORTAL_STOPS_PATH = "data/reports/portal_stops.json"


def _path(path: Optional[str]) -> str:
    return path or PORTAL_STOPS_PATH  # module default read at call time (tests)


def read_portal_stops(path: Optional[str] = None) -> dict:
    """``source -> entry``; ``{}`` when the file is missing or unreadable."""
    try:
        with open(_path(path), "r", encoding="utf-8") as f:
            stops = json.load(f).get("stops")
    except (OSError, ValueError, AttributeError):
        return {}
    return stops if isinstance(stops, dict) else {}


def record_portal_stop(
    source: str,
    stop: PortalStop,
    counts: Mapping[str, object],
    path: Optional[str] = None,
) -> None:
    """Adds or replaces the entry of ``source``. Never raises."""
    try:
        stops = read_portal_stops(path)
        entry = stop.summary()
        entry["counts"] = {
            k: v for k, v in counts.items() if k not in ("failed_ids", "stopped_ids")
        }
        stops[source] = entry
        atomic_write_json(_path(path), {"version": 1, "stops": stops}, indent=2)
    except Exception as exc:
        logger.warning("Portal stop report not written: {}", exc)


def clear_portal_stops(path: Optional[str] = None) -> None:
    try:
        os.remove(_path(path))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Portal stop report not cleared: {}", exc)
