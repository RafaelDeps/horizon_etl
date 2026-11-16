# Implementation Plan: Download Only What Is New Plus a Rotating Share

**Branch**: `026-rotating-raw-downloads` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/023-rotating-raw-downloads/spec.md`

## Summary

Lattes curricula and CNPq group pages are downloaded only when new, plus a
rotating share (default one quarter) of the stored ones with the oldest
download dates.

- **Lattes**: a manifest `lattes_id -> download date` in `data/raw/lattes/`.
  A refresh downloads into a temporary folder and replaces `cache/<id>` only
  on success.
- **CNPq**: each page is stored with its date in `data/raw/cnpq/<id>.json`.
  The phase fetches only the new and refreshed groups (still 4 workers) and
  reads the stored page for the rest, including after a failed fetch.

A pure rotation function in `src/core/logic/raw_rotation.py` picks what to
download. Every document records the date of the content it was built from
in a new `downloaded_at` column of the ETL's `source_document_states`, which
is published in `source_document_states_canonical.json`.
`HORIZON_REFRESH_SHARE` and `HORIZON_FULL_REFRESH`, also exposed as workflow
dispatch inputs, control the share and the full refresh.

## Technical Context

**Language/Version**: Python 3.12 (CI) / 3.14 (local).

**Primary Dependencies**:
- Prefect 3 flows;
- scriptLattes (unchanged), driven through the existing patched downloader;
- dgp_cnpq_lib through `CnpqCrawlerAdapter` (unchanged);
- SQLAlchemy, through the spec 021 state store.

**Storage**:
- SQLite `db/horizon.db`: migration `0012` adds `downloaded_at` to
  `source_document_states`.
- Files: `data/raw/lattes/download_manifest.json`, `data/raw/cnpq/<id>.json`
  and `cache/<lattes_id>`.

**Testing**: pytest:
- unit tests for the rotation, the manifest and the page store;
- flow tests with fake downloaders and adapters;
- the spec 021 incremental tests extended to check `downloaded_at`.

**Target Platform**: local Linux and the GitHub Actions `ubuntu-latest` weekly.

**Project Type**: ETL pipeline (Prefect flows).

**Performance Goals**: CNPq phase in the steady state at most about 6 min
(SC-002); every item refreshed at least once in four runs (SC-001).

**Constraints**:
- a stored copy is replaced only after a successful download (constitution
  rule 5);
- third-party libraries unchanged;
- CNPq keeps 4 workers, SigPesq stays sequential;
- no Docker change.

**Scale/Scope**: about 435 curricula and 350 CNPq pages; two flows, one core
module, two small adapters, one migration, the states export, the workflow
inputs.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Ports & Adapters | The rotation rule is pure core logic (`src/core/logic/raw_rotation.py`, no I/O). Manifest and page storage are adapters (`src/adapters/sources/raw_store.py`) behind a port (`src/core/ports/raw_store.py`). Flows wire them. | Pass |
| II. Domain-First | No domain entity changes; the stored page is the raw source payload. | Pass |
| III. Prefect Flows | All downloads stay inside the existing Lattes download and CNPq flows, with their Telegram hooks. | Pass |
| IV. Audit | Download counts and failures per source go to the log and to the spec 021 phase report (R6). | Pass |
| V. LGPD | The stored CNPq pages hold the same public page data already kept in `source_records`; no new personal field is exported; the states export gains a date only. | Pass |
| Data Integrity 5 (raw caches on a rotation, manifest of dates, replace only after success) | This spec implements the rule as written. | Pass |
| Data Integrity 6 (provenance: download date in the exports) | `downloaded_at` in the states export. | Pass |
| Data Integrity 2 (idempotency) | A reused unchanged item writes nothing; a refreshed unchanged item updates only `downloaded_at`, the same kind of date as spec 021's `last_seen_at`. | Pass (documented) |
| Quality gate | Tests for every new module; the workflow keeps calling Makefile targets. | Pass |

## Project Structure

### Documentation (this feature)

```text
specs/023-rotating-raw-downloads/
├── plan.md
├── research.md          # R1–R8
├── data-model.md        # manifest, stored page, downloaded_at, rotation
├── quickstart.md
├── contracts/
│   ├── raw-store.md             # port + file formats
│   └── states-export-v2.md      # downloaded_at in source_document_states_canonical.json
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
src/core/logic/raw_rotation.py         # select(listed, dates, share, full), share/flag parsing
src/core/ports/raw_store.py            # IDownloadManifest, ICnpqPageStore
src/adapters/sources/raw_store.py      # JSON manifest + page store (atomic writes)
src/flows/lattes/download.py           # rotation, refresh into a temp dir, manifest
src/flows/cnpq/groups.py               # rotation before fetch_all, store/reuse pages
src/flows/lattes/projects.py, advisorships.py, src/flows/sigpesq/*.py  # pass downloaded_at
src/core/logic/document_skip.py        # document(key, downloaded_at=...)
src/adapters/database/document_state_store.py  # write downloaded_at; export field
src/db/migrations.py                   # 0012 downloaded_at
.github/workflows/weekly-etl.yml       # refresh_share, full_refresh inputs -> env
tests/test_raw_rotation.py, tests/test_raw_store.py, tests/test_lattes_rotation.py,
tests/test_cnpq_rotation.py            # new
docs/flows-and-entrypoints.md          # rotation section
```

**Structure Decision**: single project, following the ports-and-adapters
layout already used by spec 021's document state store.

## Complexity Tracking

No constitution violation to justify.
