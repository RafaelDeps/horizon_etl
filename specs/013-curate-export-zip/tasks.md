# Tasks: Curated Export Archive

**Input**: Design documents from `/specs/013-curate-export-zip/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/export_zip_rules.md, quickstart.md

**Tests**: Included — the contract (`contracts/export_zip_rules.md`) and plan's Definition of Done mandate test-pinned rules R1–R15; each story's tests are part of its independent test criteria.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Single project layout: `src/`, `tests/`, `docs/` at repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the baseline before any code changes

- [X] T001 Record test baseline: run `.venv/bin/python -m pytest tests/test_zip_excludes_source_documents.py tests/test_export_canonical_data_flow.py -q` and note the result (expected green) as the pre-feature reference per quickstart.md §0

**Checkpoint**: Baseline recorded — story work can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

None. No blocking prerequisites exist: `zipfile` is already imported in `src/flows/exports/canonical_data.py`, the LGPD scrubber `scrub_pii_deep` already exists in `src/core/logic/pii_anonymizer.py`, and the adapter method `extract_json` already has the skip/force scaffolding this feature extends.

---

## Phase 3: User Story 1 - Archive includes the scrubbed project documents (Priority: P1) 🎯 MVP

**Goal**: `exports_canonical.zip` ships every `PJ_*.json` under `project_sigpesq_files_json/` with e-mails/phones replaced by LGPD tokens, raw corpus untouched.

**Independent Test**: Build a temp exports dir with a `PJ_*.json` containing a raw e-mail, run `zip_exports_task.fn(dir)`, assert the member exists and no clear-text e-mail is in the archive (quickstart.md §3).

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T002 [US1] Rewrite tests/test_zip_excludes_source_documents.py: new `test_zip_includes_scrubbed_pj_corpus` pinning R1 (every PJ ships, same name, same folder), R2 (no clear-text e-mail/phone; `@anon.lgpd` present), R3 (idempotent re-scrub), R9 (malformed PJ skipped with warning, archive still produced); keep `test_nested_result_files_still_ship` (R7) and update `test_skip_list_is_explicit` (R4)

### Implementation for User Story 1

- [X] T003 [US1] Add `import json` and `from src.core.logic.pii_anonymizer import scrub_pii_deep` to src/flows/exports/canonical_data.py
- [X] T004 [US1] Implement the post-walk scrubbed-PJ block inside `zip_exports_task` in src/flows/exports/canonical_data.py: after the walk, inside the same `ZipFile` context, read each `<output_dir>/project_sigpesq_files_json/PJ_*.json`, apply `scrub_pii_deep`, `zf.writestr("project_sigpesq_files_json/<name>", json.dumps(scrubbed, ensure_ascii=False, indent=2))`, count and log the total; a file that fails to parse is skipped individually with a warning (R1, R2, R3, R9 per contracts/export_zip_rules.md)
- [X] T005 [US1] Run the story tests from T002 and quickstart.md §3 manual verification; all must pass

**Checkpoint**: Archive ships the scrubbed corpus (US1 independently testable).

---

## Phase 4: User Story 2 - Archive stays a curated deliverable (Priority: P1)

**Goal**: No nested `*.zip` (covers `data_snapshot.zip`) and no `formandos/`, `docentes/`, `mestrado/`, `parquet/` folders in the archive.

**Independent Test**: Temp exports dir containing `data_snapshot.zip`, `formandos/x.html`, `docentes/ranking.json`, `mestrado/y.json`, `parquet/t.parquet`; generated archive contains none of them while other members still ship (quickstart.md §3).

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T006 [US2] Add to tests/test_zip_excludes_source_documents.py: `test_zip_excludes_nested_archives` (R5), `test_zip_excludes_report_and_format_dirs` (R6), `test_absent_categories_are_noop` (R8); extend `test_skip_list_is_explicit` to assert the full five-name `SKIP_DIRS`

### Implementation for User Story 2

- [X] T007 [US2] Extend `SKIP_DIRS` in src/flows/exports/canonical_data.py to `{"project_sigpesq_files_json", "formandos", "docentes", "mestrado", "parquet"}` (R4, R6)
- [X] T008 [US2] In the `zip_exports_task` walk in src/flows/exports/canonical_data.py, skip any file whose name ends with `.zip` (covers `data_snapshot.zip`, the archive itself and its `.tmp`; R5)
- [X] T009 [US2] Run the story tests from T006 plus T001's suite; all must pass

**Checkpoint**: Archive is a curated deliverable (US1 + US2 both independently green).

---

## Phase 5: User Story 3 - Weekly run stops emitting the parquet mirror (Priority: P1)

**Goal**: `export_canonical_data_flow` no longer calls the parquet task; script remains for manual use; ADR-003 amended.

**Independent Test**: Import-level check that the flow module no longer defines/invokes the parquet task (R10) + quickstart.md §3 smoke shows no `parquet/` members; `tests/test_export_canonical_data_flow.py` passes unchanged.

### Implementation for User Story 3

- [X] T010 [US3] Remove the `export_parquet_task` function (including its `@task` decorator and docstring) and its invocation at the end of `export_canonical_data_flow` from src/flows/exports/canonical_data.py (R10)
- [X] T011 [P] [US3] Amend docs/2 - implementacao/ADR/003-parquet-canonical-storage.md: status note that the weekly flow no longer emits `parquet/` inside the archive; `src/scripts/export_parquet.py` remains available for manual use; dashboard unaffected (reads its own repo copies)
- [X] T012 [US3] Verify `.venv/bin/python -m pytest tests/test_export_canonical_data_flow.py -q` passes unchanged and run the quickstart.md §3 smoke to confirm no `parquet/` members appear

**Checkpoint**: Parquet step gone from the flow (US3 independently verifiable).

---

## Phase 6: User Story 4 - Extraction reuses documents from the latest archive (Priority: P2)

**Goal**: `extract_json` restores `project_sigpesq_files_json/<stem>.json` from the archive next to `json_dir` instead of calling the paid extractor; graceful fallback; `force` bypasses.

**Independent Test**: Real zip in a temp dir + fake `ProjectExtractor` counting calls: hit → 0 calls + file restored with `stats["reused"]`; miss/malformed/corrupt zip → extractor called; `force=True` → always extracted (quickstart.md §4).

### Tests for User Story 4

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T013 [US4] Create tests/test_project_files_zip_reuse.py pinning R11 (local JSON exists → archive never consulted), R12 (hit → zero extractor calls, parsed copy written with standard JSON formatting, `stats["reused"]` incremented), R13 (exact `project_sigpesq_files_json/<stem>.json` matching, archive located at `os.path.join(os.path.dirname(json_dir), "exports_canonical.zip")`), R14 (`force=True` bypasses reuse), R15 (missing archive, corrupt zip, missing entry, malformed entry → normal extraction, no crash) — monkeypatch the lazy `agent_sigpesq.extraction.ProjectExtractor` import inside `extract_json`

### Implementation for User Story 4

- [X] T014 [US4] Extend `SigPesqProjectFilesAdapter.extract_json` in src/adapters/sources/sigpesq/project_files.py: open the archive lazily (only when pending PDFs exist and `force` is False), add `stats["reused"]`, and for each pending stem reuse-or-fall-back per data-model.md's state machine; log each reuse and each fallback at the appropriate level
- [X] T015 [US4] Run the story tests from T013; then the manual smoke in quickstart.md §4 (needs credentials only for the fallback path) confirming `reused` appears in the "Extraction finished" stats

**Checkpoint**: Reuse works end-to-end (US4 independently testable; zero paid calls for archived projects = SC-006).

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation and whole-feature validation

- [X] T016 [P] Update docs/outputs-and-artifacts.md: note that `exports_canonical.zip` now carries the scrubbed `project_sigpesq_files_json/` corpus and no longer carries `parquet/` or nested archives
- [X] T017 Run the full gate: `make test`, `make format-check`, `make lint`; compare against the T001 baseline (known pre-existing failures recorded in specs/009 T001 are out of scope)
- [X] T018 Validate contract traceability: every rule R1–R15 in specs/013-curate-export-zip/contracts/export_zip_rules.md maps to a passing test; tick the post-implementation checklist in quickstart.md §5

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately
- **Foundational (Phase 2)**: none exist — skip
- **US1 (Phase 3)** → **US2 (Phase 4)**: sequential, both edit `src/flows/exports/canonical_data.py` (same-file conflict if interleaved); US2's tests extend the file US1 rewrites
- **US3 (Phase 5)**: T010 also edits `canonical_data.py` — run after US2 to avoid conflicts; T011 (ADR) is independent `[P]`
- **US4 (Phase 6)**: independent of US1–US3 (different files: `src/adapters/sources/sigpesq/project_files.py` + new test file); can start any time, but the manual smoke (T015) is only meaningful after US1 ships the corpus into the archive
- **Polish (Phase 7)**: after all stories

### User Story Dependencies

- **US1 (P1)**: no story dependencies — MVP on its own
- **US2 (P1)**: same file as US1; logically independent (pruning vs. inclusion)
- **US3 (P1)**: no story dependencies; only the same-file ordering constraint above
- **US4 (P2)**: no code dependencies on other stories; builds conceptually on US1 (the archive must contain the corpus for reuse to find something in production)

### Within Each User Story

- Tests written first (T002/T006/T013), confirmed FAILING before the implementation task
- Implementation task immediately after its tests
- Story's verification task (T005/T009/T012/T015) closes the phase

### Parallel Opportunities

- T011 (ADR) can run in parallel with anything in Phase 5
- T016 (docs) can run in parallel with any story phase
- US4 (T013–T014) can run in parallel with US1–US3 by a second developer — no shared files
- All test-writing tasks are [P]-safe only within their own file; none share files across stories except `canonical_data.py` (US1→US2→US3, sequential)

---

## Parallel Example: User Story 4 (independent track)

```bash
# Developer B can run the whole US4 track while Developer A does US1–US3:
Task: "Create tests/test_project_files_zip_reuse.py pinning R11–R15"
Task: "Extend extract_json in src/adapters/sources/sigpesq/project_files.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (T001 baseline)
2. Complete Phase 3 (US1: scrubbed corpus ships)
3. **STOP and VALIDATE**: quickstart.md §3 — the archive now carries the corpus with anonymized contacts
4. This alone closes the original gap (consumers get the documents)

### Incremental Delivery

1. US1 → MVP (corpus ships, scrubbed)
2. US2 → archive becomes a strictly curated deliverable
3. US3 → weekly run sheds the parquet cost
4. US4 → fresh environments stop re-paying for extraction
5. Polish → docs and full gate

Each story adds value without breaking the previous ones; every checkpoint is independently testable.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability (US1–US4 per spec.md)
- Rules R1–R15 in contracts/export_zip_rules.md are the single source of truth; every implementation task cites its rules
- Verify tests fail before implementing (TDD within each story)
- Commit after each checkpoint
- Avoid same-file conflicts: `canonical_data.py` work is strictly sequential (US1 → US2 → US3)
