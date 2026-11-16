---

description: "Task list for stopping the downloads when a portal blocks"
---

# Tasks: Stop Downloading When a Portal Blocks

**Input**: Design documents from `specs/024-portal-early-stop/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/portal-stop.md, contracts/settings-and-report.md, quickstart.md

**Tests**: the spec requires that the healthy path is identical and that an outage finishes in minutes (FR-008, SC-001, SC-004). Each story therefore starts with its tests, using fake portals, a fake clock and injected waits; no test touches the network.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md

`$R` = this session's scratchpad. Copies of `db/horizon.db`, `data/raw/` and
`cache/` go there. The real database is never written without the backup rule.

---

## Phase 1: Setup

- [X] T001 Record the baseline in `$R/e/E_BASE.txt`:
  - run `.venv/bin/pytest -q` and save the list of failing tests (expected: the known failures of spec 023's baseline);
  - copy the CNPq numbers of research.md R1–R2:
    - run 40966298828: 8th failed attempt at +4 min 49 s, phase killed at 10,800 s;
    - run 40959876147: 87 pages in 3 min 28 s.

---

## Phase 2: Foundational

**Purpose**: the stop rule, its settings, the counts and the report file, which every story uses.

- [X] T002 [P] Create `src/core/logic/portal_stop.py` as in contracts/portal-stop.md:
  - `PortalStopSettings` (`enabled`, `cnpq_failures=8`, `cnpq_budget_s=2700`, `lattes_failures=5`) and `for_source(source, clock)`. `for_source` returns `None` when the feature is off or every rule of the source is 0; Lattes has no budget rule.
  - `portal_stop_settings(env=None)` reads `HORIZON_PORTAL_EARLY_STOP`, `HORIZON_CNPQ_STOP_AFTER_FAILURES`, `HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN` and `HORIZON_LATTES_STOP_AFTER_FAILURES`:
    - a blank value gives the default;
    - an invalid or negative value logs a WARNING and gives the default;
    - 0 turns a rule off;
    - it never raises.
  - `PortalStop`, guarded by a `threading.Lock`, with:
    - `start()`, `should_stop()` (time budget, from an injected clock) and `record(success)` (failures in a row, reset by a success);
    - `wait(seconds)` on a `threading.Event`, set on the stop;
    - `summary()`.
    It stops once, sets `reason`, `stopped_at` (UTC) and `elapsed_s`, and logs `portal given up: <source> reason=... limit=... after=...s failures=... successes=...`.
- [X] T003 [P] Create `tests/test_portal_stop.py` for T002:
  - it stops at exactly N failures in a row; a success between them resets the count;
  - the budget stops it with a fake clock; a limit of 0 or a budget of 0 turns that rule off;
  - after the stop it stays stopped and `record` only counts;
  - `wait` returns at once once stopped, and after the timeout otherwise;
  - `for_source` returns `None` when disabled;
  - settings: defaults, blank, invalid values (warning and default), `0`/`false`/`no` turn it off;
  - 8 threads recording at once still give exact counters and a single stop.
- [X] T004 [P] In `src/core/logic/raw_rotation.py`:
  - extend `download_counts(plan, failed, stopped=())` with `stopped` and `stopped_ids`;
  - a stopped refresh id counts in `reused`, not in `refreshed`;
  - a stopped new id counts in neither `new` nor `failed`;
  - add `stopped=N` to the end of `counts_line`.
  Extend `tests/test_raw_rotation.py` with these cases; the existing assertions stay as they are.
- [X] T005 [P] Create `src/flows/portal_stops.py` as in contracts/settings-and-report.md:
  - `PORTAL_STOPS_PATH = "data/reports/portal_stops.json"`, read at call time;
  - `record_portal_stop(source, stop, counts, path=None)`: merges `stops[source] = {**stop.summary(), "counts": {...}}`. The counts drop `failed_ids` and `stopped_ids`. It writes atomically with `atomic_write_json`, `version: 1`, and never raises;
  - `read_portal_stops(path=None)` returns `{}` when the file is missing or unreadable;
  - `clear_portal_stops(path=None)`.
- [X] T006 [P] Create `tests/test_portal_stops_report.py` for T005:
  - round trip; two sources in one file;
  - replacing a source;
  - an unreadable file;
  - a write error is logged and does not raise;
  - clear on a missing file.
- [X] T007 In `tests/conftest.py`, redirect `src.flows.portal_stops.PORTAL_STOPS_PATH` to `tmp_path / "reports" / "portal_stops.json"` next to the spec 023 redirects, so no test writes to the repository's `data/reports/`.

**Checkpoint**: `.venv/bin/pytest tests/test_portal_stop.py tests/test_raw_rotation.py tests/test_portal_stops_report.py -q` passes.

---

## Phase 3: User Story 1 - CNPq stops downloading when the portal is down or hangs (Priority: P1) 🎯 MVP

**Goal**: an outage of the CNPq portal costs minutes, and every group with a stored page keeps its data.

**Independent Test**: a fake portal that fails every attempt, with stored pages for every group. The phase stops after 8 failed attempts, processes every group from its stored page, and leaves the database unchanged. With a healthy fake portal, the result is identical to today's.

### Tests for User Story 1

- [X] T008 [P] [US1] Create `tests/test_cnpq_early_stop.py`, part 1: the fetch level, with `fetch_all` and `fetch_with_retries`. Use fake adapters (always fail; fail 3 times then succeed; healthy), `sleep` and `clock` fakes, and a `PortalStop` with limit 8:
  - always failing:
    - exactly 8 adapter calls are made before the stop, plus none after (the ones in flight are counted);
    - every outcome is `data=None`;
    - the untried groups have `stopped=True, attempts=0`;
    - a back-off waiting on `stop.wait` returns at once at the stop;
  - recovering after 3: no stop, and every page is fetched;
  - budget: with a fake clock past 45 min, no attempt starts afterwards;
  - `stop=None`: outcomes and call counts are the same as today (compare with the same fake and no stop).
- [X] T009 [P] [US1] In `tests/test_cnpq_early_stop.py`, part 2: the phase level, `_sync_cnpq_groups`. Follow `tests/test_cnpq_rotation.py`: an SQLite file database, stored pages in the redirected `data/raw/cnpq`, and an adapter that always fails:
  - every group with a stored page is processed from it, keeps its stored `downloaded_at`, and is skipped as unchanged;
  - an untried group has no failure recorded in `source_document_states`;
  - a group with a failed attempt is recorded as a download failure (today's rule);
  - a group with no stored page is a failed download, and its rows are unchanged;
  - `skip.downloads` has `stopped` > 0;
  - the phase returns normally.
  Healthy adapter: the result and the database equal those of the same test with `HORIZON_PORTAL_EARLY_STOP=0`.

### Implementation for User Story 1

- [X] T010 [US1] In `src/flows/cnpq/concurrent_fetch.py`, as in contracts/portal-stop.md:
  - add `stopped: bool = False` to `FetchOutcome`;
  - `fetch_with_retries(..., stop=None)` checks `stop.should_stop()` before each attempt and again after acquiring the gate slot, calls `stop.record(bool(data))` after each attempt, and waits the back-off on `stop.wait(...)`, returning `stopped=True` when woken by the stop;
  - `fetch_all(..., stop=None)` calls `stop.start()` before submitting and passes `stop` to every task;
  - with `stop=None` the code path is today's.
- [X] T011 [US1] In `src/flows/cnpq/groups.py`, `_sync_cnpq_groups`:
  - build `stop = portal_stop_settings().for_source("cnpq")` and pass it to `fetch_all`;
  - in the writer loop, an outcome with `stopped and attempts == 0` is "not tried": use the stored page and its date, record no failure, and add the id to a `stopped_downloads` list. Without a stored page it stays a failed download (FR-004);
  - an outcome with `attempts > 0` and no data stays on today's failed path;
  - call `download_counts(plan, failed_downloads, stopped_downloads)`;
  - when `stop and stop.stopped`, call `record_portal_stop("cnpq", stop, counts)`;
  - add `stopped=` to the `CNPq fetch:` summary line.
- [X] T012 [US1] Run `.venv/bin/pytest tests/test_cnpq_early_stop.py tests/test_cnpq_concurrent_fetch.py tests/test_cnpq_rotation.py tests/test_cnpq_groups_flow.py tests/test_incremental_cnpq_sigpesq.py -q`. Every test passes, and the spec 017 and spec 023 tests pass unchanged.

**Checkpoint**: the CNPq early stop works on its own (MVP).

---

## Phase 4: User Story 2 - Lattes stops refreshing when the portal blocks (Priority: P1)

**Goal**: a blocking Lattes portal gets at most the limit of requests, plus the ones in flight; the curricula left keep their cached copy and are taken first next run.

**Independent Test**: a fake downloader that writes the access check page. The download stops after 5 in a row, every cached copy is kept, the new curricula stay missing, and the next `plan_downloads` lists the untried curricula first.

### Tests for User Story 2

- [X] T013 [P] [US2] Create `tests/test_lattes_early_stop.py`, using the helpers of `tests/test_lattes_rotation.py` (`_page`, `CAPTCHA`, the fake downloaders):
  - always the access check page, limit 5, 1 worker:
    - exactly 5 downloader calls;
    - every cached copy keeps its bytes and its manifest date;
    - the new curricula have no cache file;
    - `counts["stopped"]` is the number of untried ids;
  - with 3 workers: at most 5 + 2 calls;
  - access check page from the 4th request: the stop comes at the 8th call;
  - interleaved, 1 of every 5 requests: no stop;
  - a stop during the new-curricula download leaves the refreshes untried too (shared counter);
  - the next run's `plan_downloads` puts the untried refreshes first, and the untried new curricula are new again;
  - `HORIZON_PORTAL_EARLY_STOP=0`: every due curriculum is requested, as in spec 023;
  - `retry_unidentified` behaves as before.

### Implementation for User Story 2

- [X] T014 [US2] In `src/flows/lattes/download.py`:
  - add `class _NotTried(Exception)`;
  - `prefetch_lattes_cache(..., stop=None, not_tried=None)` and `refresh_lattes_cache(..., stop=None)` wrap each task:
    - if `stop.should_stop()`, raise `_NotTried` without calling the downloader;
    - otherwise run the download and the existing checks, then `stop.record(True)` on success, or `stop.record(False)` on any exception, and re-raise;
  - a `_NotTried` is collected apart from failures and logged at INFO;
  - `refresh_lattes_cache` returns `(refreshed, failed, not_tried)`, and its existing caller is updated;
  - with `stop=None` the code path is today's.
- [X] T015 [US2] In `rotate_lattes_downloads` in `src/flows/lattes/download.py`:
  - build `stop = portal_stop_settings().for_source("lattes")`, call `stop.start()`, and pass the same stop to the prefetch and to the refresh;
  - record dates only for the successes (today);
  - call `download_counts(plan, failed, stopped)`;
  - when stopped, call `record_portal_stop("lattes", stop, counts)`.
- [X] T016 [US2] Run `.venv/bin/pytest tests/test_lattes_early_stop.py tests/test_lattes_rotation.py tests/test_download_lattes_flow.py -q`; spec 023's Lattes tests pass unchanged.

**Checkpoint**: both early stops work on their own.

---

## Phase 5: User Story 3 - The run says when a portal was given up (Priority: P2)

**Goal**: the weekly summary and its Telegram message show each stop, its reason and its counts, and the exit code does not change.

**Independent Test**: with a `portal_stops.json` holding a CNPq entry, `run_weekly` (phases faked as in `tests/test_weekly_orchestrator.py`) logs the `⚠ cnpq` line, sends it in the Telegram text, returns 0, and clears the file at the start of the next call.

### Tests for User Story 3

- [X] T017 [P] [US3] In `tests/test_weekly_orchestrator.py`, add:
  - a stale `portal_stops.json` from an earlier weekly is removed before the first phase;
  - a phase fake that writes a CNPq entry gives one `⚠ cnpq: portal given up (failures_in_a_row, limit 8) ...` summary line and the Portuguese line in the captured `send_telegram_message` text;
  - the exit code equals that of the same run without the file;
  - no file means no extra line.

### Implementation for User Story 3

- [X] T018 [US3] In `src/flows/pipelines/weekly_orchestrator.py`:
  - call `clear_portal_stops()` in `run_weekly` before the first phase;
  - after the phase lines of the summary, read `read_portal_stops()` and log one line per source (contracts/settings-and-report.md);
  - pass the same entries to `_notify`, which adds the Portuguese lines after the phase list;
  - wrap all of it so a report problem never changes the outcome.
- [X] T019 [US3] Run `.venv/bin/pytest tests/test_weekly_orchestrator.py tests/test_weekly_orchestrator_finalize.py tests/test_weekly_pipeline_flow.py -q`.

**Checkpoint**: an early stop is visible in the summary alone (SC-006).

---

## Phase 6: User Story 4 - The limits are configurable (Priority: P3)

**Goal**: the limits and the switch can be set from the Makefile and from a manual dispatch; scheduled runs use the defaults.

**Independent Test**: `make -n weekly-flows CNPQ_STOP_AFTER=2 EARLY_STOP=0` shows both variables. The workflow test sees the four inputs mapped to the four variables of the "Run weekly flows" step.

### Tests for User Story 4

- [X] T020 [P] [US4] In `tests/test_weekly_etl_workflow.py`, assert:
  - the inputs `early_stop` (boolean, default true), `cnpq_stop_after`, `cnpq_budget_min` and `lattes_stop_after` (string, default `""`) exist;
  - the "Run weekly flows" step sets `HORIZON_PORTAL_EARLY_STOP`, `HORIZON_CNPQ_STOP_AFTER_FAILURES`, `HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN` and `HORIZON_LATTES_STOP_AFTER_FAILURES` from them;
  - the dispatch inputs are at most 10.

### Implementation for User Story 4

- [X] T021 [US4] In `.github/workflows/weekly-etl.yml`:
  - add the four inputs with the descriptions of contracts/settings-and-report.md;
  - map them in the "Run weekly flows" `env:` block, next to `HORIZON_REFRESH_SHARE`, with a one-line comment naming spec 024.
- [X] T022 [P] [US4] In `Makefile`:
  - forward `EARLY_STOP`, `CNPQ_STOP_AFTER`, `CNPQ_BUDGET_MIN` and `LATTES_STOP_AFTER` in `weekly-flows`, `sync-cnpq` and `ingest-lattes-download`, only when set, in the `REFRESH_SHARE` style;
  - name them in the `weekly-flows` help text.
- [X] T023 [US4] Run `.venv/bin/pytest tests/test_weekly_etl_workflow.py -q` and `make -n weekly-flows CNPQ_STOP_AFTER=2 EARLY_STOP=0`, and check the variables in the printed command.

**Checkpoint**: all four stories work.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T024 Run the full suite, `.venv/bin/pytest -q`: no failure beyond the T001 baseline. Then run `black --check`, `isort --check` and `flake8` on the changed files.
- [X] T025 Local replay of the outage (quickstart.md §2 and plan Validation 2):
  - back up `db/horizon.db`, `data/raw/` and `cache/` first;
  - on a copy in `$R/e/work/`, run the CNPq phase with an adapter that fails every attempt after a 95 s fake wait, using an accelerated clock in a scratch script;
  - expected: the phase ends in minutes, the database file is unchanged (`sqlite3 .dump` compare), and `portal_stops.json` is written;
  - then run `make sync-cnpq CNPQ_BUDGET_MIN=0.5` on the copy against the real portal: a `time_budget` stop and the stored pages are used.
- [X] T026 [P] In `docs/backlog.md`, add the residual risk of research R4: a navigation that hangs past the library's timeout still holds the phase until 10,800 s. Add it as a TD item, without changing the library.
- [X] T027 [P] Document the four variables in the weekly section of the docs that lists `HORIZON_REFRESH_SHARE`. Find it with `grep -rn HORIZON_REFRESH_SHARE docs README.md`.
- [X] T028 Write `docs/reports/2026-10-30-portal-early-stop-validation.md` with:
  - the baseline;
  - the test results;
  - the local replay (T025);
  - after the maintainer's approval, the two fork dispatches of quickstart.md §3: healthy with the defaults, and forced with `cnpq_budget_min=1` and `lattes_stop_after=1`.
  Never dispatch without asking the maintainer.
- [X] T029 Mark the finished tasks `[X]` in this file, and update the personal `PLANO_PROXIMOS_PASSOS.md`. Never stage or commit that file.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001; blocks every story.
- **US1 (Phase 3)** and **US2 (Phase 4)**: after Phase 2; independent of each other (different files).
- **US3 (Phase 5)**: after Phase 2; its tests fake the report file, so it does not wait for US1 or US2.
- **US4 (Phase 6)**: after Phase 2 (the settings exist); independent of US1–US3.
- **Polish (Phase 7)**: after the stories wanted; T025 needs US1, and T028 needs everything.

### Within Each Story

- Tests first (they fail before the implementation), then the implementation, then the test run task.
- T010 before T011 (the writer uses `stopped`); T014 before T015.

### Parallel Opportunities

- Phase 2: T002, T004 and T005 are different files; T003 and T006 go with their pairs; T007 after T005.
- US1 tests T008 and T009 (two parts of one new file, written together) alongside US2's T013, US3's T017 and US4's T020.
- T021 and T022.
- T026 and T027.

---

## Parallel Example: after Phase 2

```bash
Task: "T008/T009 CNPq early stop tests in tests/test_cnpq_early_stop.py"
Task: "T013 Lattes early stop tests in tests/test_lattes_early_stop.py"
Task: "T017 Weekly summary tests in tests/test_weekly_orchestrator.py"
Task: "T020 Workflow input tests in tests/test_weekly_etl_workflow.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 and Phase 2.
2. Phase 3 (CNPq): this alone fixes the 3 h outage of run 40966298828.
3. **Stop and validate**: T012 and the CNPq part of T025.

### Incremental Delivery

1. US1, the CNPq stop: the biggest cost removed.
2. US2, the Lattes stop.
3. US3, visible in the summary.
4. US4, configurable from the dispatch.
5. Polish, the report, and the fork dispatches after approval.

---

## Notes

- Commit only when the maintainer asks, staging explicit paths; never `PLANO_*.md` or `RESUMO_*.md`.
- Third-party libraries (dgp_cnpq_lib, scriptLattes) unchanged; CNPq keeps 4 workers; SigPesq is untouched; no Docker change.
- The access check page is never answered or bypassed.
