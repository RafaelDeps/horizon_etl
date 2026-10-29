# Research: Download Only What Is New Plus a Rotating Share

Facts checked on 2026-10-29 against the code on branch
`026-rotating-raw-downloads` (spec 022 tip).

## R1. How a Lattes curriculum is downloaded today

**Finding**: `download_lattes_flow` (`src/flows/lattes/download.py:554`):

1. reads `data/lattes_run/lattes.list`;
2. deletes `data/lattes_json/*.json` (`clean_lattes_json_output`);
3. calls `prefetch_lattes_cache`, which downloads only the ids with no file
   `cache/<lattes_id>`;
4. runs scriptLattes, which builds every JSON from `cache/`.

The per-curriculum downloader (`bounded_baixa_cv_lattes`, patched over
scriptLattes' `baixaCVLattes`) returns at once when `cache/<id>` exists, and
writes `<dir>/<id>` otherwise. A listed id whose download failed is left out
of the scriptLattes list, so its JSON is missing and spec 021 records the CV
as `failed:download`, keeping its data.

**Decision**: refresh a cached curriculum by downloading it into an empty
temporary folder (`cache/.refresh/<run>/`) with the same downloader, then
`os.replace` the new file over `cache/<id>` only when the download produced it
(FR-003). New ids keep today's path (download straight into `cache/`). The
JSONs are still regenerated from `cache/` every run; scriptLattes is not
changed.

**Alternatives considered**: deleting `cache/<id>` before the download (loses
the copy on failure, against FR-003 and the constitution); asking the Lattes
portal for the curriculum's "last update" date first (one request per
curriculum, which is the cost this spec removes).

## R2. Where the download dates live

**Finding**: the CI artifact restores `data/raw/` and `cache/` (spec 022) but
not file times. **Decision**:

- **Lattes**: a manifest `data/raw/lattes/download_manifest.json`,
  `{"<lattes_id>": "<ISO-8601 UTC>"}`, written atomically at the end of the
  download phase (and after each successful refresh batch, so an interrupted
  run keeps what it did).
- **CNPq**: each stored page carries its own date, so there is no separate
  manifest: `data/raw/cnpq/<group id>.json` =
  `{"group_id", "url", "downloaded_at", "page"}`.

Both live under `data/raw`, which spec 022 restores and never compresses.

## R3. The rotation rule

**Decision**: a pure function in `src/core/logic/raw_rotation.py`:

```text
select(listed_ids, dates, share, full) -> (new, refresh, reuse)
```

- `new` = listed ids with no stored copy.
- `refresh`:
  - with `full`, every stored listed id;
  - otherwise, the `ceil(share × stored)` stored listed ids with the oldest
    dates. Undated ids count as the oldest, and ties are broken by id
    (FR-002, FR-010).
- `reuse` = the other stored listed ids.

With `share = 0.25`, a stored id is refreshed at least once in any four runs
(SC-001): each run takes the oldest quarter, and a refreshed id moves to the
newest end.

Configuration (FR-009):
- `HORIZON_REFRESH_SHARE`: a fraction in (0, 1], default `0.25`; an invalid
  value logs and uses the default.
- `HORIZON_FULL_REFRESH=1` refreshes everything.
- Both reach the CI through two new `workflow_dispatch` inputs (`refresh_share`,
  `full_refresh`) and locally through the environment or make variables. One
  setting covers both sources (spec assumption).

## R4. How the CNPq phase fetches

**Finding**: `_sync_cnpq_groups` (`src/flows/cnpq/groups.py`):

1. lists the groups (`get_groups_to_sync`, filtered to groups active in
   SigPesq by spec 021);
2. starts `fetch_all(groups, CnpqCrawlerAdapter, workers)` (4 workers, retries
   and an adaptive gate, spec 017);
3. writes one group at a time from `batch.outcome(i)`, in the list's order,
   through `_sync_group_document` (spec 021 skip/commit).

`FetchOutcome(index, group_info, data, attempts)`.

**Decision**: split the groups with R3 before `fetch_all`, and fetch only
`new ∪ refresh`, keeping the 4 workers and the gate. The writer loop keeps the
list's order. For each group:
- a fetched page with data is stored (written to a temporary file, then
  `os.replace`) and used;
- a failed fetch with a stored page uses the stored page and counts as
  `reused after failure` (FR-006);
- a failed fetch without a stored page stays `failed:download` (spec 021);
- a reused group gets `FetchOutcome(data=stored page, attempts=0)`.

The stored page is processed exactly like a downloaded one, so an unchanged
page is skipped (spec 021) and the result equals a fresh download of the same
content.

## R5. Provenance in the database and the export

**Finding**: `source_document_states` (spec 021) has `processed_at` and
`last_seen_at`, but no download date; `source_document_states_canonical.json`
publishes `source_system`, `document_key`, `status`, `last_seen_at`,
`processed_at`.

**Decision**:

- **Schema**: an ETL migration `0012_source_document_downloaded_at` adds
  `downloaded_at TEXT` (nullable) to `source_document_states`, which is an
  ETL-owned table, so no library table changes (FR-008). The states export
  gains the field `downloaded_at`. It is the export introduced by spec 021,
  and its contract is updated; no other export changes.
- **How it is set**: `DocumentSkip.document(key, downloaded_at=...)` records
  the date given by the phase on every outcome where the content was read:
  - processed: written with the state;
  - skipped: one short `UPDATE` of that column only, like `last_seen_at`;
  - failed: unchanged.
- **Where the date comes from**:
  - Lattes documents: the manifest date of their lattes id;
  - CNPq: the stored or fetched page's `downloaded_at`;
  - SigPesq rows: the modification time of the report file, downloaded whole
    in this run.

This adds one write per skipped document only when its date changed, so an
unchanged item reused from storage writes nothing. Spec 021's fixpoint rule
already allows `last_seen_at`; `downloaded_at` is the same kind of date.

## R6. What is recorded about downloads

**Decision**: each source logs one line, for example
`downloads cnpq: new=2 refreshed=88 reused=260 failed=1 reused_after_failure=1`
(FR-011). The same counts go into the phase entry of
`data/reports/source_document_states_report.json` (spec 021, R12) under
`downloads`, with the ids that failed. A refresh failure that fell back to the
stored copy is not a document failure: the document is processed (or skipped)
from the stored copy.

## R7. First run after this spec

**Finding**: `cache/` holds about 435 curricula (467 files locally) with no
dates, and there are no stored CNPq pages yet. **Decision**:

- **Lattes**: undated curricula count as the oldest, so the first run
  refreshes `ceil(0.25 × 435) = 109` of them, picked by id. After four runs
  every curriculum is dated.
- **CNPq**: every group is "new" on the first run, so all ~350 pages are
  downloaded once (as today) and stored. The rotation starts on the second
  run.

## R8. Time estimate

- **CNPq**: steady-state CI took 15.6 min for 350 pages. With 88 pages per run
  (a quarter), the estimate is about 4–5 min (SC-002: at most about 6 min).
- **Lattes**: about 109 downloads per run instead of 0 in the steady state of
  spec 022, at a few seconds each with 3 prefetch workers, so a few minutes.
  It is the price of FR-002, which is a correctness fix (spec D, US1).
