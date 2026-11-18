# Implementation Plan: Dashboard-visible data fixes and Slack notices on main only

**Branch**: `041-dashboard-visible-fixes` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/041-dashboard-visible-fixes/spec.md`

## Summary

Seven fixes for errors anyone notices on the dashboard, plus the Slack change.

1. **Slack only on main.** `notify_slack.main` and the `curl` fallback of the
   end step send nothing when `GITHUB_REF_NAME` is not `main`. They print a
   `::notice::` that names the branch instead.
2. **Real advisors instead of "Prof", "Dr", "Ph", "M", "-".** The advisor of
   an academic degree was cut at the first full stop
   (`src/flows/lattes/projects.py:680`). A new pure module,
   `src/core/logic/person_name_rules.py`, reads the advisor and the co-advisor
   past their academic titles and refuses name fragments. The Lattes project
   strategy also skips one-letter members.
3. **One person per student.** `clean_student_name` (branch 036) cuts a work
   title or an "(orientador: …" first, then splits "/" into several students
   when every part is a name. The advisorship handler stores every student,
   not only the first.
4. **No self-edges.** The collaboration graphs drop an edge whose two ends
   are the same person. The source error behind it is kept.
5. **Each person once per team.** The exporter merges a person's rows across
   all teams of an initiative, with the earliest start date.
6. **Dash instead of " ? ".** A pure `fix_lost_dash` restores the dash that
   the downloaded curricula replaced with "?" in Lattes titles (initiatives,
   productions, articles). Real question marks stay.
7. **No year 0.** Lattes article and conference years outside 1950 to the
   current year plus one are exported as no year. The database keeps the
   source year (`articles.year` is NOT NULL); see research R9.

The parser and flow fixes change what curricula produce. Documents are
skipped by content hash and rule version, so `HORIZON_RULE_VERSION` goes from
6 to 7 and the weekly's guard rebuilds an older database once (clarification
of 2026-11-17). The id rules do not change. Source errors stay as they are:
the titleless article, the 3 workplans that end before they start, and a
curriculum owner listed as their own student.

## Technical Context

**Language/Version**: Python 3.12 in GitHub Actions; the local `.venv` runs 3.14

**Primary Dependencies**:
- `research-domain` / `eo_lib` (`Advisorship`, `Person`, unchanged);
- networkx (collaboration graphs, unchanged);
- Prefect (the Lattes flows, unchanged in structure);
- standard library only for the new rules (`re`, `unicodedata`, `datetime`);
- no new dependency.

**Storage**: SQLite `db/horizon.db`.
- Tables touched: `persons`, `academic_educations` (`advisor_id`,
  `co_advisor_id`), `advisorship_members`, `team_members`, `initiatives`,
  `research_productions`, `articles`.
- `horizon_meta` holds the rule version.
- No schema change.

**Testing**: pytest.
- New: `tests/test_person_name_rules.py` and `tests/test_title_rules.py`.
- Extended:
  - `tests/test_student_name_rules.py`: splits, citations, unchanged cases;
  - `tests/test_lattes_parser.py`: titles, years, several students;
  - `tests/test_lattes_projects_strategy.py`: one-letter members are skipped;
    create it if absent;
  - `tests/test_initiative_handlers.py`: several Student members, kept rows
    on a second pass;
  - `tests/test_canonical_exporter.py`: one entry per person across teams;
  - `tests/test_people_collaboration_graph_generator.py`: no self-edge;
    create it if absent;
  - `tests/test_notify_slack.py`: branch gate for both events;
  - `tests/test_weekly_etl_workflow.py`: the fallback gate and the notice;
  - `tests/test_rule_version_guard.py`: a version 6 database needs a reset.
- Then the full suite, and black, isort and flake8 on the touched files.

**Target Platform**: Linux, local runs and the GitHub Actions weekly workflow

**Project Type**: ETL pipeline (Prefect flows + domain logic)

**Performance Goals**: none new; a few regular expressions per degree,
member, advisorship item and title; the exporter's grouping moves out of one
loop

**Constraints**:
- No new setting, Makefile target or workflow input.
- No Docker change and no change to third-party libraries (the crawler stays
  as it is).
- No schema change, and the export shape is unchanged.
- The id rules are unchanged; only the rule version goes up.
- SigPesq collection stays sequential, and nothing goes upstream.

**Scale/Scope**:
- 435 curricula: 1,296 degree descriptions with an advisor (112 cut today),
  about 11,600 advisorship items (60 with several students or a citation),
  and Lattes titles (374 with " ? ").
- 15,550 initiatives, 5 collaboration graphs.
- About ten source files and the rule version.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Ports & Adapters | PASS | The name and title rules are pure modules in `src/core/logic/`. The parser (an adapter) and the Lattes flow call them, as they call the student and institution rules today. No new port. |
| II. Domain-First Data Modeling | PASS | `Person`, `Advisorship` and the team entities are used as they are; no field is added. |
| III. Prefect Flow Orchestration | PASS | No new flow. `notify_slack.py` stays an operational script that sends no data and runs no ingestion. |
| IV. Audit-Driven Data Quality | PASS | The quickstart counts every fixed case on the exports before and after, and checks that every old horizon_id resolves. The Lattes advisorship summary line gains the count of split fields. |
| V. LGPD Compliance | PASS | Only names already stored are handled. Checks print counts and public names, never a CPF or a phone number. The Slack webhook is still never printed. |
| Data Integrity: 2. Idempotency | PASS | Every rule depends on the source text alone. The several-student member list keeps unchanged rows (spec 020, FR-022). A second run writes nothing for unchanged sources. |
| Data Integrity: 3. Re-creatable | PASS | The rule version goes from 6 to 7 and the database is rebuilt before use. The same rules run in an incremental run and in a rebuild. |
| Data Integrity: 4. Published identity history | PASS | The id rules are unchanged. Removed fake people and renamed advisors are resolved by the existing alias history or reported as retired (R10). The key of a split advisorship keeps its text (R5). |
| Data Integrity: 7. Sources of truth | PASS | The raw curricula are not changed. Source errors stay (clarification 2026-11-17). |
| Development Workflow | PASS | Tests are written before the change, then the full suite runs and formatters and the linter run on touched files. `make ci-check` is recorded (it fails on the repository before this branch, see spec 033 T026). |

Re-check after Phase 1: PASS, no violation to justify.

## Project Structure

### Documentation (this feature)

```text
specs/041-dashboard-visible-fixes/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1-R10
├── data-model.md        # Phase 1: the rows and texts each fix touches
├── quickstart.md        # Phase 1: how to validate
├── contracts/
│   └── dashboard-fixes.md   # Phase 1: contract of the rules and behaviours
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/scripts/
└── notify_slack.py           # NOTIFY_BRANCH = "main"; main() returns after a ::notice:: on other branches

.github/workflows/
└── weekly-etl.yml            # end step: the curl fallback also checks $GITHUB_REF_NAME

src/core/logic/
├── person_name_rules.py      # NEW: is_name_fragment(text), advisor_name(description, co=False)
├── title_rules.py            # NEW: fix_lost_dash(title), plausible_year(value)
├── student_name_rules.py     # cut work title / "(orientador" first, then split "/"; CleanedName.names
├── strategies/
│   ├── lattes_projects.py    # skip members whose name is a fragment
│   └── lattes_advisorships.py   # student_names = every name; identity key keeps the names joined by " / "
├── initiative_handlers.py    # Student role takes a list of persons (advisorship_members and the deferred queue)
├── people_collaboration_graph_generator.py  # _add_evidence: no edge when a == b
├── canonical_exporter.py     # one person_map per initiative across its teams; earliest start, latest end
└── horizon_identity.py       # HORIZON_RULE_VERSION 6 -> 7 (comment line for branch 041)

src/adapters/sources/
└── lattes_parser.py          # fix_lost_dash on project, advisorship, article, conference and production titles;
                              # student_names from CleanedName.names (years stay as the source gives them, R9)

src/flows/lattes/
├── projects.py               # advisor / co-advisor through advisor_name instead of the two regexes
└── advisorships.py           # summary line counts split fields

tests/  (see Technical Context)

docs/operations/automation.md # Slack notices only on main; the log notice on other branches
docs/backlog.md               # remainders: one-word texts from advisorships ("Vários", "FAPEC", links,
                              # comma lists), " e " between two students, "?" used as quotes, broken
                              # encoding in titles, initiatives with two teams holding the same person
```

**Structure Decision**: the existing single-project layout. Two new pure
modules hold the name and title rules. The other fixes are a few lines where
each defect is.

## Complexity Tracking

No violation to justify.
