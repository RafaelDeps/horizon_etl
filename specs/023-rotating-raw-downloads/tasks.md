---

description: "Task list for downloading only new items plus a rotating share"
---

# Tasks: Download Only What Is New Plus a Rotating Share

**Input**: Design documents from `specs/023-rotating-raw-downloads/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/raw-store.md, contracts/states-export-v2.md, quickstart.md

**Tests**: the spec requires local validation before CI, and every story has a measurable criterion, so each story starts with its tests.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md

`$R` = this session's scratchpad (copies of `cache/`, `data/raw` and databases); never the real `db/horizon.db` without the backup rule.

---

## Phase 1: Setup

- [X] T001 Record the baseline in `$R/d/D_BASE.txt`:
  - run the full test suite and save the failing tests (expected: the 6 known failures);
  - count the files in `cache/` and the ids in `data/lattes_run/lattes.list`;
  - copy the cnpq phase time of CI run 40914744437 (15.6 min) and of the local weekly run 5 (13.9 min).
- [X] T002 [P] Make a scratch copy for the local checks:
  - copy `cache/`, `data/raw/`, `data/lattes_run/` to `$R/d/work/`;
  - make a database copy `$R/d/work/db/horizon.db` from `db/horizon.db` with `sqlite3`'s backup API (WAL included).

---

## Phase 2: Foundational

**Purpose**: the rotation rule, the storage port and adapters, and the provenance column, which every story uses.

- [X] T003 [P] Create `src/core/logic/raw_rotation.py`, as in contracts/raw-store.md:
  - `RotationPlan` and `plan_downloads(listed, dates, share, full)`: undated ids are the oldest; ties are broken by id; `ceil(share × stored)`; output in listed order;
  - `refresh_settings(env)`: reads `HORIZON_REFRESH_SHARE` (default 0.25, valid range (0, 1], invalid values logged and replaced by the default) and `HORIZON_FULL_REFRESH`.
- [X] T004 [P] Create `tests/test_raw_rotation.py`:
  - new, refresh and reuse sets;
  - undated ids first, ties by id, rounding up;
  - with share 0.25, every stored id is refreshed at least once in four simulated runs (SC-001);
  - `full=True`;
  - invalid share values;
  - the same inputs give the same plan.
- [X] T005 [P] Create `src/core/ports/raw_store.py` with `IDownloadManifest` and `ICnpqPageStore` (contracts/raw-store.md).
- [X] T006 Create `src/adapters/sources/raw_store.py`:
  - `JsonDownloadManifest(path, cache_dir)`:
    - dates of the 16-digit files in `cache_dir`, `None` when undated;
    - atomic `save()`;
    - an unreadable file means every id is undated, and the reason is logged;
  - `FileCnpqPageStore(dir)`:
    - `stored()`, `load()` and atomic `save()` of `data/raw/cnpq/<id>.json` in the data-model.md format;
    - an invalid or empty page counts as not stored.
- [X] T007 [P] Create `tests/test_raw_store.py` for T006:
  - manifest round trip and atomic replace;
  - unreadable manifest;
  - page save and load;
  - an invalid page counts as absent;
  - no temporary file left behind.
- [X] T008 Add migration `0012_source_document_downloaded_at` to `src/db/migrations.py`: `ALTER TABLE source_document_states ADD COLUMN downloaded_at TEXT`, guarded like the existing column migration. Update `tests/test_schema_compatibility.py`: the new column is on an ETL table, and no library table changes.
- [X] T009 Carry `downloaded_at` through the document layer:
  - `DocumentState` gets the field `downloaded_at: Optional[str] = None` (`src/core/ports/document_state_store.py`);
  - `DocumentSkip.document(key, downloaded_at=None)` (`src/core/logic/document_skip.py`) passes it to the store:
    - processed: written with the state;
    - skipped: `store.set_downloaded(source, key, when)` only when the date differs;
    - failed: unchanged;
  - implement `set_downloaded` in `src/adapters/database/document_state_store.py`, write the column in `commit_processed`, and add a no-op `set_downloaded` to the fake stores in `tests/conftest.py` and `tests/test_document_skip.py`.
- [X] T010 [P] Add to `tests/test_document_skip.py` and `tests/test_document_state_store.py`:
  - a processed document stores its `downloaded_at`;
  - a skipped document with a new date updates only that column;
  - the same date writes nothing;
  - a failed document keeps its date.

**Checkpoint**: the rotation, the stores and the provenance column work on their own.

---

## Phase 3: User Story 1 - Lattes curricula are refreshed on a rotation (Priority: P1) 🎯 MVP

**Goal**: download missing curricula plus the oldest share, replacing a cached copy only after a successful download (FR-001–FR-003).

**Independent Test**: on a scratch `cache/` with a manifest, run the download with a fake downloader: missing ids plus the oldest quarter are downloaded, dates recorded, a failing refresh keeps its file and date; four runs date every curriculum.

### Tests for User Story 1

- [X] T011 [P] [US1] Create `tests/test_lattes_rotation.py` with a fake downloader (writes `<dir>/<id>` or raises):
  - new ids are downloaded into `cache/`;
  - the planned refresh ids are downloaded into a temporary folder and replace the cache file;
  - a failing refresh leaves `cache/<id>` byte for byte and the manifest date unchanged, and is counted as failed;
  - an undated cache is refreshed a quarter at a time;
  - the temporary folder is removed;
  - the manifest is saved;
  - the scriptLattes list leaves out only the ids that have no cache file.

### Implementation for User Story 1

- [X] T012 [US1] In `src/flows/lattes/download.py`, change `prefetch_lattes_cache` to take the `RotationPlan`:
  - download `plan.new` as today;
  - download `plan.refresh` into `cache/.refresh/<timestamp>/` with the same downloader and workers, then `os.replace` each produced file over `cache/<id>` and record its date in the manifest;
  - return the per-id results;
  - keep the existing signature as a thin wrapper for its current callers and tests.
- [X] T013 [US1] In `download_lattes_flow` (`src/flows/lattes/download.py`):
  - read `refresh_settings()` and the manifest (`data/raw/lattes/download_manifest.json`);
  - plan the downloads, run the prefetch, save the manifest;
  - log `downloads lattes: new=… refreshed=… reused=… failed=…` (FR-011);
  - keep `clean_lattes_json_output`, the scriptLattes run, and the effective list without failed new ids.
- [X] T014 [US1] Pass each CV's download date to its document:
  - in `src/flows/lattes/projects.py` and `src/flows/lattes/advisorships.py`, read the manifest once per phase and call `skip.document(key, downloaded_at=manifest date)`;
  - in `src/flows/lattes/cv_document.py`, make `finish_lattes_listing` keep `downloaded_at` out of the failed-download path.
- [X] T015 [US1] Local check (quickstart §2) on `$R/d/work/` with a fake downloader that copies the existing cache file (no portal calls):
  - run 1 refreshes 109 undated curricula;
  - runs 2–4 refresh the next quarters;
  - after run 4, every curriculum has a date;
  - record the numbers in `$R/d/D_BASE.txt`.

**Checkpoint**: Lattes refreshes on a rotation and never loses a cached copy.

---

## Phase 4: User Story 2 - CNPq pages are stored and refreshed on a rotation (Priority: P1)

**Goal**: store every page with its date, fetch only new plus the oldest share, reuse stored pages, also after a failed fetch (FR-004–FR-006).

**Independent Test**: with stored pages for most groups and a fake adapter, the phase fetches new plus a quarter, processes stored pages for the rest (skipped when unchanged), and a failing fetch uses the stored page.

### Tests for User Story 2

- [X] T016 [P] [US2] Create `tests/test_cnpq_rotation.py` with a fake `CnpqCrawlerAdapter` (records the URLs it was asked for):
  - first run: every group is fetched and stored;
  - second run: only the oldest quarter is fetched, the rest is read from storage, and the documents of unchanged pages are skipped;
  - a failing fetch with a stored page processes the stored page and counts as `reused_after_failure`;
  - a failing fetch without a stored page is `failed:download`;
  - a campus-filtered run plans only the filtered groups and never does a full refresh;
  - write order equals the group list order.
- [X] T017 [P] [US2] Extend `tests/test_incremental_cnpq_sigpesq.py`: with stored pages and the portal fully down, the CNPq phase completes, every group keeps its data, and the states show the stored pages' `downloaded_at` (SC-005).

### Implementation for User Story 2

- [X] T018 [US2] In `_sync_cnpq_groups` (`src/flows/cnpq/groups.py`), as in contracts/raw-store.md:
  - plan with `FileCnpqPageStore("data/raw/cnpq")`;
  - `fetch_all(new + refresh)`;
  - build the per-group outcome in list order (store fetched pages, reuse stored ones, fall back to stored after a failure);
  - pass `downloaded_at` to `_sync_group_document`, and from there to `skip.document`;
  - log the `downloads cnpq: …` counts.
- [X] T019 [US2] Add the CNPq download counts and the failed ids to the phase entry of `data/reports/source_document_states_report.json` (`src/core/logic/document_skip.py`, `write_phase_report`): `summary()["downloads"]`, set by the phase.
- [X] T020 [US2] Local check on `$R/d/work/` with the recorded payloads of `$R/inputs/cnpq_payloads.json` behind a fake adapter:
  - run 1 stores 350 pages;
  - run 2 fetches 88 pages and reuses 262;
  - run 3 with every fetch failing still completes;
  - record the counts and phase times in `$R/d/D_BASE.txt`.

**Checkpoint**: CNPq downloads a quarter per run and survives a portal outage.

---

## Phase 5: User Story 3 - Every document says when it was downloaded (Priority: P2)

**Goal**: `downloaded_at` for every document, published in the states export (FR-007, FR-008).

**Independent Test**: after a run, every document read in it has a `downloaded_at` in the export; a reused item keeps its earlier date; SigPesq rows have their report's file time.

### Tests for User Story 3

- [X] T021 [P] [US3] Extend `tests/test_export_canonical_data_flow.py::test_document_states_file_follows_the_contract`:
  - the export has `downloaded_at` (`null` when absent);
  - every other export file keeps its fields (contracts/states-export-v2.md).

### Implementation for User Story 3

- [X] T022 [US3] In `src/adapters/database/document_state_store.py` and `src/core/logic/document_skip.py`, add `downloaded_at` to `read_document_states` and to the fields of `write_states_file`.
- [X] T023 [US3] SigPesq rows: in `src/core/logic/project_loader.py` and `src/core/logic/research_group_loader.py`, pass the report file's modification time (ISO-8601 UTC) as `downloaded_at` to each row's `skip.document`. Give `process_file` the file path, as today.
- [X] T024 [US3] Update the export contract text in `specs/021-skip-unchanged-documents/contracts/source-document-states-export.md` with a pointer to `specs/023-rotating-raw-downloads/contracts/states-export-v2.md`.

**Checkpoint**: every document carries its download date in the export.

---

## Phase 6: User Story 4 - The share is configurable and a full refresh stays possible (Priority: P3)

**Goal**: `HORIZON_REFRESH_SHARE` and `HORIZON_FULL_REFRESH` locally and as CI dispatch inputs (FR-009).

**Independent Test**: share 0.5 refreshes half; full refresh downloads everything; the workflow passes both inputs to the weekly.

### Tests for User Story 4

- [X] T025 [P] [US4] Add to `tests/test_weekly_etl_workflow.py`:
  - `workflow_dispatch` has `refresh_share` (string, default empty) and `full_refresh` (boolean, default false);
  - the "Run weekly flows" step passes `HORIZON_REFRESH_SHARE` and `HORIZON_FULL_REFRESH` from those inputs.

### Implementation for User Story 4

- [X] T026 [US4] In `.github/workflows/weekly-etl.yml`, add the two inputs and their `env` on "Run weekly flows". Scheduled runs keep the defaults.
- [X] T027 [US4] In `Makefile`, document the two variables in the `weekly-flows` help text, and pass them through when they are set (`REFRESH_SHARE`, `FULL_REFRESH`).

**Checkpoint**: the rotation can be tuned or bypassed on demand.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T028 [P] Add a "Rotating raw downloads (spec 023)" section to `docs/flows-and-entrypoints.md`:
  - the share and how often each item is refreshed;
  - where the dates and pages live;
  - `downloaded_at` in the export;
  - how to force a full refresh;
  - what the `downloads …` log line means.
- [X] T029 [P] Format and lint the new and changed files; run the full suite and compare with T001: no new failure.
- [ ] T030 Local weekly on the real database (backup rule: check `data/_backup_2026-10-28_pre021/` or make a fresh backup first). Run `make weekly-flows` twice:
  - run 1: CNPq stores all pages and Lattes refreshes 109;
  - run 2: the CNPq phase time falls to about a third.
  - Record the times.
- [ ] T031 CI, after the maintainer's go-ahead: push `026-rotating-raw-downloads` to the fork and dispatch the weekly twice:
  - run 1 restores the database (spec 022) and stores the CNPq pages;
  - run 2 fetches a quarter;
  - measure the cnpq phase (SC-002) and check that `downloaded_at` is in the export (SC-004).
- [ ] T032 Write `docs/reports/2026-XX-XX-rotating-raw-downloads-validation.md` with SC-001 to SC-006, the local checks (T015, T020, T030) and the CI runs (T031).

---

## Dependencies & Execution Order

- **Setup (T001–T002)**: none.
- **Foundational (T003–T010)**: after Setup. T003, T005 and T008 in parallel. T006 needs T005. T009 needs T008. T004, T007 and T010 test T003, T006 and T009.
- **US1 (T011–T015)**: after Foundational. T012 → T013 (same file); T014 after T009 and T013.
- **US2 (T016–T020)**: after Foundational; independent of US1. T018 needs T006 and T009; T019 is in `document_skip.py` after T009.
- **US3 (T021–T024)**: after T009; T023 touches the loaders (no conflict with US1 or US2 files).
- **US4 (T025–T027)**: after T003; workflow and Makefile only.
- **Polish (T028–T032)**: after all stories; T031 needs the maintainer's go-ahead.

### Parallel Opportunities

- Foundational: T003, T005 and T008 together; their tests T004, T007 and T010 together.
- US1 and US2 can proceed in parallel (different flows).
- US4 can run beside US1–US3.

## Parallel Example: User Story 2

```bash
Task: "tests/test_cnpq_rotation.py — rotation, reuse, fallback, order"
Task: "tests/test_incremental_cnpq_sigpesq.py — portal down, data kept"
```

## Implementation Strategy

1. **MVP**: Foundational + US1. It fixes the correctness problem spec 022 introduced (Lattes stops updating in CI).
2. **US2**: the CNPq time saving and outage fallback.
3. **US3 + US4**: provenance in the export and the operational knobs, then Polish and CI.

## Notes

- A cached item is never deleted before its replacement exists.
- No third-party library changes; CNPq stays at 4 workers; SigPesq stays sequential.
- Commit only when the maintainer asks.
