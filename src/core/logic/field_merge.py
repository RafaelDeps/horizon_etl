"""The fixed rule for fields written by several documents (branch 030).

A project listed in the CV of each participant and in a SigPesq row, or a
fellowship shared by many workplans, used to keep the values of the last
document processed, so an incremental run and a rebuild disagreed (TD-028).
Each document now records a claim per field (``FieldClaim``), and the winner
is picked from all the claims of the row:

1. an empty value never wins (None, blank, status "Unknown", value 0);
2. the most recent document wins; a dated document beats an undated one
   (Lattes CVs carry their last update date, SigPesq rows and PDFs none);
3. then the source order Lattes > SigPesq > CNPq;
4. then a fixed tie key: the lowest Lattes id, the highest SigPesq Id, a
   SigPesq report row before the PDF of the same project.

``resolve`` is pure, so any order of the same claims gives the same result.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

from loguru import logger

from src.core.logic.horizon_identity import canonical
from src.core.ports.field_claim_store import (
    Entity,
    FieldClaim,
    IFieldClaimStore,
    IFieldWriter,
)

LATTES_RANK = 0
SIGPESQ_RANK = 1
CNPQ_RANK = 2

DATE_FIELDS = ("start_date", "end_date")
BOOL_FIELDS = ("cancelled",)
MERGED_FIELDS = ("status", "description", "start_date", "end_date")
# A SigPesq workplan whose student was replaced has two rows (the cancelled
# one and the new one) writing the same advisorship: the highest Id wins.
ADVISORSHIP_FIELDS = MERGED_FIELDS + ("cancelled",)
FIELDS = {
    "initiative": MERGED_FIELDS,
    "advisorship": ADVISORSHIP_FIELDS,
    "fellowship": ("value",),
}

_EMPTY_STATUS = {"unknown"}
_SIGPESQ_ID_SPAN = 10**12

ClaimSource = Tuple[Optional[str], int, str]  # (doc_date, source_rank, tie_key)


def lattes_source(doc_date: Optional[str], lattes_id: str) -> ClaimSource:
    return (doc_date, LATTES_RANK, str(lattes_id))


def sigpesq_source(sigpesq_id: Any) -> ClaimSource:
    """A SigPesq report row: the highest Id wins, and a row beats a PDF."""
    try:
        number = int(float(sigpesq_id))
    except (TypeError, ValueError):
        return (None, SIGPESQ_RANK, f"0|z|{sigpesq_id}")
    return (None, SIGPESQ_RANK, f"0|{_SIGPESQ_ID_SPAN - number:013d}")


def project_file_source(code: Any) -> ClaimSource:
    return (None, SIGPESQ_RANK, f"1|{code}")


def lattes_document_date(cv: Any) -> Optional[str]:
    """``informacoes_pessoais.atualizacao_cv`` (dd/mm/yyyy) as an ISO date."""
    try:
        raw = (cv or {}).get("informacoes_pessoais", {}).get("atualizacao_cv")
    except AttributeError:
        return None
    match = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", str(raw or ""))
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def claim_value(field: str, value: Any) -> Any:
    """The form a claim stores: dates as ISO dates, numbers as numbers, text
    as text. Keeps claims comparable whatever type the loader held."""
    if value is None:
        return None
    if field in DATE_FIELDS:
        if hasattr(value, "date") and callable(value.date):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip()
        return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else None
    if field == "value":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if field in BOOL_FIELDS:
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "sim"}
        return bool(value)
    return value


def is_empty(field: str, value: Any) -> bool:
    if value is None:
        return True
    if field == "value":
        try:
            return float(value) == 0
        except (TypeError, ValueError):
            return True
    if isinstance(value, str):
        text = value.strip()
        return not text or (field == "status" and text.casefold() in _EMPTY_STATUS)
    return False


def same_value(field: str, value: Any) -> Any:
    """Comparison form: case and spaces do not make another value."""
    if field in DATE_FIELDS or field in BOOL_FIELDS:
        return claim_value(field, value)
    value = canonical(value)
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return value


def _stored_form(field: str, value: Any) -> Any:
    """Exact comparison with the stored value: the winner's text is stored
    as it is, so a rebuild and an incremental run keep the same text."""
    if field in DATE_FIELDS or field in BOOL_FIELDS:
        return claim_value(field, value)
    return canonical(value)


def claim_sort_key(claim: FieldClaim) -> tuple:
    dated = claim.doc_date is not None
    ordinal = date.fromisoformat(claim.doc_date).toordinal() if dated else 0
    return (0 if dated else 1, -ordinal, claim.source_rank, claim.tie_key)


@dataclass(frozen=True)
class Resolution:
    value: Any
    decided_by: str  # single | by_date | by_source | by_tiebreak


def _decided_by(winner: FieldClaim, runner_up: FieldClaim) -> str:
    if winner.doc_date is not None and (
        runner_up.doc_date is None or runner_up.doc_date < winner.doc_date
    ):
        return "by_date"
    if winner.source_rank < runner_up.source_rank:
        return "by_source"
    return "by_tiebreak"


def resolve(claims: Iterable[FieldClaim]) -> Dict[str, Resolution]:
    """Field -> winner for every field with a non-empty claim."""
    by_field: Dict[str, List[FieldClaim]] = defaultdict(list)
    for claim in claims:
        if not is_empty(claim.field, claim.value):
            by_field[claim.field].append(claim)
    result = {}
    for field, candidates in by_field.items():
        ranked = sorted(candidates, key=claim_sort_key)
        winner = ranked[0]
        wanted = same_value(field, winner.value)
        runner_up = next(
            (c for c in ranked[1:] if same_value(field, c.value) != wanted), None
        )
        decided_by = "single" if runner_up is None else _decided_by(winner, runner_up)
        result[field] = Resolution(winner.value, decided_by)
    return result


class FieldMergeStats:
    """Counts of one phase (FR-013): each field that had more than one
    non-empty value counts once, with how its last resolution was decided."""

    def __init__(self):
        self._decisions: Dict[Tuple[str, int, str], str] = {}
        self.collisions_resolved = 0
        self.collisions_reported = 0
        self.dates_missing = 0

    def note(self, entity: Entity, field: str, decided_by: str) -> None:
        key = (entity[0], entity[1], field)
        if decided_by == "single":
            self._decisions.pop(key, None)
        else:
            self._decisions[key] = decided_by

    def counts(self) -> Dict[str, int]:
        kinds = list(self._decisions.values())
        return {
            "fields": len(kinds),
            "by_date": kinds.count("by_date"),
            "by_source": kinds.count("by_source"),
            "by_tiebreak": kinds.count("by_tiebreak"),
            "collisions_resolved": self.collisions_resolved,
            "collisions_reported": self.collisions_reported,
        }

    def log(self, phase: str) -> Dict[str, int]:
        counts = self.counts()
        line = " ".join(f"{k}={v}" for k, v in counts.items())
        if self.dates_missing:
            line += f" dates_missing={self.dates_missing}"
        logger.info("field merge {}: {}", phase, line)
        return counts


class FieldMergeApplier:
    """Resolves entities and writes only the fields whose winner differs from
    the stored value; a field no claim fills keeps what is stored.

    ``apply`` takes either entities (every merged field is resolved) or, as
    ``replace_document_claims`` returns it, entity -> the fields a document
    claimed: then only those are resolved, so a document never rewrites a
    field it did not claim (the PDF claims only the description and must not
    undo the dates and status the parent recalculation sets)."""

    def __init__(
        self, store: IFieldClaimStore, writer: IFieldWriter, stats: FieldMergeStats
    ):
        self.store = store
        self.writer = writer
        self.stats = stats

    def apply(
        self, entities: Union[Iterable[Entity], Mapping[Entity, Iterable[str]]]
    ) -> int:
        claimed = entities if isinstance(entities, Mapping) else None
        written = 0
        for entity_type, entity_id in sorted(set(entities)):
            fields = FIELDS.get(entity_type)
            if not fields:
                continue
            resolved = resolve(self.store.claims_for(entity_type, entity_id))
            if claimed is not None:
                wanted = set(claimed[(entity_type, entity_id)])
                resolved = {f: r for f, r in resolved.items() if f in wanted}
            if not resolved:
                continue
            stored = self.writer.read(entity_type, entity_id, fields)
            if not stored:
                continue  # the row is gone (deleted with its document)
            changes = {}
            for field, resolution in resolved.items():
                self.stats.note((entity_type, entity_id), field, resolution.decided_by)
                if _stored_form(field, stored.get(field)) != _stored_form(
                    field, resolution.value
                ):
                    changes[field] = resolution.value
            if changes:
                self.writer.write(entity_type, entity_id, changes)
                written += len(changes)
        return written
