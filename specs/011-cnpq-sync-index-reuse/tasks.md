---

description: "Task list for feature 011-cnpq-sync-index-reuse"
---

# Tasks: Reuse the researcher index in CNPq member sync

**Input**: Design documents from `/specs/011-cnpq-sync-index-reuse/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/sync_members_contract.md

**Tests**: included — the spec's success criteria (SC-001 through SC-004) are
only verifiable by direct observation and by equivalence tests, not by reading
the diff.

**Organization**: grouped by user story. US1 is the fix that matters (51.5 of
~51.6 minutes); US2 rides along in the same files at near-zero marginal cost.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

**Purpose**: capture the state that "no data loss" will be judged against,
before any code changes.

- [X] T001 Copy `db/horizon.db` to `/tmp/cnpq-fix/before.db`, and record row counts for `researchers`, `persons`, `roles`, `team_members`, `research_groups`, `advisorships` into `/tmp/cnpq-fix/before_counts.json`
- [X] T002 Run the full test suite (`.venv/bin/python -m pytest tests/ -q --ignore=tests/integration`) and save the output to `/tmp/cnpq-fix/baseline_tests.txt`, to compare against after the change (SC-004)

---

## Phase 2: Foundational

**Purpose**: confirm the ground the fix stands on before touching production
code — no blocking infrastructure to build, since `load_researcher_index` and
`ResearcherRef` already exist (feature 007).

- [X] T003 Confirm `sync_members` has exactly one production caller: `grep -rn "\.sync_members(" src/` must return only `src/flows/cnpq/groups.py`; if a second caller exists, add it to the task list before proceeding (per plan.md Complexity Tracking)
- [X] T004 Confirm `load_researcher_index` and `ResearcherRef` are importable from `src/core/logic/researcher_resolution.py` and confirm `resolve_or_create_researcher` branches on `isinstance(all_researchers[0], ResearcherRef)` as documented in research.md R1

**Checkpoint**: ground confirmed; implementation can begin.

---

## Phase 3: User Story 1 — Researcher registry read once per run (P1)

**Goal**: `sync_cnpq_groups_flow` reads the researcher registry once, not once
per group; a researcher created while processing one group is found by
subsequently processed groups in the same run.

**Independent Test**: run the CNPq sync phase and confirm a single researcher
registry read, per quickstart.md §2.

- [X] T005 [US1] In `src/flows/cnpq/groups.py`, import `load_researcher_index` and `ResearcherRef` from `src.core.logic.researcher_resolution`, and `NO_CACHE` from `prefect.cache_policies` (matching the import already used in `src/flows/lattes/advisorships.py`)
- [X] T006 [US1] In `src/flows/cnpq/groups.py`, in `sync_cnpq_groups_flow`, before the `for g_info in groups:` loop, obtain a session via `ResearcherController()._service._repository._session` and call `load_researcher_index(session)` once, assigning the result to `researcher_index`
- [X] T007 [US1] In `src/flows/cnpq/groups.py`, change `sync_single_group`'s decorator to `@task(cache_policy=NO_CACHE)`, add a `researcher_index: list` parameter, and forward it into the `sync_logic.sync_members(...)` call as a new `researcher_index=researcher_index` keyword argument
- [X] T008 [US1] In `src/flows/cnpq/groups.py`, update the flow's call site `sync_single_group(g_info)` to `sync_single_group(g_info, researcher_index)`
- [X] T009 [US1] In `src/core/logic/strategies/cnpq_sync.py`, change `sync_members`'s signature to accept `researcher_index` as a required keyword-only parameter, remove the `all_res = self.res_ctrl.get_all()` line, and use `researcher_index` wherever `all_res` was passed to `resolve_or_create_researcher`
- [X] T010 [P] [US1] In `tests/test_cnpq_sync.py`, update `test_sync_members_uses_resume_fallback_for_new_researcher` to pass `researcher_index=[]` instead of relying on `logic.res_ctrl.get_all.return_value = []`, and assert `logic.res_ctrl.get_all.assert_not_called()`
- [X] T011 [P] [US1] In `tests/test_cnpq_sync.py`, add `test_researcher_created_by_one_group_is_found_by_the_next`: build a shared `researcher_index` list (starts with zero or one `ResearcherRef`), call `sync_members` twice with different `group_id`s and members that share the same new researcher name across both calls, and assert only one researcher is created (`res_ctrl.create_researcher` called once, not twice) — this is the cross-group regression this feature exists to prevent
- [X] T012 [P] [US1] In `tests/test_cnpq_sync.py`, add `test_sync_single_group_does_not_read_full_researcher_registry`: exercise `sync_single_group.fn(group_info, researcher_index)` (or the flow-level entry point) with a pre-built `researcher_index` and assert the researcher controller's `get_all` is never called

**Checkpoint**: the 51.5-minute cost is eliminated; a researcher created by an
earlier group is reused, not duplicated, by a later one.

---

## Phase 4: User Story 2 — Role registry read once per group (P2)

**Goal**: the role lookup moves from inside the per-member loop to the top of
`sync_members`, run once per group instead of once per member.

**Independent Test**: run `sync_members` for a group with multiple members and
confirm the role registry is read exactly once for that call.

- [X] T013 [US2] In `src/core/logic/strategies/cnpq_sync.py`, move `all_roles = self.role_ctrl.get_all()` out of the `for m_data in members_data:` loop in `sync_members`, to run once near the top of the function (alongside the researcher-index parameter handling from US1)
- [X] T014 [P] [US2] In `tests/test_cnpq_sync.py`, add `test_role_registry_read_once_per_group`: call `sync_members` with multiple members in `members_data`, and assert `logic.role_ctrl.get_all.call_count == 1`

**Checkpoint**: both redundant reads are gone; behavior for role assignment is
unchanged.

---

## Phase 5: Polish & Validation

**Purpose**: prove SC-001 through SC-004 with numbers, and leave the code
clean.

- [X] T015 Run `.venv/bin/python -m pytest tests/test_cnpq_sync.py -v` and confirm all tests pass, including the three added in US1/US2
- [X] T016 Run the full suite (`.venv/bin/python -m pytest tests/ -q --ignore=tests/integration`) and diff against `/tmp/cnpq-fix/baseline_tests.txt` from T002; no test that passed before may fail now (SC-004)
- [X] T017 Run `black`, `isort`, and `flake8` on `src/flows/cnpq/groups.py`, `src/core/logic/strategies/cnpq_sync.py`, and `tests/test_cnpq_sync.py`
- [ ] T018 Verify SC-001 per quickstart.md §2: instrument a run of `sync_cnpq_groups_flow` against a database copy and confirm the researcher registry query fires once, not once per group
- [ ] T019 Save the current `db/horizon.db` as the pre-change snapshot for the end-to-end comparison the user will run next (`make weekly-flows` followed by a table-count diff against this snapshot, per quickstart.md §3 and spec.md SC-003) — coordinate with the user-run comparison rather than running the 80+ minute pipeline as part of this task list

---

## Dependencies

```text
Setup (T001-T002) ──► Foundational (T003-T004) ──► US1 (T005-T012) ──► US2 (T013-T014) ──► Polish (T015-T019)
```

- **T001 before any code change**: the "no data loss" comparison the user
  will run (`make weekly-flows` after the fix) is only meaningful against a
  snapshot taken before the fix.
- **US2 depends on US1 only by file proximity** (both touch `sync_members`'s
  top), not by logic — but doing them in this order avoids a second pass
  through the same function.
- **T019 is a handoff, not a pipeline run**: the actual `make weekly-flows`
  and comparison happens outside this task list, per the user's own request,
  using the snapshot this task preserves.

## Parallel Opportunities

- T010, T011, T012 add independent test functions to the same file — logically
  parallel, applied sequentially in practice (same file).
- T014 is independent of T010-T012 (different behavior under test) but shares
  the same file.
- T017's three targets (black/isort/flake8 across three files) run as one
  command each, not meaningfully parallelizable further.

## Implementation Strategy

**US1 is the entire point.** It accounts for 51.5 of the ~51.6 minutes
measured. US2 is a two-line move inside a function US1 already touches — doing
it separately would mean re-reading the same function twice for no reason.

**T019 hands off rather than executes.** The user explicitly asked to save the
current database state, then run `make weekly-flows` themselves and compare —
an ~80-minute pipeline run does not belong inside an automated task list when
the person who asked for the comparison is present to watch it happen.
