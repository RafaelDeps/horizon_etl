# Implementation Plan: Team Lookup Index for the Lattes Ingestion Phases

**Branch**: `018-team-lookup-index` | **Date**: 2026-10-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/015-team-lookup-index/spec.md`

## Summary

`TeamSynchronizer.ensure_team` currently reloads the whole team register through
the ORM for every record. It eagerly joins members, persons and roles: about
3.7 M objects and 1.5–1.9 s per call. It then re-normalises every name. That one
step is 76–84% of the two Lattes phases, which took 333 of the 484 minutes of the
2026-10-22 weekly run.

The plan has four parts:

1. **Team lookup.** The synchroniser builds a lookup once, the first time it is
   used: a single `SELECT id, name FROM teams ORDER BY id` on the controller's
   real SQLAlchemy session, keyed by the existing `normalize_text`, lowest id
   first. It answers each record with one dictionary probe. On a miss it does
   one primary-key range read (`id > max_id`), to pick up teams created
   elsewhere in the process (research groups are rows of `teams`), and only then
   creates. Created teams are merged in; failed creations leave the lookup
   untouched. Without a real session (mocked tests), it builds the lookup from a
   single `get_all()`.
2. **One loader for advisorships.** `lattes_advisorships` builds one
   `ProjectLoader` per phase and swaps `mapping_strategy` per CV, as
   `lattes_projects` already does.
3. **Observability.** A per-loader INFO summary of the lookup counters, plus a
   per-CV INFO duration line in the Lattes loops.
4. **Verification.** Unit tests (FR-012), a controlled replay of `sigpesq`
   persistence and both Lattes phases with base vs feature code (SC-004), and a
   full timing run (SC-001, SC-002, SC-003, SC-005).

Details and rejected alternatives are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 in CI (`.github/workflows/weekly-etl.yml`); Python 3.14 in the local venv. The code must run on both.

**Primary Dependencies**: SQLAlchemy (via `eo_lib` / `libbase`), Prefect 3.6.23 (flows/tasks), loguru. No new dependency.

**Storage**: SQLite (`db/horizon.db`; a fresh file every CI run). Tables read: `teams(id, name)`. No schema change.

**Testing**: pytest with mocks for unit tests (`tests/test_team_synchronizer.py`, `tests/test_team_management.py`, plus a new flow test). Controlled replay and timing runs per [quickstart.md](quickstart.md).

**Target Platform**: Linux, both on GitHub-hosted `ubuntu-latest` and on the maintainer's machine.

**Project Type**: Batch ETL (Prefect flows run as subprocess phases by `weekly_orchestrator`).

**Performance Goals**:
- `lattes_projects` < 20 min (81 today);
- `lattes_advisorships` < 20 min (252 today);
- per-CV time flat across the phase (last 50 / first 50 ≤ 1.5×);
- full run < 4 h 02 min.

**Constraints**:
- No change to external libraries (`eo_lib`, `research_domain`, `libbase`, `dgp_cnpq_lib`, …).
- Identical produced entities for identical inputs.
- No dependency on state persisted between runs.
- SigPesq collection unchanged and sequential.

**Scale/Scope**:
- ~11 000 teams at the end of a run.
- ~13 000 team lookups in the Lattes phases plus ~1 300 in `sigpesq`.
- ~435 CVs.
- Lookup memory: a few MB.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment | Result |
|---|---|---|
| **I. Ports & Adapters** | Changes are in `src/core/logic/team_synchronizer.py` and in `src/flows/`. Core logic reads through the controller's SQLAlchemy session with plain SQL, the same precedent as `load_researcher_index` in `src/core/logic/researcher_resolution.py`. No import from `src/adapters/` is added to core logic. | PASS |
| **II. Domain-First Data Modeling** | `Team` stays owned by `eo_lib` / `research_domain`. `TeamRef` is an ETL-only transient structure (an in-memory lookup result, never persisted or exported), which this principle explicitly allows with justification (see Complexity Tracking). | PASS (justified) |
| **III. Prefect Flow Orchestration** | No new ingestion path. All changes run inside the existing flows and tasks, and the Telegram state hooks are untouched. The replay harness for validation wraps the existing persist tasks in a throwaway flow and is not committed. | PASS |
| **IV. Audit-Driven Data Quality** | Adds an audit signal: the per-loader `Team lookup [...]` summary (hits, creations, refreshes, refresh finds, failures). Equivalence is proven by a controlled replay with count and link-set comparison. `make etl-report` behaviour is unchanged. | PASS |
| **V. LGPD Compliance** | New INFO log lines carry counters, Lattes IDs and timings only: no person names, CPF, phone numbers or e-mails. The existing `Created team: <name>` line is unchanged (team names are project titles). Nothing new is written to `data/exports/` or `data/reports/`. | PASS |
| **Data Integrity & Clean-State Ingestion** | Works from a freshly created DB (empty lookup → creations → hits). No persisted cache. | PASS |
| **Quality gates** | `make ci-check` (flake8, black, isort, mypy, pytest) must pass. The flows touched already have tests, and new tests are added for the synchroniser and the advisorships flow. | PASS |

**Post-design re-check (after Phase 1)**: unchanged. All gates PASS.

## Resolved during planning: per-CV duration log level

- FR-014 originally asked for per-CV durations at DEBUG. But the weekly log
  contains **zero DEBUG lines**: `logs/weekly_run2_20261021.log` has 63 326
  lines and none at DEBUG.
- The cause: `dgp_cnpq_lib/logger.py`, imported by `app.py` through
  `src.flows.cnpq.groups`, runs `logger.remove(); logger.add(sys.stderr,
  level="INFO")` at import time. That sets the process-wide loguru threshold to
  INFO, and the library cannot be changed (FR-010).
- **Decision (2026-10-22, user):** emit the per-CV duration line at **INFO**
  (~870 lines per run against ~63 000 today). FR-014 and the clarifications in
  the spec were updated, and SC-003 is checked from the default run log.

## Project Structure

### Documentation (this feature)

```text
specs/015-team-lookup-index/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1–R11
├── data-model.md        # Phase 1: TeamRef, lookup state, transitions, log records
├── quickstart.md        # Phase 1: tests, controlled replay, timing run
├── contracts/
│   └── team-synchronizer.md   # Internal interface contract
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
src/
├── core/logic/
│   ├── team_synchronizer.py     # CHANGED: TeamRef, lazy lookup, incremental refresh,
│   │                            #          counters, log_lookup_summary()
│   ├── initiative_linker.py     # unchanged (callers use team.id only)
│   └── project_loader.py        # unchanged (mapping_strategy is already swappable)
└── flows/
    ├── lattes/
    │   ├── advisorships.py      # CHANGED: one ProjectLoader per phase; optional
    │   │                        #          project_loader param; per-CV timing; summary
    │   └── projects.py          # CHANGED: per-CV timing line; summary at end
    └── sigpesq/
        ├── projects.py          # CHANGED: summary at end of persist_projects
        └── advisorships.py      # CHANGED: summary at end of persist_advisorships

tests/
├── test_team_synchronizer.py               # EXTENDED: FR-012 lookup cases
├── test_team_lookup_sql.py                 # NEW: sql-mode lookup (in-memory SQLite session)
├── test_team_management.py                 # unchanged; must keep passing
└── test_lattes_advisorships_loader_reuse.py  # NEW: one ProjectLoader per run,
                                              #      per-CV strategy swap
```

**Structure Decision**: The existing single-project layout. Business logic stays
in `src/core/logic/`, orchestration changes stay in `src/flows/`, tests stay in
`tests/`. No new modules are needed apart from the new test file.

## Implementation outline (for `/speckit-tasks`)

1. **`TeamRef` and lookup state** in `team_synchronizer.py`:
   - session detection (`isinstance(..., sqlalchemy.orm.Session)`);
   - `_load()` in sql and controller modes;
   - `_merge(rows)` (ascending id, first writer wins, advances `max_id`);
   - `_refresh()` (`id > max_id`);
   - counters.
2. **Rewrite `ensure_team`** per the contract: probe → refresh on miss (sql
   mode) → create → merge → `TeamRef`. Same warning and info messages as today.
3. **Add `log_lookup_summary(label)`.**
4. **Unit tests** for every FR-012 case, using a fake controller in controller
   mode and an in-memory SQLite session in sql mode. Keep the existing mocks.
5. **Advisorships flow**: build the loader once; pass it to the task; set
   `mapping_strategy` per CV; keep `project_loader=None` standalone behaviour;
   per-CV timing; summary at the end.
6. **Projects flow**: per-CV timing; summary at the end.
7. **SigPesq persist tasks**: summary at the end of `persist_projects` and
   `persist_advisorships`.
8. **Flow test** asserting one `ProjectLoader` per advisorships run and the
   per-CV strategy swap.
9. **`make ci-check`.**
10. **Controlled replay** (quickstart §2) and the equivalence report.
11. **Full timing run** (quickstart §3) and the SC report.
12. **Conditional (R9)**: if a Lattes phase still exceeds ~15 min, wrap the large
    task parameters with `prefect.utilities.annotations.quote`, then re-measure.
13. **Follow-ups, not in this feature**:
    - revisit the ×10 phase ceilings in `weekly_orchestrator.py`;
    - CNPq concurrency;
    - an upstream note on `lazy="joined"` in `eo_lib` (`Team.members`,
      `TeamMember.person`).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| `TeamRef`, an ETL-only transient structure (constitution II) | Holding ORM `Team` entities for ~11 000 teams keeps them in the session's identity map with their eager collections. That is the cost being removed, and it is the out-of-memory cause noted in `project_loader.py`. | Returning the ORM entity via `get_by_id` on every hit costs a query plus a joined load per record, and no caller uses anything but `id`. |
| Plain SQL on the controller's session from core logic | It is the only way to read `id, name` without the eager joins defined in `eo_lib`, which cannot be modified (FR-010). | An ORM query with `noload` options still builds entities in the identity map. Changing `lazy=` in `eo_lib` is forbidden. |
