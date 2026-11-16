# Implementation Plan: SQLite WAL Journaling for the ETL Database

**Branch**: `021-sqlite-wal-journaling` | **Date**: 2026-10-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/018-sqlite-wal-journaling/spec.md`

## Summary

The Lattes phases spend 63% (`lattes_projects`) and 34% (`lattes_advisorships`)
of their time committing to SQLite, because `libbase` commits after every
record and each commit waits for the disk. A benchmark that only changed the
connection settings halved both phases (46.2 → 23.3 min) with identical data.
The plan has four parts:

1. **Connection settings.** A new module, `src/adapters/database/sqlite_settings.py`,
   registers one SQLAlchemy `connect` listener on the `Engine` class. On every
   new SQLite DBAPI connection it runs `PRAGMA journal_mode=WAL` and
   `PRAGMA synchronous=NORMAL`. It does nothing for other databases. It is
   installed once per process from `app.py`, next to the existing
   `install_lgpd_session_hooks()`, so every DB-writing weekly phase (all of them
   run as `python app.py <phase>`) gets it, including the engines created by
   `eo_lib` and `research_domain`.
2. **Self-contained final file.** At the end of `run_weekly`, after the last
   phase, `finalize_sqlite_database(DATABASE_URL)` checkpoints the log into the
   main file (`PRAGMA wal_checkpoint(TRUNCATE)`) and switches the file back to
   the rollback journal (`PRAGMA journal_mode=DELETE`). `db/horizon.db` then
   holds every row and opens with no companion files, so the CI artifact is
   complete.
3. **Clean reset.** `make db-clean` also removes `db/horizon.db-wal` and
   `db/horizon.db-shm`, so a stale log never meets a new database.
4. **Validation and the lock investigation.** A controlled replay of both Lattes
   phases from an offline pre-Lattes snapshot, old code against new code, on
   disk. A full local weekly run. A separate investigation of the
   `enrich_projects` `database is locked` failure, which reading the code
   suggests WAL will **not** fix (two writers in one process; see research R6).

Evidence and rejected alternatives are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 in CI; 3.14 locally.

**Primary Dependencies**: SQLAlchemy (2.0.x locally, 2.1.x in CI, unpinned), the standard-library `sqlite3` module (SQLite 3.46.1 locally), loguru. No new dependency.

**Storage**: SQLite file `db/horizon.db`, rebuilt from scratch by `make weekly-flows`. No schema change.

**Testing**: pytest unit tests on temporary SQLite files and in-memory databases; a controlled replay of the Lattes phases from an offline pre-Lattes snapshot; one full local weekly run.

**Target Platform**: Linux, local disk; GitHub Actions `ubuntu-latest` afterwards.

**Project Type**: Batch ETL (Prefect flows, one subprocess per weekly phase).

**Performance Goals**: `lattes_projects` + `lattes_advisorships` at most 60% of the baseline on the same machine (reference: 50%, 46.2 → 23.3 min). Guidance, not a hard bar.

**Constraints**:
- Third-party libraries (`libbase`, `eo_lib`, `research_domain`) untouched.
- Identical produced data.
- No-op for non-SQLite databases.
- The final `db/horizon.db` must be complete without companion files.
- Docker untouched.

**Scale/Scope**: ~184 000 commits in `lattes_projects` and ~161 000 in `lattes_advisorships` for 435 curricula; growth to thousands of curricula expected.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment | Result |
|---|---|---|
| I. Ports & Adapters | The setting is infrastructure (how the database driver behaves), so it lives in `src/adapters/database/`. `app.py` (the composition root) and `src/flows/pipelines/weekly_orchestrator.py` (a flow-level orchestrator) call it. Nothing in `src/core/logic/` imports it. | Pass |
| II. Domain-First Data Modeling | No entity, schema or export changes. | Pass |
| III. Prefect Flow Orchestration | No new ingestion. The finalize step runs in the weekly orchestrator, which already runs outside Prefect by design (it supervises the phase subprocesses). Telegram hooks unchanged. | Pass |
| IV. Audit-Driven Data Quality | The replay compares counts and by-name rows of the old and new databases. The finalize step logs what it did. | Pass |
| V. LGPD Compliance | The LGPD `before_flush` hook is unaffected (it acts on sessions, the new listener on connections). No new output. | Pass |
| Data Integrity & Clean-State | `make db-reset` keeps rebuilding from scratch, and now also removes the companion files. | Pass |
| Quality Gates | black, isort, flake8 on changed files; full pytest with no new failures (6 pre-existing). | Pass |

**Post-design re-check**: Pass. The design adds one adapter module, two call
sites and one Makefile line.

## Project Structure

### Documentation (this feature)

```text
specs/018-sqlite-wal-journaling/
├── plan.md              # This file
├── research.md          # Phase 0: decisions and evidence
├── data-model.md        # Phase 1: files and states involved
├── quickstart.md        # Phase 1: how to validate (replay, weekly, lock check)
├── contracts/
│   └── sqlite-settings.md   # Phase 1: the module's interface and behaviour
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/
├── adapters/
│   └── database/
│       ├── __init__.py                 # new (empty)
│       └── sqlite_settings.py          # new: install_sqlite_connection_settings(),
│                                       #      finalize_sqlite_database()
└── flows/
    └── pipelines/
        └── weekly_orchestrator.py      # calls finalize_sqlite_database() after the phases

app.py                                  # installs the connection settings at startup
Makefile                                # db-clean also removes -wal / -shm

tests/
├── test_sqlite_settings.py             # new: listener, no-op cases, finalize
└── test_weekly_orchestrator_finalize.py  # new: finalize runs after the phases

docs/
├── flows-and-entrypoints.md            # documents the setting and the finalize step
├── backlog.md                          # TD-018 outcome
└── reports/2026-10-XX-sqlite-wal-validation.md   # replay, weekly timing, lock investigation
```

**Structure Decision**: Single project. The new code is one adapter module
(`src/adapters/database/`), installed from the composition root (`app.py`) the
same way the LGPD session hook already is, and called once from the weekly
orchestrator.

## Complexity Tracking

No violations to justify.
