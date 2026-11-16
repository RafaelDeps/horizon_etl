"""Port for the field claims of source documents (branch 030).

Several documents write the same field of one row: a project listed in the CV
of each participant and in a SigPesq row, a fellowship shared by many
workplans. Each document records what it says about each field as a claim,
and the winner is picked from all the claims by a fixed rule
(``src/core/logic/field_merge.py``). Claims of documents that are not
reprocessed stay stored, so the winner never depends on which documents a run
reads (spec FR-007, FR-008). Keeps SQL out of the core logic (constitution I).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

Entity = Tuple[str, int]  # (entity_type, entity_id)


@dataclass(frozen=True)
class FieldClaim:
    source_system: str
    document_key: str
    entity_type: str  # "initiative" | "advisorship" | "fellowship"
    entity_id: int
    field: str
    value: Any
    doc_date: Optional[str]  # ISO date, or None for an undated document
    source_rank: int  # 0 Lattes, 1 SigPesq, 2 CNPq
    tie_key: str


class IFieldClaimStore(ABC):
    @abstractmethod
    def replace_document_claims(
        self, source_system: str, document_key: str, claims: Iterable[FieldClaim]
    ) -> Dict[Entity, Set[str]]:
        """Replaces every claim of the document. Returns, for each entity it
        claimed before or claims now, the fields of those claims, so only
        they are resolved again: a field the document never claimed may be
        set by another step (the parent recalculation) and stays as it is."""

    @abstractmethod
    def claims_for(self, entity_type: str, entity_id: int) -> List[FieldClaim]:
        """Every claim of the entity, from every source."""

    @abstractmethod
    def move_claims(self, entity_type: str, from_id: int, to_id: int) -> None:
        """A merge of duplicates: the claims of ``from_id`` go to ``to_id``."""


class IFieldWriter(ABC):
    @abstractmethod
    def read(self, entity_type: str, entity_id: int, fields: Iterable[str]) -> dict:
        """The stored values of the fields; a missing row gives ``{}``."""

    @abstractmethod
    def write(self, entity_type: str, entity_id: int, values: dict) -> None:
        """Writes the given fields of the row."""
