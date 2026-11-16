# Implementation Plan: Small fixes batch

**Branch**: `036-small-fixes-batch` | **Date**: 2026-11-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/036-small-fixes-batch/spec.md`

## Summary

Four small defects, fixed together and validated once.

1. **Student names.** The student text of a Lattes advisorship item sometimes
   carries the title of the work, an academic title, a link or a footnote
   number, or is not a name at all. A new pure module,
   `src/core/logic/student_name_rules.py`, cleans it; the Lattes parser calls
   it in the two places that read the student. About 155 persons get their
   clean name and 4 texts no longer create a person. Fields with several
   people stay as they are.
2. **Fellowship stored twice.** The research found the cause: the domain
   library's `Fellowship` constructor clears the sponsor of every new
   fellowship, and the ETL only sets it back when a second row uses the same
   fellowship. "JTC" and "PICTI" are used by one row each, so they have no
   sponsor and are not recognised in the next run. The handler sets the
   sponsor right after creating the fellowship.
3. **Project PDF on an advisorship.** The enrichment already limits its
   title index to the type "Research Project", but the loader stores nearly
   every advisorship with that type. The enrichment now leaves out every
   initiative that has a row in `advisorships`.
4. **Order of names in a SigPesq project row.** The row is compared as
   written, and the portal reorders "Estudantes" and "Pesquisadores". The
   SigPesq project strategy gives the loader a content to compare in which
   those two lists are sorted.

Cleaning names changes which person a name is, so `HORIZON_RULE_VERSION` goes
from 5 to 6 and the weekly's guard rebuilds an older database once. The id
rules do not change.

## Technical Context

**Language/Version**: Python 3.12 in GitHub Actions; the local `.venv` runs 3.14

**Primary Dependencies**: `research-domain` / `eo_lib` (`Fellowship`, `FellowshipController`, `Advisorship`, unchanged), SQLAlchemy session already used by the enrichment, Prefect (the Lattes advisorship flow, the SigPesq flows, unchanged in structure); standard library only for the name rule; no new dependency

**Storage**: SQLite `db/horizon.db`: `persons`, `fellowships`, `advisorships`, `initiatives` (`enrichment_json`), the document states of spec 021; no schema change; `horizon_meta` (rule version)

**Testing**: pytest: new `tests/test_student_name_rules.py` (the contract tables); `tests/test_lattes_parser.py` (both parser paths: clean name, kinds, item kept without a student); `tests/test_initiative_handlers.py` (a new fellowship gets its sponsor; a second pass creates none); `tests/test_project_enrichment_db.py` (an advisorship is not in the title or code index); `tests/test_sigpesq_project_mapping.py` and `tests/test_project_loader_matching.py` (reordered lists are unchanged; an added name is a change); `tests/test_rule_version_guard.py` (a version 5 database needs a reset); the full suite; black, isort and flake8 on touched files

**Target Platform**: Linux, local runs and the GitHub Actions weekly workflow

**Project Type**: ETL pipeline (Prefect flows + domain logic)

**Performance Goals**: none new; the name rule is a few regular expressions over about 11,600 items; the enrichment's two index queries gain one `NOT EXISTS`

**Constraints**: no new setting, Makefile target or workflow input; no Docker change; no change to third-party libraries or to the dashboard; no schema change; the export shape is unchanged; SigPesq collection stays sequential

**Scale/Scope**: 11,601 Lattes advisorship items (about 160 touched), 20 fellowships, 4 advisorships with PDF data, 103 SigPesq project rows; six source files and the rule version change

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Ports & Adapters | PASS | The name rule is a pure module in `src/core/logic/`; the parser (an adapter) calls it, as it calls the institution rule of branch 034. The enrichment keeps using its own session. No new port. |
| II. Domain-First Data Modeling | PASS | `Person`, `Fellowship` and `Advisorship` are used as they are; no field is added. The library's constructor is worked around in the handler, not patched. |
| III. Prefect Flow Orchestration | PASS | No new flow or script. The Lattes advisorship flow gains one summary line. |
| IV. Audit-Driven Data Quality | PASS | The quickstart counts every kind of student text against the database, the fellowships and their sponsors, and the advisorships with PDF data. The run summary reports the cleaning. |
| V. LGPD Compliance | PASS | Only names already stored are handled; nothing new is stored or exported. The checks print counts and public names, never a CPF or a phone number. |
| Data Integrity: 2. Idempotency | PASS | The name rule depends on the text alone. The fellowship is found again by name and sponsor. The compared content of a SigPesq row no longer depends on list order. A second run writes nothing for unchanged sources (FR-020). |
| Data Integrity: 3. Re-creatable | PASS | The rule version changes (5 -> 6) and the database is rebuilt before use; the same rule runs in an incremental run and in a rebuild. |
| Data Integrity: 4. Published identity history | PASS | Id rules unchanged; old ids are resolved by the existing candidate and alias history or reported as retired. The history supplies no entity data. |
| Data Integrity: 7. Sources of truth | PASS | The raw curriculum item and the tracked SigPesq payload are not changed; only what is stored as the person and what is compared for change. |
| Development Workflow | PASS | Tests before the change; full suite; formatters and linter on touched files; `make ci-check` recorded (it fails on the repository before this branch, see spec 033 T026). |

Re-check after Phase 1: PASS, no violation to justify.

## Project Structure

### Documentation (this feature)

```text
specs/036-small-fixes-batch/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1-R11
├── data-model.md        # Phase 1: the rows and texts each fix touches
├── quickstart.md        # Phase 1: how to validate
├── contracts/
│   └── small-fixes.md   # Phase 1: contract of the name rule and of the three other behaviours
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/core/logic/
├── student_name_rules.py     # NEW: clean_student_name(raw) -> CleanedName(name, kinds)
├── initiative_handlers.py    # AdvisorshipHandler._ensure_fellowship: set the sponsor after creating the fellowship
├── project_enrichment.py     # _load_research_project_names and _load_code_index leave out initiatives with a row in advisorships
├── project_loader.py         # the content compared for "unchanged" comes from the strategy when it gives one
├── strategies/
│   └── sigpesq_projects.py   # change_content(row): "Estudantes" and "Pesquisadores" as sorted lists
└── horizon_identity.py       # HORIZON_RULE_VERSION 5 -> 6 (comment line for branch 036)

src/adapters/sources/
└── lattes_parser.py          # both advisorship paths: clean the student, keep the kinds, keep an item whose text is not a name

src/flows/lattes/
└── advisorships.py           # one summary line with the counts of each kind

tests/
├── test_student_name_rules.py   # NEW: every table of contracts/small-fixes.md, section 1
├── test_lattes_parser.py        # clean student, kinds, item without a student kept, item with no student text dropped
├── test_initiative_handlers.py  # new fellowship stored with its sponsor; found again by name + sponsor
├── test_project_enrichment_db.py   # an initiative with a row in advisorships is left out of both indexes
├── test_sigpesq_project_mapping.py # change_content: reordered lists equal; an added name differs
├── test_project_loader_matching.py # the loader compares the strategy's content when it gives one
└── test_rule_version_guard.py   # a database written under version 5 needs a reset

docs/backlog.md                  # TD-034 and TD-038 closed by this branch; new entries: extra text in other person names, advisorships stored with the type "Research Project", the Fellowship constructor of the library
```

**Structure Decision**: the existing single-project layout. One new pure
module holds the name rule; the other three fixes are a few lines each where
the defect is.

## Complexity Tracking

No violation to justify.
