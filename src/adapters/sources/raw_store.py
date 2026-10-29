"""File-based raw stores (spec 023, data-model.md).

- ``JsonDownloadManifest``: ``data/raw/lattes/download_manifest.json``, the
  download date of every curriculum in ``cache/`` (file times do not survive
  the CI artifact, spec 022).
- ``FileCnpqPageStore``: one ``data/raw/cnpq/<group id>.json`` per page, with
  its download date.

Both live under ``data/raw``, which spec 022 restores between CI runs. Writes
go to a temporary file first and replace the old one in one step, so an
interrupted run never leaves half a file.
"""

import json
import os
import re
import tempfile
from typing import Dict, Optional

from loguru import logger

from src.core.ports.raw_store import ICnpqPageStore, IDownloadManifest

LATTES_MANIFEST = os.path.join("data", "raw", "lattes", "download_manifest.json")
CNPQ_PAGES = os.path.join("data", "raw", "cnpq")
LATTES_CACHE = "cache"
_LATTES_FILE = re.compile(r"^\d{16}$")
_CNPQ_FILE = re.compile(r"^(\d{16})\.json$")


def _write_json(path: str, payload) -> None:
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                payload, f, ensure_ascii=False, indent=1, sort_keys=True, default=str
            )
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class JsonDownloadManifest(IDownloadManifest):
    def __init__(self, path: Optional[str] = None, cache_dir: Optional[str] = None):
        # Defaults read at call time, so tests can point them elsewhere.
        self.path = path or LATTES_MANIFEST
        self.cache_dir = cache_dir or LATTES_CACHE
        path = self.path
        self._downloads: Dict[str, str] = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._downloads = {
                    str(k): str(v)
                    for k, v in (data.get("downloads") or {}).items()
                    if v
                }
            except (OSError, ValueError, AttributeError) as exc:
                # Every cached curriculum is then undated: the rotation
                # refreshes one share of them, never all at once.
                logger.warning("Unreadable Lattes manifest {}: {}", path, exc)
                self._downloads = {}

    def dates(self) -> Dict[str, Optional[str]]:
        if not os.path.isdir(self.cache_dir):
            return {}
        return {
            name: self._downloads.get(name)
            for name in sorted(os.listdir(self.cache_dir))
            if _LATTES_FILE.match(name)
            and os.path.isfile(os.path.join(self.cache_dir, name))
        }

    def record(self, item_id: str, when: str) -> None:
        self._downloads[item_id] = when

    def forget(self, item_id: str) -> None:
        self._downloads.pop(item_id, None)

    def save(self) -> None:
        _write_json(self.path, {"version": 1, "downloads": self._downloads})


class FileCnpqPageStore(ICnpqPageStore):
    def __init__(self, folder: Optional[str] = None):
        self.folder = folder or CNPQ_PAGES

    def _path(self, group_id: str) -> str:
        return os.path.join(self.folder, f"{group_id}.json")

    def load(self, group_id: str) -> Optional[dict]:
        path = self._path(group_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError) as exc:
            logger.warning("Unreadable stored CNPq page {}: {}", path, exc)
            return None
        if not isinstance(record, dict) or not record.get("page"):
            return None  # an invalid or empty page counts as not stored
        return record

    def stored(self) -> Dict[str, Optional[str]]:
        if not os.path.isdir(self.folder):
            return {}
        out: Dict[str, Optional[str]] = {}
        for name in sorted(os.listdir(self.folder)):
            match = _CNPQ_FILE.match(name)
            if not match:
                continue
            record = self.load(match.group(1))
            if record is not None:
                out[match.group(1)] = record.get("downloaded_at")
        return out

    def save(self, group_id: str, url: str, page: dict, when: str) -> None:
        _write_json(
            self._path(group_id),
            {"group_id": group_id, "url": url, "downloaded_at": when, "page": page},
        )
