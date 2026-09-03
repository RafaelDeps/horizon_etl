---
description: "Task list for feature 010 — campus resolution fallback"
---

# Tasks: Campus Resolution — SigPesq Execution Campus + Advisorship Fallback

**Input**: Design documents from `/specs/010-campus-resolution-fallback/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md),
[research.md](./research.md), [data-model.md](./data-model.md),
[contracts/campus-resolution.md](./contracts/campus-resolution.md)

**Tests**: Included. The constitution's Development Workflow section requires new
behaviour to ship with tests, and `make ci-check` is the merge gate.

**Organization**: Grouped by user story so each ships independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3 — maps to the user stories in spec.md
- Paths are repository-relative from `/home/rafael/horizon_etl`

## Path Conventions

Single project: `src/` and `tests/` at repository root, per plan.md.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the measurable baseline everything else is judged against.

- [X] T001 Record the pre-change baseline (researcher count, null-campus count and share) from `data/exports/researchers_canonical.json` using the command in `specs/010-campus-resolution-fallback/quickstart.md` step 0, and write the numbers into a `## Baseline` section appended to `specs/010-campus-resolution-fallback/quickstart.md`
- [X] T002 Confirm the gate is green before touching anything by running `make ci-check`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared test scaffolding and the campus-name guard both stories depend on.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

- [X] T003 Add an in-memory SQLite fixture in `tests/conftest.py` (or a new `tests/fixtures/campus_db.py` if `conftest.py` should stay untouched) that builds the minimal campus-resolution schema — `organizational_units`, `research_groups`, `teams`, `team_members`, `initiatives`, `initiative_teams`, `advisorships`, `advisorship_members`, `attribute_assertions`, `entity_matches`, `entity_change_logs`, `source_records`, `article_authors`, `group_knowledge_areas` — so resolver tests never touch `db/horizon.db`
- [X] T004 Add a fake campus controller to the same fixture module exposing `get_all()` and `create_campus(name, organization_id)` over the fixture's `organizational_units`, matching the duck-typed interface `ExportCampusResolver._load_campuses` and `SigPesqCampusStrategy.ensure` expect
- [X] T005 [P] Add `tests/test_sigpesq_campus_strategy.py` covering `SigPesqCampusStrategy.ensure` in `src/core/logic/strategies/sigpesq_excel.py`: `"Serra"`, `"serra"`, `"Serra "`, `"SERRA"` and `"Campus Serra"` must all return the existing Serra id, and none may create a new campus (contract I-02); an unknown name still creates one; a controller that raises returns `None` without propagating
- [X] T006 Make T005 pass by adding a leading-`"Campus "`/`"Câmpus "` token strip to the name used for lookup in `SigPesqCampusStrategy.ensure` in `src/core/logic/strategies/sigpesq_excel.py`, applied before the `normalize_text` comparison and before the `create_campus` fallback, so a prefixed variant can never create a duplicate campus record

**Checkpoint**: Campus name resolution is safe to call from new code paths.

---

## Phase 3: User Story 1 — Scholarship student inherits the supervisor's campus (Priority: P1) 🎯 MVP

**Goal**: People whose only institutional link is an advisorship stop exporting
with `campus: null`, inheriting the campus of that advisorship's `Supervisor`.

**Independent Test**: Re-run `make export-canonical` against the unchanged
database and confirm the null-campus share drops by roughly 1,900 people, with no
re-ingestion and no person losing a campus they previously had.

### Tests for User Story 1

- [X] T007 [P] [US1] Add `tests/test_export_campus_resolver.py` with a test that a person having no group membership, who is the `Student` of an advisorship whose `Supervisor` resolves to Serra, gets Serra from `get_campus("researcher", person_id)` (contract C-04)
- [X] T008 [P] [US1] In `tests/test_export_campus_resolver.py`, test that a person with their own research-group campus (Vitória) keeps it even when their supervisor is at Serra (contracts C-03, FR-007)
- [X] T009 [P] [US1] In `tests/test_export_campus_resolver.py`, test that a person whose advisorship has no `Supervisor` member, and a person whose supervisor has no campus, both resolve to `None` (contract C-02, FR-010)
- [X] T010 [P] [US1] In `tests/test_export_campus_resolver.py`, test that inference never chains: person A has a campus only by inference from supervisor S, and person B is a `Student` of an advisorship supervised by A — B must resolve to `None` (contract C-05, FR-008)
- [X] T011 [P] [US1] In `tests/test_export_campus_resolver.py`, test that an advisorship with two `Supervisor` members at different campuses resolves the student by weighted count, and that a 1–1 tie resolves the same way on repeated runs (contracts C-01, C-08)

### Implementation for User Story 1

- [X] T012 [US1] ~~Extract the campus-counts aggregation from `_ensure_loaded`~~ — **not needed**: `_ensure_loaded` already ends by assigning `self._primary_by_entity = self._build_primary_map(campus_counts)`, which *is* the frozen direct map the inference layer consumes. Extracting it would have been churn with no behavioural or readability gain, so the inference reads that assignment directly
- [X] T013 [US1] In `src/core/logic/export_campus_resolver.py`, add a `_load_supervisor_inferences(primary_direct)` step that queries `advisorship_members` grouped by `advisorship_id`, reads the campus of members whose `role_name` is `Supervisor` from the frozen direct map only, and returns a separate `Counter` layer keyed by person for members absent from that map
- [X] T014 [US1] In `src/core/logic/export_campus_resolver.py`, resolve the inference layer through the existing `_build_primary_map` helper and store it in a distinct `_inferred_by_entity` dict, so it reuses the same `(-count, name, id)` ordering as direct evidence
- [X] T015 [US1] In `src/core/logic/export_campus_resolver.py`, make `get_campus` consult `_primary_by_entity` first and fall back to `_inferred_by_entity` only when the direct lookup misses, returning a copy as it does today
- [X] T016 [US1] In `src/core/logic/export_campus_resolver.py`, log at debug level how many people were attributed by inference versus directly, so a weekly run leaves evidence of the fallback's contribution in the flow logs

**Checkpoint**: US1 is complete and shippable on its own. Run `make export-canonical` and compare against the T001 baseline.

---

## Phase 4: User Story 2 — Project and advisorship keep the campus the source stated (Priority: P1)

**Goal**: The execution campus stated by SigPesq survives ingestion even when the
row names no research group, and reaches the export.

**Independent Test**: Re-ingest `data/raw/sigpesq/` and confirm every row stating
a campus produced `execution_campus_id` assertions — including rows with an empty
`GrupoPesquisa` — and that those initiatives and their team members export with
that campus.

### Tests for User Story 2

- [X] T017 [P] [US2] Add `tests/test_project_loader_campus.py` asserting that loading a SigPesq project row carrying `campus_name` and **no** `research_group_name` records `execution_campus_id` and `execution_campus_name` assertions for `canonical_entity_type="initiative"` (contract I-01)
- [X] T018 [P] [US2] In `tests/test_project_loader_campus.py`, assert the same for an advisorship row (`canonical_entity_type="advisorship"`), and assert that a row **with** a research group still links that group to its campus exactly as before (contract I-04, no regression)
- [X] T019 [P] [US2] In `tests/test_project_loader_campus.py`, assert that a row whose campus name cannot be resolved (controller returns `None`) completes the load without raising and writes `execution_campus_name` but no `execution_campus_id` (contract I-03, FR-004)
- [X] T020 [P] [US2] In `tests/test_export_campus_resolver.py`, test that an initiative with an `execution_campus_id` assertion and no linked research group resolves via `get_campus("initiative", id)`, that the same holds for `advisorship`, and that a person on that initiative's team inherits it as **direct** evidence (contracts C-06, FR-005)
- [X] T021 [P] [US2] In `tests/test_export_campus_resolver.py`, test that an assertion pointing at a campus id absent from the loaded campuses is ignored rather than exported (contract C-09)

### Implementation for User Story 2

- [X] T022 [US2] In `src/core/logic/project_loader.py`, resolve `project_data.get("campus_name")` to a campus id once per row via the loader's campus strategy and controller, before the tracking block at line ~518, reusing the same `org_id` the research-group linkage already uses and tolerating a `None` result
- [X] T023 [US2] In `src/core/logic/project_loader.py`, add `execution_campus_id` and `execution_campus_name` to the `tracked_attrs` dict passed to `tracking_recorder.record_attribute_assertions`, so both project and advisorship rows record them under the existing `loader_selected_values` reason
- [X] T024 [US2] In `src/core/logic/project_loader.py`, verify the existing `link_research_group` call keeps receiving the raw `campus_name` unchanged, so rows that do name a group behave exactly as they do today
- [X] T025 [US2] In `src/core/logic/export_campus_resolver.py`, add a direct-evidence query reading `attribute_assertions` where `attribute_name = 'execution_campus_id'` and `is_selected` is true, adding one weighted observation for the asserted `initiative` or `advisorship`
- [X] T026 [US2] In `src/core/logic/export_campus_resolver.py`, add a direct-evidence query joining those same assertions through `initiative_teams` and `team_members`, so people on a team of an initiative with an asserted execution campus gain direct evidence (research.md R6 — use `initiative_teams`, never the empty `initiative_persons`)
- [X] T027 [US2] In `src/core/logic/export_campus_resolver.py`, parse the assertion's `value_json` defensively — it is stored as JSON, so a string `"6"`, an integer `6`, and a malformed value must resolve to `6`, `6`, and "ignored" respectively, via the existing `_normalize_int`

**Checkpoint**: US1 and US2 both work, independently and together.

---

## Phase 5: User Story 3 — Multi-campus people resolve predictably (Priority: P2)

**Goal**: With several evidence sources now competing, precedence and
determinism are explicit and pinned by tests.

**Independent Test**: Build a person with conflicting evidence and confirm the
documented precedence holds, and that two exports of an unchanged database are
identical.

### Tests for User Story 3

- [X] T028 [P] [US3] In `tests/test_export_campus_resolver.py`, test that a person with an asserted execution campus at A and group membership at B resolves by weight, with neither source silently dropped (contract C-07)
- [X] T029 [P] [US3] In `tests/test_export_campus_resolver.py`, add a regression test pinning the tie-break: with equal weights the resolver picks by campus name then id, and repeated construction of the resolver over the same data yields the same answer (contracts C-01, C-08 — research.md R5, guarding the existing `(-count, name, id)` sort at `export_campus_resolver.py:218`)
- [X] T030 [P] [US3] In `tests/test_export_campus_resolver.py`, test that a failing internal query is swallowed and logged rather than raised, leaving the other evidence sources intact (contract C-10)

### Implementation for User Story 3

- [X] T031 [US3] In `src/core/logic/export_campus_resolver.py`, add a module docstring and inline comments stating the two-layer model — direct evidence versus supervisor inference — and why the inference reads only the frozen direct map, so the invariant survives future edits
- [X] T032 [P] [US3] Add `src/scripts/audit_campus_coverage.py` reporting, against `db/horizon.db`, the exported researcher count, the null-campus count and share, and the split between directly-evidenced and inference-attributed people, following the read-only operational-script convention (constitution Principle III: scripts may read, never ingest or export)
- [X] T033 [US3] Extend `src/scripts/audit_campus_coverage.py` to diff against a previous `researchers_canonical.json` and list any person who had a campus before and does not now, which is the executable form of SC-004

**Checkpoint**: All three stories functional and independently verifiable.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T034 Run the gate and fix every failure attributable to this feature — `make ci-check` is **already red on `main`** (`format-check` rejects 52 pre-existing files, and 5 tests fail without these changes), so it was run as `pytest` plus `black`/`isort`/`flake8` scoped to the touched files. 409 tests pass; the 4 remaining failures are pre-existing and were confirmed to fail with this branch's changes stashed
- [X] T035 Execute `specs/010-campus-resolution-fallback/quickstart.md` end to end and record the achieved numbers against SC-001 through SC-006 in its `## Baseline` section
- [X] T036 [P] Verify SC-006 — `organizational_units` still holds 23 rows, and the prefix guard is unit-tested against every dirty spelling observed in the reports. SC-007 is unaffected: the resolver adds two aggregate queries over tables of 6,338 and ~19,600 rows, and the audit run resolves all 9,806 people in well under a second
- [ ] T037 [P] Confirm the campus-scoped path still works and sees the new attributions by running `make export-canonical CAMPUS=Serra` (FR-013) — **deferred to the operator**: it rewrites the artifacts under `data/exports/`, and the same resolution was verified non-destructively via `src/scripts/audit_campus_coverage.py`
- [X] T038 Update `campus_ajuste.md` to record which of its five proposals were implemented and which were rejected with the measured reasons, so the analysis document does not outlive its own conclusions

---

## Phase 7: Follow-up after the first full pipeline run

Added after `make weekly-flows` on 2026-09-03 exposed gaps the earlier phases
did not cover.

- [X] T039 In `src/core/logic/export_campus_resolver.py`, weight research-group membership at 3 against the execution campus's 1 via `RESEARCH_GROUP_MEMBERSHIP_WEIGHT`, so a Serra-scoped ingestion cannot move people off their group's campus by bare majority (research.md R8)
- [X] T040 [P] In `tests/test_export_campus_resolver.py`, replace the equal-weight expectations with the two-sided rule: a narrow execution majority leaves the group standing, clear dominance unseats it, and the tie-break case is rebuilt at genuinely equal weight
- [X] T041 In `src/core/logic/project_loader.py`, extract `_tracked_attrs` from `_process_row` so the merge of the execution-campus attributes into the recorded assertions is reachable from a test
- [X] T042 [P] In `tests/test_project_loader_campus.py`, cover that wiring: the campus attributes reach the tracked attributes, and a source without a campus records exactly the eight attributes it recorded before
- [X] T043 [P] Add `tests/test_audit_campus_coverage.py` covering `collect_coverage` and `find_regressions` against a real SQLite fixture, including the `row_factory` omission that made the script report a total loss of campuses — verified to fail when the bug is reintroduced

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. Blocks both P1 stories, because
  every resolver test needs the fixture from T003/T004 and US2's ingestion path
  needs the guard from T006.
- **US1 (Phase 3)**: Depends only on Foundational. Ships alone.
- **US2 (Phase 4)**: Depends only on Foundational. Independent of US1 — they
  touch different methods and different evidence sources.
- **US3 (Phase 5)**: Depends on US1 and US2, since it pins the precedence
  *between* the layers those stories add.
- **Polish (Phase 6)**: Depends on all stories.

### Within Each Story

Tests are written before the implementation tasks in the same phase and must
fail first. Within US1, T012 → T013 → T014 → T015 is strictly sequential (same
file, same method). Within US2, T022 → T023 → T024 is sequential in
`project_loader.py`, and T025 → T026 → T027 is sequential in the resolver; the
two chains touch different files and can proceed in parallel.

### Parallel Opportunities

- T005 runs parallel to T003/T004 only if the strategy test avoids the shared
  fixture; otherwise it follows them.
- All of T007–T011 (US1 tests) are parallel to each other.
- All of T017–T021 (US2 tests) are parallel to each other.
- The `project_loader.py` chain (T022–T024) and the resolver chain (T025–T027)
  are parallel.
- T032, T036, and T037 are parallel.

---

## Parallel Example: User Story 1

```bash
# The five US1 tests are independent and can be written together:
Task: "Student inherits supervisor campus in tests/test_export_campus_resolver.py"
Task: "Direct evidence beats inference in tests/test_export_campus_resolver.py"
Task: "No supervisor campus stays null in tests/test_export_campus_resolver.py"
Task: "Inference never chains in tests/test_export_campus_resolver.py"
Task: "Multiple supervisors resolve by weight in tests/test_export_campus_resolver.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → Phase 2 Foundational → Phase 3 US1.
2. **STOP and VALIDATE**: `make export-canonical`, compare to the T001 baseline.
   Expect roughly 1,900 newly-attributed people and zero regressions.
3. This is shippable on its own: it needs no re-ingestion and no schema change.

### Incremental Delivery

1. US1 → export → validate → commit (largest single gain, lowest risk).
2. US2 → `make ingest-sigpesq` → export → validate → commit (authoritative data).
3. US3 → precedence tests and audit script → commit.
4. Polish.

---

## Notes

- No database migration and no change to `research-domain` anywhere in this list
  — if a task seems to need one, stop and revisit research.md R1.
- `initiative_persons` is empty; any task that seems to want it means
  `initiative_teams` → `team_members` instead.
- Commit after each checkpoint, not after each task.
