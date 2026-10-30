# Implementation Plan: Stop Downloading When a Portal Blocks

**Branch**: `027-portal-early-stop` | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/024-portal-early-stop/spec.md`

## Summary

The CNPq and Lattes downloads stop calling their portal once it clearly
stops answering, and the run finishes from the stored copies of spec 023.

- **CNPq**: stop after 8 failed attempts in a row with no success between
  them (an attempt already includes the library's 3 tries), or after 45 min
  of downloads. No new attempt or retry starts after the stop. The attempts
  in flight end within the library's timeouts, and every group left is
  processed from its stored page. In the outage of run 40966298828 this
  stops after about 5 min instead of 3 h (research R1).
- **Lattes**: stop after 5 requests in a row that failed or returned the
  access check page, counted across new and refreshed curricula. Untried
  curricula keep their cached copy and their old date, so the next rotation
  takes them first.

A pure, thread-safe `PortalStop` in `src/core/logic/portal_stop.py` holds the
counter, the deadline and the stop decision. The CNPq fetch tasks and the
Lattes download tasks ask it before each request. The stop is logged, counted
apart from failures (`stopped`), written to `data/reports/portal_stops.json`,
and shown in the weekly summary and its Telegram message. It never changes a
phase's exit code.

Four environment variables, with Makefile variables and workflow inputs, set
the limits or turn the feature off.

## Technical Context

**Language/Version**: Python 3.12 (CI) / 3.14 (local).

**Primary Dependencies**:
- Prefect 3 flows;
- dgp_cnpq_lib through `CnpqCrawlerAdapter` (unchanged);
- scriptLattes through the existing patched downloader (unchanged);
- the spec 017 concurrent fetch (`AdaptiveGate`, `fetch_with_retries`,
  `fetch_all`) and the spec 023 rotation (`plan_downloads`,
  `download_counts`).

**Storage**:
- Unchanged: `data/raw/cnpq/<id>.json`, `cache/<lattes_id>`,
  `data/raw/lattes/download_manifest.json`, `db/horizon.db`.
- New report file: `data/reports/portal_stops.json`. It is removed at the
  start of each weekly and never read as an input.

**Testing**: pytest with fake adapters and downloaders, a fake clock and an
injected wait (research R7). The spec 017 and spec 023 tests stay unchanged
as the "identical when healthy" check.

**Target Platform**: local Linux and the GitHub Actions `ubuntu-latest` weekly.

**Project Type**: ETL pipeline (Prefect flows).

**Performance Goals**:
- **CNPq portal down:** the phase ends in at most 15 min (SC-001); about 8 to
  10 min is expected.
- **Lattes portal blocking:** at most 5 requests plus the 2 others in flight
  (SC-003).
- **Healthy portals:** no change in time or output.

**Constraints**:
- CNPq keeps 4 workers, the adaptive gate, the 3 ETL attempts and the
  30/90 s back-offs, with a single database writer.
- SigPesq stays sequential.
- Third-party libraries are unchanged; the access check is never answered or
  bypassed.
- No table or export file changes; no Docker change.

**Scale/Scope**: about 435 curricula and 350 CNPq pages. The change covers:
- one new core module and one small flows helper for the report;
- changes to `concurrent_fetch.py`, `groups.py`, `download.py`,
  `raw_rotation.py` and the weekly orchestrator;
- the Makefile and the workflow.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Ports & Adapters | `PortalStop` and `portal_stop_settings` are pure core logic. They read the environment like `refresh_settings`, use no I/O and import no adapter. The report file is written by a flows helper (`src/flows/portal_stops.py`), as `document_phase.py` does. The portal calls stay in the existing adapters. | Pass |
| II. Domain-First | No domain entity changes. | Pass |
| III. Prefect Flows | The stop runs inside the existing CNPq and Lattes download flows, with their hooks. The orchestrator only reads the report. | Pass |
| IV. Audit | Every stop is logged, counted (`stopped`), written to a report, and shown in the weekly summary. The CNPq counts keep going to the spec 021 phase report. | Pass |
| V. LGPD | No personal data is added; the report holds counts, reasons and times. | Pass |
| Data Integrity 2 (idempotency) | An untried item is processed from its stored copy, so an unchanged one writes nothing (spec 021 skip). | Pass |
| Data Integrity 5 (replace only after success) | A stop never replaces or deletes a stored copy; untried items keep theirs. | Pass |
| Data Integrity 6 (provenance) | A group from its stored page keeps the page's original `downloaded_at`. | Pass |
| Quality gate | New tests for every new rule; existing tests unchanged; the workflow keeps calling Makefile targets. | Pass |

Re-check after Phase 1: still Pass. The design adds no port, because the stop
has no I/O and the report is a flows-level concern.

## Project Structure

### Documentation (this feature)

```text
specs/024-portal-early-stop/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R7
├── data-model.md        # PortalStop, settings, counts, report entry
├── quickstart.md        # how to try it locally and on the fork
├── contracts/
│   ├── portal-stop.md       # the core API and its rules
│   └── settings-and-report.md # environment, Makefile, workflow, report file
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/core/logic/
├── portal_stop.py         # NEW: PortalStop, PortalStopSettings, portal_stop_settings()
└── raw_rotation.py        # download_counts(..., stopped=[]) and counts_line with stopped=

src/flows/
├── portal_stops.py        # NEW: record_portal_stop(), read/clear the report file
├── cnpq/
│   ├── concurrent_fetch.py # fetch_with_retries/fetch_all take an optional PortalStop
│   └── groups.py           # builds the CNPq stop; untried groups from stored pages; report
├── lattes/
│   └── download.py         # one Lattes stop shared by prefetch and refresh; report
└── pipelines/
    └── weekly_orchestrator.py # clears the report at start; summary and Telegram lines

Makefile                     # EARLY_STOP, CNPQ_STOP_AFTER, CNPQ_BUDGET_MIN, LATTES_STOP_AFTER
.github/workflows/weekly-etl.yml # 4 dispatch inputs passed to make weekly-flows

tests/
├── test_portal_stop.py      # NEW
├── test_cnpq_early_stop.py  # NEW
├── test_lattes_early_stop.py # NEW
├── test_weekly_orchestrator.py # summary lines from portal_stops.json
└── test_weekly_etl_workflow.py # the 4 new dispatch inputs reach make weekly-flows
```

**Structure Decision**: follow spec 023's split. The decision rule is pure
core logic next to `raw_rotation.py`. The flows own the threads, the stored
copies and the report file.

## Design Notes

1. **CNPq fetch** (`concurrent_fetch.py`):
   - `fetch_with_retries` gets `stop: Optional[PortalStop]`.
   - Before each attempt, and again after acquiring a gate slot, it returns
     `FetchOutcome(..., data=None, attempts=k, stopped=True)` if
     `stop.should_stop()`.
   - After each attempt it calls `stop.record(success)`.
   - The back-off uses `stop.wait(seconds)`, which wakes on the stop, instead
     of `sleep` when a stop is given. The injected `sleep` stays for tests.
   - `FetchOutcome` gains `stopped: bool = False`.
   - With `stop=None` the behaviour is byte-for-byte today's.
2. **CNPq writer** (`groups.py`):
   - A stopped outcome with `attempts == 0` is "not tried". With a stored
     page, it is processed from it with the page's date, and nothing is
     recorded as failed. Without one, it is a failed download, as today
     (FR-004).
   - A stopped outcome with `attempts > 0` is a failed download, as today:
     the stored page is used if it exists.
   - `download_counts(plan, failed, stopped)` gives the counts.
   - On a stop, the phase calls `record_portal_stop("cnpq", stop, counts)`
     and logs `portal given up: cnpq ...`.
   - The deadline starts when `fetch_all` is called.
3. **Lattes** (`download.py`):
   - `rotate_lattes_downloads` builds one stop from the settings and passes it
     to `prefetch_lattes_cache` and `refresh_lattes_cache`.
   - Each task checks `should_stop()` first. When stopped, it raises
     `_NotTried`, which goes to a `stopped` list, not to `failed`.
   - Then it records success or failure, where the access check page counts
     as a failure.
   - The manifest records only the successes, as today.
   - `retry_unidentified` is unchanged.
   - Stop: `record_portal_stop("lattes", ...)` and a log line.
4. **Orchestrator**:
   - At the start of `run_weekly`, it deletes `data/reports/portal_stops.json`.
   - At the end, it reads the file, adds one line per source to the summary
     log and to `_notify`, and keeps the exit code.
5. **Settings**: `portal_stop_settings(env)` returns `PortalStopSettings`
   (`enabled`, `cnpq_failures`, `cnpq_budget_s`, `lattes_failures`). An
   invalid value is logged and the default used; a limit of 0 turns that rule
   off; disabled gives `None` stops, today's path.

## Validation

1. **Unit and flow tests** (R7).
2. **Local replay of the outage.** Run the CNPq phase on a copy of the
   database and of `data/raw/cnpq/` (backup first) with a fake adapter that
   fails every attempt after the library's real wait, from a small script
   in the scratchpad. The phase ends in minutes, the database is unchanged,
   and `portal_stops.json` is written.
3. **Fork dispatch on a healthy day.** The CNPq time and counts match spec
   023's run 40959876147, and `portal_stops.json` is absent.
4. **Fork dispatch with tight limits** (e.g. `cnpq_budget_min=1`,
   `lattes_stop_after=1`) to exercise the stop on the real portals. The run
   ends green, the summary shows both stops, and the next run picks the
   untried items first.
5. **Report.** `docs/reports/2026-10-30-portal-early-stop-validation.md`.

Nothing goes upstream before the maintainer's manager validates.

## Complexity Tracking

No constitution violations to justify.
