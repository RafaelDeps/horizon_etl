---

description: "Task list for the concurrent CNPq group sync"
---

# Tasks: Concurrent CNPq Group Sync with a Single Writer

**Input**: Design documents from `specs/017-cnpq-concurrent-sync/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/cnpq-sync.md](contracts/cnpq-sync.md), [quickstart.md](quickstart.md)

**Tests**: Requested by the spec (FR-015, SC-006). Test tasks come first in each story and must fail before the implementation.

**Organization**:
- **US1**: concurrent fetch with a single ordered writer.
- **US2**: researcher index once per phase (TD-008).
- **US3**: retries with back-off and the failure-burst rule.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task).
- **[Story]**: US1–US3.
- `$R` = `/tmp/claude-1000/-home-rafael-horizon-etl/326c8482-b2cb-4ce7-918a-b95d4469a905/scratchpad`. `$R/replay` holds the spec 015 replay assets (`inputs/`, `prep_run.sh`, `env.sh`, `replay_sigpesq.py`, `compare.py`). `$R/replay017` holds this feature's assets, including `cnpq_payloads.json` with the 350 captured payloads. Nothing under `$R` is committed.

---

## Phase 1: Setup (replay assets, built before any code change)

**Purpose**: Freeze the base code and the replay inputs, and build the comparison tools.

- [X] T001 Verify that `$R/replay017/cnpq_payloads.json` exists and holds 347 URLs, and that `$R/replay/inputs/sigpesq/` exists. Copy the **base** code (the current spec 016 tree: `src/`, `app.py`, `lattes.config`, `db/create_db.py`) to `$R/replay017/base_code/` (`cp -r`, then remove `__pycache__`). Write `git rev-parse HEAD` and `git status --short` to `$R/replay017/BASE.txt`.
- [X] T002 [P] Build the pre-CNPq snapshot with the base code:
  1. `D=$($R/replay/prep_run.sh $R/replay017/base_code pre_cnpq)`, `source $R/replay/env.sh`, `export DATABASE_URL=sqlite:///$R/replay017/pre_cnpq.db` (a fresh file);
  2. from `$D`: `PYTHONPATH=$D .venv/bin/python db/create_db.py`, then `PYTHONPATH=$D .venv/bin/python $R/replay/replay_sigpesq.py`.

  The result is the state the weekly run has right before `cnpq`.
- [X] T003 [P] Write `$R/replay017/replay_cnpq.py`, a throwaway Prefect flow with no Telegram hooks:
  - load `cnpq_payloads.json`;
  - patch `src.adapters.sources.cnpq_crawler.CnpqCrawlerAdapter.get_group_data` with a function `(self, url)` that sleeps `random.Random(hash(url)).uniform(0.5, 3.0)` seconds and returns a deep copy of the payload for `url`, or `None` when the URL is missing;
  - call `src.flows.cnpq.groups.sync_cnpq_groups_flow.fn()` inside the flow;
  - print `REPLAY cnpq <seconds>s` and the summary's `success_count`/`failed_count`.
- [X] T004 [P] Write `$R/replay017/compare_cnpq.py <a.db> <b.db>`. It opens both databases read-only and compares:
  - row counts of `research_groups`, `team_members`, `persons`, `researchers`, `knowledge_areas`, `group_knowledge_areas` and `teams`;
  - the multiset `(team name, person name, role name)` from `team_members ⋈ teams ⋈ persons ⟕ roles`;
  - the multiset `(team name, knowledge area name)` from `group_knowledge_areas ⋈ teams ⋈ knowledge_areas`. Read the column names with `PRAGMA table_info`;
  - `source_records` counts per `source_entity_type`.

  It prints the differences and `RESULT: IDENTICAL` or `RESULT: DIFFERENT`, and exits 0 only when identical.
- [X] T005 Produce the **base** replay result:
  1. `D=$($R/replay/prep_run.sh $R/replay017/base_code base_cnpq)`, `source $R/replay/env.sh`;
  2. `cp $R/replay017/pre_cnpq.db $R/replay017/base_cnpq.db`, `export DATABASE_URL=sqlite:///$R/replay017/base_cnpq.db`;
  3. from `$D`: `PYTHONPATH=$D .venv/bin/python $R/replay017/replay_cnpq.py > $R/replay017/base_cnpq.log 2>&1`.

  Record the time and the counts in `BASE.txt`. Depends on T001–T003.

**Checkpoint**: The base reference exists, and code changes may start.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Make the write stage accept pre-fetched data. US1 and US3 need it; US2 is independent.

- [X] T006 In `src/flows/cnpq/groups.py`, change `sync_single_group(group_info: dict)` to `sync_single_group(group_info: dict, data=_NOT_FETCHED, researcher_index=None)`, with a module-level sentinel `_NOT_FETCHED = object()`.
  - When `data is _NOT_FETCHED`: keep today's code path exactly (build the adapter and call `get_group_data`).
  - Otherwise: use the given `data`, still constructing `CnpqCrawlerAdapter()`, which `extract_members`, `extract_leaders` and `extract_research_lines` need.
  - Pass `researcher_index` to `sync_logic.sync_members(...)` only if it is not `None`.
  - Every log message and return dict must stay identical.

**Checkpoint**: `pytest -q tests/test_cnpq_sync.py` still passes.

---

## Phase 3: User Story 1 - Group pages are fetched in parallel, data is written by one writer (Priority: P1) 🎯 MVP

**Goal**: Up to N fetches in flight through a gate. Writes run on the flow thread, in the original order. `HORIZON_CNPQ_WORKERS` sets N (default 4). N = 1 behaves sequentially.

**Independent Test**: `tests/test_cnpq_concurrent_fetch.py` (US1 cases) passes, and the replay comparison (T024) is identical.

### Tests for User Story 1 ⚠️ (write first)

- [X] T007 [P] [US1] Create `tests/test_cnpq_concurrent_fetch.py` with a `FakeAdapter` whose `get_group_data(url)` sleeps a per-URL delay chosen so that completions arrive out of order, records the peak number of concurrent calls (lock-protected counter) and returns `{"nome_grupo": url}`. Cover:
  - `fetch_all(groups, adapter_factory, max_workers=4, sleep=…, clock=…)` from `src/flows/cnpq/concurrent_fetch.py` yields one `FetchOutcome` per group;
  - the peak in flight is ≤ 4 and equals 4 for 12 groups;
  - outcomes are consumed by index 0..n-1 in order;
  - `max_workers=1` gives a peak of 1;
  - `resolve_workers("0")`, `("-2")` and `("abc")` return 4 and log a WARNING; `("3")` returns 3.
- [X] T008 [P] [US1] In `tests/test_cnpq_concurrent_fetch.py`, add a flow-level test for `sync_cnpq_groups_flow.fn()`. Patch:
  - `get_groups_to_sync` to return 6 groups;
  - `CnpqCrawlerAdapter.get_group_data` to the fake, with out-of-order delays;
  - `sync_single_group` with a recorder of `(threading.current_thread(), group id)`;
  - `load_researcher_index` and `tracking_recorder.run_context`.

  Assert that every write ran on the flow's thread, the group ids were written in the original order, and the returned summary has `success_count == 6`.

### Implementation for User Story 1

- [X] T009 [US1] Create `src/flows/cnpq/concurrent_fetch.py` with:
  - `FetchOutcome` (dataclass: `index`, `group_info`, `data`, `attempts`);
  - `resolve_workers(value: Optional[str], default=4) -> int`;
  - `AdaptiveGate(max_workers, clock)` with `acquire()`/`release()` (a context manager) on a `threading.Condition`, holding `limit` and `in_flight`;
  - `fetch_all(groups, adapter_factory, max_workers, sleep=time.sleep, clock=time.monotonic)`. It submits one job per group to a `ThreadPoolExecutor(max_workers + 4)`. Each job calls `adapter_factory().get_group_data(group["url"])` inside the gate once (retries come in US3). It returns a list of futures by index.

  No database access and no Prefect imports in this module.
- [X] T010 [US1] Rewrite the loop in `sync_cnpq_groups_flow` (`src/flows/cnpq/groups.py`):
  - read `HORIZON_CNPQ_WORKERS` through `resolve_workers`;
  - `futures = fetch_all(groups, CnpqCrawlerAdapter, workers)`;
  - then, inside the existing `tracking_recorder.run_context(...)`, for `i, g_info in enumerate(groups)`: `outcome = futures[i].result()`, then `res = sync_single_group(g_info, data=outcome.data, researcher_index=researcher_index)`, and append it to `results`.

  `researcher_index` is `None` for now (US2 sets it). Shut the executor down in a `finally`. Keep `build_cnpq_sync_summary` and the final log unchanged. Depends on T006, T009.
- [X] T011 [US1] Run `.venv/bin/python -m pytest -q tests/test_cnpq_concurrent_fetch.py tests/test_cnpq_sync.py`. All must pass. Depends on T007, T008, T010.

**Checkpoint**: The phase fetches in parallel and writes serially, in order.

---

## Phase 4: User Story 2 - Member sync stops re-reading the whole researcher register per group (Priority: P2)

**Goal**: `load_researcher_index` runs once per phase and is passed to every `sync_members`, with hit and created counters.

**Independent Test**: `tests/test_cnpq_sync.py` (new cases) passes, and the replay comparison (T024) is identical.

### Tests for User Story 2 ⚠️ (write first)

- [X] T012 [P] [US2] In `tests/test_cnpq_sync.py`, add tests, reusing the existing `MagicMock` setup pattern of `test_sync_members_uses_resume_fallback_for_new_researcher`:
  - **No `get_all`:** `sync_members(..., researcher_index=[ResearcherRef(id=5, name="Ana Lima")])` with member "Ana Lima" never calls `logic.res_ctrl.get_all`, and links researcher 5.
  - **Created, then found:** two calls share one index list. Group A creates "Novo Pesquisador" (`create_researcher` mocked to return id 900), and group B with the same member reuses id 900 without a second creation. The index list now contains a `ResearcherRef` with id 900.
  - **Counters:** `CnpqSyncLogic.researcher_counters` (class-level, reset by a helper) reports hits and created as expected.
  - **Old path:** with `researcher_index` omitted, `get_all` is called once, as today.

### Implementation for User Story 2

- [X] T013 [US2] In `src/core/logic/strategies/cnpq_sync.py`, add `researcher_index: Optional[list] = None` to `sync_members`:
  - `all_res = researcher_index if researcher_index is not None else self.res_ctrl.get_all()`;
  - count hits (the result was in `all_res` before the call) and creations (the list grew) in a module-level counter dict, exposed through `CnpqSyncLogic.researcher_counters` and reset by `reset_researcher_counters()`.

  Leave everything else untouched.
- [X] T014 [US2] In `sync_cnpq_groups_flow` (`src/flows/cnpq/groups.py`), before the write loop, load the index once:
  - `researcher_index = load_researcher_index(ResearcherController()._service._repository._session)`, mirroring `src/flows/lattes/advisorships.py`, with the same warning fallback to an empty list;
  - pass it to every `sync_single_group` call;
  - call `reset_researcher_counters()` at the flow start.

  Depends on T010, T013.
- [X] T015 [US2] Run `.venv/bin/python -m pytest -q tests/test_cnpq_sync.py tests/test_cnpq_concurrent_fetch.py`. All must pass. Depends on T012, T014.

**Checkpoint**: The researcher register is read once per phase.

---

## Phase 5: User Story 3 - Portal resets do not silently cost groups (Priority: P3)

**Goal**: Up to 3 attempts per group with waits of 30 s and 90 s ±20% outside the gate. The burst rule (≥ 4 failures in 60 s) halves the limit, which is restored one step after 120 s without failures. The final summary line is added.

**Independent Test**: `tests/test_cnpq_concurrent_fetch.py` (US3 cases) passes, using an injected sleep and clock.

### Tests for User Story 3 ⚠️ (write first)

- [X] T016 [P] [US3] In `tests/test_cnpq_concurrent_fetch.py`, add:
  - **Retry and recover:** a fake that returns `None` on the first 1 or 2 calls for a URL and data afterwards. The group ends with data, `attempts` is 2 or 3, and the injected `sleep` received waits within 30 s ±20% and 90 s ±20%.
  - **Permanent failure:** a URL that is always `None` gives `FetchOutcome(data=None, attempts=3)`, the other groups still complete, and their order is preserved.
  - **Waits outside the gate:** while one group sleeps between attempts, other fetches proceed. Use a blocking `sleep` with an event and assert another fetch completes during it.
  - **Burst rule:** with an injected clock, 4 failures within 60 s drop `gate.limit` from 4 to 2 and record one reduction. Advancing the clock 120 s without failures restores it to 3. The limit never goes below 1.
  - **Summary line:** a flow-level test asserts one INFO line matching `CNPq fetch: workers=\d+ fetched=\d+ retries=\d+ failed_after_retries=\d+ concurrency_reductions=\d+ researcher_index_loaded=\d+ researcher_hits=\d+ researcher_created=\d+`.

### Implementation for User Story 3

- [X] T017 [US3] In `src/flows/cnpq/concurrent_fetch.py`:
  - add the burst window to `AdaptiveGate`: `record_failure()`, `maybe_restore()` called in `acquire()`, a `reductions` counter, a WARNING on reduction (`CNPq fetch: failures clustering, concurrency <old> → <new>`) and an INFO on restore;
  - add `fetch_with_retries(group, adapter_factory, gate, sleep, rng)`: up to 3 attempts; each attempt calls `get_group_data` inside the gate; on `None`, call `gate.record_failure()` and, if attempts remain, `sleep(base * rng.uniform(0.8, 1.2))` **outside** the gate with `base` in `(30, 90)`. It returns a `FetchOutcome`;
  - use it from `fetch_all`, and accept `rng` (a seeded `random.Random` in tests).
- [X] T018 [US3] In `sync_cnpq_groups_flow` (`src/flows/cnpq/groups.py`), after the write loop, log the INFO summary line in the data-model.md format: `workers`; `fetched` (outcomes with data); `retries` (sum of `attempts - 1`); `failed_after_retries`; `concurrency_reductions` (from the gate); `researcher_index_loaded` (`len` at load time); and `researcher_hits` / `researcher_created` from `CnpqSyncLogic.researcher_counters`. Depends on T014, T017.
- [X] T019 [US3] Run `.venv/bin/python -m pytest -q tests/test_cnpq_concurrent_fetch.py tests/test_cnpq_sync.py`. All must pass. Depends on T016–T018.

**Checkpoint**: Resets are retried, and bursts slow the phase down.

---

## Phase 6: Polish, Validation & Cross-Cutting Concerns

- [X] T020 Run `.venv/bin/black` and `.venv/bin/isort` on `src/flows/cnpq/groups.py`, `src/flows/cnpq/concurrent_fetch.py`, `src/core/logic/strategies/cnpq_sync.py`, `tests/test_cnpq_concurrent_fetch.py` and `tests/test_cnpq_sync.py`. Run `.venv/bin/flake8` on them and confirm no warnings are new compared with `git show HEAD:<file>`.
- [X] T021 Run the full suite: `.venv/bin/python -m pytest -q tests --ignore=tests/integration -p no:cacheprovider`. Only the 6 pre-existing failures (spec 015 report §6) may fail. Depends on T020.
- [X] T022 Run a thread-safety smoke test of the real library: `HORIZON_CNPQ_WORKERS=4` and `fetch_all` over 8 groups whose URL is a local `file://` HTML page with `<h1>` and two `<fieldset>`s (reuse `$R/replay017/page.html`), using the real `CnpqCrawlerAdapter`. It must give 8 outcomes with data and a peak in flight ≤ 4. No portal access.
- [X] T023 Run the feature replay:
  1. `D=$($R/replay/prep_run.sh /home/rafael/horizon_etl feature_cnpq)`, `source $R/replay/env.sh`;
  2. `cp $R/replay017/pre_cnpq.db $R/replay017/feature_cnpq.db`, `export DATABASE_URL=sqlite:///$R/replay017/feature_cnpq.db`;
  3. from `$D`: `PYTHONPATH=$D .venv/bin/python $R/replay017/replay_cnpq.py > $R/replay017/feature_cnpq.log 2>&1`.

  Record the time and the `CNPq fetch: …` line. Depends on T005, T021.
- [X] T024 Run `.venv/bin/python -I $R/replay017/compare_cnpq.py $R/replay017/base_cnpq.db $R/replay017/feature_cnpq.db`. It must print `RESULT: IDENTICAL` (SC-004). If it differs, stop and investigate before any timing run. Depends on T023.
- [X] T025 Run the replay once more with `HORIZON_CNPQ_WORKERS=1` into `feature1_cnpq.db`, and compare it against `base_cnpq.db`. It must be identical (FR-005). Depends on T024.
- [X] T026 Full timing run. Start it only if no full CNPq crawl ran in the previous few hours. Run `make weekly-flows > logs/weekly_017_validation.log 2>&1` in the background, with `HORIZON_TELEGRAM_BOT_TOKEN=`, `TELEGRAM_BOT_TOKEN=`, `HORIZON_TELEGRAM_CHAT_ID=` and `TELEGRAM_CHAT_ID=` exported empty. From the log, extract:
  - each phase's duration;
  - the `CNPq sync: x/y` line;
  - the `CNPq fetch: …` line;
  - any WARNING `failures clustering` lines;
  - any `database is locked` lines (must be none).

  Depends on T025.
- [X] T027 Write `docs/reports/2026-10-<dd>-cnpq-concurrent-validation.md` in English, in the structure of the spec 016 report:
  - a success-criteria table;
  - the replay results (N = 4 and N = 1);
  - the full-run phase table against the spec 016 run;
  - the `CNPq fetch` line and the retry/burst behaviour observed;
  - every difference found, with its cause;
  - suggested tuning, if any.

  Depends on T026.
- [X] T028 [P] Update `docs/backlog.md`: mark TD-008 (the CNPq part) and TD-014 as Fixed by spec 017, with a link to the T027 report. Note any open follow-up observed, such as tuning the retry waits.
- [X] T029 [P] Update `docs/flows-and-entrypoints.md` with a short subsection on `HORIZON_CNPQ_WORKERS` (default 4; 1 = sequential), the retry and burst behaviour, and the meaning of each counter of the `CNPq fetch: …` line, with real values from T026.
- [X] T030 Mark T001–T029 as done in this file, and set `specs/017-cnpq-concurrent-sync/spec.md` **Status** to `Implemented`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 first; T002, T003 and T004 in parallel; T005 after T001–T003. It runs on the base code, before any change.
- **Foundational (Phase 2)**: T006, after Phase 1.
- **US1 (Phase 3)**: after T006.
- **US2 (Phase 4)**: T012 and T013 can start after Phase 1. They touch `cnpq_sync.py` and its tests. T014 needs T010.
- **US3 (Phase 5)**: after US1 (it extends `concurrent_fetch.py` and the flow), and T018 also after T014.
- **Polish (Phase 6)**: after US1–US3.

### User Story Dependencies

- **US1 (P1)**: the MVP; it overlaps the portal waits.
- **US2 (P2)**: independent code in `cnpq_sync.py`; it is wired into the flow after US1.
- **US3 (P3)**: builds on US1's fetcher.

### Within Each User Story

- Tests first: T007/T008 before T009/T010; T012 before T013; T016 before T017.
- T009 → T010 → T011; T013 → T014 → T015; T017 → T018 → T019.

### Parallel Opportunities

- T002 ∥ T003 ∥ T004 (separate scratch files).
- T007 ∥ T012: different test files. (T008 shares T007's file, so write them together.)
- US2 implementation (`cnpq_sync.py`, T013) ∥ US1 implementation (`concurrent_fetch.py`, T009).
- T028 ∥ T029.

---

## Parallel Example: User Stories 1 and 2

```bash
Task: "Concurrent fetch tests in tests/test_cnpq_concurrent_fetch.py"        # T007
Task: "researcher_index tests in tests/test_cnpq_sync.py"                    # T012
Task: "AdaptiveGate + fetch_all in src/flows/cnpq/concurrent_fetch.py"       # T009
Task: "sync_members(researcher_index=...) in src/core/logic/strategies/cnpq_sync.py"  # T013
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Setup (T001–T005), then Foundational (T006).
2. US1 (T007–T011): parallel fetch with an ordered single writer.
3. **Stop and validate**: run the replay comparison early, with a quick run of T023 and T024.

### Incremental Delivery

1. US1, then the replay check.
2. US2, which removes the per-group register read.
3. US3: retries, the burst rule and the summary line.
4. Validation: the full replay at N = 4 and N = 1, the timing run, the report, the backlog and the docs.

---

## Notes

- Never modify `dgp_cnpq_lib` or any other installed library, and never write an own DGP crawler (FR-013).
- No database access from worker threads. `concurrent_fetch.py` must not import controllers, sessions or `tracking_recorder`.
- Keep SigPesq sequential. Do not touch the phase timeouts, the workflow file or Docker.
- The replay never contacts the portal. Only T026 does, and only spaced from other crawls.
