# Implementation Plan: LinkedIn links from a local list

**Branch**: `037-alumni-linkedin-links` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/037-alumni-linkedin-links/spec.md`

## Summary

A local, unversioned list (`data/linkedin_run/linkedin.list`, "link,Name" per
line) gives the LinkedIn profile link of persons the ETL already stores. A new
weekly phase, `linkedin_links`, reads it after the duplicate persons are
merged, finds each name among all persons (exact name, ignoring case, accents
and spaces), and makes an ETL-owned table, `person_linkedin_links`, equal to
the usable lines of the list. A name with no person, with several persons,
with conflicting lines or with an invalid link stores nothing and is reported.
No list, or a list with no usable line, changes nothing.

The research found that one export file already lists every person
(`researchers_canonical.json`, 18,329 entries) and that the student and other
classification files are built from the same person entry, so `linkedin_url`
is added in one place of the exporter and reaches all of them.

No identity rule, permanent id or rule version changes; a database created
before the feature gets the new table by migration, without a rebuild.

## Technical Context

**Language/Version**: Python 3.12 in GitHub Actions; the local `.venv` runs 3.14

**Primary Dependencies**: Prefect (one small maintenance flow), SQLAlchemy session for the store and the exporter's extra query, `sqlite3` connection inside the consolidator's merge hook; standard library only for the rule (`urllib.parse`, `re`, `dataclasses`); `research-domain` / `eo_lib` unchanged; no new dependency

**Storage**: SQLite `db/horizon.db`: new ETL-owned table `person_linkedin_links` (migration 0015); `persons` read only; local file `data/linkedin_run/linkedin.list` (not versioned); report `data/reports/linkedin_links_report.json`

**Testing**: pytest: new `tests/test_linkedin_links.py` (the contract tables of the rule), new `tests/test_linkedin_link_store.py` (store and merge hook on a temporary SQLite database), new `tests/test_linkedin_links_flow.py` (the flow with a temporary list and database: stored, removed, no file, empty file, second run writes nothing); `tests/test_canonical_exporter.py` (the field in the person entry, empty when absent, missing table tolerated); `tests/test_weekly_orchestrator.py` (the phase exists, in order, not critical); `tests/test_ensure_db.py` (migration 0015); `tests/test_consolidate_duplicates_script.py` (the merge hook is registered); the full suite; black, isort and flake8 on touched files

**Target Platform**: Linux, local runs and the GitHub Actions weekly workflow (where the list is absent)

**Project Type**: ETL pipeline (Prefect flows + domain logic)

**Performance Goals**: none; a few hundred lines against about 18,000 names in memory, one query to read the names and one to read the stored links

**Constraints**: no new setting, Makefile target or workflow input; no Docker change; no change to third-party libraries or to the dashboard; no library table altered; no path outside the repository in the code; the list never versioned; no identity rule or rule version change

**Scale/Scope**: 182 lines today, about 148 links; one new pure module, one store, one flow, one phase, one exporter field, one migration

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Ports & Adapters | PASS | The rule is a pure module in `src/core/logic/`. The table is read and written by a store in `src/adapters/database/`; the flow wires them. The core never opens the file or the database. |
| II. Domain-First Data Modeling | PASS | `Person` is used as it is. The link is an ETL addition kept in an ETL-owned table, as the ETL's other additions; no library entity or table changes. |
| III. Prefect Flow Orchestration | PASS | The step is a Prefect flow called by `app.py`, registered as a phase of the weekly orchestrator, like the other maintenance phases. |
| IV. Audit-Driven Data Quality | PASS | Every line has an outcome; the summary and the report list the unused lines with their reason; the quickstart checks that the stored links equal the usable lines. |
| V. LGPD Compliance | PASS | Only a public profile address and the name already stored are handled. The list and the report stay under `data/`, ignored by git. Nothing else from the alumni data enters. Checks print counts; the log prints the names of unused lines only. |
| Data Integrity: 1. Persistent database | PASS | The table persists between runs; a run only writes the difference from the list. |
| Data Integrity: 2. Idempotency | PASS | The same list a second time writes nothing: no row, no timestamp, no record. The plan depends on the list and the person names only. |
| Data Integrity: 3. Re-creatable | PASS | After a rebuild, one run with the same list gives the same links. No rule version change: the link takes part in no key, hash or id. |
| Data Integrity: 4. Published identity history | PASS | Untouched. |
| Data Integrity: 5. Raw inputs | PASS | The list is a local input kept by the maintainer, not a downloaded snapshot; the ETL never deletes or rewrites it. |
| Data Integrity: 7. Sources of truth | PASS | The list is a source input; no export or report is read back. |
| Development Workflow | PASS | Tests before the change; full suite; formatters and linter on touched files; `make ci-check` recorded as in the earlier specs. |

Re-check after Phase 1: PASS, no violation to justify.

## Project Structure

### Documentation (this feature)

```text
specs/037-alumni-linkedin-links/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1-R11
├── data-model.md        # Phase 1: the list, the table, the export field
├── quickstart.md        # Phase 1: how to make the list and validate
├── contracts/
│   └── linkedin-links.md  # Phase 1: list format, rule, step and export contracts
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/core/logic/
├── linkedin_links.py            # NEW: normalize_profile_link, parse_list, plan (pure)
└── canonical_exporter.py        # person entry gains linkedin_url, from a map loaded once

src/adapters/database/
└── linkedin_link_store.py       # NEW: read person names, read/apply the table, repoint_linkedin_link (merge hook)

src/db/
└── migrations.py                # 0015_person_linkedin_links

src/flows/maintenance/
└── linkedin_links.py            # NEW: the flow: read the file, plan, apply, log the summary, write the report

src/flows/pipelines/
└── weekly_orchestrator.py       # phase "linkedin_links" after consolidate_duplicates

src/scripts/
└── consolidate_duplicates.py    # merge_hooks gains repoint_linkedin_link

app.py                           # dispatch "linkedin_links"

tests/
├── test_linkedin_links.py           # NEW: contract tables of the rule
├── test_linkedin_link_store.py      # NEW: store and merge hook
├── test_linkedin_links_flow.py      # NEW: the flow end to end on temporary files
├── test_canonical_exporter.py       # linkedin_url in the person entry
├── test_weekly_orchestrator.py      # the phase exists, after consolidate_duplicates, not critical
├── test_consolidate_duplicates_script.py # the merge hook is registered
└── test_ensure_db.py                # migration 0015 creates the table

docs/
├── flows-and-entrypoints.md     # the new phase and the list
└── backlog.md                   # limits: exact name only; no links in the GitHub Actions exports
```

**Structure Decision**: the existing single-project layout. The rule is pure,
the table access is an adapter, the flow joins them, and the exporter reads
the table once per export. The list's path is a constant of the flow, beside
the Lattes list's convention (`data/<name>_run/<name>.list`).

## Complexity Tracking

No violation to justify.
