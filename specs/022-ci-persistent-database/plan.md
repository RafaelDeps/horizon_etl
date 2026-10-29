# Implementation Plan: Persistent Database Between GitHub Actions Weekly Runs

**Branch**: `025-ci-persistent-database` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/022-ci-persistent-database/spec.md`

## Summary

Every GitHub Actions weekly run starts on an empty runner and rebuilds the
database (1 h 38 min on 2026-10-29), although spec 021 made the database
persistent and incremental. The workflow already uploads the database and
`data/` as an artifact at the end of each run; this spec restores it at the
start of the next run.

A new operational module, `src/scripts/restore_weekly_artifact.py`, runs as one
workflow step after the virtual environment is ready and before
`make weekly-flows`:

1. It finds the newest successful weekly run of the same branch whose artifact
   has not expired.
2. It downloads that artifact with the runner's `gh` CLI.
3. It undoes any compression of restored files.
4. It checks the database with `PRAGMA quick_check`.
5. It moves `db/horizon.db`, `data/raw` and `cache/` into place.

Any failure ends as "rebuild" with a reason, never as a failed step. The
workflow adds `cache/` to the artifact, raises its retention to 90 days, stops
compressing `data/raw`, writes the outcome to the job summary, and gains a
`fresh_database` dispatch input to force a rebuild. `make weekly-flows`
(`make db-ensure`, migrations, rule-version guard) then works exactly as on a
local kept database.

## Technical Context

**Language/Version**: Python 3.12 in CI (`actions/setup-python`), 3.14 locally;
POSIX shell in the workflow.

**Primary Dependencies**: standard library only (`sqlite3`, `subprocess`,
`zipfile`, `shutil`, `json`); the GitHub CLI `gh` preinstalled on
`ubuntu-latest` (CI only); existing `loguru` for logging.

**Storage**: `db/horizon.db` (SQLite, 318 MB), `data/raw/` (223 MB), `cache/`
(66 MB), carried by the `weekly-etl-artifacts` artifact (366 MB compressed).

**Testing**: pytest; the module is tested on temporary folders with a fake
`gh` (a script on `PATH` that returns recorded JSON), so no network is used.

**Target Platform**: GitHub Actions `ubuntu-latest` runner; the same module
runs locally on an artifact folder or zip for the simulation (FR-012).

**Project Type**: ETL pipeline (Prefect flows) plus its CI workflow.

**Performance Goals**: restore in under about 3 min (download plus
`quick_check`); a restored run on unchanged sources takes at most 60% of a
rebuild run (SC-001, a reference target).

**Constraints**:
- never fail the run because of the restore (FR-003);
- no new secret, no external service, no Docker change, third-party libraries
  unchanged;
- only artifacts of this repository's own weekly runs (FR-010).

**Scale/Scope**: one workflow file, one new module with its tests, one make
target, documentation. No ETL phase changes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Ports & Adapters | No core logic changes; the module is an operational script in `src/scripts/` that moves files and reads the database. Nothing in `src/core/logic/` imports it. | Pass |
| II. Domain-First Data Modeling | No entity, table or export changes (FR-014). | Pass |
| III. Prefect Flow Orchestration | The restore ingests nothing: it places the files a previous flow run produced, before the flows start. Scripts in `src/scripts/` "may read from DB/artifacts". All ingestion stays in the existing flows and their Telegram hooks. | Pass |
| IV. Audit-Driven Data Quality | Every run records its restore outcome (job summary and `data/reports/restore_outcome.json`); the spec 021 document report is unchanged. | Pass |
| V. LGPD | No personal data is read or written by the restore. The database keeps being written only with the CI key (FR-010); the outcome file holds run ids, dates, sizes and reasons only. | Pass |
| Data Integrity 1 (persistent DB, also in GitHub Actions) | This spec is what makes rule 1 true in CI. | Pass |
| Data Integrity 3 (re-creatable; rebuild on rule change) | Fallback to a rebuild in every failure case; `fresh_database` forces one; the rule-version guard of spec 021 runs on the restored database. | Pass |
| Data Integrity 5 (raw inputs) | SigPesq reports are still cleared before their download; per-item caches (`cache/`, project PDFs) are kept, as the rule allows. | Pass |
| Quality gate (`make ci-check`, Makefile entry points) | New tests in `tests/`; the workflow calls `make restore-weekly`, not a bare `python`. | Pass |

No violation, so Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/022-ci-persistent-database/
├── plan.md              # This file
├── research.md          # Phase 0: R1-R10
├── data-model.md        # Phase 1: run, artifact, restore outcome
├── quickstart.md        # Phase 1: local simulation and the two fork dispatches
├── contracts/
│   ├── restore-cli.md       # restore_weekly_artifact.py: modes, exit codes, outcome file
│   └── workflow-steps.md    # the weekly-etl.yml changes, step by step
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
.github/workflows/weekly-etl.yml      # restore step, GH_TOKEN, fresh_database input,
                                      # cache/ in the artifact, retention 90,
                                      # compression skips data/raw
src/scripts/restore_weekly_artifact.py # find, download, unzip, check, place, report
Makefile                              # restore-weekly target
tests/test_restore_weekly_artifact.py # selection, fallback reasons, unzip,
                                      # check, placement, summary (fake gh)
tests/test_weekly_etl_workflow.py     # workflow assertions (step order, inputs,
                                      # artifact paths, retention, compression)
docs/flows-and-entrypoints.md         # CI persistence section
```

**Structure Decision**: single project; the module lives next to the other
operational utilities in `src/scripts/` (e.g. `save_horizon_id_history.py`),
and the workflow keeps calling Makefile targets.

## Phase Notes

- **Phase 0** ([research.md](research.md)): no open questions. R2 widens the
  description's `--limit 1` to the newest successful run with a non-expired
  artifact (the spec's edge case). R3 stops compressing `data/raw` and adds an
  unzip safety net for older artifacts. R8 adds the `fresh_database` input.
- **Phase 1**: [data-model.md](data-model.md),
  [contracts/restore-cli.md](contracts/restore-cli.md),
  [contracts/workflow-steps.md](contracts/workflow-steps.md),
  [quickstart.md](quickstart.md).
- **Constitution re-check after design**: unchanged, all pass. The only new
  write is `data/reports/restore_outcome.json` (ids, dates, sizes, reasons; no
  personal data).

## Complexity Tracking

No constitution violation to justify.
