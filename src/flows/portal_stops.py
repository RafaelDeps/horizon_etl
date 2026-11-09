"""The portals given up in this weekly (spec 024, research R5).

Each phase that stops downloading from a portal adds its entry to
``data/reports/portal_stops.json``; the weekly orchestrator clears the file
before the first phase and reads it for its summary. Spec 025 adds the
``retries`` key: the second try of the Lattes access check pages, written
only when it ran. Spec 031 adds the ``extractions`` key: the counts of the
project PDF extraction, written when that stage ran. A report, never an
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


def _read_document(path: Optional[str]) -> dict:
    try:
        with open(_path(path), "r", encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def _section(path: Optional[str], key: str) -> dict:
    section = _read_document(path).get(key)
    return section if isinstance(section, dict) else {}


def read_portal_stops(path: Optional[str] = None) -> dict:
    """``source -> entry``; ``{}`` when the file is missing or unreadable."""
    return _section(path, "stops")


def read_access_check_retries(path: Optional[str] = None) -> dict:
    """``source -> entry`` of spec 025; ``{}`` when missing or unreadable."""
    return _section(path, "retries")


def read_extractions(path: Optional[str] = None) -> dict:
    """``source -> entry`` of spec 031; ``{}`` when missing or unreadable."""
    return _section(path, "extractions")


def _write_entry(path: Optional[str], key: str, source: str, entry: dict) -> None:
    document = _read_document(path)
    section = document.get(key)
    if not isinstance(section, dict):
        section = {}
    section[source] = entry
    document[key] = section
    document["version"] = 1
    document.setdefault("stops", {})
    atomic_write_json(_path(path), document, indent=2)


def record_portal_stop(
    source: str,
    stop: PortalStop,
    counts: Mapping[str, object],
    path: Optional[str] = None,
) -> None:
    """Adds or replaces the entry of ``source``, keeping the other keys of
    the file. Never raises."""
    try:
        entry = stop.summary()
        entry["counts"] = {
            k: v
            for k, v in counts.items()
            if k not in ("failed_ids", "stopped_ids", "retried_ids")
        }
        _write_entry(path, "stops", source, entry)
    except Exception as exc:
        logger.warning("Portal stop report not written: {}", exc)


def record_access_check_retry(
    source: str, entry: Mapping[str, object], path: Optional[str] = None
) -> None:
    """Spec 025: adds or replaces ``retries[source]``, keeping the other keys
    of the file. Never raises."""
    try:
        _write_entry(path, "retries", source, dict(entry))
    except Exception as exc:
        logger.warning("Access check retry report not written: {}", exc)


def record_extraction(
    source: str, entry: Mapping[str, object], path: Optional[str] = None
) -> None:
    """Spec 031: adds or replaces ``extractions[source]``, keeping the other
    keys of the file. Never raises."""
    try:
        _write_entry(path, "extractions", source, dict(entry))
    except Exception as exc:
        logger.warning("Extraction report not written: {}", exc)


def clear_portal_stops(path: Optional[str] = None) -> None:
    try:
        os.remove(_path(path))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Portal stop report not cleared: {}", exc)
