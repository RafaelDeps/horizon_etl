"""Port for the state of source documents (spec 021).

A source document is one unit a phase reads and writes as a whole: a Lattes
CV, a CNPq group page, a SigPesq report row or a PJ file. The store keeps what
the ETL knows about each one (content hash, dependency fingerprint, status),
and gives the phase one transaction per document. Keeps SQL out of the core
logic (constitution I).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

ACTIVE = "active"
INACTIVE = "inactive"


class DocumentFailed(Exception):
    """A document that must not change anything (research R4): its reason is
    one of download, unparsable, unidentified, total_loss, partial."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class DocumentState:
    source_system: str
    document_key: str
    content_hash: Optional[str]
    dependency_fingerprint: Optional[str]
    rule_version: int
    max_person_id: Optional[int]
    max_initiative_id: Optional[int]
    item_count: int
    last_ingestion_run_id: Optional[int]
    processed_at: Optional[str]
    last_seen_at: str
    status: str
    last_failure: Optional[str] = None
    last_failure_at: Optional[str] = None


@dataclass(frozen=True)
class Reference:
    """One resolution a document made (research R3): the kind, the key the
    resolver looked up, and the target's stable key (never a database id)."""

    kind: str
    lookup_key: str
    outcome: str
    score: Optional[float] = None


@dataclass
class DocumentOutcome:
    """What a successfully processed document leaves behind."""

    source_system: str
    document_key: str
    content_hash: str
    dependency_fingerprint: str
    rule_version: int
    ingestion_run_id: Optional[int]
    references: List[Reference] = field(default_factory=list)
    # (item_type, item_ref, is_subject)
    items: List[Tuple[str, str, bool]] = field(default_factory=list)


@dataclass
class Delta:
    """Persons and initiatives created or renamed after a document was last
    processed (research R3): only they can change how its names resolve."""

    persons: List[Tuple[str, Optional[str]]] = field(
        default_factory=list
    )  # name, cnpq_url
    initiatives: List[str] = field(default_factory=list)  # names


@dataclass
class ListingResult:
    listed: int = 0
    reactivated: int = 0
    newly_inactive: int = 0


class IDocumentStateStore(ABC):
    @abstractmethod
    def load(self, source_system: str) -> Dict[str, DocumentState]:
        """Every stored state of one source, by document key."""

    @abstractmethod
    def references(self, source_system: str, document_key: str) -> List[Reference]:
        """The references recorded when the document was last processed."""

    @abstractmethod
    def delta(self, state: DocumentState) -> Delta:
        """Persons and initiatives created or renamed since ``state``."""

    @abstractmethod
    def target_keys(
        self, after_person_id: int = 0, after_initiative_id: int = 0
    ) -> Tuple[set, set, int, int]:
        """Stable keys of the current persons and initiatives with an id above
        the given ones (all of them by default), and the highest ids seen
        (R3 check 1). Lets the caller extend its set after each write."""

    @abstractmethod
    def begin_document(self) -> None:
        """Starts the document's transaction."""

    @abstractmethod
    def commit_document(self) -> None:
        """Commits the document's data and state together."""

    @abstractmethod
    def rollback_document(self) -> None:
        """Undoes everything written since ``begin_document``."""

    @abstractmethod
    def commit_processed(self, outcome: DocumentOutcome) -> list:
        """Writes the state, references and item links of a processed
        document inside its open transaction (the caller then commits), and
        deletes the items the document dropped (FR-011). Returns the deleted
        items (objects with ``entity_type``, ``entity_id``, ``before``).
        Raises ``DocumentFailed("total_loss")`` instead of writing when the
        document lost every item (FR-008)."""

    @abstractmethod
    def record_failure(
        self, source_system: str, document_key: str, reason: str
    ) -> None:
        """The failure record only (FR-008): never the processing state."""

    def clear_failure(self, source_system: str, document_key: str) -> None:
        """Clears a stale failure record: the document was read again,
        unchanged, so its stored processing state is current (FR-008)."""

    @abstractmethod
    def mark_listing(
        self, source_system: str, listed_keys: Iterable[str], complete: bool
    ) -> ListingResult:
        """Marks listed documents as seen (and active again); with
        ``complete``, active documents not listed become inactive (R8)."""
