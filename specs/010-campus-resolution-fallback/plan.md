# Implementation Plan: Campus Resolution — SigPesq Execution Campus + Advisorship Fallback

**Branch**: `010-campus-resolution-fallback` | **Date**: 2026-09-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/010-campus-resolution-fallback/spec.md`

## Summary

Reduce the 31.4% of exported researchers with `campus: null` through two changes
that do not touch the database schema or the shared domain package.

1. **Persist the execution campus stated by SigPesq.** The value is already
   parsed into `campus_name` by both SigPesq mapping strategies, but
   `ProjectLoader` only forwards it to `link_research_group`, so it is dropped
   whenever the row has no research group. It will instead be resolved to a
   campus id and recorded as an **attribute assertion** (`execution_campus_id`,
   `execution_campus_name`) on the initiative or advisorship, using the tracking
   write path already invoked a few lines below in the same method.
2. **Add a supervisor fallback tier to the export resolver.** After the map of
   directly-evidenced campuses is built, a second pass gives every person with
   no direct evidence the campus of the `Supervisor` members of the advisorships
   they belong to. The pass reads only from the frozen direct map, so inference
   never feeds inference and direct evidence always wins.

The resolver additionally learns to read the new assertions as direct evidence
for the initiative/advisorship and for the people on its teams. Its tie-break is
already deterministic (`-count`, campus name, campus id) and stays as it is,
pinned by a new regression test.

## Technical Context

**Language/Version**: Python 3.14 (project venv at `.venv`)

**Primary Dependencies**: SQLAlchemy (raw `text()` queries in the resolver),
Prefect (flow orchestration), pandas + openpyxl (SigPesq report reading),
loguru, `research-domain` (external canonical entity package — read-only for
this feature)

**Storage**: SQLite at `db/horizon.db`; canonical JSON and Parquet artifacts
under `data/exports/`

**Testing**: pytest (`tests/`), with integration tests under
`tests/integration/`; gate is `make ci-check` (flake8, black, isort, mypy,
pytest)

**Target Platform**: Linux; runs both locally and in the weekly Prefect pipeline

**Project Type**: Single-project ETL service (ports & adapters)

**Performance Goals**: The resolver's load phase adds at most two aggregate
queries over `advisorship_members` (6,338 rows) and `attribute_assertions`;
the whole `export_canonical` phase must stay inside its existing 1,800 s budget
in the weekly orchestrator.

**Constraints**:

- No migration to `db/horizon.db` and no change to `research-domain`.
- The supervisor fallback must work against an existing database with no
  re-ingestion (FR-011).
- Campus attribution must be deterministic across runs (SC-005).
- No person who has a campus today may lose it (SC-004).

**Scale/Scope**: 9,806 persons, 4,096 initiatives (3,669 projects + 427
advisorships), 3,169 advisorships, 6,338 advisorship memberships, 23 campuses.

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design.*

| Principle | Verdict | Notes |
|-----------|---------|-------|
| I. Ports & Adapters | **PASS** | All edits land in `src/core/logic/`. No adapter is imported from core logic; the loader keeps receiving its controllers from the flow layer as it does today. |
| II. Domain-First Data Modeling | **PASS** | No new domain entity and no change to `research-domain`. The execution campus is stored as an ETL-side tracking assertion, and campus itself stays the existing organizational unit. |
| III. Prefect Flow Orchestration | **PASS** | No new entry point. Behaviour changes inside `ProjectLoader` and `ExportCampusResolver`, both already driven by the existing `sigpesq` ingestion flows and the `export_canonical` flow. |
| IV. Audit-Driven Data Quality | **PASS** | The chosen storage *is* the audit trail: every attributed execution campus is an `attribute_assertion` carrying its `source_record_id` and `selection_reason`. Task list includes a campus-coverage audit check. |
| V. LGPD Compliance by Default | **PASS** | Campus is institutional, not personal, data. No new PII enters any export; no e-mail, CPF or phone is read by this feature. |
| Data Integrity & Clean-State Ingestion | **PASS** | No new source of truth. Everything remains re-derivable from `make db-reset` plus the ingestion flows. |
| Development Workflow & Quality Gates | **PASS** | `make ci-check` must pass; new unit tests accompany both changes. |

**Post-Phase-1 re-check**: unchanged — the design in `data-model.md` introduces
no new table, no new adapter, and no new flow. **No violations, so the
Complexity Tracking table below stays empty.**

## Project Structure

### Documentation (this feature)

```text
specs/010-campus-resolution-fallback/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output — R1..R7 decisions
├── data-model.md        # Phase 1 output — entities, assertions, evidence model
├── quickstart.md        # Phase 1 output — how to run and verify
├── contracts/
│   └── campus-resolution.md   # Behavioural contract of the resolver
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
src/core/logic/
├── project_loader.py              # CHANGED: resolve + assert execution campus
├── export_campus_resolver.py      # CHANGED: read assertions, add supervisor tier
└── strategies/
    ├── sigpesq_excel.py           # CHANGED: guard against "Campus X" duplicates
    ├── sigpesq_projects.py        # UNCHANGED: already maps CampusExecucao
    └── sigpesq_advisorships.py    # UNCHANGED: already maps CampusExecucao/Campus

src/tracking/
└── recorder.py                    # UNCHANGED: record_attribute_assertions reused

tests/
├── test_export_campus_resolver.py # NEW: tiers, precedence, no-chaining, ties
├── test_project_loader_campus.py  # NEW: assertion written with/without a group
└── test_sigpesq_campus_strategy.py# NEW: name normalization, no duplicate campus

src/scripts/
└── audit_campus_coverage.py       # NEW: reports null-campus share before/after
```

**Structure Decision**: Single-project layout, unchanged. The feature is a
behavioural change to two existing core-logic classes plus a guard in one
strategy; it introduces no new package, adapter, or flow.

## Implementation Phases

### Phase A — Supervisor fallback (independent, ships first)

Delivers User Story 1 on its own, against the current database, with no
re-ingestion. Touches only `export_campus_resolver.py`. Verified by re-running
the canonical export and comparing null-campus counts.

### Phase B — Execution campus persistence

Delivers User Story 2. Touches `project_loader.py` and the campus strategy
guard, then teaches the resolver to read the resulting assertions. Requires
re-ingesting the SigPesq reports already present in `data/raw/`.

### Phase C — Precedence, determinism, and audit

Delivers User Story 3: the explicit direct-vs-inferred layering, a regression
test pinning the existing deterministic tie-break, and the coverage audit script
that proves SC-001 through SC-006.

## Complexity Tracking

> No Constitution Check violations. This table is intentionally empty.
