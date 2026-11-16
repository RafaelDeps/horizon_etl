# Implementation Plan: Stable enrichment strategy for document-created projects

**Branch**: `032-stable-enrichment-strategy` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/032-stable-enrichment-strategy/spec.md`

## Summary

On the run after a project PDF creates an initiative, the same PDF finds that
initiative by title and the enrichment note's `match_strategy` changes from
`new_from_document` to `title_exact`, rewriting 37 notes and logging 37
changes over unchanged inputs (TD-033). The fix decides the stored strategy in
`build_enrichment` with a pure function, `strategy_from_prior`: when the
resolved origin is `new_from_document`, the current document is the creating
one (same code, or same file without a code) and it matched by title, the note
keeps `new_from_document`. Notes that already drifted are repaired by the next
run. `_enrich_winners` also skips the UPDATE of a note whose canonical payload
did not change. Per-run tracking and the phase counters keep the real match.

## Technical Context

**Language/Version**: Python 3.12 in GitHub Actions; the local `.venv` runs 3.14

**Primary Dependencies**: SQLAlchemy (sessions and raw `text()` SQL), pydantic (`EnrichmentPayload`), Prefect (the `enrich_projects` flow, unchanged)

**Storage**: SQLite `db/horizon.db`, column `initiatives.enrichment_json`; tracking tables `entity_matches` and `entity_change_logs`

**Testing**: pytest (`tests/test_project_enrichment.py` for the pure logic, `tests/test_project_enrichment_db.py` for the loader on SQLite)

**Target Platform**: Linux, local runs and the GitHub Actions weekly workflow

**Project Type**: ETL pipeline (Prefect flows + domain logic)

**Performance Goals**: none new; skipping unchanged UPDATEs makes the phase slightly cheaper

**Constraints**: no new setting; no Docker change; no change to third-party libraries; changes only in `src/core/logic/project_enrichment.py` and its tests

**Scale/Scope**: about 280 enriched initiatives per run, 37 of them created from a document

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Ports & Adapters | PASS | The rule is pure logic in `src/core/logic/`; the loader's existing SQL path is unchanged in kind. |
| II. Domain-First Data Modeling | PASS | No entity or export shape changes; only the value of one note field. |
| III. Prefect Flow Orchestration | PASS | No new flow or script; the repair (R4) happens inside the normal `enrich_projects` run. |
| IV. Audit-Driven Data Quality | PASS | Per-run `entity_matches` still records the real strategy; the change log stops recording false changes. |
| V. LGPD Compliance | PASS | No personal data involved. |
| Data Integrity: 2. Idempotency | PASS (goal) | This feature removes a known violation: second pass rewrites 0 notes. |
| Data Integrity: 3. Re-creatable | PASS (goal) | The rebuild and incremental notes become equal. |
| Development Workflow | PASS | New tests before the change; full suite, black, isort, flake8 on touched files. |

Re-check after Phase 1: PASS, no violation to justify.

## Project Structure

### Documentation (this feature)

```text
specs/032-stable-enrichment-strategy/
├── plan.md              # This file
├── research.md          # Phase 0 (R1-R6)
├── data-model.md        # Phase 1: the enrichment note and the rule
├── quickstart.md        # Phase 1: how to validate locally
├── contracts/
│   └── enrichment-strategy.md   # Phase 1: rule contract of strategy_from_prior
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/core/logic/
└── project_enrichment.py
    ├── strategy_from_prior()        # new, pure (R1-R4)
    ├── build_enrichment()           # uses it for match_strategy
    └── ProjectEnrichmentLoader._enrich_winners()  # skips unchanged UPDATE (R5)

tests/
├── test_project_enrichment.py       # rule tests at payload level
└── test_project_enrichment_db.py    # loader: second run, repair, other document

docs/
└── backlog.md                       # TD-033 marked Done
```

**Structure Decision**: single project; the change stays in the enrichment
module and its two existing test files. Two existing assertions that require
`title_exact` on the creating document's second run
(`test_build_enrichment_carries_origin_and_review_forward`,
`test_rerun_does_not_shrink_the_review_backlog`) encode the TD-033 behaviour
and are updated to the new rule.

## Complexity Tracking

No constitution violation to justify.
