"""Raw items kept between runs (spec 023, contracts/raw-store.md)."""

from abc import ABC, abstractmethod
from typing import Dict, Optional


class IDownloadManifest(ABC):
    """Download dates of the Lattes curricula kept in the cache."""

    @abstractmethod
    def dates(self) -> Dict[str, Optional[str]]:
        """Every cached id -> its last successful download date (ISO-8601
        UTC), or ``None`` when the date is unknown."""

    @abstractmethod
    def record(self, item_id: str, when: str) -> None:
        """A successful download of ``item_id`` at ``when``."""

    @abstractmethod
    def forget(self, item_id: str) -> None:
        """Drops the date of ``item_id``: its cached copy is then undated and
        counts as the oldest in the next rotation."""

    @abstractmethod
    def save(self) -> None:
        """Writes the manifest atomically."""


class ICnpqPageStore(ABC):
    """CNPq group pages kept with their download dates."""

    @abstractmethod
    def stored(self) -> Dict[str, Optional[str]]:
        """Group id -> download date of every valid stored page."""

    @abstractmethod
    def load(self, group_id: str) -> Optional[dict]:
        """``{"group_id", "url", "downloaded_at", "page"}``, or ``None`` when
        no valid page is stored."""

    @abstractmethod
    def save(self, group_id: str, url: str, page: dict, when: str) -> None:
        """Stores a page that was just downloaded (atomic replace)."""
