# Implementation Plan: Paced Retry for Project PDFs Refused by the Rate Limit

**Branch**: `031-mistral-rate-limit-retry` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/031-mistral-rate-limit-retry/spec.md`

## Summary

The extraction stage of phase `extract_project_files` sends the pending
project PDFs to Mistral one after the other and gives a document up at the
first HTTP 429. On 2026-11-09 the same 25 documents failed that way in two
fork runs, so those projects never get the PDF enrichment in CI.

The change wraps the library call `ProjectExtractor.extract_project` in a
paced loop inside horizon_etl:

- a pause between calls;
- a rate limit refusal is retried after a growing wait (honouring
  `Retry-After` when the service sends it);
- a wait budget for the whole phase, after which the remaining documents are
  left for the next run;
- every other failure keeps today's behaviour.

The decisions (settings, which error is a rate limit, how long to wait,
whether the budget allows it) are pure core logic. The adapter only calls
the library, sleeps and counts.

The extraction counts are split (present, restored, extracted, recovered,
retried, failed by reason, left), the opening log line stops announcing
restored documents as "to extract", and the weekly summary and Telegram get
one line from a new `extractions` key of `data/reports/portal_stops.json`.

With 0 retries and a 0 s pause the stage behaves as today.

## Technical Context

**Language/Version**: Python 3.12 in CI (local venv 3.14)

**Primary Dependencies**:
- Prefect 3 (existing flow `Extract SigPesq Project Files`);
- agent_sigpesq `ProjectExtractor` (unchanged);
- mistralai 1.12 errors, read by duck typing (`status_code`, `headers`), so
  the core logic never imports the optional library;
- loguru.

**Storage**: files only. `PJ_<code>.json` in
`data/exports/project_sigpesq_files_json/` (format unchanged) and the
report `data/reports/portal_stops.json` (new `extractions` key). No database
change.

**Testing**: pytest, with a fake extractor raising fake 429 errors, a fake
clock and a fake sleep. No network, no real waits.

**Target Platform**: local Linux and GitHub Actions `ubuntu-latest`
(`weekly-etl.yml`).

**Project Type**: single-project ETL (ports and adapters + Prefect flows).

**Performance Goals**:
- With the defaults, the 25 pending documents of 2026-11-09 take at most
  about 25 × (2 s pause + call time) plus the 429 waits, within the
  20 min wait budget.
- Nothing is added when nothing is pending.

**Constraints**:
- phase limit 7200 s (the PDF download from scratch took 33 min);
- job limit 300 min;
- the phase never fails the weekly run;
- third-party libraries unchanged;
- SigPesq sequential;
- feature 013 order (restore before any call).

**Scale/Scope**: 322 PDFs, about 26 pending per CI run today, 0 locally.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Ports & Adapters | The new module `src/core/logic/extraction_pacing.py` is pure core logic: settings read from a mapping, error classification by duck typing, wait and budget decisions. It has no I/O and imports no adapter or library. The adapter `project_files.py` keeps the library call and the sleep. The report helper stays in `src/flows/portal_stops.py`. | Pass |
| II. Domain-First | No domain entity or table changes. | Pass |
| III. Prefect Flows | It runs inside the existing `Extract SigPesq Project Files` flow and its task. There is no new flow and no new phase. | Pass |
| IV. Audit | Every retry is logged (document, try, wait, reason). The end summary splits all counts. The weekly summary and Telegram show one line per run. | Pass |
| V. LGPD | No personal data is added. Logs and the report hold PJ codes and counts, as today. | Pass |
| Data Integrity 2 (idempotency) | A recovered document is written like any extracted one. An unchanged run with nothing pending makes no call and writes nothing. | Pass |
| Data Integrity 5 (replace only after success) | A JSON is written only after a successful extraction, as today. A refused document writes nothing. | Pass |
| Data Integrity 7 (sources of truth) | The report is output only; no phase reads it as input. | Pass |
| Quality gate | New tests cover every rule. The existing zip reuse tests pass unchanged. The workflow keeps calling Makefile targets. 15 dispatch inputs stay below the 25 allowed. | Pass |

Re-check after Phase 1: still Pass. No new port is needed. The pacing logic
has no I/O, the extractor is already behind the adapter, and the clock and
sleep are injected parameters.

## Project Structure

### Documentation (this feature)

```text
specs/031-mistral-rate-limit-retry/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1-R8
├── data-model.md        # Phase 1: settings, outcomes, counts, report entry
├── quickstart.md        # Phase 1: how to validate locally and in the fork
├── contracts/
│   └── extraction-retry.md   # settings, retry rules, counts, report, log lines
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/core/logic/
└── extraction_pacing.py          # NEW: settings, is_rate_limit, retry_after_s,
                                  #      next wait, WaitBudget (pure)
src/adapters/sources/sigpesq/
└── project_files.py              # extract_json: paced loop around
                                  #   extract_project, split counts, clearer lines
src/flows/
├── portal_stops.py               # record_extraction / read_extractions
│                                 #   (new "extractions" key)
├── sigpesq/project_files.py      # records the extraction entry after the stage
└── pipelines/weekly_orchestrator.py  # _extraction_lines in the log summary
                                      #   and Telegram
Makefile                          # EXTRACT_* variables in weekly-flows and
                                  #   extract-project-files
.github/workflows/weekly-etl.yml  # 4 dispatch inputs -> HORIZON_EXTRACT_* env
docs/flows-and-entrypoints.md     # the extraction retry and its settings

tests/
├── test_extraction_pacing.py         # NEW: settings, classification, waits, budget
├── test_project_files_rate_limit.py  # NEW: adapter loop with fake extractor and clock
├── test_project_files_zip_reuse.py   # unchanged, must still pass
├── test_portal_stops_report.py       # + extractions key
├── test_weekly_orchestrator.py       # + summary lines
└── test_weekly_etl_workflow.py       # + inputs wired to env
```

**Structure Decision**: single project. The new logic follows spec 025's
`access_check_retry.py`: a pure settings and decision module in
`src/core/logic`, used by an existing adapter, reported through the
existing `portal_stops.json` helper and summary.

## Complexity Tracking

No constitution violation; nothing to justify.
