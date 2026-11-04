---

description: "Task list for the second try of the Lattes access check pages"
---

# Tasks: Second Try for Lattes Access Check Pages

**Input**: Design documents from `specs/025-lattes-captcha-retry/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/access-check-retry.md, contracts/settings-and-report.md, quickstart.md

**Tests**: the spec requires two things:
- the output is identical with the second pass off or with a healthy portal
  (FR-006, SC-004);
- the second pass never goes past the portal stop (FR-005, SC-003).

Each story therefore starts with its tests. They use the fake portal of
`tests/test_lattes_early_stop.py`, extended to answer per id and per
attempt, and an injected `sleep`. No test touches the network.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md

`$R` = this session's scratchpad. Copies of `db/horizon.db`,
`data/raw/lattes/` and `cache/` go there. The real database is never written
without the backup rule.

---

## Phase 1: Setup

- [X] T001 Record the baseline in `$R/e/E_BASE.txt`:
  - run `.venv/bin/pytest -q` and save the list of failing tests (expected: the 6 known failures of the spec 024 report, section 3);
  - copy the numbers of research.md R3 and R8:
    - the run from scratch of 2026-11-03: 38 access check pages in 435 requests, 17 to 22 successes per minute with 3 workers, the first pass in 25 min;
    - the `lattes_download` limit of 5,400 s.

---

## Phase 2: Foundational

**Purpose**: the settings, the detection of the access check page, and the test default that every story uses.

- [X] T002 [P] Create `src/core/logic/access_check_retry.py` as in contracts/settings-and-report.md:
  - `AccessCheckRetrySettings(workers=1, pause_s=300.0)`, a frozen dataclass with an `enabled` property (`workers > 0`);
  - the constants `WORKERS_ENV = "HORIZON_LATTES_RETRY_WORKERS"`, `PAUSE_ENV = "HORIZON_LATTES_RETRY_PAUSE_MIN"`, `DEFAULT_WORKERS = 1` and `DEFAULT_PAUSE_MIN = 5.0`, with a comment citing research R3;
  - `access_check_retry_settings(env=None)`:
    - a blank value gives the default;
    - an invalid value logs `Invalid <NAME>=<value>; using <default>` and gives the default. Invalid means not a number, negative, not finite, or not an integer for workers;
    - it never raises; the pause is converted from minutes to seconds;
  - a module docstring in the style of `portal_stop.py`: pure logic, no file or network access.
- [X] T003 [P] Create `tests/test_access_check_retry.py` for T002. It checks:
  - the defaults; blank values;
  - `0` workers is off, and a `0` pause is no wait;
  - decimal minutes (`0.1` → 6 s);
  - invalid values (`abc`, `-1`, `1.5` workers, `inf`), each with a warning and the default;
  - that the env mapping is read and not `os.environ` when one is given.
- [X] T004 In `src/flows/lattes/download.py`:
  - add `class AccessCheckPage(ScriptLattesRuntimeError)`, with a docstring citing spec 025, research R1;
  - `_download_lattes_to_cache` and `refresh_one` (inside `refresh_lattes_cache`) raise `AccessCheckPage` in place of the current `ScriptLattesRuntimeError` for the access check page, with the same message. The deletion of the file in `_download_lattes_to_cache` stays as it is;
  - `prefetch_lattes_cache(..., access_checked: Optional[List[str]] = None)` and `refresh_lattes_cache(..., access_checked: Optional[List[str]] = None)` append the id when the caught exception is an `AccessCheckPage`, in both the one-worker and the pool branches of the prefetch. The logging and the failed lists stay as they are.
- [X] T005 In `tests/conftest.py`, add an autouse fixture that sets `HORIZON_LATTES_RETRY_WORKERS=0` with `monkeypatch`, and a comment: the spec 023 and spec 024 tests describe the behaviour without the second pass (research R7). The new tests set or delete the variable themselves.
- [X] T006 Run `.venv/bin/pytest tests/test_lattes_rotation.py tests/test_lattes_early_stop.py tests/test_download_lattes_flow.py -q`. They must pass unchanged, apart from the 3 known `test_download_lattes_flow.py` failures of the baseline.

**Checkpoint**: the access check page is told apart, and nothing else changed.

---

## Phase 3: User Story 1 - A rejected curriculum is asked for again in the same run (Priority: P1) 🎯 MVP

**Goal**: the curricula that got the access check page get one more request, after a pause, with 1 worker. They end the run with their real page.

**Independent Test**: use a fake portal that rejects the first request of some ids and serves the second. Run `rotate_lattes_downloads`. Those curricula end with their real page and today's date, new ones in `cache/` and refreshes replacing their copy.

### Tests for User Story 1

- [X] T007 [US1] Create `tests/test_lattes_access_check_retry.py`. It reuses `CAPTCHA` and `_page` from `tests/test_lattes_rotation.py`.
  - **Fixtures:**
    - a `Portal` fake that answers by `(id, attempt)`, with a rule such as "reject the first request of these ids";
    - a fixture that sets `HORIZON_LATTES_RETRY_WORKERS` to 1;
    - a `sleep` recorder passed to `rotate_lattes_downloads`.
  - **Cases:**
    - a new curriculum rejected once, then served: it is cached with the run's manifest date, `failed` excludes it, and `new` counts it;
    - a refresh rejected once, then served: the cached copy becomes v2, its date is updated, and `refreshed` counts it;
    - a curriculum rejected twice: a new one is not in `cache/` and has no date; a refresh keeps v1 and its old date. Both stay in `failed`, as today;
    - the pause is passed once to the injected `sleep` (with `HORIZON_PORTAL_EARLY_STOP=0`), or to `stop.wait` (with the stop on). Use a pause of 0 in the other tests, so they take no time;
    - the second pass uses the configured worker count: with `retry=AccessCheckRetrySettings(workers=1, ...)`, at most one request is in flight (a counter in the fake);
    - each id gets at most one second request, even with a duplicated id in the list;
    - a first request that hits a timeout, is retried by `bounded_baixa_cv_lattes`'s rule, and ends with the access check page joins the second pass. Simulate it with a fake that writes `CAPTCHA` on its call;
    - no rejection: no `sleep` call, no second request, and counts identical to the same run with `workers=0`;
    - `workers=0`: the requests, the cache, the manifest and the counts are identical to today's, for a run with rejections.

### Implementation for User Story 1

- [X] T008 [US1] In `rotate_lattes_downloads` (`src/flows/lattes/download.py`), implement the second pass of contracts/access-check-retry.md, rules 1–5 and 8:
  - **Parameters:** `retry: Optional[AccessCheckRetrySettings] = None` (`None` → `access_check_retry_settings()`) and `sleep: Callable[[float], None] = time.sleep`.
  - **First pass:** pass `access_checked` lists to the prefetch and the refresh.
  - **Second-pass ids:** the deduplicated access-checked new ids, then the refresh ids, in plan order.
  - **When it runs:** only with `retry.enabled` and at least one id.
    1. log `Retrying N Lattes curricula that got the access check page, after M min, with W worker(s): [ids]`;
    2. wait: `stop.wait(retry.pause_s)` when a stop exists, else `sleep(retry.pause_s)`;
    3. call `prefetch_lattes_cache(new_ids, max_workers=retry.workers, ...)` and `refresh_lattes_cache(refresh_ids, max_workers=retry.workers, ...)`.
  - **Recovered:**
    - a new id whose file now exists in `cache/`;
    - a refresh id in the returned refreshed list.

    It gets the run's `now` in the manifest and is removed from `failed`. Log `Second try for the access check page: R of N recovered`.
  - Keep the manifest save, the `counts_line` log and `record_portal_stop` after both passes.
- [X] T009 [US1] Run `.venv/bin/pytest tests/test_lattes_access_check_retry.py tests/test_lattes_rotation.py tests/test_lattes_early_stop.py -q`.

**Checkpoint**: US1 works on its own; the MVP.

---

## Phase 4: User Story 2 - The second try respects the portal stop (Priority: P1)

**Goal**: there is no second pass after a stop in the first pass, and the second pass stops at the same limit, with the count carried over.

**Independent Test**: use a fake portal that serves only the access check page. A stop in the first pass gives no second request; a stop during the second pass leaves its remaining ids untried.

### Tests for User Story 2

- [X] T010 [US2] Add to `tests/test_lattes_access_check_retry.py`:
  - **Stop in the first pass:** 5 rejections in a row with the default limit. No `sleep` and no `stop.wait` for the pause, no second request, and the counts and the `portal_stops.json` stop entry equal those of the same run with `workers=0`.
  - **Carry-over:** a first pass with 3 rejections in a row at its end and no stop, then a second pass where every request is rejected. The stop triggers after 2 second-pass requests (3 + 2 = 5), and the rest of the second-pass ids are not tried:
    - a new one is neither new nor failed (`stopped`);
    - a refresh is reused from its copy.
  - **A success resets the count:** the first second-pass request is served and the next 5 are rejected. The stop comes after those 5, not before.
  - **With `HORIZON_PORTAL_EARLY_STOP=0`:** the second pass runs over every rejected id, with no stop, and the pause goes to `sleep`.

### Implementation for User Story 2

- [X] T011 [US2] In `rotate_lattes_downloads`, apply contracts/access-check-retry.md rules 2 and 6:
  - skip the pause and the second pass when `stop is not None and stop.stopped` after the first pass;
  - pass the same `stop` to both second-pass calls, without resetting it;
  - move the ids not tried in the second pass from `failed` to `not_tried`. The prefetch appends to the shared `not_tried`; the refresh returns its own list.
- [X] T012 [US2] Run `.venv/bin/pytest tests/test_lattes_access_check_retry.py tests/test_lattes_early_stop.py -q`.

**Checkpoint**: US1 and US2 together; the second pass never adds requests to a blocked portal.

---

## Phase 5: User Story 3 - The run says how many were retried and recovered (Priority: P2)

**Goal**: the downloads line, the report file and the weekly summary show the second pass, and only when it ran.

**Independent Test**: run the US1 fake portal through `rotate_lattes_downloads`. The downloads line ends with `retried=N recovered=M`, the report has a `retries.lattes` entry, and the weekly summary shows the `↻ lattes` line. A run with no second pass shows none of them.

### Tests for User Story 3

- [X] T013 [P] [US3] Tests for the counts and the downloads line:
  - in `tests/test_raw_rotation.py`:
    - `counts_line` appends ` retried=38 recovered=35` when the counts have `retried`;
    - it is unchanged without the key;
  - in `tests/test_lattes_access_check_retry.py`:
    - with a second pass, `counts` has `retried`, `recovered` and `retried_ids`;
    - without one, it has none of those keys and equals today's dict;
    - `retried = recovered + still failed + not tried`.
- [X] T014 [P] [US3] In `tests/test_portal_stops_report.py`:
  - `record_access_check_retry` writes `retries.lattes` and keeps `stops`;
  - `record_portal_stop` keeps `retries`;
  - `read_access_check_retries` returns `{}` for a missing file, a missing key or bad JSON;
  - `read_portal_stops` still returns only `stops`;
  - neither writer raises on a write error (an unwritable path).
- [X] T015 [P] [US3] In `tests/test_weekly_orchestrator.py`:
  - with a `retries.lattes` entry in the report, the summary log has `↻ lattes: 38 access check pages asked again after 5 min; 35 recovered, 3 still missing`, after any stop line;
  - the Telegram text has the Portuguese line of contracts/settings-and-report.md;
  - the exit code is unchanged;
  - no entry gives no line.

### Implementation for User Story 3

- [X] T016 [US3] In `src/core/logic/raw_rotation.py`, `counts_line` appends ` retried={retried} recovered={recovered}` when `"retried"` is in the counts.
- [X] T017 [US3] In `src/flows/portal_stops.py`:
  - add `record_access_check_retry(source, entry, path=None)` and `read_access_check_retries(path=None)`, as in contracts/settings-and-report.md;
  - make `record_portal_stop` read the whole file and keep the other keys. Add a private `_read_document(path)` that both writers use;
  - update the module docstring to name the `retries` key.
- [X] T018 [US3] In `rotate_lattes_downloads`, when a second pass ran:
  - add `retried`, `recovered` and `retried_ids` to the counts before `counts_line`;
  - call `record_access_check_retry("lattes", entry)` with `source`, `pause_s`, `workers`, `retried`, `recovered`, `not_tried`, `elapsed_s` (from the start of the pause, `time.monotonic`) and `finished_at` (UTC), as in data-model.md.
- [X] T019 [US3] In `src/flows/pipelines/weekly_orchestrator.py`:
  - read `read_access_check_retries()` next to `read_portal_stops()`;
  - add a `_access_check_retry_lines(retries, portuguese=False)` helper;
  - log its lines after the stop lines;
  - pass `retries` to `_notify`, which adds the Portuguese lines after the stop lines.
- [X] T020 [US3] Run `.venv/bin/pytest tests/test_raw_rotation.py tests/test_portal_stops_report.py tests/test_weekly_orchestrator.py tests/test_lattes_access_check_retry.py -q`.

**Checkpoint**: the second pass is visible in the log, the report and the summary.

---

## Phase 6: User Story 4 - The second try is configurable (Priority: P3)

**Goal**: the workers and the pause can be set, or the second pass turned off, locally and in a manual dispatch.

**Independent Test**: `make -n` shows the variables forwarded only when set. The workflow inputs reach the "Run weekly flows" step, and a blank input gives the default.

### Tests for User Story 4

- [X] T021 [P] [US4] In `tests/test_weekly_etl_workflow.py`:
  - the inputs `lattes_retry_workers` and `lattes_retry_pause_min` are strings with default `""`;
  - the "Run weekly flows" step maps them to `HORIZON_LATTES_RETRY_WORKERS` and `HORIZON_LATTES_RETRY_PAUSE_MIN`;
  - `make -n weekly-flows LATTES_RETRY_WORKERS=0 LATTES_RETRY_PAUSE_MIN=1` forwards both, and `make -n weekly-flows` forwards neither;
  - change the spec 024 assertion `len(inputs) <= 10` to `<= 25`, with a comment citing GitHub's 2025-12-04 changelog (research R6).
- [X] T022 [P] [US4] In `tests/test_lattes_access_check_retry.py`: with `retry=None`, `rotate_lattes_downloads` reads the environment (`HORIZON_LATTES_RETRY_WORKERS=2`, `HORIZON_LATTES_RETRY_PAUSE_MIN=0`). An invalid value falls back to the default with a warning, without failing the download.

### Implementation for User Story 4

- [X] T023 [US4] In `Makefile`:
  - add the two optional variables to the `PORTAL_STOP_ENV` block, as in contracts/settings-and-report.md, and update the block's comment;
  - name `LATTES_RETRY_WORKERS` and `LATTES_RETRY_PAUSE_MIN` in the help texts of `weekly-flows` and `ingest-lattes-download`.
- [X] T024 [US4] In `.github/workflows/weekly-etl.yml`:
  - add the two `workflow_dispatch` inputs with the descriptions of the contract;
  - map them in the "Run weekly flows" step, under a `# Spec 025: ...` comment.
- [X] T025 [US4] Run `.venv/bin/pytest tests/test_weekly_etl_workflow.py tests/test_lattes_access_check_retry.py -q`.

**Checkpoint**: every story done.

---

## Phase 7: Polish & Validation

- [X] T026 Run the full suite, `.venv/bin/pytest -q`, and compare it with `$R/e/E_BASE.txt`. The failing tests must be the same 6 as before, and the new ones must pass.
- [X] T027 Local validation (quickstart.md §2; plan Validation 2). First back up `cache/`, `data/raw/lattes/download_manifest.json` and `db/horizon.db`, following the memory rule. Then run `make ingest-lattes-download LATTES_RETRY_PAUSE_MIN=1` on a cache where some curricula are missing, to get new requests. Record:
  - the `Retrying …` and `Second try …` lines;
  - the `retried=`/`recovered=` counts;
  - the `retries.lattes` entry;
  - the time the second pass took.

  If no page was rejected, record that, and keep the tests as the evidence of the rule.
  - **Done 2026-11-03** (`logs/lattes_download_2026-11-03_spec025_t027.log`; backup `data/_backup_2026-11-03_pre_spec025_t027/`):
    - first pass: 38 new and 100 refreshes; 6 access check pages (3 new, 3 refreshes), never 5 in a row;
    - second pass: 1 min pause, 1 worker, `6 of 6 recovered`, 111.9 s from the start of the pause;
    - downloads line `new=38 refreshed=100 reused=297 failed=0 reused_after_failure=0 retried=6 recovered=6`;
    - `retries.lattes` in `data/reports/portal_stops.json`, `stops` empty;
    - all 435 curricula in `cache/` and in the manifest, 435 JSON files, none `Nome-nao-identificado`; `db/horizon.db` unchanged.

- [X] T028 Fork dispatches (quickstart.md §3; plan Validation 3–4), each one only after the maintainer agrees:
  - the defaults: GitHub accepts the 11 inputs, the run is green, and the counts are recorded;
  - `lattes_retry_workers=0`: no `retried=` and no `↻` line.
  - **Run 41729360132 (2026-11-03, defaults, `da21d11`)**: green in 47 min. It was the branch's first run, so it rebuilt from scratch, with no stored pages and only the 16 curricula tracked in `cache/`.
    - GitHub accepted the 11 inputs.
    - Both portals were blocking:
      - CNPq: timeouts; stopped at 803 s, `new=105 failed=7 stopped=235`, 0 from stored copies;
      - Lattes: 8 access check pages in the first 11 requests; stopped at 42 s, `new=5 reused=13 failed=8 stopped=413`.
    - No second pass, as FR-005 requires after a stop in the first pass, so no `↻` line.
    - The run committed its export zip to the branch (`bea2664`).
  - **Run 41739712881 (2026-11-03, defaults, `da21d11`)**: green in 1 h 46 min, all phases `exit 0`.
    - It restored the database (58 MB), `data/raw` (222 MB) and `cache/` (4 MB) from run 41729360132.
    - CNPq was healthy: `new=242 refreshed=27 reused=78 failed=0`, no stop.
    - Lattes, first pass: 417 new curricula asked with 3 workers; 69 came back as the access check page (about 17%), no stop.
    - Lattes, second pass: logged "Retrying 69 …, after 5 min, with 1 worker(s)", then "Second try for the access check page: 55 of 69 recovered", about 19 min including the pause.
    - Downloads line: `new=403 refreshed=5 reused=13 failed=14 reused_after_failure=0 retried=69 recovered=55`.
    - Summary: `↻ lattes: 69 access check pages asked again after 5 min; 55 recovered, 14 still missing`; no `⚠` line.
    - The run committed its export zip to the branch (`481024f`, 50.8 MB, over GitHub's recommended 50 MB, a warning only).
    - `SQLite finalize failed: database is locked` at the end, as in run 41729360132 and the local run from scratch, so it predates spec 025.
  - **Run 41754550238 (2026-11-04, `lattes_retry_workers=0`)**: green in 37 min, all 22 phases `exit 0`.
    - The job had `HORIZON_LATTES_RETRY_WORKERS: 0`; it restored the database (347 MB), `data/raw` (224 MB) and `cache/` (65 MB) from run 41739712881.
    - CNPq: `new=0 refreshed=87 reused=260 failed=0`.
    - Lattes: the 14 still missing, then the refresh share; 24 access check pages, no second pass and no `Retrying …` line.
    - Downloads line as before spec 025: `new=10 refreshed=86 reused=315 failed=24 reused_after_failure=20`, no `retried=`/`recovered=`.
    - Summary: no `↻` and no `⚠` line.
    - The run committed its export zip to the branch (`eeeda3c`).

- [X] T029 Write `docs/reports/<date>-lattes-captcha-retry-validation.md`, in English, in the style of `docs/reports/2026-10-30-portal-early-stop-validation.md`:
  - why, with the evidence of research R3;
  - tests before and after;
  - the local run;
  - the fork runs;
  - residual risk: if the access check depends on the IP rate, fewer are recovered.
- [X] T030 [P] Update `docs/backlog.md`:
  - correct TD-022: the 27 curricula were access check pages saved before spec 023, not real content, and specs 021 and 023 already handle the case;
  - add a line pointing to spec 025 as the same-run retry.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001. T002 and T003 are [P] with each other and with T004; T005 comes after T004, and T006 last.
- **US1 (Phase 3)**: after Phase 2.
- **US2 (Phase 4)**: after T008 (same function).
- **US3 (Phase 5)**: T013–T017 can start after Phase 2. T018 needs T008 and T017, and T019 needs T017.
- **US4 (Phase 6)**:
  - T021, T023 and T024 can start after Phase 2;
  - T022 needs T008.
- **Polish (Phase 7)**: after the stories wanted. T027 and T028 need everything; T030 can be done at any time.

### Within Each User Story

- Tests first; they fail before the implementation.
- `rotate_lattes_downloads` is touched by T008, T011, T018 and T022, so those tasks run in that order.

### Parallel Opportunities

- T002, T003 and T004 (three files).
- T013, T014 and T015 (three test files).
- T021, T023 and T024 (the workflow test, the Makefile, the workflow).

---

## Parallel Example: User Story 3

```bash
Task: "counts_line tests in tests/test_raw_rotation.py (T013)"
Task: "report key tests in tests/test_portal_stops_report.py (T014)"
Task: "summary line tests in tests/test_weekly_orchestrator.py (T015)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 and Phase 2.
2. Phase 3 (US1): the second pass.
3. **Stop and validate**: T009, then a local run (T027) if the portal rejects something.

### Incremental Delivery

1. US1, the recovery.
2. US2, the safety against a blocking portal. It is P1 too, and is needed before any CI run.
3. US3, the visibility.
4. US4, the dispatch levers.
5. Polish: the full suite, local, fork, report.

---

## Notes

- Third-party libraries (scriptLattes) are unchanged. The access check page is never answered or bypassed.
- No Docker change. SigPesq stays sequential, and the first pass keeps its 3 workers.
- Commit only when the maintainer asks, with explicit `git add` paths. Never stage `PLANO_*.md`, `RESUMO_*.md`, `cache/` or `data/exports/`.
- Nothing goes upstream before the maintainer's manager validates.
