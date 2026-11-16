# Implementation Plan: One advisorship per student when titles repeat

**Branch**: `035-one-advisorship-per-student` | **Date**: 2026-11-11 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/035-one-advisorship-per-student/spec.md`

## Summary

An advisorship item whose title equals a stored advisorship's title is written
over that advisorship whatever the student, and the student is replaced. About
1,600 advisorships are missing because of it: the stored 10,260 should be
about 11,890.

The research found two facts that shape the fix. The source identity of an
advisorship is kept only in memory (the table has no column for it), so in a
later run a changed curriculum or SigPesq report is matched by title alone.
And the loader's title cache holds the last advisorship written with a title,
not the one with the bare title.

The fix adds one pure module, `src/core/logic/advisorship_matching.py`, with
the rule: an item matches a stored advisorship of the same title only when the
student is the same (same person, or the same name ignoring case and accents)
and their years share at least one year, or one side has no year. The loader
keeps an index of the stored advisorships per base title (the title without
the `| Orientacao ...` suffix) with each one's student and years, and asks the
rule instead of the title cache. An item that matches nothing is created by
the existing handler, under the bare title or the existing distinct name. A
matched advisorship keeps its stored name. Because the rule changes when two
records are the same advisorship, `HORIZON_RULE_VERSION` goes from 4 to 5 and
the weekly's guard rebuilds an older database once. The id rules do not
change.

## Technical Context

**Language/Version**: Python 3.12 in GitHub Actions; the local `.venv` runs 3.14

**Primary Dependencies**: `research-domain` / `eo_lib` (`Advisorship`, `AdvisorshipController`, `Initiative`, unchanged), SQLAlchemy session already used by the loader, Prefect (the SigPesq and Lattes advisorship flows, unchanged); standard library only for the rule; no new dependency

**Storage**: SQLite `db/horizon.db`: `initiatives`, `advisorships`, `advisorship_members`, `persons` (read for the index; no schema change); `horizon_meta` (rule version)

**Testing**: pytest: new `tests/test_advisorship_matching.py` (the contract tables); `tests/test_project_loader_matching.py` (loader lookup with the index); `tests/test_initiative_handlers.py` (stored name kept, new name as today); new `tests/test_advisorship_same_title.py` (loader with stubs, as the existing loader tests: the SigPesq replaced-student case and the two-curricula case); `tests/test_rule_version_guard.py` (a version 4 database needs a reset); the full suite; black, isort and flake8 on touched files

**Target Platform**: Linux, local runs and the GitHub Actions weekly workflow

**Project Type**: ETL pipeline (Prefect flows + domain logic)

**Performance Goals**: none new; one extra query per loader to fill the index, then dictionary lookups for about 12,200 advisorship items per rebuild

**Constraints**: no new setting, Makefile target or workflow input; no Docker change; no change to third-party libraries or to the dashboard; no schema change; the export shape and the distinct-name format are unchanged; SigPesq collection stays sequential

**Scale/Scope**: 11,532 Lattes advisorship items and 705 SigPesq rows; 10,260 advisorships become about 11,890; two source files and the rule version change

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Ports & Adapters | PASS | The rule is a pure module in `src/core/logic/`. The loader fills the index through the session it already uses for its other lookups; no new port and no adapter imports the rule. |
| II. Domain-First Data Modeling | PASS | `Advisorship` and its members are used as they are. No field is added; the identity key is not persisted because the entity has no place for it (research R2). |
| III. Prefect Flow Orchestration | PASS | No new flow or script. The change lives in the loader and handler the existing flows call, and in the weekly's rule-version guard. |
| IV. Audit-Driven Data Quality | PASS | The quickstart checks every tracked advisorship item against the database (SC-001, SC-002) and the invariants of SC-005. |
| V. LGPD Compliance | PASS | Student names are compared in memory; nothing new is stored or exported. The checks print counts only; the SigPesq payload fields with CPF and phone are not read. |
| Data Integrity: 2. Idempotency | PASS | The rule depends on the item and on the stored advisorship (student, dates), never on a row id except as a last tie-break between equal rows. A matched advisorship is not renamed, so the same input writes nothing new (SC-007). |
| Data Integrity: 3. Re-creatable | PASS | The rule version changes (4 -> 5) and the database is rebuilt before use. One known limit across sources is recorded in research R11 (7 pairs). |
| Data Integrity: 4. Published identity history | PASS | Id rules unchanged; old ids are resolved by the existing candidate and alias history or reported as retired. The history supplies no entity data. |
| Data Integrity: 7. Sources of truth | PASS | The tracking tables are not read by the run (research R2, rejected alternative); only the quickstart reads them, to audit. |
| Development Workflow | PASS | Tests before the change; full suite; formatters and linter on touched files; `make ci-check` recorded (it fails on the repository before this branch, see spec 033 T026). |

Re-check after Phase 1: PASS, no violation to justify.

## Project Structure

### Documentation (this feature)

```text
specs/035-one-advisorship-per-student/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1-R11
├── data-model.md        # Phase 1: the rows read, the index, the names
├── quickstart.md        # Phase 1: how to validate
├── contracts/
│   └── advisorship-matching.md  # Phase 1: contract of the rule and of the loader/handler behaviour
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/core/logic/
├── advisorship_matching.py   # NEW: base_title, year_range, years_differ, same_student, pick_match, StoredAdvisorship
├── project_loader.py         # advisorship index (fill, update, reset); _lookup_existing_initiative uses pick_match for advisorships
├── initiative_handlers.py    # AdvisorshipHandler: a matched advisorship keeps its stored name; helper that resolves the item's student
└── horizon_identity.py       # HORIZON_RULE_VERSION 4 -> 5 (comment line for branch 035)

tests/
├── test_advisorship_matching.py      # NEW: every table of contracts/advisorship-matching.md
├── test_project_loader_matching.py   # lookup: other student -> none; same student -> match; other year -> none; projects unchanged
├── test_initiative_handlers.py       # stored name kept on update; bare title or distinct name on create
├── test_advisorship_same_title.py    # NEW: loader with stubs: 49 students, replaced SigPesq student, advisor + co-advisor, other year, index loaded from stored rows
└── test_rule_version_guard.py        # a database written under version 4 needs a reset

docs/backlog.md                       # TD-037 closed by this branch; new entry for this defect; entries for the suffix in names and the limits of research R11
```

**Structure Decision**: the existing single-project layout. One new pure
module holds the rule; the loader and the advisorship handler change only
where an advisorship is looked up and named. The strategies, the flows, the
id rules, the exporter and the document-skip mechanism need no change
(research R9, R10).

## Complexity Tracking

No violation to justify.
