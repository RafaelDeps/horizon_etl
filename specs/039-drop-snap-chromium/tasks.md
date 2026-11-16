---

description: "Task list for spec 039: weekly workflow without the snap Chromium"
---

# Tasks: Weekly workflow without the snap Chromium

**Input**: Design documents from `specs/039-drop-snap-chromium/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/weekly-workflow-browser.md, quickstart.md

**Tests**: included. FR-008 asks for workflow tests that guard the change. They are written first and seen failing.

**Organization**: tasks are grouped by user story so each story can be implemented and checked on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story the task belongs to (US1, US2, US3)

---

## Phase 1: Setup

- [X] T001 Record the baseline: run `.venv/bin/python -m pytest -q > logs/pytest_039_before.log 2>&1` and `.venv/bin/flake8 src tests | wc -l`, and record the passed/skipped/failed counts and the flake8 count under this task.
  - Result: 1511 passed, 10 skipped, 0 failed in 7m43 (logs/pytest_039_before.log), the same count as spec 038 T025. flake8 src tests: 579. The run started before any change of this branch; tests are collected at the start, so the new tests of T003-T005 are not in it.
- [X] T002 [P] Record the starting point: list every match of `grep -rnIE "chromium-browser|chromium-driver|chromedriver|CHROME_BINARY|CHROMEDRIVER_PATH|selenium|snap install" --exclude-dir={.git,.venv,data,logs,specs,cache} .` under this task, and mark each one keep (Docker, `selenium` dependency, PDF report script, `.gitignore`/`.dockerignore`, historical reports in docs/reports and docs/backlog) or change (research R3).
  - Result: 17 files match. Change: .github/workflows/weekly-etl.yml (the apt step and the two env vars), src/flows/lattes/download.py (unused parameters), README.md, docs/flows-and-entrypoints.md, docs/operations/automation.md, .env.example. Keep: Dockerfile, docker-compose.yml, .dockerignore (Docker, out of scope); requirements.txt and pyproject.toml (selenium entry, research R5); src/scripts/generate_relatorio_institucional.py (PDF report, not in the weekly); .gitignore (chromedriver pattern, harmless); docs/backlog.md and three docs/reports files (history). The comment 'Playwright/Selenium' in src/flows/pipelines/weekly_orchestrator.py describes past crashes and stays.

---

## Phase 2: Foundational

No shared prerequisite: the stories touch different files. Phase 1 is enough.

---

## Phase 3: User Story 1 - The weekly reaches the ETL even when the Snap Store is down (Priority: P1) 🎯 MVP

**Goal**: the weekly workflow installs only the Playwright Chromium and sets neither browser variable.

**Independent Test**: the workflow tests pass. A weekly run on the fork has no apt/snap browser step and passes every phase.

### Tests for User Story 1

> Write these first and see them fail before T006.

- [X] T003 [US1] In `tests/test_weekly_etl_workflow.py`, add `test_no_step_installs_a_browser_through_apt_or_snap`. It fails if any step's `run` matches `apt-get install` followed by a package starting with `chromium`, or contains `snap install`, or if a step is named "Install Chromium for Lattes (Selenium)" (contract items 2 and 3).
  - Result: test_no_step_installs_a_browser_through_apt_or_snap added; fails on the current workflow (apt-get install chromium-browser).
- [X] T004 [US1] In `tests/test_weekly_etl_workflow.py`, add `test_the_job_sets_no_browser_path`. It fails if the job `env` or any step `env` has `CHROME_BINARY` or `CHROMEDRIVER_PATH` (contract item 4).
  - Result: test_the_job_sets_no_browser_path added; fails on the current workflow (CHROME_BINARY in the job env).
- [X] T005 [US1] In `tests/test_weekly_etl_workflow.py`, add `test_the_playwright_chromium_install_is_kept`. The step "Install Playwright Chromium" must exist with `run == ".venv/bin/python -m playwright install --with-deps chromium"`, after "Create virtual environment and install dependencies" and before "Validate required secrets" (contract item 1). Run the file and record that T003 and T004 fail and T005 passes.
  - Result: test_the_playwright_chromium_install_is_kept added; passes. Run of the three: 2 failed (T003, T004), 1 passed, as expected before T006.

### Implementation for User Story 1

- [X] T006 [US1] In `.github/workflows/weekly-etl.yml`, remove the step "Install Chromium for Lattes (Selenium)" (`sudo apt-get update -qq` / `sudo apt-get install -y chromium-browser chromium-driver`) and the job env entries `CHROME_BINARY: /usr/bin/chromium-browser` and `CHROMEDRIVER_PATH: /usr/bin/chromedriver`. Leave every other step and env entry as it is (contract item 5). Run `tests/test_weekly_etl_workflow.py` and record that it passes.
  - Result: Removed the step 'Install Chromium for Lattes (Selenium)' and the job env entries CHROME_BINARY and CHROMEDRIVER_PATH; added a comment above 'Install Playwright Chromium' (spec 039). Every other step and env entry unchanged. tests/test_weekly_etl_workflow.py: 22 passed.
- [X] T007 [US1] In `src/flows/lattes/download.py`, remove the unused parameters: `validate_script_lattes_runtime(chromedriver_path="./chromedriver", chrome_binary=None)` becomes `validate_script_lattes_runtime()`, and `patch_script_lattes_runtime(chrome_binary=None)` becomes `patch_script_lattes_runtime()`. Keep the bodies, return value and errors. Check with `grep -rn "chrome_binary\|chromedriver_path" src tests` that no caller passes them. Then run `tests/test_download_lattes_flow.py` and record that it passes.
  - Result: validate_script_lattes_runtime() and patch_script_lattes_runtime() lost their unused parameters; bodies unchanged. grep finds no chrome_binary or chromedriver_path left in src/ or tests/. tests/test_download_lattes_flow.py: 9 passed (the 'Logging error' line after pytest is loguru writing to a closed stream at exit, also present before).

**Checkpoint**: the workflow can no longer stop on the Snap Store, and the Lattes runtime check is unchanged.

---

## Phase 4: User Story 2 - The documentation describes the browser the download really uses (Priority: P2)

**Goal**: no doc or example asks for Selenium, `chromedriver`, `CHROME_BINARY` or `CHROMEDRIVER_PATH` for the Lattes download.

**Independent Test**: read the four files. The grep of quickstart section 1, run on them, finds no instruction for the Lattes download.

- [X] T008 [P] [US2] `README.md`, section "Fluxo Lattes" (about lines 115-138):
  - replace the Selenium/`chromedriver` version-check paragraph and the "Chromium via Snap" `CHROME_BINARY` example. The new text says that scriptLattes opens the browser through Playwright, that the flow checks the Playwright Chromium before it starts, and that it is installed with `.venv/bin/python -m playwright install chromium` (`--with-deps` on a fresh Linux machine);
  - drop `CHROME_BINARY=/caminho/para/chrome` from the two prefetch examples.
  - Keep the text in Portuguese, as the rest of the README.
  - Result: README.md 'Fluxo Lattes': the Selenium/chromedriver paragraph and the Snap CHROME_BINARY example replaced by the Playwright Chromium text with both install commands and a line saying Selenium, chromedriver and CHROME_BINARY are not needed (spec 039); CHROME_BINARY dropped from the two prefetch examples. In Portuguese.
- [X] T009 [P] [US2] `docs/flows-and-entrypoints.md`, section "Lattes" (about lines 58-70): the same change as T008, in the doc's language.
  - Result: docs/flows-and-entrypoints.md 'Lattes': same change, with the install command and a note that the weekly installs only the Playwright Chromium.
- [X] T010 [P] [US2] `docs/operations/automation.md` (about lines 111-114):
  - replace the bullet "O download Lattes usa `scriptLattes` via Selenium…" with one saying that the Lattes download and the SigPesq agent both use the Playwright Chromium installed by the workflow;
  - say that the workflow installs no other browser (spec 039).
  - Result: docs/operations/automation.md: the Selenium bullet replaced; it now says scriptLattes also opens the Playwright Chromium and that the workflow installs no other browser (spec 039, why the apt/snap Chromium was removed).
- [X] T011 [P] [US2] `.env.example` (about lines 53-56): remove `CHROME_BINARY=` and `CHROMEDRIVER_PATH=` from the local settings. Keep one comment line saying that the Docker image sets both variables for its own Chromium (Docker unchanged, research R4).
  - Result: .env.example: CHROME_BINARY= and CHROMEDRIVER_PATH= removed; a comment says Lattes and SigPesq use the Playwright Chromium, gives the install command, and notes the Docker image sets both variables. The remaining mentions in the four files only say these are not needed (SC-005).

**Checkpoint**: docs match the code.

---

## Phase 5: User Story 3 - A local weekly still runs as before (Priority: P3)

**Goal**: show that nothing the ETL needs was removed.

**Independent Test**: a local weekly passes every phase, and the Lattes download behaves as in the previous local run.

- [X] T012 [US3] Run `tests/test_download_lattes_flow.py` and `tests/test_weekly_etl_workflow.py` together and record the result. Run `.venv/bin/python -c "from src.flows.lattes.download import validate_script_lattes_runtime as v; print(v())"` and record that it prints `playwright-chromium`.
  - Result: tests/test_download_lattes_flow.py + tests/test_weekly_etl_workflow.py: 31 passed. validate_script_lattes_runtime() on this machine prints 'playwright-chromium'.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T013 Add a line to `docs/backlog.md` closing the snap Chromium failure, citing the five failed fork runs of 2026-11-16. If the `selenium` dependency is still listed, add a TD to remove it later (research R5).
  - Result: docs/backlog.md: TD-055 (weekly stopped on a Snap Store outage; five failed fork runs of 2026-11-16) closed by branch 039, and TD-056 (selenium dependency no longer used) open.
- [X] T014 Run black and isort on the touched Python files, and flake8 on them. Record the result and the repository flake8 count (the T001 count or lower).
  - Result: black and isort left src/flows/lattes/download.py and tests/test_weekly_etl_workflow.py unchanged. flake8 on the two files: 1 finding, src/flows/lattes/download.py:8 F401 'platform.system' imported but unused, already there before this branch (1 finding with the branch's changes stashed). Repository count checked in T015.
- [X] T015 Run the full suite: `.venv/bin/python -m pytest -q > logs/pytest_039_full.log 2>&1`. Record the result: every test of T001 still passes, plus the new ones, 0 failed.
  - Result: 1514 passed, 10 skipped, 0 failed in 6m43 (logs/pytest_039_full.log): the 1511 of T001 plus the 3 new workflow tests. flake8 src tests: 579, the same as T001. git status shows no file under data/ changed by the tests.
- [X] T016 Run quickstart.md section 1, the greps on the workflow, and record the output.
  - Result: quickstart section 1: the grep for chromium-browser, chromium-driver, snap install, CHROME_BINARY and CHROMEDRIVER_PATH in .github/workflows/weekly-etl.yml prints nothing; the grep for the Playwright install prints one line (line 111).
- [X] T017 Local weekly run. Ask the maintainer first, and back up `db/horizon.db`, `data/lattes_json` and `data/raw` before. Follow quickstart.md section 2 and record:
  - the phases and the time;
  - the Lattes line `downloads lattes: new=… refreshed=… reused=…`;
  - that a `.env` with or without `CHROME_BINARY` makes no difference.
  - Result: (2026-11-16, passed) backup in data/_backup_2026-11-16_pre039/ (horizon.db, lattes_json, raw, both archives, RESTORE.txt), database hash checked. Weekly 15:11-15:52 (41 min) with make weekly-flows, exit 0, 24 phases with exit 0 (logs/weekly_039_run1.log). Lattes: 'downloads lattes: new=13 refreshed=104 reused=316 failed=2 reused_after_failure=2 retried=13 recovered=11': the curricula were downloaded through the Playwright Chromium; the 2 failed downloads kept their stored copies. The .env was not opened (maintainer's rule); no code reads CHROME_BINARY or CHROMEDRIVER_PATH. Database after the run copied to data/_backup_2026-11-16_pre039/horizon_after_run1.db.
- [X] T018 Second local weekly run (ask the maintainer first). Record the same items as T017.
  - Result: (2026-11-16, passed) a first try at 15:52 was stopped by the maintainer at 16:14 during consolidate_duplicates; its database was kept as data/_backup_2026-11-16_pre039/horizon_aborted_run2.db and db/horizon.db was restored from horizon_after_run1.db (hash checked). Weekly 18:10-18:51 (41 min), exit 0, 24 phases with exit 0 (logs/weekly_039_run2.log). Lattes: 'downloads lattes: new=0 refreshed=108 reused=326 failed=1 reused_after_failure=1 retried=7 recovered=6', through the Playwright Chromium; the failed download kept its stored copy. linkedin links: 313 lines, 243 stored, unchanged. Parquet archive built, 126 members, 50,652,951 bytes.
- [X] T019 GitHub Actions, only if the maintainer asks; only on the RafaelDeps fork, never upstream; push without force. Follow quickstart.md section 3 and record:
  - that no step "Install Chromium for Lattes (Selenium)" ran;
  - that "Install Playwright Chromium" passed and every phase passed;
  - the Lattes download line, compared with run 43663739197.
  - Result: (2026-11-16, passed) commit 86ecbf5 pushed to the RafaelDeps fork, branch 039-drop-snap-chromium, without force, nothing upstream. Run 43926472687 (18:13-20:11 UTC, success): no step 'Install Chromium for Lattes (Selenium)'; 'Install Playwright Chromium' passed; 24 phases with exit 0. First run of the branch: 'restore: rebuilt — no successful run', so every curriculum was downloaded: 'downloads lattes: new=431 refreshed=0 reused=0 failed=4' through the Playwright Chromium (run 43663739197 restored its state and reused copies, so the counts differ by design). linkedin links: 313 lines, 243 stored, 70 not found. Parquet archive built, 125 members, 49,917,286 bytes. Both archives publishable; bot commit bdf8f86 'chore(exports): update the export archives from weekly run 2026-11-16' (243 persons with linkedin_url; 18,213 persons, fewer than locally because the 4 failed curricula had no stored copy on a first run, the behaviour noted in the 2026-11-16 data audit).

  Or record that the maintainer chose not to run it.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: first.
- **US1 (Phase 3)**: after Setup. T003-T005 come before T006; T007 is independent of T006.
- **US2 (Phase 4)**: after Setup; independent of US1 (docs only).
- **US3 (Phase 5)**: after US1 (it checks the code change of T007).
- **Polish (Phase 6)**: after all stories. T014 before T015; T015 before T017; T017 before T018; T018 before T019.

### Within Each User Story

- Tests are written first and seen failing, then the code.

### Parallel Opportunities

- T002 runs alongside T001.
- T008, T009, T010 and T011 run in parallel: four different files.
- US2 can run while US1 is being done.

---

## Parallel Example: User Story 2

```bash
Task: "README.md section Fluxo Lattes: Playwright Chromium (T008)"
Task: "docs/flows-and-entrypoints.md section Lattes: Playwright Chromium (T009)"
Task: "docs/operations/automation.md browser notes (T010)"
Task: ".env.example without the two variables (T011)"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1.
2. US1: tests T003-T005, then T006 and T007.
3. **Stop and validate**: the workflow tests and the Lattes runtime tests pass. This alone unblocks the weekly.

### Incremental Delivery

1. US1: the weekly no longer depends on the Snap Store.
2. US2: the docs match.
3. US3 and Polish: local weeklies, then the fork run when the maintainer asks.

---

## Notes

- Docker files, the `selenium` entry in `requirements.txt`/`pyproject.toml`, and `src/scripts/generate_relatorio_institucional.py` stay unchanged.
- Never stage `PLANO_*`, `RESUMO_*`, `data/`, `logs/` or the export zips.
