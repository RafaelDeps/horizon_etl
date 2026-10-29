# Contract: raw item storage and rotation

## Port `src/core/ports/raw_store.py`

```python
class IDownloadManifest(ABC):
    def dates(self) -> dict[str, str | None]: ...      # stored id -> date (None if undated)
    def record(self, item_id: str, when: str) -> None: ...
    def save(self) -> None: ...                         # atomic

class ICnpqPageStore(ABC):
    def stored(self) -> dict[str, str]: ...             # group id -> downloaded_at
    def load(self, group_id: str) -> dict | None: ...   # {"page", "downloaded_at", ...} or None
    def save(self, group_id: str, url: str, page: dict, when: str) -> None: ...  # atomic
```

Adapters in `src/adapters/sources/raw_store.py`:

- `JsonDownloadManifest(path, cache_dir)`: `dates()` lists the files in
  `cache_dir` named by a 16-digit id, with the manifest's date or `None`.
- `FileCnpqPageStore(dir)`.

## Rotation `src/core/logic/raw_rotation.py`

```python
@dataclass
class RotationPlan:
    new: list[str]
    refresh: list[str]
    reuse: list[str]

def plan_downloads(listed: list[str], dates: dict[str, str | None],
                   share: float, full: bool) -> RotationPlan: ...

def refresh_settings(env=os.environ) -> tuple[float, bool]:
    """HORIZON_REFRESH_SHARE (default 0.25; invalid -> default, logged),
    HORIZON_FULL_REFRESH ('1'/'true'/'yes' -> True)."""
```

## Lattes download (`download_lattes_flow`)

1. Read the list.
2. Read the dates: `dates = manifest.dates()`.
3. Plan the downloads: `plan_downloads(ids, dates, share, full)`.
4. Download `new` into `cache/`, as today.
5. Download `refresh` into `cache/.refresh/<run id>/`. For each id that the
   download produced, `os.replace` the new file over `cache/<id>` and
   `manifest.record(id, now)`. Then remove the folder.
6. `manifest.save()`; log `downloads lattes: ...`.
7. Leave out of the scriptLattes list only the ids with no `cache/<id>` (new
   ids that failed), as today. Then regenerate the JSONs from `cache/`.

## CNPq (`_sync_cnpq_groups`)

1. List the groups, as today.
2. Plan the downloads:
   `plan_downloads(ids, store.stored(), share, full and campus_name is None)`.
3. `fetch_all(new + refresh)` with 4 workers.
4. In the original order, give each group a `FetchOutcome`:
   - fetched with data: `store.save(...)` and use it;
   - fetch failed with a stored page: use the stored page;
   - fetch failed without a stored page: `data=None`, which is a failed
     download, as today;
   - reused: the stored page, with `attempts=0`.
5. Pass to `_sync_group_document` the page's `downloaded_at` as the
   document's download date.

## Guarantees

- A stored copy (Lattes cache file, CNPq page) is replaced only by a
  successful download.
- The same inputs give the same plan.
- With the portal down, every stored copy is used and the phases complete.
