---

description: "Task list for the paced retry of the project PDFs refused by the rate limit"
---

# Tasks: Paced Retry for Project PDFs Refused by the Rate Limit

**Input**: Design documents from `specs/031-mistral-rate-limit-retry/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/extraction-retry.md, quickstart.md

**Tests**: the spec requires two things:

- the stage behaves as today with the retry off (FR-010, SC-005);
- it never holds the run past the wait budget (FR-005, SC-003).

Each story therefore starts with its tests. They use a fake extractor that
raises a fake HTTP 429 error per document and per try, an injected `sleep`
that only records, and an injected monotonic `clock`. No test calls Mistral
or waits for real.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md

`$R` = this session's scratchpad.

---

## Phase 1: Setup

- [X] T001 Record the baseline in `$R/e031/E_BASE.txt`:
  - run `PYTHONPATH=. .venv/bin/python -m pytest -q` on `031-mistral-rate-limit-retry`; the expected result is 1027 passed and 0 failed, since TD-031 is in the branch;
  - copy the numbers of research.md (Evidence):
    - 321 and 322 PDFs, 296 restored, 25 errors with HTTP 429 in each run;
    - the 25 PJ codes;
    - stage time 39 s and 45 s;
    - `field merge sigpesq_project_files: fields=132` in CI against 139 locally.

---

## Phase 2: Foundational

**Purpose**: the pure pacing logic, and the test seams of the adapter that every story uses.

- [X] T002 [P] Create `src/core/logic/extraction_pacing.py` as in contracts/extraction-retry.md (C1–C5):
  - **Constants**:
    - `RETRIES_ENV`, `PAUSE_ENV`, `FIRST_WAIT_ENV` and `BUDGET_ENV`;
    - the defaults 3, 2.0, 30.0 and 20 (minutes);
    - `MAX_WAIT_S = 300.0`;
    - a comment citing research R3 (26 calls within about 40 s, so a per-period limit).
  - **Settings**: a frozen dataclass `ExtractionPacingSettings(retries, pause_s, first_wait_s, wait_budget_s)`.
    - `extraction_pacing_settings(env=None)` reads the four variables. A blank value means the default.
    - An invalid value (not a number, negative, not finite, or not an integer for retries) logs `Invalid <NAME>=<value>; using <default>` and uses the default.
    - The budget is converted from minutes to seconds. The function never raises.
    - Follow the `_read` helper of `src/core/logic/access_check_retry.py`.
  - **`is_rate_limit(exc)`**: walks `exc` and its `__cause__`/`__context__` chain, at most 5 deep.
    - It is true when one of them has `status_code == 429` or `raw_response.status_code == 429`.
    - When no status attribute exists anywhere, it is true only if `"Status 429" in str(exc)`.
  - **`retry_after_s(exc, now=None)`**: the `Retry-After` header from `exc.headers` or `exc.raw_response.headers`, given as seconds or as an HTTP date (`email.utils.parsedate_to_datetime`). It returns `None` when the header is absent, unparsable or negative.
  - **`backoff_s(retry, settings, retry_after)`**: `min(MAX_WAIT_S, max(first_wait_s * 2 ** (retry - 1), retry_after or 0))`.
  - **`WaitBudget(total_s)`**: `spent_s`, `allows(wait_s)` and `spend(wait_s)`.
  - **Docstring**: pure logic, no file, network or clock access, and no import of `mistralai`.
- [X] T003 [P] Create `tests/test_extraction_pacing.py` for T002:
  - **Settings**:
    - the defaults; blank values;
    - `0` retries means off, `0` pause means no pause, a `0` budget means stop at the first 429;
    - decimal values (`EXTRACT_PAUSE_S=0.5`, a budget of `0.5` min giving 30 s);
    - invalid values (`abc`, `-1`, `1.5` retries, `inf`), each with a warning and the default;
    - a given mapping is read instead of `os.environ`.
  - **`is_rate_limit`**:
    - a fake error with `status_code=429`, and one with only `raw_response.status_code=429`;
    - a `RuntimeError` raised `from` a 429 error;
    - a `status_code=500` error is false;
    - a plain `ValueError` is false;
    - an exception with no status whose text has `Status 429` is true.
  - **`retry_after_s`**: `"12"` gives 12.0, an HTTP date 30 s after `now` gives 30.0, and `"soon"`, `"-5"` or no header give `None`.
  - **`backoff_s`**:
    - retries 1, 2 and 3 give 30, 60 and 120 s;
    - a `retry_after` of 90 on retry 1 gives 90;
    - retry 10 is capped at 300.
  - **`WaitBudget`**: `allows` at the exact edge, and `spend` accumulating.
- [X] T004 In `src/adapters/sources/sigpesq/project_files.py`, add the keyword-only parameters `settings: Optional[ExtractionPacingSettings] = None`, `sleep: Callable[[float], None] = time.sleep` and `clock: Callable[[], float] = time.monotonic` to `extract_json`.
  - When `settings` is `None`, read it with `extraction_pacing_settings()`, after the restore pass and only if something is left to extract, so a run with nothing pending reads and logs nothing new.
  - The behaviour does not change yet.
- [X] T005 [P] Create `tests/test_project_files_rate_limit.py` with the shared helpers:
  - **`RateLimitError(Exception)`**: carries `status_code=429` and `headers={}`, with a message in the SDK's format (`API error occurred: Status 429. Body: {...}`).
  - **`ScriptedExtractor`**: built from a mapping `stem -> list of outcomes` (`"ok"`, `"429"`, `"429:<retry_after>"` or an exception instance). It records each call as `(stem, try)` and returns a minimal valid `Projeto`, as `FakeExtractor` does in `tests/test_project_files_zip_reuse.py`.
  - **A fixture**: makes `pdf_dir` hold N empty `PJ_<n>.pdf` files with no local JSON and no archive, and patches `_build_extractor` to return the scripted extractor.
  - **`FakeClock` and `RecordingSleep`**: `sleep` advances the clock, and each call is recorded.

**Checkpoint**: the pure logic is tested; the adapter accepts the seams and still behaves as before (`tests/test_project_files_zip_reuse.py` passes unchanged).

---

## Phase 3: User Story 1 - A document refused by the rate limit is tried again in the same run (Priority: P1) 🎯 MVP

**Goal**: a 429 is retried after growing waits, calls are paced, and a recovered document is written like any other.

**Independent Test**: a scripted extractor refuses some documents once or twice and then accepts them. They end with their JSON; the recorded waits are 30 s and then 60 s; consecutive calls are at least `pause_s` apart.

### Tests for User Story 1

- [X] T006 [US1] In `tests/test_project_files_rate_limit.py`, add these tests. They fail until T007.
  - **One refusal**: `PJ_1: ["429", "ok"]`. One JSON is written, the sleeps include 30 s, `extracted=1`, `recovered=1`, `retried=1`, `retries=1`.
  - **Two refusals**: `PJ_1: ["429", "429", "ok"]`. Waits of 30 and 60 s.
  - **`Retry-After`**: `PJ_1: ["429:90", "ok"]`. A wait of 90 s.
  - **Tries exhausted**: `PJ_1: ["429"] * 4` with 3 retries. No JSON, `failed_rate_limit=1`, `errors=1`, and exactly 4 calls.
  - **Pause**: three documents with `"ok"` and `pause_s=2`, where each call advances the fake clock 0.5 s. The sleeps between calls are 1.5 s, there is no sleep before the first call, and no pause sleep comes right after a backoff.
  - **Same JSON**: a recovered document's JSON is byte-identical to the one written without a refusal, with the same `model_dump(by_alias=True)` and indent.

### Implementation for User Story 1

- [X] T007 [US1] In `extract_json` of `src/adapters/sources/sigpesq/project_files.py`, replace the single call with the paced loop of contracts A2, A3 and A6:
  - **Pause**: keep `last_end`. Before every call except the first, `sleep(max(0, pause_s - (clock() - last_end)))` when positive.
  - **Retry**: on an exception with `is_rate_limit`, while the tries allow it:
    - compute `backoff_s(n, settings, retry_after_s(exc))`;
    - log WARNING `[i/n] PJ_X rate limited (try t/1+retries); waiting w s`;
    - sleep, and count the retry.
  - **Success**: write the JSON exactly as today. When the document needed a retry, log `[i/n] PJ_X -> PJ_X.json (after t tries)`.
  - Keep the `_meta.campos_ausentes` suffix.
  - Add the counters `recovered`, `retried`, `retries` and `failed_rate_limit`, with `errors` kept as their sum plus the other failures.

**Checkpoint**: US1 is testable on its own; the 25 documents of 2026-11-09 would be retried.

---

## Phase 4: User Story 2 - Other failures and a long outage never hold the run (Priority: P1)

**Goal**: only a 429 is retried, and the wait budget ends the stage cleanly.

**Independent Test**: an extractor that always answers 429 ends the stage once the budget is used up, with the rest counted as `left`. An extractor that raises `ValueError` is not retried.

### Tests for User Story 2

- [X] T008 [US2] In `tests/test_project_files_rate_limit.py`, add these tests. They fail until T009.
  - **Other error**: `PJ_1: [ValueError("bad pdf")]`. One call, `failed_other=1`, no backoff sleep, and the next document is still extracted.
  - **Other HTTP error**: a fake error with `status_code=500` is not retried.
  - **Budget**: five documents that always answer 429, with a budget of 100 s (`first_wait_s=30`, so 30 + 60 = 90 s spent and 120 s not allowed).
    - `PJ_1` ends as `failed_rate_limit` after 3 calls;
    - `PJ_2`–`PJ_5` count as `left=4` and are never called;
    - the WARNING `Wait budget of … used up; 4 PDF(s) left for the next run` is logged;
    - `waited_s=90`.
  - **Budget 0**: the first 429 stops the stage. That document counts as `failed_rate_limit`, the others as `left`.
  - **Never raises**: a mix of every outcome returns the counts with no exception.
  - **Invariants**: `extracted + failed_rate_limit + failed_other + left == to_extract`.

### Implementation for User Story 2

- [X] T009 [US2] In `extract_json` of `src/adapters/sources/sigpesq/project_files.py`, add contracts A4, A5 and A7:
  - **Other failures**: logged at WARNING as today, counted as `failed_other`, no retry.
  - **Budget**: a `WaitBudget(settings.wait_budget_s)` checked before every backoff. When it does not allow the wait:
    - the document counts as `failed_rate_limit`;
    - the rest of the queue counts as `left`;
    - the WARNING is logged and the loop ends.
  - **Waiting**: `waited_s` adds up the backoffs.
  - **Never raises**: no extraction failure escapes the method.

**Checkpoint**: US1 and US2 together satisfy FR-001 to FR-007.

---

## Phase 5: User Story 3 - The log tells reused, extracted and failed documents apart (Priority: P2)

**Goal**: honest opening lines, complete end counts, and one line in the weekly summary and Telegram.

**Independent Test**: a run with present, restored, extracted, recovered and failed documents logs each count. The report holds the `extractions` entry, and the weekly summary shows the `✎` line.

### Tests for User Story 3

- [X] T010 [P] [US3] In `tests/test_project_files_rate_limit.py`, test the counts and lines of R6. They fail until T012.
  - Use 2 present, 2 restored from a temporary archive (as in `tests/test_project_files_zip_reuse.py`), and 3 pending with outcomes `ok`, `429→ok` and `ValueError`.
  - The opening line is `7 PDFs | 2 already present | 5 pending`.
  - The restore line is `2 restored from the archive | 3 to extract`.
  - The returned dict has every key of data-model.md, with `skipped == present` and the invariants.
  - With nothing pending, there are no restore or extract lines, `_build_extractor` is never called, and `sleep` is never called (SC-004).
- [X] T011 [P] [US3] In `tests/test_portal_stops_report.py` and `tests/test_weekly_orchestrator.py`, add these tests. They fail until T013 and T014.
  - **Report**: `record_extraction` adds `extractions.sigpesq_project_files` and keeps `stops` and `retries`. `read_extractions` returns `{}` when the file is missing or broken. `record_extraction` never raises on an unwritable path.
  - **Summary lines**: `_extraction_lines` gives the English and Portuguese lines of the contract for an entry with calls. It gives nothing for `to_extract == 0`. A broken entry is logged and skipped.
  - **Weekly summary**: the line appears in the log summary and in the Telegram text built by `_notify`.

### Implementation for User Story 3

- [X] T012 [US3] In `extract_json` of `src/adapters/sources/sigpesq/project_files.py`:
  - replace the opening line with `<pdfs> PDFs | <present> already present | <pending> pending`;
  - after the restore pass, log `<reused> restored from the archive | <to_extract> to extract` (only when something was pending);
  - return every count of data-model.md (`present`, with `skipped` as its alias, `to_extract` and `left`);
  - keep `Extraction finished: {...}` as the last line.
- [X] T013 [P] [US3] In `src/flows/portal_stops.py`:
  - add `record_extraction(source, entry, path=None)`, which never raises, and `read_extractions(path=None)`, under the key `extractions`, using `_write_entry` and `_section`;
  - update the module docstring (spec 031 adds `extractions`).

  In `src/flows/sigpesq/project_files.py`, after the extraction stage has run (not when `skip_extract`), call `record_extraction("sigpesq_project_files", entry)`. The entry holds the counts and `settings` (from `dataclasses.asdict`); the adapter returns the settings it used.
- [X] T014 [US3] In `src/flows/pipelines/weekly_orchestrator.py`, add `_extraction_lines(extractions, portuguese=False)`, following `_access_check_retry_lines`:
  - the English and Portuguese texts of contracts/extraction-retry.md;
  - only entries with `to_extract > 0`;
  - minutes from `waited_s`.

  Then:
  - read `read_extractions()` in `run_weekly` after the retry lines, and log each line at INFO;
  - pass the result to `_notify`, which adds the Portuguese lines next to the stop lines.

**Checkpoint**: FR-008 and SC-006 are met; the maintainer reads the extraction outcome in the weekly summary.

---

## Phase 6: User Story 4 - The pacing and the retry are configurable (Priority: P3)

**Goal**: the four settings reach the stage locally (Makefile) and in a manual dispatch (workflow).

**Independent Test**: `make -n weekly-flows EXTRACT_RETRIES=0` shows `HORIZON_EXTRACT_RETRIES="0"`, and the workflow maps each input to its env var.

### Tests for User Story 4

- [X] T015 [P] [US4] In `tests/test_weekly_etl_workflow.py`, assert that:
  - the 4 inputs `extract_retries`, `extract_pause_s`, `extract_first_wait_s` and `extract_wait_budget_min` exist with a blank default;
  - each is mapped to its `HORIZON_EXTRACT_*` env in the `make weekly-flows` step;
  - the inputs number at most 25.
- [X] T016 [P] [US4] In `tests/test_project_files_rate_limit.py`, test FR-010 and A8:
  - with `retries=0` and `pause_s=0`, a scripted run with `ok`, `429` and `ValueError` documents makes exactly one call per document and no sleep;
  - it writes the same files as the code before this feature;
  - `errors` is 2.

### Implementation for User Story 4

- [X] T017 [US4] In `Makefile`:
  - add `EXTRACT_ENV`, which passes `HORIZON_EXTRACT_RETRIES`, `HORIZON_EXTRACT_PAUSE_S`, `HORIZON_EXTRACT_FIRST_WAIT_S` and `HORIZON_EXTRACT_WAIT_BUDGET_MIN` only when `EXTRACT_RETRIES`, `EXTRACT_PAUSE_S`, `EXTRACT_FIRST_WAIT_S` or `EXTRACT_WAIT_BUDGET_MIN` is set, with a comment like the spec 024/025 one;
  - use it in `weekly-flows` and `extract-project-files`;
  - add the variables to both help texts.
- [X] T018 [US4] In `.github/workflows/weekly-etl.yml`:
  - add the 4 string inputs with descriptions (the defaults 3, 2 s, 30 s and 20 min; 0 turns the retry off or stops at the first 429) and `default: ""`;
  - map them in the `make weekly-flows` step env, next to the spec 025 lines, with a `# Spec 031` comment.

**Checkpoint**: every story is done; FR-009 is met.

---

## Phase 7: Polish & Validation

- [X] T019 [P] In `docs/flows-and-entrypoints.md`, under the `extract_project_files` phase, describe:
  - the paced retry;
  - the four settings and their defaults;
  - the wait budget and the `left` documents;
  - the new opening lines;
  - the `✎` summary line.
- [X] T020 Run `make ci-check`.
  - Black, isort and flake8 must pass on the changed files. The format check of the files untouched since TD-031 already fails; record that, but do not fix them here.
  - The full suite must pass, with the new tests counted in `$R/e031/E_TESTS.txt`.
  Done on 2026-11-09:
  - full suite: 1079 passed, 10 skipped, 0 failed (1027 before, 52 new tests);
  - black, isort and flake8 pass on the 10 changed Python files;
  - `make lint` still fails only on old files untouched here (`tests/verify_*.py` and others), as before this branch.
- [X] T021 Run quickstart §2 (no calls): `app.py extract_project_files` with every local JSON present. Expect `322 already present | 0 pending`, no extractor and no wait (SC-004). Record the output in `$R/e031/E_LOCAL.txt`.
  Done on 2026-11-09 by calling the extraction stage alone (`SigPesqProjectFilesAdapter().extract_json()`), since the flow would also log in to SigPesq to download the PDFs:
  - the result was `322 PDFs | 322 already present | 0 pending`;
  - the extractor was never built;
  - there was no sleep, and the settings were not read.
- [ ] T022 **Ask the maintainer first: it costs Mistral calls.** Run quickstart §3 with 3 pending documents and the local archive moved aside.
  - Restore the moved JSONs and the zip afterwards, and check that the files are back.
  - Record the counts and the log lines.
- [ ] T023 **Ask the maintainer first.** Commit (only code and docs, with explicit paths) and push `031-mistral-rate-limit-retry` to the fork only. Then dispatch `weekly-etl.yml` on it (quickstart §4) and check:
  - every phase exits 0;
  - at least 23 of the 25 documents of 2026-11-09 are extracted (SC-001);
  - the `✎` summary line appears;
  - the stage stays within the budget (SC-003);
  - `field merge sigpesq_project_files: fields=` is close to 139 (SC-002).
- [ ] T024 **Ask the maintainer first.** Run a second dispatch: the recovered documents are now restored from the committed archive, with no calls for them. Mark the tasks done and update `docs/backlog.md` if a follow-up appears (for example keeping the JSONs in the state bundle).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)**: no dependencies.
- **Foundational (T002–T005)**: T002 and T003 in parallel. T004 depends on T002. T005 can be written alongside T004. These tasks block every story.
- **US1 (T006–T007)**: after Phase 2.
- **US2 (T008–T009)**: after US1, because both change the same loop in `project_files.py`.
- **US3 (T010–T014)**:
  - T012 changes `project_files.py`, so it comes after US2;
  - T013 and T014 touch other files and can start after Phase 2.
- **US4 (T015–T018)**:
  - T017 and T018 touch only the Makefile and the workflow, so they can start any time;
  - T016 needs US1 and US2.
- **Polish (T019–T024)**: after every story. T022 to T024 wait for the maintainer.

### User Story Dependencies

- US1 is the MVP; US2 completes the safety of the same loop.
- US3 and US4 do not change the retry behaviour; they add visibility and configuration.

### Parallel Opportunities

- T002 and T003, and later T004 and T005.
- T011, T013 and T014 (report and summary) alongside US1 and US2, since they touch other files.
- T015, T017 and T018 (wiring) at any time.
- T019 (docs) alongside T020.

---

## Parallel Example: after Phase 2

```bash
# Loop work (sequential, one file):
Task: "T006/T007 retry and pause in src/adapters/sources/sigpesq/project_files.py"
# Alongside it, other files:
Task: "T013 record_extraction/read_extractions in src/flows/portal_stops.py"
Task: "T014 _extraction_lines in src/flows/pipelines/weekly_orchestrator.py"
Task: "T017 EXTRACT_ENV in Makefile"
Task: "T018 extract_* inputs in .github/workflows/weekly-etl.yml"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. T001–T005: baseline, pure logic, seams.
2. T006–T007: retry and pause.
3. **Stop and validate**: the US1 tests pass and `tests/test_project_files_zip_reuse.py` is unchanged and passes.

### Incremental Delivery

1. Add US2 (budget, other failures): the stage is now safe to ship.
2. Add US3 (counts, report, summary).
3. Add US4 (Makefile, workflow).
4. Polish: docs, `make ci-check`, then local and fork validation, with the maintainer's ok for every step that costs calls or touches the fork.

---

## Notes

- Never change agent_sigpesq or mistralai; the retry lives around `extract_project`.
- Never print `.env` values, and never read `.env` beyond what the app does.
- Stage only code and docs, with explicit paths. Never stage `PLANO_*.md`, `RESUMO_*.md`, `data/`, `cache/` or `logs/`.
- Commit only when the maintainer asks; nothing goes upstream until the boss validates.
- No Docker work.
