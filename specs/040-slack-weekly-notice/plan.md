# Implementation Plan: Slack notice of the GitHub Actions weekly

**Branch**: `040-slack-weekly-notice` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/040-slack-weekly-notice/spec.md`

## Summary

Two new steps in the `run-etl` job of `.github/workflows/weekly-etl.yml`, plus
one small script:

- **"Notify Slack: start"** runs right after checkout. It sends the branch, how
  the run was started and the link to the run, and writes the start time to
  `$GITHUB_ENV`.
- **"Notify Slack: end"** is the last step. It has `if: always()` and
  `continue-on-error: true`, so it runs after a failure or a cancellation and
  can never change the job's result. It sends the result, the branch, the
  total time and the link to the run, plus:
  - when the run failed: the first failed step and the critical phases;
  - when it passed: the archive commit or "unchanged", and the non-critical
    phases that failed.
- **`src/scripts/notify_slack.py`** builds and sends the messages, using the
  standard library only. Its rules:
  - it reads the webhook only from `HORIZON_SLACK_WEBHOOK_URL`;
  - it never prints the address;
  - it always exits 0, with a `::warning::` line when the secret is missing or
    Slack refuses.

Where each piece of information comes from:

- **Result**: `job.status` (success / failure / cancelled), refined by the
  phase summary: a successful job with failed non-critical phases becomes
  "passou com avisos".
- **First failed step**: the GitHub API for the current job (`GITHUB_TOKEN`,
  read access), the first step whose conclusion is `failure`.
- **Phases**: a small JSON summary that the weekly orchestrator now writes at
  its end (`data/reports/weekly_phase_summary.json`: name, ok, critical, rc).
  The phases themselves are unchanged.
- **Archive commit**: an output of the commit step (`sha`, or `unchanged`).
- **Times**: the start time from the start step, the end time read when the
  end notice is sent.

If checkout itself failed, the script is not on the runner. The end step then
sends a minimal message with `curl`, from the same secret.

## Technical Context

**Language/Version**: Python 3.12 (runner's `python3`, no venv needed for the notice); GitHub Actions YAML; bash

**Primary Dependencies**: Python standard library only (`urllib.request`, `json`, `os`); `gh`/REST API through `urllib` with `GITHUB_TOKEN`; `curl` for the checkout-failure fallback; no new package

**Storage**: one new report file, `data/reports/weekly_phase_summary.json` (no database change)

**Testing**: pytest; new `tests/test_notify_slack.py` (message builder, missing secret, Slack error, no URL in output); `tests/test_weekly_etl_workflow.py` (step order, `if: always()`, `continue-on-error`, secret wiring); `tests/test_weekly_orchestrator.py` (summary file)

**Target Platform**: GitHub Actions `ubuntu-latest`, RafaelDeps fork

**Project Type**: ETL pipeline with a CI workflow

**Performance Goals**: each notice adds under 10 seconds to the run (one HTTP call; API call for the end notice)

**Constraints**:
- the job's result must never depend on the notice;
- the webhook address must never be logged;
- no new dependency, no Docker change;
- Telegram unchanged;
- local runs send nothing: the script is only called from the workflow, and
  the orchestrator only writes a file.

**Scale/Scope**: 1 workflow, 1 new script, 1 small orchestrator addition, 1 doc, 3 test files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Note |
|-----------|--------|------|
| I. Ports & Adapters | Pass | Slack is reached only from a CI script, not from ETL logic; `src/core/logic/` is untouched. |
| II. Domain-First Data Modeling | Pass | No entity or export change. |
| III. Prefect Flow Orchestration | Pass (justified) | The notice is a CI helper in `src/scripts/` (allowed for operational scripts that perform no ingestion or export). The orchestrator only writes its existing summary to a file. |
| IV. Audit-Driven Data Quality | Pass | The phase summary file adds to the audit trail; reports unchanged otherwise. |
| V. LGPD Compliance by Default | Pass | Messages carry branch, result, step and phase names, times and links: no personal data, no data totals. The summary file passes the artifact's text scan like the other reports. |
| Data Integrity & Persistent Incremental Ingestion | Pass | No change to keys, hashes, rule version or caches. |
| Development Workflow & Quality Gates | Pass | black, isort, flake8 and the full pytest suite before commit. |

Post-design re-check: unchanged, all pass.

## Project Structure

### Documentation (this feature)

```text
specs/040-slack-weekly-notice/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── slack-messages.md
│   └── weekly-workflow-notices.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
.github/workflows/weekly-etl.yml         # start and end notice steps; commit step gets an id and an output
src/scripts/notify_slack.py              # new: build and send the start/end messages
src/flows/pipelines/weekly_orchestrator.py  # write data/reports/weekly_phase_summary.json at the end
tests/test_notify_slack.py               # new
tests/test_weekly_etl_workflow.py        # notice steps
tests/test_weekly_orchestrator.py        # summary file
docs/operations/automation.md            # Slack notice section
```

**Structure Decision**: single project. `notify_slack.py` lives next to the
other CI helpers in `src/scripts/` (`check_publishable_archive.py`,
`restore_weekly_artifact.py`).

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|------|------------|--------------------------------------|
| GitHub API call for the failed step | the end step must name the first failed step, also before the ETL | giving every step an `id` and reading `steps.<id>.outcome` needs ids on all 14 steps and breaks silently when a step is added |
| curl fallback when checkout failed | the spec requires the end message for any failure | without it, a checkout failure would send nothing |
