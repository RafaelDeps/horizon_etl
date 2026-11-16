---

description: "Task list for spec 040: Slack notice of the GitHub Actions weekly"
---

# Tasks: Slack notice of the GitHub Actions weekly

**Input**: Design documents from `specs/040-slack-weekly-notice/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/slack-messages.md, contracts/weekly-workflow-notices.md, quickstart.md

**Tests**: included. FR-012 asks for workflow tests, and the message rules and the secret handling need unit tests. Tests are written first and seen failing.

**Organization**: tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1, US2, US3

---

## Phase 1: Setup

- [X] T001 Record the baseline: run `.venv/bin/python -m pytest -q > logs/pytest_040_before.log 2>&1` and `.venv/bin/flake8 src tests | wc -l`. Record passed/skipped/failed and the flake8 count under this task.
  - Result: 1514 passed, 10 skipped, 0 failed in 7m56 (logs/pytest_040_before.log), the count of spec 039: the tests were collected before this branch's first test change. flake8 src tests: 579.

---

## Phase 2: Foundational (blocking: the script skeleton and the phase summary)

- [X] T002 [P] In `tests/test_weekly_orchestrator.py`, add `test_run_weekly_writes_the_phase_summary`. Fake `_run_phase` results (one critical passed, one non-critical failed, one skipped), monkeypatch `PHASE_SUMMARY_PATH` (defined in T003) to a file under `tmp_path`, call `run_weekly`, and check `weekly_phase_summary.json`:
  - `phases` (name, ok, critical, rc, with `"skipped"` for a skipped phase), `critical_failed` and `failed`, as in data-model.md;
  - the return code is unchanged.
  - Result: tests/test_weekly_orchestrator.py: autouse fixture _phase_summary_in_tmp (keeps every run_weekly test from writing data/reports/), plus test_run_weekly_writes_the_phase_summary, test_a_skipped_phase_is_written_as_skipped and test_a_summary_write_error_does_not_change_the_result. Before T003 the two writing tests failed.

  Add `test_a_summary_write_error_does_not_change_the_result`: an unwritable path logs a warning and keeps the return code. See both fail.
- [X] T003 In `src/flows/pipelines/weekly_orchestrator.py`:
  - add a module constant `PHASE_SUMMARY_PATH = "data/reports/weekly_phase_summary.json"`;
  - add `_write_phase_summary(results, path)`, which writes the JSON of data-model.md (`ensure_ascii=False`, `indent=2`) and catches `OSError` into a `logger.warning`;
  - call it in `run_weekly` right after the "=== Weekly pipeline summary ===" block, before `_notify`;
  - do not change any phase, the return codes or the Telegram summary.
  - Result: weekly_orchestrator.py: PHASE_SUMMARY_PATH and _write_phase_summary (OSError -> logger.warning), called right after the log summary and before the Telegram _notify; phases, return codes and Telegram unchanged. tests/test_weekly_orchestrator.py: 41 passed; no data/reports/weekly_phase_summary.json written by the tests.

  T002 passes.
- [X] T004 Create `src/scripts/notify_slack.py` with the module docstring (spec 040, what it sends, that it never prints the webhook and always exits 0) and the entry point `main(argv=None) -> int`:
  - `python3 -m src.scripts.notify_slack start|end [--dry-run]`;
  - it uses the standard library only, and the imports must work under the runner's `python3` without the venv;
  - `main` returns 0 on every path, and `if __name__ == "__main__": sys.exit(main())`.
  - Result: src/scripts/notify_slack.py created with the docstring of the task, main(argv) -> int, 'start|end [--dry-run]', standard library only; main returns 0 on every path.

---

## Phase 3: User Story 1 - Know that the weekly started and how it ended (Priority: P1) 🎯 MVP

**Goal**: start and end messages with branch, trigger, link, result, time and archive commit, for runs that pass.

**Independent Test**: unit tests of the message texts. A fork run that passes sends two messages.

### Tests for User Story 1

- [X] T005 [P] [US1] In a new `tests/test_notify_slack.py`, add:
  - `test_start_message` (schedule → "agendada", workflow_dispatch → "manual", any other event → its name; branch; link `{server}/{repo}/actions/runs/{id}`);
  - `test_end_message_passed_with_commit` (`ARCHIVE_COMMIT=<40-char sha>` → short hash 7 chars with link `{server}/{repo}/commit/{sha}`);
  - `test_end_message_passed_archives_unchanged` (`unchanged` → "Zips: não mudaram");
  - `test_end_message_passed_with_warnings` (`JOB_STATUS=success` and a phase summary with `failed: [x, y]` → "⚠️ … passou com avisos" and "Fases com falha: x, y");
  - `test_duration_format` (59 min → "59min", 112 min → "1h 52min", no `WEEKLY_STARTED_AT` → no "tempo:").
  - Result: tests/test_notify_slack.py: start message (3 triggers), passed with commit, archives unchanged, passed with warnings, duration format (59min, 1h 52min, 1h 00min), no start time, time shown, start writes WEEKLY_STARTED_AT, dry run, JSON sending, summary reading. Collection failed before the script existed.

  Exact texts are in contracts/slack-messages.md. Build messages through pure functions that take a dict of environment values and the summary, so the tests set no real environment. See them fail.

### Implementation for User Story 1

- [X] T006 [US1] In `src/scripts/notify_slack.py`, implement:
  - `start_message(env) -> str`;
  - `end_message(env, summary, failed_step) -> str` for "passou" and "passou com avisos";
  - `_duration(started_at, now) -> str | None`;
  - `_run_link(env)` and `_commit_link(env, sha)`;
  - `_read_summary(path) -> dict | None`, which returns None when the file is missing or invalid.
  - Result: start_message, end_message, _duration, _run_link, _commit_link, _read_summary implemented with the texts of contracts/slack-messages.md; T005 passes.

  The texts are those of contracts/slack-messages.md. T005 passes.
- [X] T007 [US1] In `src/scripts/notify_slack.py`:
  - implement `send(text, webhook, timeout=15) -> bool` with `urllib.request` (POST JSON `{"text": …}`, `Content-Type: application/json`);
  - wire `main`:
    - `start` sends `start_message` and writes `WEEKLY_STARTED_AT=<epoch>` to the file in `GITHUB_ENV`, when set;
    - `end` reads the summary and `ARCHIVE_COMMIT` and sends `end_message`;
    - `--dry-run` prints the text and sends nothing.
  - Result: send() posts {"text": …} as JSON with a 15 s timeout; main wires start (writes WEEKLY_STARTED_AT to GITHUB_ENV) and end (summary + ARCHIVE_COMMIT); --dry-run prints and sends nothing.
- [X] T008 [US1] In `.github/workflows/weekly-etl.yml`, add the step "Notify Slack: start" right after "Checkout repository" (contract item 1):
  - `continue-on-error: true`;
  - `env: HORIZON_SLACK_WEBHOOK_URL: ${{ secrets.HORIZON_SLACK_WEBHOOK_URL }}`;
  - `run: python3 -m src.scripts.notify_slack start`.
  - Result: Step 'Notify Slack: start' added right after checkout: continue-on-error, secret only in its env, 'python3 -m src.scripts.notify_slack start'.
- [X] T009 [US1] In `.github/workflows/weekly-etl.yml`, give the step "Commit the export archives if changed" `id: archives` (contract item 3):
  - where it prints "No changes to the export archives; nothing to commit." and exits, first `echo "commit=unchanged" >> "$GITHUB_OUTPUT"`;
  - after `git push`, `echo "commit=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"`;
  - nothing else changes.
  - Result: Commit step: id archives; 'commit=unchanged' to GITHUB_OUTPUT before 'exit 0', 'commit=$(git rev-parse HEAD)' after git push; nothing else changed.
- [X] T010 [US1] In `.github/workflows/weekly-etl.yml`, add the last step "Notify Slack: end" (contract item 2):
  - `if: always()`, `continue-on-error: true`;
  - `env`: `HORIZON_SLACK_WEBHOOK_URL`, `JOB_STATUS: ${{ job.status }}`, `ARCHIVE_COMMIT: ${{ steps.archives.outputs.commit }}`, `GITHUB_TOKEN: ${{ github.token }}`;
  - `run`: if `src/scripts/notify_slack.py` exists, run `python3 -m src.scripts.notify_slack end`. Otherwise, when the secret is set, send the checkout-failure line of the contract with `curl -s -o /dev/null -X POST -H 'Content-type: application/json' --data "$PAYLOAD" "$HORIZON_SLACK_WEBHOOK_URL" || true`, never echoing the URL.
  - Result: Last step 'Notify Slack: end': if always(), continue-on-error, env (secret, JOB_STATUS, ARCHIVE_COMMIT, GITHUB_TOKEN); runs the script when it exists, otherwise the curl line of the contract when the secret is set (URL never echoed), otherwise the warning. YAML loads.

**Checkpoint**: a passing run sends both messages.

---

## Phase 4: User Story 2 - Be told when the weekly fails, wherever it fails (Priority: P1)

**Goal**: the end message says "falhou" with the step, and the critical phases when it is the weekly flows step, or says "cancelada".

**Independent Test**: unit tests with fake API answers. A fork run with a forced failure before the ETL.

### Tests for User Story 2

- [X] T011 [P] [US2] In `tests/test_notify_slack.py`, add:
  - `test_end_message_failed_with_step` (`JOB_STATUS=failure`, failed step "Install Playwright Chromium" → "❌ … falhou" and "Passo: Install Playwright Chromium", no phase line);
  - `test_end_message_failed_in_weekly_flows_names_critical_phases` (failed step "Run weekly flows", summary `critical_failed: [sigpesq]` → "Fases críticas: sigpesq");
  - `test_end_message_failed_step_unknown` (lookup returned None → no "Passo:" line);
  - `test_end_message_cancelled` → "⏹️ … cancelada", no detail lines;
  - `test_first_failed_step_from_api`: a fake JSON of `/actions/runs/{id}/attempts/{n}/jobs` with job `run-etl` and steps success, failure, failure → the first failure's name. An HTTP error or bad JSON gives None, with the urlopen call monkeypatched.
  - Result: Added: failed with step, failed in 'Run weekly flows' with critical phases, failed step unknown, cancelled, first failed step from a fake API answer (job run-etl, first failure, Bearer token, attempts URL), API HTTP error / URLError / timeout / bad JSON -> None.

  See them fail.

### Implementation for User Story 2

- [X] T012 [US2] In `src/scripts/notify_slack.py`:
  - implement `first_failed_step(env) -> str | None`, which calls `{GITHUB_API_URL or https://api.github.com}/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs` with `Authorization: Bearer $GITHUB_TOKEN`, a 15 s timeout and `per_page=100`, and returns None on any error;
  - extend `end_message` for "falhou" and "cancelada";
  - in `main end`, call `first_failed_step` only when `JOB_STATUS` is `failure`.
  - Result: first_failed_step() calls /repos/{repo}/actions/runs/{id}/attempts/{n}/jobs?per_page=100 with the token, returns None on any error; end_message covers falhou and cancelada; main asks the API only when JOB_STATUS is failure. T011 passes.

  T011 passes.

**Checkpoint**: failures and cancellations are reported with their place.

---

## Phase 5: User Story 3 - The notice never changes the weekly (Priority: P2)

**Goal**: a missing secret or a Slack error only logs a warning, and the address never leaks. Local runs send nothing.

**Independent Test**: unit tests. Workflow tests. A grep of the fork run logs.

### Tests for User Story 3

- [X] T013 [P] [US3] In `tests/test_notify_slack.py`, add:
  - `test_missing_secret_is_a_warning_and_exit_0` (no `HORIZON_SLACK_WEBHOOK_URL` → prints the `::warning::Slack não configurado…` line, sends nothing, returns 0);
  - `test_http_error_is_a_warning_without_the_url` (urlopen raises `HTTPError` 404 → the warning has "HTTP 404" and the captured stdout and stderr do not contain the fake webhook `https://hooks.slack.com/services/T000/B000/XXXX`);
  - `test_network_error_is_a_warning_without_the_url` (URLError and timeout);
  - `test_no_flow_or_makefile_calls_the_notice`: `notify_slack` appears in no file under `src/flows/`, in no `Makefile` line, and in `app.py`.
  - Result: Added: missing and empty secret -> exact warning, exit 0, nothing sent; HTTP 404 -> 'Slack recusou a mensagem (HTTP 404)' with no webhook in stdout/stderr; URLError (whose text holds the URL) and timeout -> 'Slack não respondeu' without the URL; unexpected error -> warning, exit 0; no flow, Makefile or app.py calls the script (the test checks calls, since the orchestrator comment names the script). 31 passed.
- [X] T014 [P] [US3] In `tests/test_weekly_etl_workflow.py`, add for the contract of weekly-workflow-notices.md:
  - `test_slack_start_notice_comes_right_after_checkout` (item 1);
  - `test_slack_end_notice_is_last_and_always_runs` (item 2: last step, `if == "always()"`, `continue-on-error is True`, env keys);
  - `test_archive_commit_step_exposes_the_commit` (item 3: `id == "archives"`, `run` writes `commit=unchanged` and `commit=$(git rev-parse HEAD)` to `GITHUB_OUTPUT`);
  - `test_the_webhook_is_only_in_the_notice_steps` (item 4: not in the job `env`; only the two notice steps reference `secrets.HORIZON_SLACK_WEBHOOK_URL`);
  - `test_no_step_prints_the_webhook` (item 5: no `run` contains `echo` followed by `HORIZON_SLACK_WEBHOOK_URL`).
  - Result: tests/test_weekly_etl_workflow.py: start notice right after checkout, end notice last with always()/continue-on-error and its env, commit step id and outputs (order checked), webhook only in the two notice steps, no step prints the webhook value (\b(echo|printf|cat)\b … $HORIZON_SLACK_WEBHOOK_URL; the warning that names the variable is allowed). Before T008-T010: 4 failed, 1 passed; after: 27 passed.

  Run them.

### Implementation for User Story 3

- [X] T015 [US3] In `src/scripts/notify_slack.py`:
  - make every warning path match contracts/slack-messages.md;
  - never include `str(exc)` of an urllib error;
  - make sure no code path prints the webhook value.
  - Result: Warnings match contracts/slack-messages.md; no urllib error text is printed (HTTPError becomes SlackRefused with the code only, other errors the fixed 'não respondeu' line); a URLError carrying the address is covered by a test. test_notify_slack.py + test_weekly_etl_workflow.py + test_weekly_orchestrator.py: 99 passed.

  Run T013 and T014 and record that they pass.

**Checkpoint**: the notice is harmless when Slack is unavailable.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T016 [P] In `docs/operations/automation.md`, add a section "Aviso no Slack (spec 040)" covering:
  - what is sent and when;
  - the four results;
  - how to create the app, choose "Incoming Webhooks" and pick the channel;
  - the secret `HORIZON_SLACK_WEBHOOK_URL`, and that a missing secret only skips the notice;
  - that local runs send nothing and that Telegram is unchanged.
  - Result: docs/operations/automation.md: the secret listed as optional under 'Secrets usados', and a new section 'Aviso no Slack (spec 040)' (what is sent and when, the four results, where phases and the failed step come from, how to create the app with incoming-webhook and pick the channel, the secret, that the URL is never printed and a missing secret only warns, that local runs send nothing and Telegram is unchanged). In Portuguese without accents, as the rest of the file. The file still says the schedule is 06:00 UTC (0 6 * * 6) while the workflow uses 0 2 * * 6; left as it is, outside this spec.
- [X] T017 [P] In `docs/backlog.md`:
  - if TD-053 is still "decision needed", note that the LinkedIn list is versioned since 2026-11-16 (commits d6b5eb9 and a95856c on main) and set Status: Closed;
  - add nothing else.
  - Result: docs/backlog.md TD-053 closed: the list is versioned on main since 2026-11-16 (d6b5eb9, a95856c), with the manager's approval; the CI weekly of branch 039 stored 243 links.
- [X] T018 Run black and isort on the touched Python files and flake8 on them. Record the result and the repository flake8 count (T001's or lower).
  - Result: black reformatted tests/test_notify_slack.py and tests/test_weekly_etl_workflow.py (long lines of this branch); isort no change; flake8 on src/scripts/notify_slack.py, src/flows/pipelines/weekly_orchestrator.py, tests/conftest.py and the three test files: 0 findings. Repository: 579, as in T001.
- [X] T019 Run the full suite: `.venv/bin/python -m pytest -q > logs/pytest_040_full.log 2>&1`. Record it: every test of T001 plus the new ones, 0 failed.
  - Result: 1553 passed, 10 skipped, 0 failed in 6m41 (logs/pytest_040_full.log): the 1514 of T001 plus 39 new. A first full run left data/reports/weekly_phase_summary.json behind: four older test files (test_weekly_orchestrator_finalize, test_rule_version_guard, test_sqlite_settings, conftest users) run run_weekly without the per-file fixture. The fixture moved to tests/conftest.py (autouse, suite-wide), the stray file was deleted, and the rerun left nothing under data/ (git status shows only the export zips of the local weeklies).
- [X] T020 Run quickstart.md section 2: the dry run for start, passou, passou com avisos, falhou and cancelada. Record the five texts with the fork links replaced by `<link>`.
  - Result: Dry runs with the system python3 (no venv), run link and fake commit: start '🟡 Weekly do Horizon ETL começou / Branch: main · agendada / <link|Ver a run>'; passou '✅ … passou / Branch: main · tempo: 1h 52min / Zips: <link|bdf8f86> / <link|Ver a run>'; passou com avisos '⚠️ … / Zips: não mudaram / Fases com falha: openalex_citations / …'; falhou '❌ … / Passo: Run weekly flows / Fases críticas: sigpesq / …'; cancelada '⏹️ … cancelada / Branch: main · tempo: 1h 52min / <link|Ver a run>'. Real call without the secret: the warning line, exit 0.
- [ ] T021 Fork run, normal (only when the maintainer asks; RafaelDeps fork only; push without force). Follow quickstart section 3.1 and record:
  - the run id and its result;
  - that the two messages arrived (the maintainer confirms in the channel);
  - their result line;
  - 0 matches of `hooks.slack.com` in the run log.
- [ ] T022 Fork run with a forced failure before the ETL (only when the maintainer asks). Follow quickstart section 3.2, on a throwaway branch deleted afterwards, and record that the end message said "falhou" with the step name.

---

## Dependencies & Execution Order

- **Setup (Phase 1)**: first.
- **Foundational (Phase 2)**: T002 before T003. T004 can run alongside them.
- **US1 (Phase 3)**:
  - after T004;
  - T005 before T006 and T007;
  - T008, T009 and T010 edit the same file, so they run in order.
- **US2 (Phase 4)**: after US1 (it extends `end_message` and `main`).
- **US3 (Phase 5)**: after US2 for T015. T013 and T014 can be written earlier.
- **Polish (Phase 6)**:
  - T016 and T017 run in parallel;
  - T018 before T019, and T019 before T020;
  - T021 and T022 last, after a commit and a push the maintainer asked for.

### Parallel Opportunities

- T002 and T004.
- T005, T011, T013 and T014 are test files or sections. They run in parallel when written first.
- T016 and T017.

---

## Parallel Example: tests first

```bash
Task: "Orchestrator summary tests in tests/test_weekly_orchestrator.py (T002)"
Task: "Message tests in tests/test_notify_slack.py (T005, T011, T013)"
Task: "Workflow notice tests in tests/test_weekly_etl_workflow.py (T014)"
```

---

## Implementation Strategy

### MVP First (User Stories 1 and 2)

1. Phases 1 and 2.
2. US1, then US2: start and end messages for every result.
3. **Stop and validate**: unit and workflow tests, and dry runs.

### Incremental Delivery

1. US1 + US2: notices work.
2. US3: harmless when Slack is missing; no leak.
3. Polish, then the fork runs when the maintainer asks.

---

## Notes

- Validation is on the fork only, with no local weekly (maintainer's decision for this spec).
- The webhook address is never written in any file, test or log. Tests use the fake `https://hooks.slack.com/services/T000/B000/XXXX`.
- Never stage `PLANO_*`, `RESUMO_*`, `data/`, `logs/` or the export zips.
