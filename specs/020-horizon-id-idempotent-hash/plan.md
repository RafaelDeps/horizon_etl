# Implementation Plan: Permanent Horizon Ids and Idempotent Tracking Keys

**Branch**: `023-horizon-id-idempotent-hash` | **Date**: 2026-10-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/020-horizon-id-idempotent-hash/spec.md`

## Summary

Every entity gets a permanent, readable `horizon_id` derived only from source
data. The tracking keys and payload hashes stop depending on database ids and
processing order, and a second run on the same input writes nothing. The
change is additive: existing tables and export files keep their format.
The plan has five parts:

1. **Pure identity module** `src/core/logic/horizon_identity.py`: text
   normalization (reusing `normalize_text`), canonical payload form, hash, the
   id rules per entity type (research R2/R3), candidate ids, collision suffix
   (R4) and `HORIZON_RULE_VERSION`. No I/O.
2. **New weekly phase `assign_horizon_ids`** (a Prefect flow), run after
   `consolidate_duplicates` and before `export_canonical`. It derives all ids
   from the finished database, reconciles them with the id history into
   aliases: upgraded key, rebuild, merge, key corrected (R5–R8). The history
   comes from the previous database's tables when they exist, else from the
   snapshot that `make db-reset` saves before deleting the database, else from
   the published `exports_canonical.zip`. It then writes the new tables and an
   audit report.
3. **Stable tracking keys** at the 9 `record_source_record` call sites (R6),
   with same-CV duplicates kept once, and a canonical `stable_hash`.
   Simulated: keys with more than one hash per run drop from 1 005 to 22, and
   those 22 are resolved by keeping one version.
4. **No-op writes removed** (R9): updates and change logs only when a value
   changes; team membership computed as the union of all documents'
   contributions, so the result no longer depends on the starting state.
5. **Exports and version guard**: two new files in the export package (R12);
   the rule version is stored and compared at weekly start (R11).

**Decided on 2026-10-27 (research R9.3)**: fuzzy person resolution in a
fresh run depends on which persons already exist at that moment, so 25 team
rows change on the first rerun of the 2026-10-24 data. The maintainer accepted
measuring SC-002 as a fixpoint: the second and third passes must be identical,
and the first pass's changes are counted. Person resolution gets a
deterministic tie-break (FR-023a).

Measured on the current database, the id rules produce 149 groups of shared
ids. All of them are rows the database already holds twice for the same thing
(case or accent variants). The suffix rule gives each a distinct, stable id,
and the report lists them.

## Technical Context

**Language/Version**: Python 3.12 in CI; 3.14 locally.

**Primary Dependencies**: SQLAlchemy (2.0.x locally, 2.1.x in CI), pysqlite
(standard library), Prefect, loguru, rapidfuzz (already used by
`PersonMatcher`), `eo_lib` (unchanged). No new dependency.

**Storage**: SQLite `db/horizon.db`. New ETL-owned tables only, created by
`src/db/migrations.py`: `horizon_ids`, `horizon_id_candidates`,
`horizon_id_aliases`, `horizon_merge_log`, `horizon_meta`,
`team_member_contributions` ([data-model.md](data-model.md)). Existing tables
unchanged.

**Testing**: pytest on temporary SQLite files: unit tests for the pure module,
plus scenario tests for rerun idempotency, two rebuilds, merge, upgraded key,
key corrected, collisions and the version guard. Replay of old and new code on
frozen inputs from a reset database. Rerun of the source phases on a populated
copy ([quickstart.md](quickstart.md)).

**Target Platform**: Linux, locally and on GitHub Actions `ubuntu-latest`.

**Project Type**: Batch ETL (Prefect flows run as weekly phase subprocesses).

**Performance Goals**: None set by the spec. `assign_horizon_ids` reads ~63 000
rows and the published history once; expected well under a minute. The
contribution-based team sync and the before/after comparisons add one read per
written entity, which the existing indexes cover.

**Constraints**:
- No existing table changes schema; no existing export file changes fields
  (FR-014, FR-015).
- No CPF, e-mail or phone in any id; the ids never depend on
  `HORIZON_PII_HMAC_KEY` (FR-007, SC-006).
- Third-party libraries unchanged; Docker untouched.
- Must work on a reset database (today's weekly) and on a populated one.

**Scale/Scope**: ~17 100 persons, 354 groups, 11 723 initiatives (8 680 of them
advisorships), 6 736 articles, 2 807 other productions, ~10 000 child items,
11 431 teams, ~2 000 reference rows. 9 tracking call sites. 35 547 source
records per run.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment | Result |
|---|---|---|
| I. Ports & Adapters | The id rules are pure functions in `src/core/logic/`. Reading the database and writing the new tables goes through a store port (`src/core/ports/horizon_id_store.py`) with a SQLite adapter (`src/adapters/database/horizon_id_store.py`); the flow wires them. The consolidators already use `sqlite3` directly, and only gain a call to record merges. | Pass |
| II. Domain-First Data Modeling | No domain entity is redefined. The new tables are ETL-only identity and tracking structures, like `source_records` and `entity_matches`; the justification required for ETL-only structures is in Complexity Tracking. | Pass (justified) |
| III. Prefect Flow Orchestration | `assign_horizon_ids` is a Prefect flow under `src/flows/maintenance/`, with the Telegram state hooks, registered in `app.py` and in the weekly orchestrator. | Pass |
| IV. Audit-Driven Data Quality | `data/reports/horizon_ids_report.json` lists ids per rule, collision groups (149 today), aliases per reason, retired ids and failed relinks. Rerun and rebuild tests are part of validation. | Pass |
| V. LGPD Compliance | Ids and the new export files contain no CPF, e-mail or phone; names and titles are already in the existing exports. Change logs keep the scrubbed values they carry today. | Pass |
| Data Integrity & Persistent Incremental Ingestion (constitution 2.0.0) | Rule 2: keys and hashes come only from source data; idempotency is checked as a fixpoint (SC-002). Rule 3: the database stays re-creatable by `make db-reset` + flows, and the rule version forces a rebuild (FR-024). Rule 4: the published identity history (previous database, its pre-reset snapshot, or the zip) is read only to build aliases, never entity data. Raw inputs are untouched by this spec. | Pass |
| Quality Gates | `make ci-check` (format-check, lint, test) with no new test failures (spec 019 recorded 6 pre-existing failures; recount before starting). The constitution also lists mypy, which the `ci-check` target does not run today; the plan does not add it. | Pass |

**Post-design re-check** (after the 2026-10-27 analysis and constitution 2.0.0): Pass. The design adds tables and files, a flow and a
port. It moves no logic between layers.

## Project Structure

### Documentation (this feature)

```text
specs/020-horizon-id-idempotent-hash/
├── plan.md               # This file
├── research.md           # Phase 0: measurements and decisions (R1–R13)
├── data-model.md         # Phase 1: new tables, rules, state transitions
├── quickstart.md         # Phase 1: tests, rerun, rebuild and replay steps
├── contracts/
│   ├── horizon-id-format.md     # id grammar and rules per entity type
│   ├── export-files.md          # the two new export files
│   └── tracking-keys.md         # source_record_id per tracked type
├── research-scripts/
│   ├── sim_horizon_ids.py       # R2: ids and collisions on a database
│   └── sim_tracking_keys.py     # R6: tracking-key collisions on a database
├── checklists/
│   └── requirements.md
└── tasks.md              # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/core/logic/horizon_identity.py        # new: pure rules, canonical form, hash,
                                          #   candidates, suffix, HORIZON_RULE_VERSION
src/core/logic/horizon_id_assigner.py     # new: derive all ids, reconcile history,
                                          #   write the two export files
                                          #   into aliases, collision report
src/core/ports/horizon_id_store.py        # new: read entities/history, write tables
src/adapters/database/horizon_id_store.py # new: SQLite implementation
src/flows/maintenance/horizon_ids.py      # new: assign_horizon_ids Prefect flow
src/db/migrations.py                      # + migrations for the new tables
src/tracking/recorder.py                  # stable_hash on the canonical form
src/flows/cnpq/groups.py                  # CNPq-id tracking key
src/core/logic/strategies/cnpq_sync.py    # member / research line keys
src/flows/lattes/projects.py              # education / article keys, same-CV
                                          #   duplicates, researcher no-op update
src/core/logic/project_loader.py          # Lattes initiative/advisorship keys,
                                          #   no-op update and change log
src/core/logic/team_synchronizer.py       # contribution-based membership
src/core/logic/person_matcher.py          # deterministic tie-break between equal scores
src/core/logic/initiative_linker.py       # pass the source document key
src/core/logic/person_consolidator.py     # record merges in horizon_merge_log
src/core/logic/reference_consolidator.py  # record merges in horizon_merge_log
src/flows/exports/canonical_data.py       # + tasks for the two new files
src/flows/pipelines/weekly_orchestrator.py# + assign_horizon_ids phase, version guard
app.py                                    # + assign_horizon_ids entry point
src/scripts/save_horizon_id_history.py    # new: snapshot of the id tables before a reset
Makefile                                  # db-reset saves the id history first
.gitignore                                # ignore db/horizon_id_history.json
src/scripts/export_parquet.py             # keep horizon_id columns as text
tests/test_horizon_identity.py            # new: rules, normalization, suffix
tests/test_horizon_ids_flow.py            # new: the Prefect flow end to end
tests/test_horizon_id_assigner.py         # new: history, aliases, rebuild, merge,
                                          #   key corrected, version guard
tests/test_idempotent_rerun.py            # new: same input twice -> no writes
tests/test_team_synchronizer.py           # + multi-document membership
tests/test_export_canonical_data_flow.py  # + new files, existing files unchanged
docs/backlog.md                           # 149 duplicate rows as backlog item
docs/reports/2026-10-XX-horizon-id-validation.md   # measurements of the replay
```

**Structure Decision**: Single project, existing layout. The new logic gets
its own modules (pure rules, assigner, port, adapter, flow). Existing modules
only change at the points listed above.

## Complexity Tracking

| Item | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| ETL-only tables (`horizon_ids`, `horizon_id_candidates`, `horizon_id_aliases`, `horizon_merge_log`, `horizon_meta`, `team_member_contributions`) instead of `research-domain` entities (Principle II) | They describe identity and provenance of ETL output, the same category as the existing tracking tables, not a domain concept | Adding columns to domain tables is forbidden by FR-014 and would change `eo_lib`; a domain entity for "an id of another entity" has no meaning outside this ETL |
