# Implementation Plan: Every professional activity is kept, with the right institution

**Branch**: `034-keep-professional-activities` | **Date**: 2026-11-11 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/034-keep-professional-activities/spec.md`

## Summary

Two defects change the professional activities of a Lattes curriculum on the
way to the database. The ingestion treats as a repeat every activity of a
researcher with the same institution and start year, so 2,923 different
activities are dropped. And the curriculum data arrives with the institution
text cut at each comma, so a name with commas gives a wrong name, acronym and
country: 2,260 rows store "IFES" as the country.

The fix adds one pure module, `src/core/logic/professional_activity_rules.py`,
with two functions. `split_institution` reads name, acronym and country from
the full institution text, from the end. `distinct_activities` removes exact
repeats within a curriculum and drops an item that carries only the
institution when the curriculum has a filled activity there (clarification of
2026-11-11). The parser returns the items after both; the ingestion compares
the 13 stored fields instead of three; the permanent id hashes the fields that
tell two activities apart and keeps the old-rule id as a candidate, so old
ids become aliases where one new row owns them. Because the identity of an
activity changes, `HORIZON_RULE_VERSION` goes from 3 to 4 and the existing
guard of the weekly rebuilds an older database once.

Measured with a prototype over the 435 curricula: about 9,555 rows instead of
7,855, 0 rows with an acronym as the country, 3 collision groups instead of
114 suffixed ids, 5,871 of the 7,855 old ids resolved as aliases.

## Technical Context

**Language/Version**: Python 3.12 in GitHub Actions; the local `.venv` runs 3.14

**Primary Dependencies**: `research-domain` (`ProfessionalActivityController`, `ProfessionalActivity` entity, unchanged), SQLAlchemy session in the ingestion task, Prefect (the `lattes_projects` flow, unchanged), standard library only for the rules; no new dependency

**Storage**: SQLite `db/horizon.db`: `professional_activities` (no schema change); `horizon_ids` / `horizon_id_candidates` / `horizon_id_aliases` / `horizon_meta` (rule version); `source_document_items` (the items a curriculum carries, existing mechanism)

**Testing**: pytest: new `tests/test_professional_activity_rules.py` (contract of the two functions); `tests/test_lattes_parser.py` (parser output); a new ingestion test beside the existing Lattes ingestion tests; `tests/test_horizon_identity.py` and `tests/test_horizon_id_assigner.py` (id key, legacy candidate, aliases); `tests/test_incremental_lattes.py` (incremental equals rebuild, compared on every field); `tests/test_rule_version_guard.py` (a version 3 database needs a reset); `make ci-check` before a merge

**Target Platform**: Linux, local runs and the GitHub Actions weekly workflow

**Project Type**: ETL pipeline (Prefect flows + domain logic)

**Performance Goals**: none new; the rules are string operations over about 13,400 items per run, and the ingestion compares tuples in a dictionary per researcher

**Constraints**: no new setting, Makefile target or workflow input; no Docker change; no change to third-party libraries; no schema change (the table belongs to the domain library); the export shape is unchanged

**Scale/Scope**: 435 curricula, 13,439 activity items, 13,420 with an institution; 7,855 rows become about 9,555; every activity id changes once (rule version 4)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Ports & Adapters | PASS | The rules are pure functions in `src/core/logic/`; the parser (adapter) imports them, never the reverse. The id store adapter only selects more columns. No new port. |
| II. Domain-First Data Modeling | PASS | The `ProfessionalActivity` entity of `research-domain` is used as it is; no field added. The lists the entity cannot hold stay out of scope and go to the backlog. |
| III. Prefect Flow Orchestration | PASS | No new flow or script. The work happens inside the existing `lattes_projects` flow and the weekly's rule-version guard. |
| IV. Audit-Driven Data Quality | PASS | The quickstart check compares every curriculum item with the database (SC-001); the id report already counts collisions and aliases per reason. |
| V. LGPD Compliance | PASS | Institutions, periods and roles only; no CPF, phone or e-mail is touched. |
| Data Integrity: 2. Idempotency | PASS | Both rules depend only on the curriculum; the ingestion carries equal rows without writing; SC-006 checks unchanged curricula. |
| Data Integrity: 3. Re-creatable | PASS | The rule version changes (3 -> 4) and the database is rebuilt before use. The incremental and the rebuilt database agree because parser, ingestion and id share one rule. |
| Data Integrity: 4. Published identity history | PASS | Old ids are resolved through the existing candidate and alias history, or recorded as retired; the history supplies no entity data. |
| Development Workflow | PASS | Tests before the change; full suite, black, isort, flake8 on touched files; `make ci-check` recorded (it fails on the repository before this branch, see spec 033 T026). |

Re-check after Phase 1: PASS, no violation to justify.

## Project Structure

### Documentation (this feature)

```text
specs/034-keep-professional-activities/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1-R11
├── data-model.md        # Phase 1: the activity row, its id and its aliases
├── quickstart.md        # Phase 1: how to validate
├── contracts/
│   └── activity-rules.md  # Phase 1: contract of split_institution and distinct_activities
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/
├── core/logic/
│   ├── professional_activity_rules.py  # NEW: split_institution, distinct_activities, the stored-field tuple
│   └── horizon_identity.py             # _CHILD_PARTS of professional_activity; legacy candidate in child_decision; HORIZON_RULE_VERSION 3 -> 4
├── adapters/
│   ├── sources/lattes_parser.py        # parse_professional_activities uses the two rules
│   └── database/horizon_id_store.py    # the professional_activity query selects the hashed columns
└── flows/lattes/
    └── projects.py                     # ingest_professional_activities_task compares the 13 stored fields

tests/
├── test_professional_activity_rules.py # NEW: the examples of contracts/activity-rules.md
├── test_lattes_parser.py               # parser output: institution fields, repeats, institution-only items
├── test_lattes_professional_activities.py  # NEW: ingestion keeps different activities, carries equal ones
├── test_horizon_identity.py            # id fields, legacy candidate
├── test_horizon_id_assigner.py         # table fixture with the hashed columns; old id becomes an alias or is retired
├── test_incremental_lattes.py          # compares activities on every stored field
└── test_rule_version_guard.py          # a database written under version 3 needs a reset

docs/backlog.md                         # new entry for this defect; entries for the task/course lists and the cut institution texts
```

**Structure Decision**: the existing single-project layout. One new pure
module holds the two rules; the parser, the ingestion task and the id rule
change only where they read or compare activity fields. The exporter, the
person consolidator and the document-item store need no change (research
R10).

## Complexity Tracking

No violation to justify.
