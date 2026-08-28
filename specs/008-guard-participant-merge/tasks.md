---

description: "Task list for the reliable participant deduplication redesign"
---

# Tasks: Reliable Participant Deduplication

**Input**: Design documents from `specs/008-guard-participant-merge/`

**Prerequisites**: plan.md, spec.md (user stories US1–US5), research.md, data-model.md (scenarios A–G), contracts/dedup_rules.md (R1–R14)

**Tests**: The spec mandates regression tests (FR-014, SC-005) — every user story includes a "write tests FIRST, see them fail" gate.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

**Format**: `[ID] [P] [Story] Description`

## Path Conventions

- Single project: `src/`, `tests/` at repository root.
- Real paths (from plan.md): `src/core/logic/person_identity.py` (new), `person_consolidator.py`, `person_matcher.py`, `researcher_resolution.py`, `initiative_identity.py` (untouched), `src/flows/pipelines/weekly.py`, `src/scripts/consolidate_duplicates.py`; tests `tests/test_person_identity.py`, `tests/test_person_consolidator.py`, `tests/test_person_matcher.py`, `tests/test_project_loader_matching.py`, `tests/test_weekly_orchestrator.py`.

---

## Phase 1: Foundation (Shared Key Function)

**Purpose**: One normalization function that every comparison path agrees on — the prerequisite of US1 and US2.

**⚠️ CRITICAL**: No user-story implementation can begin before this phase green-lights.

- [x] T001 [US1] Write failing contract tests for the shared key function in `tests/test_person_identity.py`, pinning the spelling table from data-model.md Scenario B (case, diacritics, whitespace, punctuation/hyphen, particle forms `DE`/`do`/`DOS`/`e`/`y`).
- [x] T002 [US1] Implement `normalize_participant_name` in `src/core/logic/person_identity.py` (NFD, drop combining marks, uniform case, punctuation/hyphen → space, whitespace collapse, particle canonicalization) and make T001 pass.
- [x] T003 [P] [US1] Add contract tests in the same file pinning junk-name detection (honorific-only and single-token names) used by R13.

**Checkpoint**: Foundation ready — the key function is deterministic, shared, and pinned by tests that fail on any change.

---

## Phase 2: User Story 1 - One participant, many spellings, one record (P1) 🎯 MVP

**Goal**: A participant arriving from a second source in a different spelling resolves to the stored record instead of creating a new one.

**Independent Test**: `tests/test_person_identity.py` + `tests/test_person_matcher.py` (no DB, <5s).

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T004 [P] [US1] Test in `tests/test_person_matcher.py`: `PersonMatcher.normalize_name`/`canonicalize_name` delegate to the shared key and return identical keys for "Israel Magalhães do Carmo" and "ISRAEL MAGALHÃES DO CARMO".
- [x] T005 [P] [US1] Test in `tests/test_person_consolidator.py`: a name group split across case/particle spellings is grouped under one key (Scenario B).

### Implementation for User Story 1

- [x] T006 [US1] Delegate `PersonMatcher.normalize_name` and `canonicalize_name` in `src/core/logic/person_matcher.py` to `person_identity.normalize_participant_name` (keeping the existing particle lowercasing behavior identical to current output).
- [x] T007 [US1] Point `resolve_researcher_by_name`/`resolve_or_create_researcher` in `src/core/logic/researcher_resolution.py` at the shared key for its participant-side name comparison.
- [x] T008 [US1] Confirm `tests/test_project_loader_matching.py` (R1–R5 initiative guard) still passes — the advisorship/project title matching in `src/core/logic/initiative_identity.py` is NOT touched.

**Checkpoint**: US1 functional — a participant is recognized across spellings but the initiative guard is unchanged.

---

## Phase 3: User Story 2 - Complementary data merged, never discarded (P1)

**Goal**: The union merge: the surviving participant keeps every initiative/group link either duplicate held.

**Independent Test**: `tests/test_person_consolidator.py` consolidates Scenario A/D fixtures (no DB needed).

### Tests for User Story 2 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T009 [P] [US2] Test: consolidating Scenario A (Person 579 with five initiatives + Person 5767 with a research-group membership, same normalized key, no identifiers) yields ONE record holding BOTH the five initiatives AND the group membership.
- [x] T010 [P] [US2] Test: union transfer of advisorship memberships, team memberships, initiative links, article authorships, person emails, academic education, knowledge areas and the researcher-side record (Scenario D).
- [x] T011 [P] [US2] Test: an identical (entity, role) link shared by both records stays exactly once.

### Implementation for User Story 2

- [x] T012 [US2] Rework link transfer in `src/core/logic/person_consolidator.py` as a **union** across all link tables, skipping (entity, role) pairs already present on the winner.
- [x] T013 [US2] Fill missing winner scalar fields from the loser; record field conflicts per R12 (winner wins + logged).
- [x] T014 [US2] Make the merge idempotent (R14): a second run over the same catalog is a no-op.

**Checkpoint**: US2 functional — no participant loses initiative or group data during consolidation.

---

## Phase 4: User Story 3 - Simultaneous and same-researcher initiatives preserved (P1)

**Goal**: Merging never collapses a person's history; overlapping and researcher-shared initiatives survive.

**Independent Test**: `tests/test_person_consolidator.py`, Scenario E (in-memory fixtures).

### Tests for User Story 3 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T015 [P] [US3] Test: a person simultaneously Student on two advisorships and Researcher on one project, with the advisor shared across both duplicates, keeps all three initiatives after consolidation.
- [x] T016 [P] [US3] Test: two records sharing researcher R but carrying different initiatives keep every initiative of R's shared work.

### Implementation for User Story 3

- [x] T017 [US3] Verify/guard that link transfer is **additive per (initiative, role)** and never collapses links by time window or by shared researcher — add a comment-free guard assertion where the transfer happens in `src/core/logic/person_consolidator.py`.

**Checkpoint**: US3 functional — simultaneous and same-researcher initiatives survive by construction.

---

## Phase 5: User Story 4 - Homonyms and conflicting identifiers never merged (P1)

**Goal**: Conflicting strong identifiers or junk names veto a merge and land in the refusal report.

**Independent Test**: `tests/test_person_consolidator.py`, Scenarios F/G.

### Tests for User Story 4 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T018 [P] [US4] Test: two "José da Silva" records with distinct Lattes URLs are NOT merged and the group is reported as refused-homonym (Scenario F, R8).
- [x] T019 [P] [US4] Test: two records with distinct identification IDs are NOT merged and reported (R8).
- [x] T020 [P] [US4] Test: junk names ("Dr", "PROF", single-token) are refused and never absorb a real participant (Scenario G, R13).

### Implementation for User Story 4

- [x] T021 [US4] Enforce the strong-identifier veto in `src/core/logic/person_consolidator.py` whenever ANY pair inside a key group disagrees on Lattes/CNPq URL or identification ID.
- [x] T022 [US4] Implement junk-name refusal (plausibility floor) and route refused groups into the report with a reason.
- [x] T023 [P] [US4] Emit `dedup_report.json` under `data/reports/` from `src/scripts/consolidate_duplicates.py` (merged groups, refused groups, reasons; no raw emails in it).

**Checkpoint**: US4 functional — merge is guarded by conflicting-identity evidence and junk names never enter a merge.

---

## Phase 6: User Story 5 - The deduplicated catalog is what the dashboard reads (P2)

**Goal**: Dedup runs inside the weekly pipeline before the canonical exports.

**Independent Test**: `tests/test_weekly_orchestrator.py` (no DB, no network).

### Tests for User Story 5 ⚠️

> **NOTE: Write these Tests FIRST, ensure they FAIL before implementation**

- [x] T024 [P] [US5] Test: running the weekly flow over a catalog containing the Israel pair yields a `researchers_canonical.json` export with exactly ONE record for the pair and the union of its links.
- [x] T025 [P] [US5] Test: the pipeline emits the dedup report artifact and records refused groups with reasons.

### Implementation for User Story 5

- [x] T026 [US5] Insert the dedup phase into `src/flows/pipelines/weekly.py` between `ingest_all_sources_flow` and `export_canonical_data_flow` (importing the consolidator run, not reimplementing it).
- [x] T027 [US5] Wire the dedup report into the pipeline's `data/reports/` output alongside the ETL report.

**Checkpoint**: US5 functional — exports and the dashboard consume an already-deduplicated catalog.

---

## Phase 7: Validation & Regression Experiment

**Purpose**: Proof the guards are load-bearing and the baseline moves.

- [x] T028 [P] Run `pytest tests/ -q --ignore=tests/integration` (baseline 277 passed / 6 pre-existing failures) — all new tests pass, no existing test changes result, suite <5s, no DB needed.
- [x] T029 Run the **mandated experiment** (SC-005) once: disable the strong-identifier veto in `src/core/logic/person_consolidator.py` and confirm at least one test fails; restore the veto and confirm the suite passes again.
- [x] T030 Run experiment (SC-005) once more on the key function: break particle canonicalization in `src/core/logic/person_identity.py` and confirm a key test fails; restore and pass.
- [ ] T031 [P] Reproduce the real baseline: re-run the weekly pipeline on the current catalog and confirm the exported `researchers_canonical.json` drops from 176 duplicate groups to **zero**, with aggregate link counts equal to the pre-dedup union (SC-001, SC-002).
- [ ] T032 Quickstart validation: follow every command in `quickstart.md` end-to-end.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundation (Phase 1)**: no dependencies — starts immediately; BLOCKS US1 and US2.
- **US1 (Phase 2)**: depends on Foundation.
- **US2 (Phase 3)**: depends on Foundation (US1 is needed only for the multi-spelling fixture; can run after).
- **US3 (Phase 4)**: depends on US2 (attaches to the union transfer).
- **US4 (Phase 5)**: depends on the Foundation key function; can run in parallel with US2/US3 (different tests, different code sections — kept parallel-friendly via [P]).
- **US5 (Phase 6)**: depends on US2 (uses the consolidator run).
- **Validation (Phase 7)**: depends on US2/US4/US5.

### Within each user story

- Tests MUST be written first and verified failing (each phase's ⚠️ note).
- Key function → consolidator semantics → pipeline wiring.
- Story complete before moving to next priority (but US2/US3/US4 can be staffed in parallel after Phase 1).

### Parallel Opportunities

- Phase 1 T001/T003 run in parallel; Phase 2 T004/T005 in parallel; Phase 3 T009–T011 in parallel; Phase 4 T015/T016; Phase 5 T018–T020; Phase 6 T024/T025.
- US2, US3 and US4 touch different sections of `person_consolidator.py` plus independent test files — a team of three can staff them after Phase 1.

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Phase 1 (key function) — everything rests on it.
2. Phase 2 (US1, spellings resolve).
3. Phase 3 (US2, union merge) — this is the user-visible fix for the Israel pair.
4. **STOP and VALIDATE** with `tests/test_person_identity.py` + `tests/test_person_consolidator.py`.

### Incremental Delivery

1. Foundation → US1 → US2 → validate (MVP: duplicated participants fixed).
2. US3 and US4 (guards and preservation) → validate.
3. US5 (pipeline) → validate end-to-end export.
4. Phase 7 regression experiment.

### Parallel Team Strategy

1. Foundation together.
2. Developer A: US2 (union merge); Developer B: US4 (vetoes/report); Developer C: US1 (path unification).
3. US3 attaches to US2 output; US5 after US2.
4. Phase 7 single-runner.

---

## Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps each task to its user story for traceability.
- The initiative guard (`tests/test_project_loader_matching.py`, contract R1–R5) must pass unchanged at every checkpoint (spec SC-006).
- Commit after each task or logical group.
- Stop at each Checkpoint to validate the story independently.
- Avoid: vague tasks, same-file conflicts, cross-story dependencies that break independence.