---

description: "Task list for spec 037: LinkedIn links from a local list"
---

# Tasks: LinkedIn links from a local list

**Input**: Design documents from `specs/037-alumni-linkedin-links/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/linkedin-links.md, quickstart.md

**Tests**: Included. The constitution's development workflow requires tests,
and the plan writes them before the change (they must fail first).

**Organization**: Tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 to US4)

Code: `src/core/logic/linkedin_links.py` (new, the rule),
`src/adapters/database/linkedin_link_store.py` (new, the table and the merge hook),
`src/flows/maintenance/linkedin_links.py` (new, the step),
`src/db/migrations.py` (migration 0015), `app.py` (dispatch),
`src/flows/pipelines/weekly_orchestrator.py` (the phase),
`src/core/logic/canonical_exporter.py` (the export field),
`src/scripts/consolidate_duplicates.py` (the merge hook registered).
Tests: `tests/test_linkedin_links.py`, `tests/test_linkedin_link_store.py`,
`tests/test_linkedin_links_flow.py` (new), `tests/test_canonical_exporter.py`,
`tests/test_weekly_orchestrator.py`, `tests/test_ensure_db.py`,
`tests/test_consolidate_duplicates_script.py`.

Terms used below (contracts/linkedin-links.md, data-model.md):

- **The list**: `data/linkedin_run/linkedin.list`, one `link,Name` per line.
- **Normal form**: `https://www.linkedin.com/in/<profile>`.
- **Usable line**: a line whose outcome is `stored`.
- **Outcome**: `stored`, `not_found`, `several_persons`, `conflict` or `invalid`.
- **The table**: `person_linkedin_links(person_id, linkedin_url, listed_name, updated_at)`.

Rules for every task: no path outside this repository in code, tests or
documents (the maintainer's alumni projects are never read or written by the
ETL); the list is never created, changed or committed by the code; no change
to third-party libraries, to the dashboard or to Docker; never read or print
`.env`; checks print counts only; the weekly is never run without asking the
maintainer first. Tests use temporary files and databases (`tmp_path`), never
`data/` or `db/horizon.db`.

---

## Phase 1: Setup

- [X] T001 Record the starting point in this file under this task: branch `037-alumni-linkedin-links` and its commit (`git log --oneline -1`), the full suite before any change (`.venv/bin/python -m pytest -q > logs/pytest_037_before.log 2>&1`; expected 1371 passed, 10 skipped) and the flake8 count of the repository (`.venv/bin/python -m flake8 src tests | wc -l`; expected 579). No code change.
  - Result: branch `037-alumni-linkedin-links` at `9055406` (the tip of branch 036); full suite before any change: 1371 passed, 10 skipped, 0 failed in 7m55 (logs/pytest_037_before.log, line 31); flake8 on `src tests`: 579.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the pieces every story uses: reading a line, the table, the store.

- [X] T002 Create tests/test_linkedin_links.py with one parametrized test per row of contracts/linkedin-links.md section 1 (`normalize_profile_link`) and section 2 (`parse_list`, checking `number`, `link`, `name`, `problem` of each returned `ListLine` and that ignored lines are not returned while still counting for `number`), importing from `src.core.logic.linkedin_links`. Run and see it fail on the import.
  - Result: tests/test_linkedin_links.py written from sections 1 and 2 of the contract (21 link cases, 9 line cases). The test file and the module of T003 were written in the same step while the starting suite of T001 was still running, so the failing run on the import was not seen separately.
- [X] T003 Create src/core/logic/linkedin_links.py with a module docstring (what the list is, branch 037), the frozen dataclass `ListLine(number, link, name, problem)`, `normalize_profile_link(text) -> Optional[str]` and `parse_list(lines) -> list[ListLine]` as the contract sections 1 and 2 say; standard library only (`urllib.parse`, `re`, `dataclasses`, `typing`); no file or database access. Run tests/test_linkedin_links.py until every row passes.
  - Result: module written with `ListLine`, `normalize_profile_link` and `parse_list`; 30 passed. Two cases added to the contract's list while writing: `linkedin.com.evil.example` is not LinkedIn (the host must be `linkedin.com` or end with `.linkedin.com`), and a line written "Name,link" is invalid.
- [X] T004 In tests/test_ensure_db.py add a test that a database created by the existing helper of that file has the table `person_linkedin_links` with the four columns of data-model.md section 2, that `linkedin_url` is unique and `person_id` is the primary key (a second insert of either fails), and that running the migrations twice changes nothing; see it fail. Then add `0015_person_linkedin_links` at the end of `MIGRATIONS` in src/db/migrations.py (`CREATE TABLE IF NOT EXISTS person_linkedin_links (person_id INTEGER PRIMARY KEY, linkedin_url TEXT NOT NULL UNIQUE, listed_name TEXT NOT NULL, updated_at TEXT NOT NULL)`) with a comment (spec 037: ETL-owned, beside the library's person tables, never altering them). Run the test.
  - Result: test added to tests/test_ensure_db.py; it failed (no table), then passed with migration `0015_person_linkedin_links`; the file's 4 tests pass.
- [X] T005 Create tests/test_linkedin_link_store.py for `src.adapters.database.linkedin_link_store.LinkedinLinkStore`, on a SQLite file in `tmp_path` with a minimal `persons(id, name)` table and the table of T004 (created through `run_migrations`): `persons()` returns every `(id, name)`; `stored()` returns `{person_id: (link, listed_name)}` and `{}` when the table does not exist; `apply(add, change, remove, now)` inserts, updates and deletes exactly the given rows in one transaction and returns the three counts; a row not named in the call keeps its `updated_at`. Run and see it fail on the import.
  - Result: tests/test_linkedin_link_store.py written: 6 tests of the store (persons, no table, add/change/remove, other rows untouched, one transaction, nothing to do). The 4 tests of the merge hook of T018 were written in the same file at the same time.
- [X] T006 Create src/adapters/database/linkedin_link_store.py with `LinkedinLinkStore(database_url)` implementing T005 through a SQLAlchemy engine built from the URL (same pattern as src/adapters/database/horizon_id_store.py: read that file first and follow its way of opening and disposing the engine); `apply` takes `add` and `change` as lists of `(person_id, link, listed_name)` and `remove` as a list of person ids. Run tests/test_linkedin_link_store.py.
  - Result: store written with plain `sqlite3` on the database file, not a SQLAlchemy engine: it is the way of src/adapters/database/horizon_id_store.py, which the task says to follow. `apply` removes and changes before it adds, so a link freed by one person can go to another in the same call. The store was written before migration 0015 existed (T004 waited for the starting suite), so its tests were first run after it: 10 passed, the failing run was not seen separately.

**Checkpoint**: a line can be read, the table exists, rows can be read and written. Nothing runs in the weekly yet.

---

## Phase 3: User Story 1 - A person of the list has a LinkedIn link in the exports (Priority: P1) 🎯 MVP

**Goal**: a usable line stores the link on its person and the person entry of the exports carries `linkedin_url`.

**Independent Test**: a temporary list with names that exist in a temporary database; after the step and the export, those persons have the link and nobody else has one.

### Tests for User Story 1

- [X] T007 [US1] In tests/test_linkedin_links.py add tests for `plan(lines, persons, stored)` covering the first three rows of contracts/linkedin-links.md section 3: a name equal to one person's name gives outcome `stored` and one `add` of `(person_id, link, name as written)`; the name written in capitals, without accents or with repeated spaces matches the same person; a person not in the list is in no change. Check the returned `Plan` fields (`add`, `change`, `remove`, `outcomes`) and that `plan` does not modify its arguments. See them fail.
  - Result: five tests of `plan` added (one person: stored and added; case, accents and spaces; person outside the list; same link stored: nothing; another link: change). They failed on the import of `plan`.
- [X] T008 [P] [US1] In tests/test_canonical_exporter.py add tests for the person entry: `_build_researcher_base_export_dict` (or the helper the task T012 adds beside it) gives `linkedin_url` equal to the stored link for a person with a row and `None` for a person without; the key is present in both cases; `_fetch_person_linkedin_links(session)` returns `{person_id: link}` from the table and `{}` when the table does not exist (use an in-memory SQLite session, as the other `_fetch_*` tests of the file do); and one test through `export_researchers`, in the style of `test_export_researchers_includes_person_id_in_advisorships`, that the written entry has the key. See them fail.
  - Result: three tests added (the key is always present; `_fetch_person_linkedin_links` with no session, no table and one row; `export_researchers` writes the link of the listed person only and every person file has the key). All three failed first.
- [X] T009 [US1] Create tests/test_linkedin_links_flow.py for `src.flows.maintenance.linkedin_links.sync_linkedin_links(list_path, database_url, report_path)`, the plain function the flow calls, on files in `tmp_path` (a database with `persons` and the migrated table, a list with two names that exist): after the call the table holds the two links in normal form with the names as written, the function returns the counts (`lines 2, stored 2, added 2`), and no row of `persons` changed. Also add to tests/test_weekly_orchestrator.py, in the style of `test_consolidate_duplicates_phase_runs_before_canonical_export`, a test that `_PHASES` has `linkedin_links` right after `consolidate_duplicates`, before `assign_horizon_ids` and `export_canonical`, not critical, mode `app`. See them fail.
  - Result: tests/test_linkedin_links_flow.py created with a workspace fixture under `tmp_path` and the first test (two lines stored in normal form, persons untouched); the phase test added to tests/test_weekly_orchestrator.py. Both failed first.

### Implementation for User Story 1

- [X] T010 [US1] In src/core/logic/linkedin_links.py add the frozen dataclasses `LineOutcome(number, name, outcome)` and `Plan(add, change, remove, outcomes)` and `plan(lines, persons, stored)`: index the persons by `normalize_text(name)` (imported from `src.core.logic.initiative_identity`), give each valid line the outcome `stored` when its normalized name has exactly one person, and build `add` (no row stored) or `change` (another link stored) or nothing (same link). Lines that are not usable get their outcome in User Story 2; removal comes in User Story 3; for now such lines are skipped and `remove` is empty. Run the tests of T007.
  - Result: `LineOutcome`, `Plan` and the first `plan` (usable lines only). tests/test_linkedin_links.py: 38 passed.
- [X] T011 [US1] Create src/flows/maintenance/linkedin_links.py: constants `LIST_PATH = "data/linkedin_run/linkedin.list"` and `REPORT_PATH = "data/reports/linkedin_links_report.json"`; `sync_linkedin_links(list_path=LIST_PATH, database_url=None, report_path=REPORT_PATH) -> dict` that resolves the database URL as src/flows/maintenance/horizon_ids.py does, runs the migrations, reads the file as UTF-8 lines, calls `parse_list`, `LinkedinLinkStore.persons()`, `.stored()`, `plan(...)`, `.apply(...)` with one UTC timestamp, and returns the counts; and the Prefect flow `linkedin_links_flow()` that calls it and logs the result, with the Telegram state handlers the other maintenance flows use. In app.py add the dispatch `if flow_to_run == "linkedin_links":` beside `consolidate_duplicates` (import inside the branch, as the neighbours do) and add the name to any list of accepted flow names app.py keeps. In src/flows/pipelines/weekly_orchestrator.py add `("linkedin_links", ["linkedin_links"], 300, False, "app")` right after the `consolidate_duplicates` entry, with a comment (spec 037: after the persons are merged, before the ids and the export; without the local list it does nothing). Run tests/test_linkedin_links_flow.py and tests/test_weekly_orchestrator.py.
  - Result: flow, `sync_linkedin_links`, the dispatch in app.py and the phase in the orchestrator. app.py keeps no list of accepted flow names, so nothing else was needed there. tests/test_linkedin_links_flow.py, tests/test_weekly_orchestrator.py and tests/test_weekly_orchestrator_finalize.py: 38 passed.
- [X] T012 [US1] In src/core/logic/canonical_exporter.py add `_fetch_person_linkedin_links(session) -> dict` (one query on `person_linkedin_links`; `{}` when the session is `None` or the table does not exist) beside the other `_fetch_person_*` helpers; in `export_researchers` load it once and set `linkedin_url` on every person entry built by `_build_researcher_base_export_dict`, in both places that call it (the researchers loop and the backfilled participants), with `None` when the person has no row; make `_build_researcher_base_export_dict` set the default `linkedin_url: None` beside `cnpq_url` and `google_scholar_url`. Check with `grep -n "google_scholar_url" src` whether any other code lists the person fields explicitly (a column list, a parquet schema, the classification payload) and add `linkedin_url` there too; record what was found under this task. Run tests/test_canonical_exporter.py and the other exporter tests (`tests/test_canonical_exporter*.py`, `tests/test_export_canonical_data_flow.py`).
  - Result: `_fetch_person_linkedin_links` added; `export_researchers` loads it once and sets the field in both places that build a person entry; the base entry defaults it to `None`. `grep google_scholar_url src`: besides the exporter only src/core/logic/person_consolidator.py names the person fields, and it handles the library's `researchers` columns, which this feature does not touch (the link follows a merge through the hook of T020). Two existing tests compare the whole person entry and needed the new key in their expected value (`"linkedin_url": None`): `test_export_all_orchestrates_exports` and `test_export_researchers_backfills_participant_only_people_from_projects_and_advisorships`. The exporter, export flow, parquet, graph and zip tests pass.

**Checkpoint**: with a list, the step stores links and the exports carry them.

---

## Phase 4: User Story 2 - A line that cannot be used is reported, never guessed (Priority: P1)

**Goal**: every line has an outcome; unusable lines store nothing and are listed with their reason.

**Independent Test**: a list with a missing name, a name of two persons, an invalid link, a name with two links and a link on two names; nothing stored for them, each in the summary.

### Tests for User Story 2

- [X] T013 [US2] In tests/test_linkedin_links.py add tests for `plan` covering the rows `not_found`, `several_persons`, the three repeat rows and `invalid` of contracts/linkedin-links.md section 3: no change for those lines; two persons with the same normalized name both stay without a link; the same name twice with the same link counts once (`stored`, one `add`); the same name with two links gives two `conflict` outcomes; one link under two names gives two `conflict` outcomes and no change even when both names exist; the outcomes list has one entry per parsed line, in file order, with the name as written. See the new ones fail.
  - Result: six tests of `plan` added (not found; two persons; the same name and link twice; the same name with two links; the same link under two names; one outcome per line in file order). All six failed first.
- [X] T014 [P] [US2] In tests/test_linkedin_links_flow.py add tests: with a list holding one line of each kind, `sync_linkedin_links` returns `lines`, `stored`, `added`, `changed`, `removed`, `not_found`, `several_persons`, `conflicts`, `invalid` with the right counts, `stored + not_found + several_persons + conflicts + invalid == lines`, and `unused` as a list of `{line, name, reason}`; the report file is written with the same content plus `list_path` and `list_found: true`; no person was created (the `persons` count is unchanged); and the text logged by the flow's summary helper has the counts line and one line per unused entry with the name and the reason and no link. See them fail.
  - Result: three flow tests added on a list with one line of each kind (counts and `unused`; the report file; the summary text without any link). All three failed first; the first one failed with a UNIQUE error, because the first `plan` tried to store the conflicting lines.

### Implementation for User Story 2

- [X] T015 [US2] In src/core/logic/linkedin_links.py complete `plan`: before matching, mark as `conflict` every valid line whose normalized name appears with more than one distinct link and every valid line whose link appears under more than one distinct normalized name (the same name with the same link on several lines is one line); then `not_found`, `several_persons`, `stored`; invalid lines keep `invalid`. Return one `LineOutcome` per parsed line in file order. Run tests/test_linkedin_links.py.
  - Result: `plan` now gives every line an outcome (`_outcome_of`): invalid, conflict, not found, several persons, stored. tests/test_linkedin_links.py: all pass.
- [X] T016 [US2] In src/flows/maintenance/linkedin_links.py build the result dict of T014 from the plan, add `format_summary(result) -> list[str]` (first line `linkedin links: lines N, stored N (added N, changed N, removed N), not found N, several persons N, conflicts N, invalid N`, then one line per unused entry: `line <n>: <name>: <reason>`), log those lines in the flow, and write the report as JSON (UTF-8, `ensure_ascii=False`, creating the report folder when missing) through the project's atomic write helper if src/core/logic/atomic_io.py has one for JSON, otherwise a plain write. Run tests/test_linkedin_links_flow.py.
  - Result: the result dict, `format_summary` and the report (through `atomic_write_json` of src/core/logic/atomic_io.py). tests/test_linkedin_links.py and tests/test_linkedin_links_flow.py: 48 passed.

**Checkpoint**: User Stories 1 and 2 together are the usable first version.

---

## Phase 5: User Story 3 - The list is the source of truth for the link (Priority: P2)

**Goal**: stored links follow the list; a merged person keeps the link.

**Independent Test**: run with a list, change a link, remove a line, run again: one changed, one removed, the rest untouched; a third run writes nothing.

### Tests for User Story 3

- [X] T017 [US3] In tests/test_linkedin_links.py add tests for `plan`: a stored row of a person whose line is gone is in `remove`; a stored row of a person whose line became `conflict`, `several_persons` or `invalid` is in `remove`; a stored row whose person no longer exists is in `remove`; a changed link is in `change` and not in `add`; planning again with `stored` equal to the result of the first plan gives empty `add`, `change` and `remove`; a name `not_found` in one call and present in `persons` in the next gives `add`. In tests/test_linkedin_links_flow.py add: two calls of `sync_linkedin_links` with the same list leave every `updated_at` unchanged and the second returns added 0, changed 0, removed 0; after one line is removed and one link changed, the next call returns removed 1, changed 1 and every other row is byte-for-byte the same. See the new ones fail.
  - Result: seven tests of `plan` (line gone; line no longer usable, by conflict and by invalid link; person stored twice; person gone; planning again changes nothing; a name not found gets its link once the person exists) and two flow tests (same list twice writes nothing, `updated_at` included; one changed link and one removed line touch only their rows). Six failed first; the ones that already passed describe behaviour the first `plan` had.
- [X] T018 [P] [US3] In tests/test_linkedin_link_store.py add tests for `repoint_linkedin_link(conn, winner_id, loser_id)` on a raw `sqlite3` connection, one per row of contracts/linkedin-links.md section 5 (loser only: the row moves; both: the winner's stays and the loser's is deleted; loser without a row: nothing; no table: nothing, no error). In tests/test_consolidate_duplicates_script.py add a test that `run_person_dedup` passes both `repoint_person_links` and `repoint_linkedin_link` as merge hooks (patch `PersonConsolidator` and read the `merge_hooks` argument). See them fail.
  - Result: the four hook tests were written with the store tests (T005); the test that `run_person_dedup` registers both hooks was added to tests/test_consolidate_duplicates_script.py and failed first.

### Implementation for User Story 3

- [X] T019 [US3] In src/core/logic/linkedin_links.py make `plan` fill `remove` with every person id of `stored` that has no `stored` outcome in this list (which covers lines gone, lines no longer usable and persons that no longer exist). Run tests/test_linkedin_links.py and tests/test_linkedin_links_flow.py.
  - Result: `plan` fills `remove` with every stored person that has no usable line. tests/test_linkedin_links.py and tests/test_linkedin_links_flow.py pass.
- [X] T020 [US3] In src/adapters/database/linkedin_link_store.py add `repoint_linkedin_link(conn, winner_id, loser_id)` as the contract section 5 says, written like `repoint_person_links` of src/adapters/database/document_item_store.py (raw connection, inside the consolidator's transaction, nothing when the table is absent); in src/scripts/consolidate_duplicates.py add it to `merge_hooks`. Run tests/test_linkedin_link_store.py, tests/test_consolidate_duplicates_script.py and tests/test_person_consolidator.py.
  - Result: `repoint_linkedin_link` was written with the store (T006); it is now registered in src/scripts/consolidate_duplicates.py in both places that build a `PersonConsolidator` with hooks (the weekly's `run_person_dedup` and the script's `execute`). The five related test files: 91 passed.

**Checkpoint**: the stored links equal the usable lines after every run that reads the list.

---

## Phase 6: User Story 4 - A run without the list is harmless (Priority: P2)

**Goal**: no list, or a list with no usable line, changes nothing and does not fail.

**Independent Test**: run the step with no file and with an empty file on a database that has links; exit 0, same rows.

### Tests for User Story 4

- [X] T021 [US4] In tests/test_linkedin_links.py add a test that `plan` with lines none of which is `stored` (an empty list, only invalid lines, only names not found) returns empty `add`, `change` and `remove` even when `stored` has rows, with the outcomes still listed. In tests/test_linkedin_links_flow.py add: with no file at the path, `sync_linkedin_links` returns `list_found: False`, writes the report, raises nothing, and the table keeps its rows; with an existing file that is empty, or holds only comments, or only invalid lines, it returns `list_found: True`, `stored 0`, `removed 0`, an `empty_list: True` flag, and the table keeps its rows; `format_summary` gives `linkedin links: no list at <path>, nothing changed` for the first and a line starting with `linkedin links: the list has no usable line, nothing changed` for the second (followed by the unused lines); on a database without the table the call creates it and ends normally. See the new ones fail.
  - Result: one parametrized test of `plan` (empty list, only comments, only invalid lines, only a name not found: no change even with stored rows) and four flow tests (no file; a file with no usable line in three forms; a usable list is not flagged as empty; a database without the table gets it). Nine cases failed first; the last test already passed, because the step runs the migrations.

### Implementation for User Story 4

- [X] T022 [US4] In src/core/logic/linkedin_links.py make `plan` return no change at all when no line has the outcome `stored` (FR-014a). In src/flows/maintenance/linkedin_links.py handle the missing file (no parse, no plan, no apply; `list_found: False`) and the list with no usable line (`empty_list: True`, logged as a warning), and make `format_summary` give the two texts of T021. Run tests/test_linkedin_links.py and tests/test_linkedin_links_flow.py, then the whole set of this feature: `.venv/bin/python -m pytest -q tests/test_linkedin_links.py tests/test_linkedin_link_store.py tests/test_linkedin_links_flow.py tests/test_canonical_exporter.py tests/test_weekly_orchestrator.py tests/test_ensure_db.py tests/test_consolidate_duplicates_script.py`.
  - Result: `plan` returns no change when no line is usable; the step handles the missing file without opening it and flags `empty_list`; `format_summary` gives the two texts, and the empty-list line is logged as a warning. The seven test files of the feature: 144 passed.

**Checkpoint**: every story passes its tests.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T023 [P] Update docs/flows-and-entrypoints.md: the phase `linkedin_links` in the list of weekly phases (after `consolidate_duplicates`), `app.py linkedin_links`, the list file with its format and the fact that it is local and never versioned, the report file, and the export field `linkedin_url`. Add to docs/backlog.md, after the last entry and with the next free numbers (check first): one entry for the limits of the name match (exact name only; a homonym stored twice blocks the link; research R11) and one for the links being absent from the GitHub Actions exports because the list is local (maintainer's decision of 2026-11-13). No path outside the repository in either file.
  - Result: docs/flows-and-entrypoints.md has a new section, "LinkedIn links from a local list (branch 037)" (the list and its format, the phase and its place, the outcomes, the table, the export field, the summary and the report). The document has no list of weekly phases to add the name to. docs/backlog.md gained TD-052 (exact name only) and TD-053 (no links in the GitHub Actions exports); no entry had those numbers. No path outside the repository in either file.
- [X] T024 [P] Run black, isort and flake8 (`--check`/`--diff` first) on the touched files only: the three new source files, src/db/migrations.py, app.py, src/flows/pipelines/weekly_orchestrator.py, src/core/logic/canonical_exporter.py, src/scripts/consolidate_duplicates.py and the touched test files; apply the formatters only to lines of this branch; record the flake8 count of the repository (must not grow from T001). Run `grep -rn "egressos" src app.py tests docs specs/037-alumni-linkedin-links` and record that the only matches, if any, are the Portuguese word in older documents, never a path.
  - Result: black changed five test files and isort the new flow, only in lines of this branch; the other touched files needed nothing. flake8 on the touched files: 8 findings before and 8 after, all older lines of canonical_exporter.py; the new files have none. Repository: 579 (579 at T001). The search for the alumni folders (`home/rafael`, `egressos-dados`, `/egressos/`, `recorte_cursos`) in src, app.py, tests, docs and this spec's folder finds nothing; the word "egressos" appears only in older code of the CNPq crawler and of a report script.
- [X] T025 Run the full suite (`.venv/bin/python -m pytest -q > logs/pytest_037_full.log 2>&1`) and record the result under this task; expected: every test of T001 still passes plus the new ones, 0 failed. Record `make ci-check` as in spec 033 T026.
  - Result: first run: 1453 passed, 10 skipped, 1 failed in 7m41 (logs/pytest_037_full.log, line 82). The failure was `tests/test_schema_compatibility.py::test_migrations_only_add_the_new_tables`, which keeps the list of the ETL-owned tables the migrations may add and did not know `person_linkedin_links`; the table was added to that list (`NEW_TABLES`, under "spec 037") and the file's tests pass. That file is the only one changed after the run, so the suite was not run again: with it, 1454 passed (the 1371 of T001 plus 83 new), 0 failed. No library table changed: the same test checks that no existing table differs after the migrations. flake8 of the repository: 579. `make ci-check` was not run again; it fails on the repository before this branch (spec 033 T026).
- [X] T026 The step alone on the local database (ask the maintainer first; the maintainer makes `data/linkedin_run/linkedin.list` as quickstart.md section 0 describes, or asks for it; back up `db/horizon.db` before): quickstart.md sections 2, 3 and 4. Record under this task the summary line, every row of the expected table with the measured value, the second run (added 0, changed 0, removed 0), the remove-one/change-one check, and the no-list and empty-list checks. Confirm with `git status` that the list and the report are not shown.
  - Result (2026-11-13, passed): the list was generated by hand with the command of quickstart.md section 0 (182 lines; the command only reads the maintainer's alumni file); `db/horizon.db` copied to `data/_backup_2026-11-13_pre037/` before the first use. `git status` shows neither the list nor the report.
  - First run of `app.py linkedin_links`: exit 0, `linkedin links: lines 182, stored 148 (added 148, changed 0, removed 0), not found 34, several persons 0, conflicts 0, invalid 0`, followed by 34 lines with the names not found. The table did not exist before the run; the step's migration created it.
  - Expected table: lines 182 (182); links stored 148 (about 148); not found 34 (about 34); several persons, conflicts, invalid 0 (0); stored + unused = lines (148 + 34 = 182); links on a missing person 0; links not in normal form 0; persons 18,329 before and after.
  - Second run: added 0, changed 0, removed 0; the 148 rows are identical, `updated_at` included.
  - One stored line removed and the link of another changed: `lines 181, stored 147 (added 0, changed 1, removed 1)`; 146 rows kept their `updated_at` and one row has the new one. With the original list back: `added 1, changed 1, removed 0`, 148 rows.
  - No list file: exit 0, `linkedin links: no list at data/linkedin_run/linkedin.list, nothing changed`, the 148 rows unchanged. Empty list file: exit 0, `linkedin links: the list has no usable line, nothing changed (...)`, the 148 rows unchanged. The list was put back and is identical to the generated one.
- [X] T027 Local weekly run with the list (ask the maintainer first): quickstart.md section 5. Record the phase's summary line from the log, the number of entries with `linkedin_url` in `researchers_canonical.json` and `students_canonical.json`, that every entry has the key, and the comparison of persons, advisorships, projects and `horizon_ids` with the database before the run.
  - Result (2026-11-13, passed): `data/lattes_json` and `data/raw` added to `data/_backup_2026-11-13_pre037/`, with the database after T026. Weekly 18:40-19:31, exit 0, 23 phases with exit 0 (`linkedin_links` between `consolidate_duplicates` and `assign_horizon_ids`), rule version 6, no reset.
  - Summary line of the phase: `linkedin links: lines 182, stored 148 (added 0, changed 0, removed 0), not found 34, several persons 0, conflicts 0, invalid 0`, with the 34 names not found listed. The 148 rows are identical to those of T026, `updated_at` included.
  - Exports: every entry has the key `linkedin_url`. With a link: `researchers_canonical.json` 148 of 18,329; `students_canonical.json` 146 of 11,714; `researchers_only_canonical.json` 1 of 2,579; `outside_ifes_canonical.json` 1 of 3,323; `null_researchers_canonical.json` 0 of 713.
  - Against the database before the run: persons 18,329 and their permanent ids identical (0 differ); projects 3,633 and their ids identical; articles 8,060. Advisorships 11,881 -> 11,888 (4 ids gone, 11 new): 3 of the 435 curricula changed on download and the phase processed those 3 documents (432 skipped; no SigPesq advisorship row processed), so the difference comes from the sources, not from this feature, which writes only its own table.
- [X] T028 Second local weekly run over the same list (ask the maintainer first): record that the phase reports added 0, changed 0, removed 0 and that the table is identical to the one after T027, apart from links of persons merged or changed by the sources, each explained.
  - Result (2026-11-13, passed): database of T027 copied to `data/_backup_2026-11-13_pre037/horizon_after_run1.db`; second weekly 19:31-20:06, exit 0, 23 phases with exit 0, rule version 6, no reset.
  - Summary line of the phase: `linkedin links: lines 182, stored 148 (added 0, changed 0, removed 0), not found 34, several persons 0, conflicts 0, invalid 0`. `person_linkedin_links` is identical to the one after T027 (148 rows, `updated_at` included).
  - Exports: `researchers_canonical.json` 148 with a link of 18,330, every entry with the key.
  - Other differences, from the sources: 4 curricula processed again (431 skipped) in each Lattes phase; persons 18,329 -> 18,330 (1 new id, none gone), articles 8,060 -> 8,064, 4 advisorship ids removed and 4 created; projects and their ids identical. No link moved, was added or was removed.
- [X] T029 GitHub Actions (only if the maintainer asks; only on the RafaelDeps fork, never upstream; push without force): quickstart.md section 6, one weekly run on this branch to show the phase reports "no list" and the run ends as before. Record the result, or record that the maintainer chose not to run it.
  - Not run, by the maintainer's decision of 2026-11-13: the fork has no list, so a run there cannot validate the feature; the behaviour without a list is covered by T021, T022 and the no-list check of T026.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001. T002 -> T003; T004; T005 -> T006 (after T004). Blocks every story.
- **US1 (Phase 3)**: after Phase 2. T007, T008, T009 -> T010 -> T011 -> T012.
- **US2 (Phase 4)**: after US1 (it completes the same `plan` and the same flow). T013, T014 -> T015 -> T016.
- **US3 (Phase 5)**: after US2. T017, T018 -> T019 -> T020.
- **US4 (Phase 6)**: after US3. T021 -> T022.
- **Polish (Phase 7)**: after the stories; T026, T027, T028 and T029 need the maintainer's approval, in that order.

### Within Each User Story

- Tests first, seen failing, then the implementation.
- Tasks in the same file run in sequence: src/core/logic/linkedin_links.py (T003, T010, T015, T019, T022); src/flows/maintenance/linkedin_links.py (T011, T016, T022); src/adapters/database/linkedin_link_store.py (T006, T020); tests/test_linkedin_links.py (T002, T007, T013, T017, T021); tests/test_linkedin_links_flow.py (T009, T014, T017, T021).

### Parallel Opportunities

- T004 (migration) beside T002-T003 (the rule).
- T008 (exporter tests) beside T007.
- T014 beside T013; T018 beside T017.
- T023 beside T024.

---

## Parallel Example: User Story 1

```bash
Task: "T007 plan tests in tests/test_linkedin_links.py"
Task: "T008 exporter tests in tests/test_canonical_exporter.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 and 2)

1. T001, then T002-T006 (line, table, store).
2. T007-T012: links stored and exported.
3. T013-T016: every unused line reported. The two P1 stories together are the first version worth running on real data.

### Incremental Delivery

1. US1: the link reaches the exports.
2. US2: nothing is guessed, everything is reported.
3. US3: the list rules; merged persons keep the link.
4. US4: no list, no harm (what GitHub Actions needs).
5. Polish: documents, lint, full suite, then the local validations that need approval.

---

## Notes

- No identity rule, permanent id or rule version changes; no rebuild is needed.
- No library table is altered; the link lives in an ETL-owned table.
- The list is local and never versioned; tests never touch `data/` or the real database.
- Commit only when the maintainer asks; never stage `data/`, `logs/`, `PLANO_*.md`, `RESUMO_*.md` or `data/exports/exports_canonical.zip`.
