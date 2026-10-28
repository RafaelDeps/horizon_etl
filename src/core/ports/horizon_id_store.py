from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional

# Entity types read by the horizon_id assigner, in dependency order: parents
# (persons, initiatives) come before the children and teams built on them.
REFERENCE_TYPES = (
    "knowledge_area",
    "organization",
    "campus",
    "initiative_type",
    "production_type",
    "role",
    "language",
    "education_type",
    "fellowship",
)
ROOT_TYPES = (
    "person",
    "research_group",
    "initiative",
    "advisorship",
    "article",
    "research_production",
)
CHILD_TYPES = (
    "academic_education",
    "professional_activity",
    "award",
    "proficiency",
    "team",
)
ENTITY_TYPES = REFERENCE_TYPES + ROOT_TYPES + CHILD_TYPES


class IHorizonIdStore(ABC):
    """Reads the finished database for the horizon_id assigner and writes the
    ETL-owned identity tables (spec 020). Keeps SQL out of the core logic."""

    @abstractmethod
    def iter_entities(self, entity_type: str) -> Iterable[Dict[str, Any]]:
        """Rows of one entity type as plain dicts, with ``id`` and the columns
        its rule needs (see contracts/horizon-id-format.md)."""

    @abstractmethod
    def source_keys(self) -> Dict[tuple, List[Dict[str, Any]]]:
        """``(canonical_entity_type, canonical_entity_id)`` -> the source
        records matched to it (``source_system``, ``source_entity_type``,
        ``source_record_id``, ``source_file``)."""

    @abstractmethod
    def team_initiatives(self) -> Dict[int, List[int]]:
        """team id -> ids of the initiatives it staffs."""

    @abstractmethod
    def load_history(self) -> Dict[str, Any]:
        """Previous ids, candidates, aliases and merge log (research R5)."""

    @abstractmethod
    def replace_current(
        self, ids: List[Dict[str, Any]], candidates: List[tuple]
    ) -> None:
        """Replaces ``horizon_ids`` and ``horizon_id_candidates`` atomically."""

    @abstractmethod
    def upsert_aliases(self, aliases: List[Dict[str, Any]], current: set) -> None:
        """Writes alias rows and removes alias rows of ids current again."""

    @abstractmethod
    def mark_merges_consumed(self, merge_ids: List[int]) -> None:
        """Merge-log entries already turned into aliases."""

    @abstractmethod
    def current_ids(self) -> List[Dict[str, Any]]:
        """Rows of ``horizon_ids`` (empty if the table is missing)."""

    @abstractmethod
    def current_aliases(self) -> List[Dict[str, Any]]:
        """Rows of ``horizon_id_aliases`` (empty if the table is missing)."""

    @abstractmethod
    def has_entities(self) -> bool:
        """Whether the database holds any ingested row (persons)."""

    @abstractmethod
    def get_meta(self, key: str) -> Optional[str]:
        """A value from ``horizon_meta``, or None."""

    @abstractmethod
    def set_meta(self, key: str, value: str) -> None:
        """Stores a value in ``horizon_meta``."""
