---

description: "Task list for feature 012-cnpq-concurrent-fetch"
---

# Tasks: Concurrent CNPq group fetch, serial write

**Input**: Design documents from `/specs/012-cnpq-concurrent-fetch/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/fetch_write_contract.md

**Tests**: included, and one of them (T014) is the single most important test in
this feature — it is the only thing standing between "looks correct" and "is
provably correct" for the one invariant this whole design rests on.

**Organization**: US1 (concurrent fetch) and US2 (serial write) are two halves
of one architectural change — splitting `sync_single_group` necessarily
produces both properties at once. They are still tracked as separate stories
because their tests answer different questions: US1 proves speed, US2 proves
safety.

**Handoff**: this task list stops after T017 (full suite, formatting). The
live `make weekly-flows` comparison, per the user's explicit instruction, is
run by the user afterward, the same way it was for feature 011.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

**Purpose**: capture what "no data loss, same duration at concurrency=1"
will be judged against, before any code changes — same discipline as feature
011.

- [ ] T001 Copy `db/horizon.db` to `/tmp/cnpq-concurrent-fix/before.db`, and record row counts for `researchers`, `persons`, `roles`, `team_members`, `research_groups`, `advisorships` into `/tmp/cnpq-concurrent-fix/before_counts.json`
- [ ] T002 Run the full test suite (`.venv/bin/python -m pytest tests/ -q --ignore=tests/integration`) and save the output to `/tmp/cnpq-concurrent-fix/baseline_tests.txt`

---

## Phase 2: Foundational

**Purpose**: the shared building block both stories need — the lean fetch
module — plus confirming the ground it stands on.

- [ ] T003 Confirm `ProcessPoolTaskRunner` is importable from `prefect.task_runners` in this environment, and confirm `sync_single_group` (in `src/flows/cnpq/groups.py`) has exactly one caller — `sync_cnpq_groups_flow` — per plan.md's Complexity Tracking precedent from feature 011
- [ ] T004 Create `src/flows/cnpq/fetch_worker.py` with a single `@task`-decorated function `fetch_group(group_info: dict) -> dict`, importing only `prefect`, `CnpqCrawlerAdapter`, and `normalize_cnpq_url` from `src/adapters/sources/cnpq_crawler.py` — no `research_domain`, no `tracking_recorder`, no `CnpqSyncLogic`
- [ ] T005 In `src/flows/cnpq/fetch_worker.py`, implement `fetch_group`'s body: call `adapter.get_group_data(url)`; on falsy result return `{"success": False, "group_id", "group_name", "url"}` (matching today's failure shape in `sync_single_group`); on success, call `extract_members`, `extract_leaders` (merging leaders into members as `{"role": "Líder", ...}` entries, exactly as `sync_single_group` does today), and `extract_research_lines`, returning `{"success": True, "group_id", "group_name", "url", "data", "members", "research_lines"}` per data-model.md
- [ ] T006 [P] In `tests/test_cnpq_fetch_worker.py` (new file), test `fetch_group.fn(...)` in isolation with a mocked `CnpqCrawlerAdapter`: one test for the success shape (all four fields present, leaders merged into members), one for the failure shape (falsy `get_group_data` result)

**Checkpoint**: the fetch step exists, is lean, and is independently tested.

---

## Phase 3: User Story 1 — CNPq page fetching runs concurrently (P1)

**Goal**: `sync_cnpq_groups_flow` submits fetches to a `ProcessPoolTaskRunner`
instead of calling `sync_single_group` directly, so multiple groups' pages
are in flight against the portal at once.

**Independent Test**: per quickstart.md §2, confirm fetch log lines for
different groups interleave in time.

- [ ] T007 [US1] In `src/flows/cnpq/groups.py`, add `CNPQ_FETCH_CONCURRENCY` as a module-level constant read from the environment (`int(os.getenv("CNPQ_FETCH_CONCURRENCY", "4"))`), following the `SIGPESQ_429_WAIT_SECONDS` precedent in `src/adapters/sources/sigpesq/adapter.py`
- [ ] T008 [US1] In `src/flows/cnpq/groups.py`, import `fetch_group` from `src.flows.cnpq.fetch_worker` and `ProcessPoolTaskRunner` from `prefect.task_runners`
- [ ] T009 [US1] In `src/flows/cnpq/groups.py`, add `task_runner=ProcessPoolTaskRunner(max_workers=CNPQ_FETCH_CONCURRENCY)` to `sync_cnpq_groups_flow`'s `@flow(...)` decorator
- [ ] T010 [US1] In `src/flows/cnpq/groups.py`, replace the `for g_info in groups: res = sync_single_group(g_info, researcher_index); results.append(res)` loop's fetch half: submit `fetch_group.submit(g_info)` for every group first, collecting futures **in submission order** into a list, per data-model.md's concurrency model
- [X] T011 [P] [US1] In `tests/test_cnpq_groups_flow.py`, add `test_fetches_are_all_submitted_before_any_result_is_consumed`: proves the submit-all-then-consume shape that makes concurrent fetching possible. A real running `ProcessPoolTaskRunner` needs a reachable Prefect API server, which this sandbox does not have (confirmed empirically — an ephemeral server could not be reached even over loopback), so this asserts the structural precondition instead: every `fetch_group.submit()` call happens before the loop consumes any `.result()`, per quickstart.md §2's intent expressed as a fast unit test instead of a live-portal run

**Checkpoint**: fetches run concurrently; nothing writes to the database yet
from this new path.

---

## Phase 4: User Story 2 — Writing to the database stays strictly serial (P2)

**Goal**: futures are consumed in order, and the existing write path
(`sync_group`/`sync_members`/`sync_knowledge_areas`, plus
`tracking_recorder.record_source_record`) runs exactly as it does today —
one group at a time, direct calls only, in the flow's own process.

**Independent Test**: the non-overlap test (T014) plus the existing
`test_cnpq_sync.py` suite passing unchanged.

- [X] T012 [US2] In `src/flows/cnpq/groups.py`, add a `_write_group_result(fetch_result, sync_logic, researcher_index)` function containing exactly the write-side body `sync_single_group` has today, starting from `tracking_recorder.record_source_record(...)` through `sync_logic.sync_knowledge_areas(...)`, adapted to read `data`/`members`/`research_lines` from `fetch_result` instead of computing them inline; returns the same `{"success", "group_id", "group_name", "url"}` shape
- [X] T013 [US2] In `src/flows/cnpq/groups.py`'s `sync_cnpq_groups_flow`, after collecting the futures from T010, loop over them **in the same order**, call `future.result()`, skip (record failure) if `result["success"] is False`, otherwise call `_write_group_result(...)` **as a direct call** — never `.submit()` — appending its return value to `results`; delete the now-unused `sync_single_group` function once nothing references it (confirm via T003's caller check)
- [X] T014 [US2] **The critical test.** In `tests/test_cnpq_groups_flow.py`, add `test_writes_never_overlap_even_if_fetches_finish_out_of_order`: patch `sync_logic.sync_group`/`sync_members`/`sync_knowledge_areas` (or `_write_group_result` directly) with a wrapper that increments a shared counter on entry, asserts the counter is never greater than 1, sleeps briefly (simulating write duration), then decrements on exit; drive several groups through the real flow loop and assert the counter never exceeded 1 at any point — this is the test contracts/fetch_write_contract.md requires: proof, not inference, that the one invariant holds
- [X] T015 [P] [US2] Update `tests/test_cnpq_groups_flow.py`'s existing `test_sync_single_group_forwards_shared_researcher_index` (added in feature 011) to instead exercise `_write_group_result` with the same assertion — that the `researcher_index` object passed in is the same one forwarded to `sync_members`, unchanged since 011
- [X] T016 [P] [US2] Update `tests/test_cnpq_sync.py` if any test references `sync_single_group` or the old `groups.py` call shape (grep first); `sync_members`'s own signature and behavior are unchanged by this feature, so most of that file should need no changes — confirm rather than assume (grep found no references — no changes needed)

**Checkpoint**: concurrency and serialization coexist, proven by T011 and T014
respectively, not just by code inspection.

---

## Phase 5: Polish & Validation

**Purpose**: prove SC-001, SC-003, SC-004, SC-005 with numbers; leave a clean
handoff for the user's own SC-002 run.

- [X] T017 Run the full suite (`.venv/bin/python -m pytest tests/ -q --ignore=tests/integration`), diff the FAILED lines against `/tmp/cnpq-concurrent-fix/baseline_tests.txt` from T002 — no test that passed before may fail now (SC-005) — then run `black`, `isort`, `flake8` on `src/flows/cnpq/groups.py`, `src/flows/cnpq/fetch_worker.py`, `tests/test_cnpq_groups_flow.py`, `tests/test_cnpq_fetch_worker.py`, `tests/test_cnpq_sync.py` — identical 7 pre-existing failures before and after (none introduced by this feature), 428 passed vs 424 baseline; black reformatted 2 files, flake8 caught 3 unused imports (`normalize_cnpq_url` in fetch_worker.py, `NO_CACHE` in groups.py, `MagicMock` in test_cnpq_fetch_worker.py) now removed; isort clean; also removed a leftover duplicated `return` block in `_write_group_result`

**Not in this task list — handoff to the user**:

- Live-portal verification of quickstart.md §2 and §3 (concurrent fetch
  interleaving, process isolation via `ps`).
- SC-001/SC-003 timing comparison (`CNPQ_FETCH_CONCURRENCY=4` vs `=1`)
  against the 50.2-minute baseline, which requires a real weekly run against
  the live CNPq portal.
- SC-002 end-to-end equivalence via `make weekly-flows`, compared against the
  T001 snapshot, using the same natural-key comparison methodology already
  used for feature 011 (IDs are not comparable across a `db-reset`).
- SC-004 (inject one failing group, confirm the rest complete) — best
  exercised against a real or realistically-faked portal response, not a
  unit test.

---

## Dependencies

```text
Setup (T001-T002) ──► Foundational (T003-T006) ──► US1 (T007-T011) ──► US2 (T012-T016) ──► Polish (T017)
```

- **US2 depends on US1's futures list (T010)** — there is nothing to consume
  serially until fetches are being submitted concurrently.
- **T014 depends on T012-T013** — it tests the loop structure those tasks
  build, not an independent unit.
- **T001 before any code change**: same reasoning as feature 011 — the
  comparison the user will run afterward is only meaningful against a
  snapshot taken before this feature.

## Parallel Opportunities

- T006 (fetch worker tests) is independent of the US1/US2 flow changes and
  can be written as soon as T004-T005 land.
- T011, T015, T016 touch the same test file but exercise independent
  behaviors — logically parallel, applied sequentially in practice.

## Implementation Strategy

**US1 without US2 is not shippable.** Concurrent fetching with no safe way to
consume the results serially is an incomplete feature, not a smaller one —
unlike most independently-testable user story pairs, these two exist because
they answer different questions about the *same* change, not because either
delivers value alone.

**T014 is not optional.** It is the one test explicitly demanded by
contracts/fetch_write_contract.md, because the failure mode it guards against
(a future change quietly making writes concurrent) does not throw an
exception — it produces occasional duplicate researchers under load, which is
exactly the kind of defect that survives code review and passes every test
that doesn't specifically look for it.
