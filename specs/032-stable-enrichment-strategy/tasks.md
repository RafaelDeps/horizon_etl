---

description: "Task list for spec 032: stable enrichment strategy for document-created projects (TD-033)"
---

# Tasks: Stable enrichment strategy for document-created projects

**Input**: Design documents from `specs/032-stable-enrichment-strategy/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/enrichment-strategy.md, quickstart.md

**Tests**: Included. The constitution's development workflow requires tests,
and the plan writes them before the change (they must fail first).

**Organization**: Tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

All code lives in `src/core/logic/project_enrichment.py`; tests in
`tests/test_project_enrichment.py` (pure logic) and
`tests/test_project_enrichment_db.py` (loader on SQLite).

---

## Phase 1: Setup

**Purpose**: Confirm the starting point.

- [X] T001 Run `.venv/bin/python -m pytest -q tests/test_project_enrichment.py tests/test_project_enrichment_db.py` on branch `032-stable-enrichment-strategy` and record that it passes before any change (baseline).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The pure rule every story uses (contracts/enrichment-strategy.md).

- [X] T002 Write the contract tests for `strategy_from_prior(prior, origin, strategy, code, source_file)` in tests/test_project_enrichment.py, one parametrized test covering every row of the examples table in contracts/enrichment-strategy.md (same code + title_exact, drifted prior, other code, code match, no code + same file, no code + other file, origin matched_existing, no prior); import `strategy_from_prior` from src.core.logic.project_enrichment; confirm they fail (ImportError).
- [X] T003 Implement `strategy_from_prior` in src/core/logic/project_enrichment.py next to `origin_from_prior`: returns `NEW_FROM_DOCUMENT` only when origin is `ORIGIN_NEW_FROM_DOCUMENT`, prior is a dict, strategy is `title_exact` or `title_fuzzy`, and the document is the same (with a code: `prior.get("project_code") == code`; without: `source_file` truthy and `prior.get("source_file") == source_file`); otherwise returns `strategy`. Docstring cites TD-033 and research R2-R4. T002 passes.
- [X] T004 In `build_enrichment` (src/core/logic/project_enrichment.py), set `match_strategy=strategy_from_prior(prior, origin, strategy, code or None, meta.get("arquivo"))`, using the `origin` already computed by `origin_from_prior`.

**Checkpoint**: the rule exists and `build_enrichment` uses it.

---

## Phase 3: User Story 1 - A second run over unchanged documents writes nothing (Priority: P1) 🎯 MVP

**Goal**: the creating document's second run leaves the note as is, rewrites no row and logs no change.

**Independent Test**: on SQLite, create an initiative from a document, run the loader again with the same document; the note is identical, no UPDATE of `enrichment_json` runs for it and no `entity_change_logs` row is added.

### Tests for User Story 1

- [X] T005 [US1] In tests/test_project_enrichment.py add `test_document_finding_its_own_initiative_keeps_the_note`: build the note with `strategy="new_from_document"`, build it again with `strategy="title_exact"` and `prior=` the first; assert both payloads are equal. Add the same for a document without a code (same `_meta.arquivo`).
- [X] T006 [US1] In tests/test_project_enrichment.py update `test_build_enrichment_carries_origin_and_review_forward`: its prior gets `project_code="1"`, and the final assertion changes from `"title_exact"` to `"new_from_document"` with a comment citing TD-033.
- [X] T007 [US1] In tests/test_project_enrichment_db.py update `test_rerun_does_not_shrink_the_review_backlog`: the inserted prior note gets `"source_file": "PJ_1.json"` (the document has no code), and the last assertion expects `match_strategy == "new_from_document"`; keep `stats["by_title_exact"] == 1` (FR-008).
- [X] T008 [US1] In tests/test_project_enrichment_db.py add `test_second_run_rewrites_no_unchanged_note`: run the loader twice over the same matched document; on the second run assert no `UPDATE initiatives SET enrichment_json` statement runs (count statements with a SQLAlchemy `before_cursor_execute` listener on the session's engine) and no `entity_change_logs` row is added when tracking is active (or, if the test fixture has no tracking run, that `_record_tracking` is called with `changed=False`).
- [X] T009 [US1] Run T005-T008 and confirm T005, T007 and T008 fail before T010. Result (2026-11-09): T008 failed before T010 as expected; T005 and T007 already passed, because they depend only on the rule of T003/T004, not on the UPDATE skip of T010.

### Implementation for User Story 1

- [X] T010 [US1] In `ProjectEnrichmentLoader._enrich_winners` (src/core/logic/project_enrichment.py), when `canonical(enrichment) == canonical(current_enrichment.get(init_id))` and `write_desc` is False, skip `_apply` and treat the row as written (`written = True`), so the description merge, `_record_tracking` (with `changed=False`) and the counters run as before; `dry_run` unchanged (research R5, contract).
- [X] T011 [US1] Run tests/test_project_enrichment.py and tests/test_project_enrichment_db.py; all pass.

**Checkpoint**: US1 works; SC-001 holds in tests.

---

## Phase 4: User Story 2 - Other documents still record how they matched (Priority: P2)

**Goal**: only the creating document keeps `new_from_document`.

**Independent Test**: a document-created note is matched later by another document (other code); the note records that document's strategy and keeps origin and review flag.

### Tests for User Story 2

- [X] T012 [P] [US2] In tests/test_project_enrichment.py add `test_another_document_records_its_own_strategy` (prior from code `1`, current code `2`, `title_exact` → `title_exact`, origin `new_from_document`, `needs_review` True) and `test_creating_document_matched_by_code_records_the_code` (same code, `sigpesq_project_code` → `sigpesq_project_code`).
- [X] T013 [P] [US2] In tests/test_project_enrichment_db.py add `test_per_run_tracking_records_the_real_strategy`: with a tracking run active (or by patching `tracking_recorder.record_entity_match`), the creating document's second run records `match_strategy="title_exact"` in the per-run match while the note keeps `new_from_document` (FR-005).

### Implementation for User Story 2

- [X] T014 [US2] No code beyond T003/T004 is expected; run T012-T013 and fix `strategy_from_prior` only if one fails.

**Checkpoint**: US1 and US2 pass together.

---

## Phase 5: User Story 3 - Databases that already drifted are repaired (Priority: P3)

**Goal**: a note that already says `title_exact` for its own creating document goes back to `new_from_document` once, then stays.

**Independent Test**: seed a note with origin `new_from_document`, `match_strategy="title_exact"`, the document's code; run the loader twice; the first run writes `new_from_document` and logs one change, the second writes nothing.

### Tests for User Story 3

- [X] T015 [US3] In tests/test_project_enrichment_db.py add `test_drifted_note_is_repaired_once`: insert an initiative whose note has `origin="new_from_document"`, `match_strategy="title_exact"`, `project_code` equal to the document's code; run the loader; assert the note says `new_from_document`; run again and assert no `enrichment_json` UPDATE (same listener as T008).

### Implementation for User Story 3

- [X] T016 [US3] No code beyond T003/T004/T010 is expected (the rule reads the resolved origin, research R4); run T015 and fix only if it fails.

**Checkpoint**: all stories pass.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T017 [P] Update docs/backlog.md: TD-033 marked Done with the date, the rule in one sentence (creating document + title match keeps `new_from_document`; code match and other documents record their own), the unchanged-note skip, and the test count.
- [X] T018 [P] Run `.venv/bin/black --check`, `.venv/bin/isort --check-only` and `.venv/bin/flake8` on src/core/logic/project_enrichment.py, tests/test_project_enrichment.py and tests/test_project_enrichment_db.py.
- [X] T019 Run the full suite `.venv/bin/python -m pytest -q`; record the counts. Result (2026-11-09): 1045 passed, 10 skipped, 0 failed (1030 before; 15 new tests).
- [X] T020 Local validation per quickstart.md section 2 (ask the maintainer first; back up db/horizon.db before): run `app.py enrich_projects` twice; check the 37 document-created notes keep `new_from_document`, the second run adds no `entity_change_logs` rows for them, and `by_title_exact` still counts them. Result (2026-11-09, backup in data/_backup_2026-11-09_pre032/): two runs of `app.py enrich_projects`, exit 0; the 37 document-created notes kept `new_from_document`, 0 of 277 notes changed in either run, `entity_change_logs` stayed at 36,660, and `by_title_exact` counted 180 (143 + the 37). The local database had been through one run only, so its notes had not drifted; the drift repair (US3) is covered by tests and by T021.
- [ ] T021 Fork validation per quickstart.md section 3 (ask the maintainer first; only on the RafaelDeps fork): one weekly on the persistent fork state repairs the drifted notes; a second weekly writes no enrichment change.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001; blocks every story (T002 → T003 → T004).
- **US1 (Phase 3)**: after Phase 2. T005-T008 → T009 → T010 → T011.
- **US2 (Phase 4)**: after Phase 2; independent of US1's T010.
- **US3 (Phase 5)**: after Phase 2; its second-run assertion needs T010.
- **Polish (Phase 6)**: after the stories; T020 and T021 need the maintainer's approval.

### Within Each User Story

- Tests first, and seen failing, before implementation.
- Tasks in the same test file run in sequence (T005, T006, T012 share tests/test_project_enrichment.py; T007, T008, T013, T015 share tests/test_project_enrichment_db.py).

### Parallel Opportunities

- T012 and T013 touch different files.
- T017 and T018 touch different files.

---

## Parallel Example: User Story 2

```bash
Task: "T012 rule tests for another document and code match in tests/test_project_enrichment.py"
Task: "T013 per-run tracking test in tests/test_project_enrichment_db.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001 baseline.
2. T002-T004: the rule and its use in `build_enrichment`.
3. T005-T011: second run writes nothing.
4. Stop and validate: SC-001 in tests.

### Incremental Delivery

1. MVP (US1).
2. US2: confirm other documents and code matches keep their own strategy.
3. US3: confirm drifted notes are repaired once.
4. Polish: backlog, lint, full suite; then local and fork validation after approval.

---

## Notes

- No new setting, Makefile target or workflow input (FR-009).
- No Docker change and no third-party library change.
- Commits only when the maintainer asks; nothing upstream before validation.
