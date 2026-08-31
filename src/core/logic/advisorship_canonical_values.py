"""Fetch and resolve per-advisorship canonical category values.

The canonical advisorship export needs the advisorship program (category) and
provider (funding agency) that applied to it in its own report/directory year,
taken from the original SigPesq report row. The authoritative per-row, per-year
copy of that row survives in ``source_records.raw_payload_json`` (already
LGPD-masked when persisted), linked to the advisorship entity via
``entity_matches``.

This module exposes:
- ``load_advisorship_source_values`` — one grouped SQL join that loads, for every
  advisorship, the list of its advisorship source records (sigpesq + lattes).
- ``resolve_advisorship_canonical_values`` — a pure function that turns those
  records into the canonical ``program`` / ``provider`` / ``year`` triple:
    * program  = report ``Programa``   (report spelling, trimmed)
    * provider = report ``AgFinanciadora`` (report spelling, trimmed)
    * year     = report/directory year (``.../advisorships/YYYY/...``), with the
      payload ``Ano`` used to pick the right record when the same advisorship
      appears under several report directories; Lattes rows fall back to the
      CV's own year.

Resolution never reads PII keys (LGPD, FR-006) and never invents a value
(FR-009): absent ``Programa``/``AgFinanciadora`` resolve to explicit ``None``.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import text

_REPORT_DIR_YEAR_RE = re.compile(r"advisorships[\\/](\d{4})[\\/]")

SIGPESQ_SYSTEM = "sigpesq_advisorships"
LATTES_SYSTEM = "lattes_advisorships"


@dataclass(frozen=True)
class AdvisorshipSourceInfo:
    """A tracked source row backing one advisorship entity."""

    advisorship_id: int
    source_record_id: int
    source_system: str
    source_path: Optional[str]
    payload: dict


class AdvisorshipCanonicalValues:
    """Canonical category triple published for a single advisorship."""

    __slots__ = ("year", "program", "provider", "source_record_id")

    def __init__(
        self,
        year: Optional[int] = None,
        program: Optional[str] = None,
        provider: Optional[str] = None,
        source_record_id: Optional[int] = None,
    ):
        self.year = year
        self.program = program
        self.provider = provider
        self.source_record_id = source_record_id

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"AdvisorshipCanonicalValues(year={self.year!r}, "
            f"program={self.program!r}, provider={self.provider!r})"
        )


def report_year_from_path(source_path: Optional[str]) -> Optional[int]:
    """Extract the report/directory year from a source path.

    Matches the ``advisorships/YYYY/`` segment used by the SigPesq advisorship
    report directories, e.g. ``data/raw/sigpesq/advisorships/2016/...`` -> 2016.
    """
    if not source_path:
        return None
    match = _REPORT_DIR_YEAR_RE.search(source_path)
    return int(match.group(1)) if match else None


def _mapping_to_dict(row: Any) -> dict:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    if isinstance(row, dict):
        return row
    return dict(row)


def _clean_str(value: Any) -> Optional[str]:
    """Trim a raw value; return ``None`` for blanks/NaN."""
    if value is None:
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    cleaned = str(value).strip()
    return cleaned or None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        if isinstance(value, float):
            return int(value) if value == int(value) else None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_advisorship_source_values(
    session: Any,
) -> Dict[int, List[AdvisorshipSourceInfo]]:
    """Load all advisorship source records grouped by advisorship entity id.

    Uses a single grouped SQL join (performance goal: no per-row queries) over
    ``entity_matches`` -> ``source_records`` for ``canonical_entity_type =
    'advisorship'``. Returns {advisorship_id: [AdvisorshipSourceInfo, ...]}
    ordered by ``source_record.id``.
    """
    query = text(
        """
        SELECT
            em.canonical_entity_id AS advisorship_id,
            sr.id AS source_record_id,
            sr.source_system,
            sr.source_path,
            sr.raw_payload_json
        FROM entity_matches em
        JOIN source_records sr ON sr.id = em.source_record_id
        WHERE em.canonical_entity_type = 'advisorship'
          AND sr.source_entity_type = 'advisorship'
        ORDER BY em.canonical_entity_id, sr.id
        """
    )
    grouped: Dict[int, List[AdvisorshipSourceInfo]] = {}
    try:
        rows = session.execute(query).fetchall()
    except Exception as exc:  # pragma: no cover - defensive, mirrors exporter
        logger.warning(f"Failed to load advisorship source values: {exc}")
        return grouped

    for row in rows:
        data = _mapping_to_dict(row)
        adv_id = data.get("advisorship_id")
        if adv_id is None:
            continue
        payload = {}
        raw_payload = data.get("raw_payload_json")
        if raw_payload:
            try:
                payload = (
                    json.loads(raw_payload)
                    if isinstance(raw_payload, str)
                    else raw_payload
                )
            except (TypeError, ValueError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
        grouped.setdefault(adv_id, []).append(
            AdvisorshipSourceInfo(
                advisorship_id=adv_id,
                source_record_id=int(data.get("source_record_id")),
                source_system=data.get("source_system") or "",
                source_path=data.get("source_path"),
                payload=payload,
            )
        )
    return grouped


def _choose_sigpesq_record(
    records: List[AdvisorshipSourceInfo],
) -> tuple[AdvisorshipSourceInfo, Optional[int]]:
    """Pick the SigPesq record + resolved year for one advisorship.

    Rule (research.md §2): report/directory year is authoritative; among several
    records choose the one whose directory year equals the payload ``Ano``,
    otherwise the most recent directory year; ties and no-path fallbacks resolve
    deterministically by lowest ``source_record.id``.
    """
    ordered = sorted(records, key=lambda r: r.source_record_id)

    for record in ordered:
        dir_year = report_year_from_path(record.source_path)
        ano = _to_int(record.payload.get("Ano"))
        if dir_year is not None and ano is not None and dir_year == ano:
            return record, dir_year

    with_dir_year = [
        (report_year_from_path(r.source_path), r)
        for r in ordered
        if report_year_from_path(r.source_path) is not None
    ]
    if with_dir_year:
        latest = max(dy for dy, _ in with_dir_year)
        candidates = [r for dy, r in with_dir_year if dy == latest]
        chosen = min(candidates, key=lambda r: r.source_record_id)
        return chosen, latest

    first = ordered[0]
    return first, _to_int(first.payload.get("Ano"))


def resolve_advisorship_canonical_values(
    records: List[AdvisorshipSourceInfo],
) -> AdvisorshipCanonicalValues:
    """Resolve the canonical program/provider/year triple for one advisorship.

    ``records`` is normally ``load_advisorship_source_values(session).get(id, [])``.
    Prefers the SigPesq report row (it carries ``Programa``/``AgFinanciadora``);
    Lattes-sourced rows carry no program/provider in the CV, so they resolve to
    explicit ``None`` (FR-008) and only contribute a year.
    """
    if not records:
        return AdvisorshipCanonicalValues()

    sigpesq = [r for r in records if r.source_system == SIGPESQ_SYSTEM]
    if sigpesq:
        chosen, year = _choose_sigpesq_record(sigpesq)
        payload = chosen.payload or {}
        return AdvisorshipCanonicalValues(
            year=year,
            program=_clean_str(payload.get("Programa")),
            provider=_clean_str(payload.get("AgFinanciadora")),
            source_record_id=chosen.source_record_id,
        )

    lattes = sorted(
        (r for r in records if r.source_system == LATTES_SYSTEM),
        key=lambda r: r.source_record_id,
    )
    if lattes:
        payload = lattes[0].payload or {}
        year = (
            _to_int(payload.get("year"))
            or _to_int(payload.get("end_year"))
            or _to_int(payload.get("start_year"))
        )
        return AdvisorshipCanonicalValues(
            year=year, source_record_id=lattes[0].source_record_id
        )

    return AdvisorshipCanonicalValues()
