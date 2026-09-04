---

description: "Task list for feature implementation — 009-advisorship-value-fetch"
---

# Tasks: Advisorship Canonical Data Values Fetch

**Input**: Design documents from `specs/009-advisorship-value-fetch/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — the feature spec mandates per-story Independent Tests and `make ci-check` green (SC-006). Tests are written FIRST and FAIL before implementation (TDD), per the template convention.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Single project: `src/`, `tests/` at repo root.
Key files: `src/core/logic/canonical_exporter.py`, `src/core/logic/initiative_handlers.py`, `src/core/logic/strategies/sigpesq_advisorships.py`, `src/core/logic/strategies/lattes_advisorships.py`, `src/core/logic/advisorship_canonical_values.py` (NEW).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Sanity baseline before any implementation. The repo already has full structure; setup is verification only.

- [x] T001 Verify plan artifacts exist under `specs/009-advisorship-value-fetch/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md) and run `make ci-check` to record the baseline (known pre-existing failures: test_download_lattes_flow.py x3, test_export_canonical_data_flow.py tracking test, test_loader_mapping.py, test_sigpesq_adapter.py 429 — these are NOT to be "fixed" here)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared value-fetch engine every user story consumes — loading the stored, LGPD-masked advisorship source records and resolving the canonical category values from them.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T002 Create `src/core/logic/advisorship_canonical_values.py` with data classes (`AdvisorshipSourceInfo`) and the SQL loader `load_advisorship_source_values(session) -> Dict[int, list[AdvisorshipSourceInfo]]`, joining `entity_matches (canonical_entity_type='advisorship')` → `source_records` (source_entity_type='advisorship') and extracting per record: source_system, source_path, and payload keys `Programa`, `AgFinanciadora`, `Ano`, `Id` (sigpesq) and `year`/`end_year`/`start_year` (lattes). Write-first failing unit test `tests/test_advisorship_canonical_values.py` asserting the loader returns the known stored payloads for sample advisorship ids. NOTE: must remain a single grouped SQL query (no per-row queries) to honor the plan performance goal
- [x] T003 Implement the pure resolver `resolve_advisorship_canonical_values(records) -> AdvisorshipCanonicalValues` in `src/core/logic/advisorship_canonical_values.py`: `program`/`provider` from payload report-spelled trimmed; explicit `null` when absent; `year` = sigpesq report/directory year (`source_path` regex `advisorships/(\d{4})/`) with tie-break to payload `Ano`, else most recent dir-year, ties by lowest `source_record.id`; lattes rows use payload year; null when unresolvable. Extend `tests/test_advisorship_canonical_values.py` (previously-failing assertions now pass)

**Checkpoint**: Engine module exists with passing unit tests; stories can start in parallel.

---

## Phase 3: User Story 1 - Canonical advisorship records carry their per-year category (Priority: P1) 🎯 MVP

**Goal**: `advisorships_canonical.json` advisorship objects expose additive `year`/`program`/`provider` values matching the report row (SC-001/SC-002), and new SigPesq ingestions persist the program so the value also lives in the DB (FR-007).

**Independent Test**: Regenerate the advisorship export from a fresh ingestion; for every advisorship whose source row defines a program/provider, the canonical record exposes exactly that value (no nulls where the report supplied a value, no generic placeholders).

### Tests for User Story 1 (write FIRST, ensure they FAIL before implementation) ⚠️

- [x] T004 [US1] Strategy test: `SigPesqAdvisorshipMappingStrategy.map_row` return contains `"program"` equal to the trimmed report `Programa` for a Pivic/Voluntário row in `tests/test_sigpesq_advisorship_mapping.py` (the file covering the strategy; `tests/test_mappers.py` covers the general mapper)
- [x] T005 [P] [US1] Handler test: `AdvisorshipHandler._handle_advisorship_details` persists `initiative.program` on both create and update paths in `tests/test_initiative_handlers.py`
- [x] T006 [P] [US1] Export test: `export_advisorship` dicts carry additive `year`, `program`, `provider`; a SigPesq-sourced advisorship exposes non-null report-spelled `Pivic`/`Voluntário` in `tests/test_canonical_exporter.py`
- [x] T007 [P] [US1] Parity test: every `advisorships.id` appears exactly once across `advisorships_canonical.json` groups (orphans included), and no existing key changed (FR-004/FR-005) in `tests/test_canonical_exporter.py`

### Implementation for User Story 1

- [x] T008 [US1] Add `"program": str(programa).strip()` to the return dict of `SigPesqAdvisorshipMappingStrategy.map_row` in `src/core/logic/strategies/sigpesq_advisorships.py` (makes T004 pass)
- [x] T009 [US1] Persist `initiative.program = project_data.get("program")` in `AdvisorshipHandler._handle_advisorship_details` in `src/core/logic/initiative_handlers.py` (create + update paths; makes T005 pass)
- [x] T010 [US1] Wire the engine into `CanonicalDataExporter.export_advisorships` in `src/core/logic/canonical_exporter.py`: call `load_advisorship_source_values` + `resolve_advisorship_canonical_values`, then add `year`/`program`/`provider` to each advisorship dict (additive, only `advisorships_canonical.json`; make T006/T007 pass)
- [x] T011 [US1] Handle empty/absent `Programa`/`AgFinanciadora`: resolver already returns explicit `null` (FR-009); add an export-level assertion in `tests/test_canonical_exporter.py` that absent category stays `null` and the file remains valid JSON (acceptance scenario US1.3)

**Checkpoint**: US1 functional — export carries per-year category end-to-end; new ingestions populate `advisorships.program`.

---

## Phase 4: User Story 2 - Year-correctness of the fetched category (Priority: P2)

**Goal**: The resolved year is the report/directory year (Q2=A) with the `Ano` tie-break; cross-year work plans never reuse a first-seen value; count parity per year holds (SC-004, SC-003).

**Independent Test**: Take advisorship work plans present in more than one report year and independently verify each year's canonical row exposes that year's program/provider (no cross-year contamination); advisorship rows spanning two calendar years still get the report/directory year.

### Tests for User Story 2 (write FIRST, ensure they FAIL before implementation) ⚠️

- [x] T012 [US2] Year-resolution tests in `tests/test_advisorship_canonical_values.py`: (a) same work plan under `advisorships/2016/` and `advisorships/2025/` resolves `2016`/`2025`; (b) the observed duplicate case `Id 4882` present under `2021/` and `2022/` with payload `Ano=2021` resolves to `2021`; (c) `Inicio` 2016-09-26 / `Fim` 2017-07-31 under `advisorships/2016/` resolves `2016`; (d) determinism — ties broken by lowest `source_record.id`; (e) cancelled (`Cancelado=1`) and volunteer (`AgFinanciadora=Voluntário`) advisorship rows still resolve a category; (f) the same person with two differently-categorized advisorship rows yields distinct values
- [x] T013 [US2] Per-year parity test in `tests/test_canonical_exporter.py`: advisorship export count per year equals the number of distinct sigpesq advisorship source records for that `source_path` year (SC-003)

### Implementation for User Story 2

- [x] T014 [US2] Refine/confirm the year rule in `resolve_advisorship_canonical_values` in `src/core/logic/advisorship_canonical_values.py` (`source_path` dir-year primary, `Ano` tie-break, most-recent fallback, lattes payload year) until T012 passes; add a small exported helper `report_year_from_path(source_path) -> int | None` with unit tests in `tests/test_advisorship_canonical_values.py`
- [x] T015 [US2] Export-level integration test in `tests/test_canonical_exporter.py` asserting the cross-year sample (2016 Pivic advisorship) shows `year: 2016`/`program: Pivic`, and the 2025 sample keeps its own values — makes T013 pass (fix any export-side wiring bugs this surfaces in `src/core/logic/canonical_exporter.py`)

**Checkpoint**: US2 functional — years are per-report/directory, cross-year values never contaminated, per-year parity verified.

---

## Phase 5: User Story 3 - Provenance of fetched category values (Priority: P3)

**Goal**: Every non-null fetched category is traceable to its source report file + year via the existing `source_records`/`entity_matches` data (FR-005 trust, constitution IV); audit checks prove it (SC-004).

**Independent Test**: Pick any advisorship with a non-null category, locate its canonical record and its source row, and confirm the value's origin (report path + year) is present.

### Tests for User Story 3 (write FIRST, ensure they FAIL before implementation) ⚠️

- [x] T016 [US3] Provenance test in `tests/test_advisorship_canonical_values.py`: for every advisorship source record with a resolvable `Programa`/`AgFinanciadora`, the record's `source_path` matches `data/raw/sigpesq/advisorships/(\d{4})/` and `Ano` is present; any advisorship whose category resolved non-null is traceable to such a record

### Implementation for User Story 3

- [x] T017 [US3] Expose provenance fields needed for the audit: ensure `AdvisorshipSourceInfo` carries `source_record_id`, `source_path` and payload `Ano` (extend `src/core/logic/advisorship_canonical_values.py` if absent) so T016 passes
- [x] T018 [P] [US3] Document the provenance trace path and report-year attribution in `contracts/advisorships-canonical.md` (which source record backs `program`/`provider`/`year`, how to verify, determinism note)
- [x] T019 [US3] Add audit script `src/scripts/audit_advisorship_category_provenance.py`: reads `advisorships_canonical.json` + DB (`source_records`/`entity_matches`), flags any non-null category without a matching `advisorships/YYYY/` sigpesq source record, exits non-zero on findings; wire it into `quickstart.md` §3 as the SC-004/FR-004 gate

**Checkpoint**: US3 functional — provenance auditable, contract documents the trace, audit script green on current data.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Full quality gate, LGPD gate, docs consistency, end-to-end validation.

- [x] T020 [P] Run `make ci-check` (black, isort, flake8, mypy, pytest) and fix any NEW regressions from this feature (the 6 pre-existing failures from T001 baseline must remain the only ones) — SC-006
- [x] T021 [P] Run the LGPD scan from `quickstart.md` §6 against a regenerated `advisorships_canonical.json`: assert no raw email/phone/CPF patterns in the artifact — SC-005 / FR-006
- [x] T022 [P] Update `specs/009-advisorship-value-fetch/spec.md` Status `Draft` → `Ready` and synchronize any cross-references in `plan.md`/`data-model.md`/`contracts/` left stale by implementation
- [x] T023 Run `quickstart.md` scenarios §1–§4 and §6 end-to-end on the regenerated export and confirm SC-001..SC-004 sample checks; §5 (re-ingestion) is deploy-env-only (Prefect) and treated as SKIPPED in dev envs

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — baseline gate only
- **Foundational (Phase 2)**: Depends on Setup — **BLOCKS all user stories** (shared engine)
- **User Stories (Phase 3+)**: All depend on Foundational; then independent of each other
- **Polish (Final Phase)**: Depends on US1–US3 completion

### User Story Dependencies

- **User Story 1 (P1, MVP)**: Depends on T002/T003 only. No story dependency — can be delivered first and validated alone
- **User Story 2 (P2)**: Depends on T002/T003; may read US1's export wiring but keeps its own tests (year rules are pure) — independently testable once T010 exists
- **User Story 3 (P3)**: Depends on T002/T003 + US1 export (provenance verifies exported values) — independently testable after T010+T017

### Within Each User Story

- Tests MUST be written and FAIL before implementation (T004–T007, T012–T013, T016)
- Engine (loader/resolver) before export wiring; export wiring before verification tasks
- Story complete before moving to next priority

### Parallel Opportunities

- Phase 1: single task
- Phase 2: T002 then T003 sequential (same file)
- US1: T004/T005/T006/T007 all [P] (different test files) can run together; after T008/T009 (strategy+handler, [P] different files) T010 wires them
- US2: T012 (pure resolver tests) is independent of T013 (export parity) — both [P] on different files
- US3: T016/T017 (module + its test) vs T018 (contracts doc) vs T019 (audit script) — T018/T019 are [P] and independent
- Polish: T020/T021/T022 all [P]

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together (must fail before implementation):
Task: "US1 strategy test in tests/test_mappers.py"
Task: "US1 handler test in tests/test_initiative_handlers.py"
Task: "US1 export test in tests/test_canonical_exporter.py"
Task: "US1 parity test in tests/test_canonical_exporter.py"

# Implementation (T008 and T009 are parallel — different files):
Task: "Add program to SigPesqAdvisorshipMappingStrategy.map_row (sigpesq_advisorships.py)"
Task: "Persist initiative.program in AdvisorshipHandler._handle_advisorship_details (initiative_handlers.py)"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (baseline `make ci-check`)
2. Complete Phase 2: Foundational (T002+T003 — CRITICAL, blocks all stories)
3. Complete Phase 3: User Story 1 (export carries category + FR-007 DB persistence)
4. **STOP and VALIDATE**: run US1 Independent Test + quickstart §2/§3/§5
5. Merge/deploy the MVP before starting US2/US3

### Incremental Delivery

1. Setup + Foundational → engine ready (`test_advisorship_canonical_values.py` green)
2. US1 → category in canonical export + `advisorships.program` on new ingestions → validate (MVP!)
3. US2 → year-correctness + per-year parity → validate via quickstart §4
4. US3 → provenance audit (script + contract doc) → validate via quickstart §3
5. Polish → `make ci-check` green (SC-006), LGPD gate (SC-005), spec Status `Ready`

### Notes

- [P] tasks = different files, no dependencies
- TDD: each story's tests written first and observed failing before the implementing task
- Commit after each task or logical group; never commit over the T001 baseline's 6 pre-existing failures
- Skip `data_snapshot.zip` PII issue — distinct open item, not part of this feature