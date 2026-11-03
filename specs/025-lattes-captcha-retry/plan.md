# Implementation Plan: Second Try for Lattes Access Check Pages

**Branch**: `028-lattes-captcha-retry` | **Date**: 2026-11-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/025-lattes-captcha-retry/spec.md`

## Summary

The Lattes download asks again, once, for the curricula that came back as
the portal's access check page, at the end of the same run and after a
pause.

**How it is detected**: the two places that already reject the page
(spec 023) raise a new `AccessCheckPage` exception. They collect the
rejected ids in an output list, so the other failures keep their current
retry.

**The second pass**: at the end of `rotate_lattes_downloads`, if the
spec 024 stop did not give the portal up, the download waits the pause
(default 5 min). It then runs the existing `prefetch_lattes_cache` and
`refresh_lattes_cache` again on those ids:
- with the second-pass worker count (default 1);
- with the same `PortalStop`.

The caching rules, the manifest and the scriptLattes list need no change.
A curriculum is cached, or replaces its copy, only when the real page
arrives, and a recovered one is in `cache/` when the flow builds the
scriptLattes list.

**The counts**: the downloads line gains `retried=` and `recovered=`. The
spec 024 report file gains a `retries` entry, and the weekly summary and
its Telegram message gain one line. All of this happens only when a second
pass ran, so a healthy run is unchanged.

**Settings**: two environment variables, `HORIZON_LATTES_RETRY_WORKERS` (0 =
off) and `HORIZON_LATTES_RETRY_PAUSE_MIN`. Each has a Makefile variable and
a workflow input.

## Technical Context

**Language/Version**: Python 3.12 (CI) / 3.14 (local).

**Primary Dependencies**:
- Prefect 3 flows;
- scriptLattes through the existing patched downloader (unchanged);
- the spec 023 rotation (`plan_downloads`, `download_counts`,
  `counts_line`);
- the spec 024 `PortalStop` and its report helpers.

**Storage**:
- Unchanged: `cache/<lattes_id>`, `data/raw/lattes/download_manifest.json`,
  `db/horizon.db`, the export files.
- Report file: `data/reports/portal_stops.json` gains an additive `retries`
  key. It stays version 1, is still cleared at the start of each weekly, and
  is never read as an input.

**Testing**:
- pytest with the fake portal of `tests/test_lattes_early_stop.py`, extended
  to answer per attempt, and an injected `sleep`.
- An autouse fixture in `tests/conftest.py` turns the second pass off, so
  the spec 023 and spec 024 tests keep describing today's behaviour
  (research R7).

**Target Platform**: local Linux and the GitHub Actions `ubuntu-latest` weekly.

**Project Type**: ETL pipeline (Prefect flows).

**Performance Goals**:
- At a random rejection rate of about 9%, at least 75% of the rejected
  curricula are recovered in the same run (SC-001, a reference).
- The second pass costs the pause plus about 10 s per retried curriculum and
  worker, about 11 min for the 38 of 2026-11-03 (SC-002). The phase stays
  inside its 90 min limit (research R8).

**Constraints**:
- The access check is never answered or bypassed. The second pass repeats
  the same plain request, later.
- Unchanged: the 3 first-pass workers, the refresh share, the spec 024
  limits, the timeout and connection retry (2 attempts, 30 s), SigPesq
  sequential, scriptLattes.
- No table or export file changes; no Docker change.

**Scale/Scope**:
- About 435 curricula; 30 to 40 rejected in a run from scratch, and about 7
  to 9 in a 25% rotation.
- The change covers:
  - one new core module (`access_check_retry.py`);
  - changes to `src/flows/lattes/download.py`, `src/core/logic/raw_rotation.py`
    (`counts_line`), `src/flows/portal_stops.py` and the weekly orchestrator;
  - the Makefile and the workflow.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Ports & Adapters | `access_check_retry_settings` is pure core logic. It reads the environment like `portal_stop_settings`, with no I/O and no adapter import. The portal calls stay in the existing download functions, and the report is written by the flows helper of spec 024. | Pass |
| II. Domain-First | No domain entity changes. | Pass |
| III. Prefect Flows | The second pass runs inside the existing `Download Lattes Curricula` flow and its hooks; no new flow or phase. | Pass |
| IV. Audit | Every second pass is logged (pause, ids, outcome), counted (`retried`, `recovered`), written to the report and shown in the weekly summary. | Pass |
| V. LGPD | No personal data is added. The report holds counts and times, and the log holds Lattes ids, as today. | Pass |
| Data Integrity 2 (idempotency) | A recovered curriculum is processed like any download, so an unchanged one is skipped by spec 021. A curriculum rejected twice changes nothing, as today. | Pass |
| Data Integrity 5 (replace only after success) | The second pass replaces a cached copy only with a real curriculum page, through the existing `cache/.refresh/` swap. | Pass |
| Data Integrity 6 (provenance) | The download date is recorded only on success; a rejected curriculum keeps its old date, or has none. | Pass |
| Quality gate | New tests cover every rule. With the second pass off, the older tests pass unchanged; only the input-limit assertion changes, from 10 to 25 (research R6). The workflow keeps calling Makefile targets. | Pass |

Re-check after Phase 1: still Pass. No new port is needed: the retry
decision has no I/O, and the report stays a flows-level concern.

## Project Structure

### Documentation (this feature)

```text
specs/025-lattes-captcha-retry/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R8
├── data-model.md        # settings, the two passes, counts, report entry
├── quickstart.md        # how to try it locally and on the fork
├── contracts/
│   ├── access-check-retry.md  # the download functions and their rules
│   └── settings-and-report.md # environment, Makefile, workflow, report, summary
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/core/logic/
├── access_check_retry.py  # NEW: AccessCheckRetrySettings, access_check_retry_settings()
└── raw_rotation.py        # counts_line appends retried= recovered= when present

src/flows/
├── portal_stops.py        # record_access_check_retry(), read_access_check_retries(); record_portal_stop keeps other keys
├── lattes/
│   └── download.py        # AccessCheckPage; access_checked output lists; second pass in rotate_lattes_downloads
└── pipelines/
    └── weekly_orchestrator.py # one summary line and one Telegram line per retries entry

Makefile                     # LATTES_RETRY_WORKERS, LATTES_RETRY_PAUSE_MIN
.github/workflows/weekly-etl.yml # 2 dispatch inputs passed to make weekly-flows

tests/
├── conftest.py                       # autouse: HORIZON_LATTES_RETRY_WORKERS=0
├── test_access_check_retry.py        # NEW: settings
├── test_lattes_access_check_retry.py # NEW: the second pass
├── test_portal_stops_report.py       # the retries key; stops keep it
├── test_weekly_orchestrator.py       # summary and Telegram lines
└── test_weekly_etl_workflow.py       # 2 inputs, the Makefile variables, limit 25
```

**Structure Decision**: follow spec 024's split.
- **Core:** the settings rule, pure.
- **Flows:** the threads, the cache, the manifest and the report file.

The second pass reuses the two download functions instead of adding a third
download path.

## Design Notes

1. **Detection** (`download.py`):
   - Add `class AccessCheckPage(ScriptLattesRuntimeError)`.
   - `_download_lattes_to_cache` and `refresh_one` raise it in place of the
     current `ScriptLattesRuntimeError(... "(access check page)")`, with the
     same message.
   - `prefetch_lattes_cache(..., access_checked=None)` and
     `refresh_lattes_cache(..., access_checked=None)` append the id to that
     list when the exception is an `AccessCheckPage`. It is still logged and
     counted as a failure, as today.
2. **Second pass** (`rotate_lattes_downloads`):
   - **New parameters:** `retry: Optional[AccessCheckRetrySettings] = None`
     (`None` reads the environment) and `sleep=time.sleep`.
   - **After the first pass**, it collects `checked_new` and
     `checked_refresh`, deduplicated and in plan order. If either is
     non-empty, `retry.workers > 0` and the portal was not given up
     (`stop is None or not stop.stopped`):
     1. it logs `Retrying N Lattes curricula that got the access check page,
        after M min, with W worker(s)`;
     2. it waits: `stop.wait(pause_s)` when a stop exists, otherwise
        `sleep(pause_s)`;
     3. it runs `prefetch_lattes_cache(checked_new, workers=retry.workers,
        stop=stop, not_tried=not_tried)`;
     4. it runs `refresh_lattes_cache(checked_refresh, max_workers=
        retry.workers, stop=stop)`.
   - **Recovered:** the ids of the second pass that succeeded.
     - A new curriculum is recovered if its file now exists. Its date is
       recorded and it is removed from `failed`.
     - A refresh is recovered if it is in the refreshed list. Its date is
       recorded and it is removed from `failed`.
     - A curriculum not tried in the second pass moves from `failed` to
       `not_tried`, so the spec 024 counts treat it as untried.
   - **Counts:** `counts = download_counts(plan, failed, not_tried)`; then,
     if a second pass ran, `counts["retried"]`, `counts["recovered"]` and
     `counts["retried_ids"]`.
   - **Report:** `record_access_check_retry("lattes", entry)` with the
     counts, the pause, the workers and the time it took.
   - **Order:** the manifest is saved, `counts_line` logged and
     `record_portal_stop` called after both passes, as today after the first.
3. **Counts line** (`raw_rotation.counts_line`): it appends
   ` retried={retried} recovered={recovered}` when `retried` is in the counts.
4. **Report** (`portal_stops.py`):
   - **`record_access_check_retry(source, entry)`:** sets
     `retries[source]` and keeps `stops`.
   - **`read_access_check_retries()`:** returns `{}` when the file or the
     key is missing.
   - **`record_portal_stop`:** it now reads the whole file and keeps the
     keys it does not own. Neither function ever raises.
5. **Orchestrator**: after the stop lines, one line per retries entry, in
   the log (English) and in `_notify` (Portuguese) (contract). The exit code
   does not change.
6. **Settings**: `access_check_retry_settings(env)` returns
   `AccessCheckRetrySettings(workers, pause_s)`. A blank value means the
   default, and an invalid one is logged and replaced by the default; it
   never raises. `workers == 0` means off.

## Validation

1. **Unit and flow tests** (research R7), then the full suite. Expected: the
   same 6 failures as before (spec 024 report, section 3), plus the new
   tests passing.
2. **Local Lattes download.** Back up `cache/`,
   `data/raw/lattes/download_manifest.json` and `db/horizon.db` first. Then
   run `make ingest-lattes-download`:
   - with a short pause (`LATTES_RETRY_PAUSE_MIN=1`), on a cache where some
     curricula are missing, to get new requests;
   - or as part of a weekly.

   Check the `retried=`/`recovered=` counts in the log and the `retries`
   entry in `data/reports/portal_stops.json`.
3. **Fork dispatch with the defaults.** It confirms that GitHub accepts the
   11 inputs and shows `retried`/`recovered` in a CI rotation. The summary
   line appears only if some page was rejected.
4. **Fork dispatch with `lattes_retry_workers=0`.** The output must match a
   run without this feature: no `retried=` and no line.
5. **Report.** `docs/reports/<date>-lattes-captcha-retry-validation.md`.

Ask the maintainer before each fork dispatch. Nothing goes upstream before
the maintainer's manager validates.

## Complexity Tracking

No constitution violations to justify.
