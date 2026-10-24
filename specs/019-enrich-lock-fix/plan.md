# Implementation Plan: Enrichment Survives Cross-Type Title Collisions

**Branch**: `022-enrich-lock-fix` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/019-enrich-lock-fix/spec.md`

## Summary

`enrich_projects` aborts in the CI weekly when a new project document has the
title of an existing initiative of another type. The duplicate check only knows
research project names. The refused insert leaves the SQLite write lock held,
and the next tracking write, made on another connection, fails with
`database is locked`. The plan has three parts, all in
`src/core/logic/project_enrichment.py`:

1. **All-types duplicate check** (US1). `_ingest_new` seeds its set of taken
   names with the normalized names of **every** initiative, not only the
   research projects in `name_index`. A matching document is counted in
   `skipped_duplicate`, as same-type duplicates already are.
2. **Release the lock after a failed row** (US2). When `_write_row` catches a
   failure, it ends the transaction that `ROLLBACK TO SAVEPOINT` left open, with
   `self._session.commit()`, and logs it. On SQLite the rows before it are
   already committed, so this commits nothing new; it only releases the lock.
3. **Truthful comments** (US3) in `run()` and `_write_row`: on SQLite each row
   is committed when its savepoint is released; an exception does not roll back
   earlier rows.

Both fixes were already tested on copies of the CI database: each alone
completes the phase with identical results ([research.md](research.md) R1–R3).

## Technical Context

**Language/Version**: Python 3.12 in CI; 3.14 locally.

**Primary Dependencies**: SQLAlchemy (2.0.x locally, 2.1.x in CI), pysqlite (standard library), `eo_lib` (`Initiative`, `InitiativeController`, unchanged), loguru. No new dependency.

**Storage**: SQLite `db/horizon.db`, rebuilt by every weekly. No schema change.

**Testing**: pytest on a temporary SQLite **file** (two sessions, so the lock is real), in the style of `tests/test_project_enrichment_db.py`; replay of the phase on a copy of the CI run 40002646510 database; replay on a local pre-enrichment database for equivalence.

**Target Platform**: Linux, locally and on GitHub Actions `ubuntu-latest`.

**Project Type**: Batch ETL (Prefect flow `enrich_projects`, one weekly phase subprocess).

**Performance Goals**: None. The extra query reads ~11 700 initiative names once per phase (milliseconds).

**Constraints**:
- Third-party libraries unchanged.
- Identical output when no collision or row failure happens.
- Dry run writes nothing (it never calls `_write_row`, verified).
- Docker untouched.

**Scale/Scope**: ~320 project documents, ~11 700 initiatives, tens of new initiatives per run.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment | Result |
|---|---|---|
| I. Ports & Adapters | The change stays in `src/core/logic/project_enrichment.py`, which already owns its session through `InitiativeController`. No adapter import is added. | Pass |
| II. Domain-First Data Modeling | No entity or export change. A cross-type duplicate is skipped, not redefined. | Pass |
| III. Prefect Flow Orchestration | `enrich_projects_flow` unchanged; its Telegram hooks unchanged. | Pass |
| IV. Audit-Driven Data Quality | Skipped duplicates keep being counted in `skipped_duplicate`; failed rows keep being logged and counted. The replays compare initiatives, enrichment payloads and tracking records. | Pass |
| V. LGPD Compliance | No new output; the `before_flush` anonymization hook still runs on created initiatives. | Pass |
| Data Integrity & Clean-State | The phase keeps rebuilding from a reset database each week. | Pass |
| Quality Gates | black, isort, flake8 on changed files; full pytest with no new failures (6 pre-existing). | Pass |

**Post-design re-check**: Pass.

## Project Structure

### Documentation (this feature)

```text
specs/019-enrich-lock-fix/
├── plan.md              # This file
├── research.md          # Phase 0: evidence and decisions
├── data-model.md        # Phase 1: what changes in the phase's state
├── quickstart.md        # Phase 1: tests and replays
├── contracts/
│   └── enrichment-writes.md   # Phase 1: behaviour of _ingest_new and _write_row
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/core/logic/project_enrichment.py      # _ingest_new (all-types names), _write_row
                                          # (release after failure), run() comments
tests/test_project_enrichment_db.py       # + cross-type duplicate test (dry run)
tests/test_project_enrichment_lock.py     # new: real SQLite file, two sessions:
                                          #   failed row releases the lock,
                                          #   earlier rows kept
docs/backlog.md                           # TD-020 outcome
docs/reports/2026-10-XX-enrich-lock-validation.md   # replays and tests
```

**Structure Decision**: Single project. One module changes; tests extend the
existing enrichment DB tests and add one file for the two-connection lock case,
which needs a real database file.

## Complexity Tracking

No violations to justify.
