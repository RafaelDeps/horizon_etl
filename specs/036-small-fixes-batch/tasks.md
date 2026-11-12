---

description: "Task list for spec 036: small fixes batch"
---

# Tasks: Small fixes batch

**Input**: Design documents from `specs/036-small-fixes-batch/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/small-fixes.md, quickstart.md

**Tests**: Included. The constitution's development workflow requires tests,
and the plan writes them before the change (they must fail first).

**Organization**: Tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 to US5)

Code: `src/core/logic/student_name_rules.py` (new, the name rule),
`src/adapters/sources/lattes_parser.py` (student of an advisorship item),
`src/flows/lattes/advisorships.py` (summary line),
`src/core/logic/initiative_handlers.py` (fellowship sponsor),
`src/core/logic/project_enrichment.py` (indexes without advisorships),
`src/core/logic/strategies/sigpesq_projects.py` and
`src/core/logic/project_loader.py` (content compared for change),
`src/core/logic/horizon_identity.py` (rule version).
Tests: `tests/test_student_name_rules.py` (new),
`tests/test_fellowship_sponsor_storage.py` (new), `tests/test_lattes_parser.py`,
`tests/test_initiative_handlers.py`, `tests/test_project_enrichment_db.py`,
`tests/test_sigpesq_project_mapping.py`, `tests/test_project_loader_matching.py`,
`tests/test_rule_version_guard.py`.

Terms used below (contracts/small-fixes.md, data-model.md):

- **Student text**: `item.get("orientando") or item.get("nome_do_orientado")` of a curriculum advisorship item.
- **Kinds**: the tuple returned by the rule, any of `empty`, `link`, `several`, `work_title`, `uncut`, `title`, `footnote`, `not_a_name`.
- **Initial**: the token right before a full stop, when it has one or two letters ("Q" in "Q.") or itself holds a full stop ("S.N" in "S.N.").
- **Change content**: what the loader hashes to decide whether a document changed.

Rules for every task: no change to third-party libraries, to the dashboard or
to Docker; never read or print `.env`; the checks print counts and public
names only, never a CPF or a phone number; the weekly is never run without
asking the maintainer first.

---

## Phase 1: Setup

**Purpose**: a known starting point.

- [X] T001 Record the starting point in this file under this task: branch `036-small-fixes-batch` at the commit of branch 035 (`git log --oneline -1`), the full suite result before any change (`.venv/bin/python -m pytest -q > logs/pytest_036_before.log 2>&1`; expected 1251 passed, 10 skipped) and the flake8 count of the repository (`.venv/bin/python -m flake8 src tests | wc -l`; expected 579). No code change.
  - Result: branch `036-small-fixes-batch` at `535621d` (the tip of branch 035); full suite before any change: 1251 passed, 10 skipped, 0 failed in 8m40 (logs/pytest_036_before.log, line 29); flake8 on `src tests`: 579.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the name rule, a pure function that User Story 1 needs. The
other stories need nothing shared.

- [X] T002 Create tests/test_student_name_rules.py with one parametrized test per row of the table in contracts/small-fixes.md section 1 (input, expected `name`, expected `kinds`), importing `clean_student_name` and `CleanedName` from `src.core.logic.student_name_rules`, plus two property tests: the same input gives the same output twice, and for every row whose result has a name and neither `several` nor `uncut`, `clean_student_name(result.name)` returns the same name with `kinds == ()`. Run it and see it fail on the import.
  - Result: tests/test_student_name_rules.py written from the contract table (37 rows, three parametrized tests and one link + several test); the run failed on the import, as expected.
- [X] T003 Create src/core/logic/student_name_rules.py: frozen dataclass `CleanedName(name: Optional[str], kinds: tuple)` and `clean_student_name(raw) -> CleanedName` implementing the seven steps of contracts/small-fixes.md section 1 in that order, standard library only (`re`, `dataclasses`, `typing`), with a module docstring that states the rule and names branch 036. Titles are matched as whole words, case-insensitive, at the start and at the end only. Run tests/test_student_name_rules.py until every row passes; then run the rule over every student text of `data/lattes_json/*.json` (read only, as in quickstart.md section 2, "curriculum items by kind") and record the counts under this task; they must agree with research R2 (work_title about 152 items, several 158, not_a_name 4, footnote 2, title 1, link 1, uncut 1). If a count differs, list the texts that explain it before going on.
  - Result: module written; 93 passed. While writing it the contract gained two details, both on the side of leaving the text alone: a title before a full stop ("Prof.", "Dr.") does not end the name, and a text with a comma and no work title is several people ("A, B, C", or a surname-first form), returned as written. The full words "Mestre", "Doutor", "Professor" are removed at the start only (at the end they may be a surname). Over the 11,601 student texts of the 435 curricula (9,353 distinct): work_title 150 items (149 texts), footnote 2, title 1, link 1, uncut 1, not_a_name 4, several 317, no cleaning 11,125. Against research R2: the names cleaned and the texts that are not a name agree (work_title 149 texts against 151: two heads joined by "e" are now several); `several` is 317 instead of 158 because 159 comma lists, counted as "needs no cleaning" in R2, now carry the label. They are stored as today in both cases.

**Checkpoint**: the rule exists and is covered; nothing uses it yet.

---

## Phase 3: User Story 1 - Students are stored under their name only (Priority: P1) 🎯 MVP

**Goal**: the parser gives the clean name; a text that is not a name creates no person and the item is kept; the run reports the counts.

**Independent Test**: parse a curriculum whose advisorship items hold each kind of student text; check `student_name`, `student_name_kinds` and which items are kept.

### Tests for User Story 1

- [X] T004 [US1] In tests/test_lattes_parser.py add tests for `LattesParser.parse_advisorships`, covering both paths (the `orientacoes` structure read by `_parse_items` and the flat lists read by `_parse_generic_advisorships`), following the fixtures already used in that file for advisorships: (a) "Guilherme Lopes de Oliveira. Uso do método OTA (PT 10550)" gives `student_name == "Guilherme Lopes de Oliveira"` and `student_name_kinds == ("work_title",)`; (b) "Dr. Hamilton Carvalho Tolosa" gives the name without the title; (c) "Maria da Silva" gives the same name and `student_name_kinds == ()`; (d) "Rafael Scopel Paviotti/Sidarta Barroso Veloso" is unchanged with `("several",)`; (e) "Acadêmicos do 6 periodo" keeps the item with `student_name is None` and `"not_a_name"` in the kinds; (f) an item with a title and no student text is dropped, as today; (g) the raw input dict is not modified. Run them and see (a), (b), (e) fail.
  - Result: four tests added, each run over both paths (8 cases); before the change 6 failed: the work title was kept, the text that is not a name was kept as the name, and an item whose student text is only spaces was kept (it is now dropped as an item with no student text).

### Implementation for User Story 1

- [X] T005 [US1] In src/adapters/sources/lattes_parser.py import `clean_student_name` and, in `_parse_items` and in `_parse_generic_advisorships`, replace the direct use of the student text: keep the raw text in a local variable, call the rule once, set `student_name` to the cleaned name and add `"student_name_kinds": cleaned.kinds` to the parsed dict; change the condition that keeps an item from `if title and student_name` to "title and the raw student text is not empty" (so an item whose text is not a name is kept with `student_name = None`, and an item with no student text is still dropped). Do not change any other field. Run tests/test_lattes_parser.py and tests/test_student_name_rules.py: all pass.
  - Result: `LattesParser._advisorship_student` calls the rule once; both paths use it, add `student_name_kinds` and keep the item when the text is not empty. tests/test_lattes_parser.py and tests/test_student_name_rules.py: 120 passed.
- [X] T006 [US1] Check the path of an item without a student, with tests only: in tests/test_lattes_advisorships_loader_reuse.py (or tests/test_loader_mapping.py, whichever already builds a `LattesAdvisorshipMappingStrategy`) add a test that `map_row` of a parsed row with `student_name = None` gives `student_names == []` and an identity key, and in tests/test_initiative_handlers.py a test that `AdvisorshipHandler._student_person` returns `None` and `item_student` returns `(None, "")` for `student_names == []`. If either fails, fix only the line that fails in src/core/logic/strategies/lattes_advisorships.py or src/core/logic/initiative_handlers.py and record it here; if both pass without a code change, record that.
  - Result: no code change needed. `map_row` with `student_name = None` gives `student_names == []` and an identity key (test in tests/test_lattes_advisorships_loader_reuse.py); `_student_person` returns `None` and `item_student` returns `(None, "")` without asking the person matcher (test in tests/test_initiative_handlers.py).
- [X] T007 [US1] In src/flows/lattes/advisorships.py add the run summary: a module-level helper `log_student_name_summary(counts, logger)` that logs one line `student names: title N, link N, work title N, footnote N, not a name N, several N, uncut N`; in `ingest_advisorships_file_task`, after `parser.parse_advisorships(data)` is deduplicated, add each kept row's `student_name_kinds` to a `collections.Counter` kept on the shared loader (`project_loader.student_name_counts`, created when absent; a standalone call with no shared loader uses a local counter and logs it at once); in `_ingest_lattes_advisorships`, call the helper next to `project_loader.person_matcher.log_match_summary("lattes_advisorships")`. Add a test in tests/test_lattes_advisorships_loader_reuse.py that the helper logs the seven counts for a given counter. Run the three test files of this story.
  - Result: the counts are kept in the flow module (`count_student_names`, `log_student_name_summary`), not on the loader: simpler, and the loader is a stub in the flow's tests. The line is logged once at the end of the phase and at once when the task runs alone. It counts the curricula processed in the run; unchanged curricula are skipped and not counted. The story's test files and tests/integration/flows/test_ingest_lattes_advisorships.py: 139 passed.

**Checkpoint**: User Story 1 works on parsed curricula; the database is not touched yet, because the rule version changes only in User Story 5.

---

## Phase 4: User Story 2 - A fellowship is stored once (Priority: P2)

**Goal**: a new fellowship is stored with its sponsor, so the next run finds it.

**Independent Test**: create a fellowship through the handler with a sponsor, reload the cache from what was stored, ask again: the same fellowship, nothing created.

### Tests for User Story 2

- [X] T008 [P] [US2] Create tests/test_fellowship_sponsor_storage.py, a test against the real domain entities on an in-memory SQLite database (tables created from the library's metadata, one `Organization` row inserted): (a) `Fellowship(name="JTC", value=0.0, sponsor_id=<org id>)` added and committed is read back with `sponsor_id` empty: this records the library behaviour found in research R5; (b) the same fellowship, with `sponsor_id` assigned again after it was added and flushed, is read back with the sponsor. If (a) reads the sponsor back, research R5 is wrong: stop, record what was seen under this task and ask the maintainer before T010.
  - Result: 2 passed: with the library's real entities on an in-memory database, `Fellowship(name, value, sponsor_id=3)` is stored with `sponsor_id` empty, and setting `sponsor_id` again after the row exists stores it. Research R5 is confirmed.
- [X] T009 [US2] In tests/test_initiative_handlers.py add, in the style of `test_advisorship_handler_reuses_fellowships_by_program_and_sponsor_across_workplans` (mocked controllers): (a) `_ensure_fellowship` for a row with programme "JTC" and sponsor "CNPq" and an empty cache calls `fel_controller.create` once and then `fel_controller.update` once with a fellowship whose `sponsor_id` is the id returned by `ensure_organization`; (b) a handler whose `get_all` returns that stored fellowship (name "JTC", `sponsor_id` set, sponsor name "CNPq") returns it for the same row and calls neither `create` nor `update`; (c) a row with a programme and an empty sponsor creates one fellowship, no `update`, and a second handler preloaded with it creates none; (d) sponsor written " cnpq " finds the fellowship stored under "CNPq". Run them and see (a) fail.
  - Result: three tests added (new row: `create` then `update`; stored with sponsor: found, also with the sponsor written " cnpq ", nothing created or updated; no sponsor: created once, no update, found by a handler loaded from it). Before the change the first failed (no `update`).

### Implementation for User Story 2

- [X] T010 [US2] In src/core/logic/initiative_handlers.py, `AdvisorshipHandler._ensure_fellowship`: right after `self.fel_controller.create(fellowship)`, when `sponsor_id` is not `None`, set `fellowship.sponsor_id = sponsor_id` and call `self.fel_controller.update(fellowship)`, with a comment that the library's constructor clears the sponsor of a new fellowship (branch 036, research R5); keep the `_cache_fellowship` call after it. Nothing else changes. Run tests/test_initiative_handlers.py and tests/test_fellowship_sponsor_storage.py.
  - Result: five lines in `_ensure_fellowship`. One existing assertion changed in `test_ensure_fellowship_updates_stale_value_on_existing_fellowship`: `update` is now called twice in that scenario (the sponsor of the new row, then the changed value) instead of once. tests/test_initiative_handlers.py and tests/test_fellowship_sponsor_storage.py: 21 passed.

**Checkpoint**: User Stories 1 and 2 pass their tests independently.

---

## Phase 5: User Story 3 - A project PDF is attached to a research project only (Priority: P2)

**Goal**: an initiative that has a row in `advisorships` is never matched by a project PDF.

**Independent Test**: enrich a PDF whose title equals the name of an advisorship stored with the type "Research Project"; the advisorship is untouched.

### Tests for User Story 3

- [X] T011 [US3] In tests/test_project_enrichment_db.py add an `advisorships` table (`id INTEGER PRIMARY KEY`) to the `session` fixture and a helper `add_stored_advisorship(session, init_id, name)` that inserts the initiative with `initiative_type_id` of "Research Project" (as the loader stores it) and a row in `advisorships`; add tests: (a) a PDF whose title equals that advisorship's name: `run()` leaves its `description` and `enrichment_json` empty and counts the PDF as unmatched; (b) with `ingest_new=True` no initiative is created and the PDF is counted as a skipped duplicate; (c) a PDF whose title is similar (above the fuzzy threshold) to that advisorship only is not matched; (d) a SigPesq project source record whose assertion points to that advisorship is not in the code index; (e) a research project with the same title as a PDF is still enriched when an advisorship row with another title exists. Check that the existing tests of the file still pass with the new table. Run and see (a), (c), (d) fail.
  - Result: five tests added with a fixture that creates the `advisorships` table and a helper that stores an advisorship with the type of a research project. Before the change four failed: (a) exact title, (b) no project created, (c) similar title and (d) code pointing to the advisorship; (b) failed because the PDF was matched instead of counted as a duplicate. The 14 existing tests of the file pass unchanged.

### Implementation for User Story 3

- [X] T012 [US3] In src/core/logic/project_enrichment.py add `AND NOT EXISTS (SELECT 1 FROM advisorships a WHERE a.id = i.id)` to the query of `_load_research_project_names`, and the same exclusion on `aa.canonical_entity_id` to the query of `_load_code_index`; update the two docstrings (an advisorship is recognised by its row in `advisorships`, not by its stored type; branch 036, research R6). If the `advisorships` table may be absent in a caller's database (check `ensure_schema` and the other tests of the enrichment), guard the exclusion so the query still runs. Run tests/test_project_enrichment.py, tests/test_project_enrichment_db.py and tests/test_project_enrichment_lock.py.
  - Result: `_not_an_advisorship(id_column)` builds the exclusion and both index queries use it. The condition is left out when the database has no `advisorships` table (the older tests of the enrichment build one without it). tests/test_project_enrichment.py, tests/test_project_enrichment_db.py and tests/test_project_enrichment_lock.py: 79 passed.

**Checkpoint**: User Stories 1 to 3 pass their tests independently.

---

## Phase 6: User Story 4 - The order of the names of a SigPesq project does not matter (Priority: P3)

**Goal**: a SigPesq project row with "Estudantes" or "Pesquisadores" in another order is unchanged.

**Independent Test**: the change content of a row and of the same row with reordered lists is equal; with a name added it differs.

### Tests for User Story 4

- [X] T013 [P] [US4] In tests/test_sigpesq_project_mapping.py add tests for `SigPesqProjectMappingStrategy.change_content(row)` using `stable_hash` from `src.tracking.recorder`: equal hash for a row and the same row with "Estudantes" reordered, with "Pesquisadores" reordered, and with spaces around names and `;`; different hash with a name added, with a name removed, and with "Titulo" changed; an empty or missing list gives `[]`; the input row is not modified. Run and see them fail (no such method).
  - Result: three tests added (reordered lists and spaces give the same hash; a name added or removed, or another column, gives another hash; empty and missing lists give `[]` and the row is not modified); they failed first (no `change_content`).
- [X] T014 [US4] In tests/test_project_loader_matching.py add tests for the loader, in the file's style (a `ProjectLoader` built with `ProjectLoader.__new__` and stubs): a helper method `_change_content(row)` returns `self.mapping_strategy.change_content(row)` when the strategy has that method and the row itself otherwise (strategy `None` included). Run and see them fail.
  - Result: two tests added; they failed first (no `_change_content`).

### Implementation for User Story 4

- [X] T015 [US4] In src/core/logic/strategies/sigpesq_projects.py add `change_content(self, row) -> dict`: a copy of the row in which "Estudantes" and "Pesquisadores" are replaced by `sorted(self._parse_names(value))`, with a docstring (the portal reorders the two lists between downloads; branch 036, research R7). In src/core/logic/project_loader.py add `_change_content(self, row_dict)` as specified in T014 and use it in the one place that calls `doc.unchanged(row_dict)` (`doc.unchanged(self._change_content(row_dict))`); the row passed to `_process_row_safely` and to tracking stays the raw row. Run tests/test_sigpesq_project_mapping.py, tests/test_project_loader_matching.py, tests/test_field_merge_loaders.py and tests/test_incremental_cnpq_sigpesq.py.
  - Result: `SigPesqProjectMappingStrategy.change_content` and `ProjectLoader._change_content`, used in the one call of `doc.unchanged`. The six related test files (the four of the task plus tests/test_advisorship_same_title.py and tests/test_sigpesq_full_flow.py): 59 passed.

**Checkpoint**: User Stories 1 to 4 pass their tests independently.

---

## Phase 7: User Story 5 - A database filled before the fixes is repaired (Priority: P3)

**Goal**: the rule version changes, so the weekly rebuilds an older database once.

**Independent Test**: a database recorded under version 5 needs a reset.

- [X] T016 [US5] In tests/test_rule_version_guard.py add `test_a_database_written_before_spec_036_needs_a_reset`, a copy of the test of spec 035 with the recorded version 5. Run and see it fail.
  - Result: test added; it failed with the version at 5.
- [X] T017 [US5] In src/core/logic/horizon_identity.py set `HORIZON_RULE_VERSION = 6` and add the comment line `# 6 (branch 036): the student of a Lattes advisorship is stored under the clean name, so persons named with the title of a work, an academic title or a link are renamed by one rebuild.` Search the tests for the literal version 5 used as "current" (`grep -rn "HORIZON_RULE_VERSION\|rule_version" tests`) and adjust only assertions that compare with the current version. Run tests/test_rule_version_guard.py and the id tests (`tests/test_horizon_id*.py`).
  - Result: `HORIZON_RULE_VERSION = 6` with its comment. No other test compares with a literal current version (they import the constant). tests/test_rule_version_guard.py, tests/test_horizon_id_assigner.py, tests/test_horizon_ids_flow.py, tests/test_ensure_db.py and tests/test_save_horizon_id_history.py: 40 passed.

**Checkpoint**: every story is in place; a run on an older database now rebuilds it.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T018 [P] Update docs/backlog.md: mark TD-034 (duplicate "JTC" fellowship) and TD-038 (project PDF on an advisorship) as implemented by branch 036 with the cause found (research R5, R6) and "validation pending"; add after the last entry: `TD-048 — Person names with extra text outside Lattes advisorship students` (50 persons: 27 with an academic title and 14 that are not a name, from the advisor fields of academic educations; 9 in project teams; research R4; Status: Open), `TD-049 — Advisorships are stored with the type "Research Project"` (11,367 of 11,876; the loader writes its own type for every row; consumers must use the `advisorships` table; research R6; Status: Open), `TD-050 — The library's Fellowship constructor clears the sponsor` (worked around in the handler; Status: Open, depends on the library), `TD-051 — Student fields with several people` (158 texts stored as one person; splitting needs more than one student per advisorship; Status: Open). Check first that no entry with these numbers exists and renumber if needed.
  - Result: TD-034 and TD-038 marked as implemented by branch 036, with the cause; TD-048 to TD-051 added (no entry had those numbers). TD-051 records 317 texts, the count of the final rule (T003), not the 158 of the first measurement.
- [X] T019 [P] Run black, isort and flake8 on the touched files only (src/core/logic/student_name_rules.py, src/adapters/sources/lattes_parser.py, src/flows/lattes/advisorships.py, src/core/logic/initiative_handlers.py, src/core/logic/project_enrichment.py, src/core/logic/strategies/sigpesq_projects.py, src/core/logic/project_loader.py, src/core/logic/horizon_identity.py and the touched test files) with `--check`/`--diff` first; apply the formatters only where they change lines of this branch; record the flake8 count of the repository (must not grow from T001).
  - Result: black changed three test files and isort one source file, only in lines this branch wrote (the four files were clean before); the other 13 touched files needed nothing. flake8 on the touched files: 14 findings before and 14 after (lattes_parser.py 2, initiative_handlers.py 5, project_loader.py 7), all in lines this branch did not write; the new files have none. Repository: 579 (579 at T001).
- [X] T020 Run the full suite (`.venv/bin/python -m pytest -q > logs/pytest_036_full.log 2>&1`) and record the result under this task; expected: every test of T001 still passes plus the new ones, 0 failed. Record `make ci-check` as in spec 033 T026.
  - Result: 1371 passed, 10 skipped, 0 failed in 7m34 (logs/pytest_036_full.log, line 31): the 1251 of T001 plus 120 new. The formatters of T019 ran after it; the five test files they or their code touch were run again: 68 passed. `make ci-check` was not run again; it fails on the repository before this branch (spec 033 T026).
- [X] T021 First local run, the rebuild (ask the maintainer first; back up `db/horizon.db` and `data/` to `data/_backup_<date>_pre036/` with a RESTORE.txt before it): quickstart.md section 2. Record under this task: the rule-version reset, the summary line of student names, every row of the expected table with the measured value, the counts of the other tables against the backup, and the number of person and advisorship ids that became aliases or were retired.
  - Result (2026-11-12, passed): inputs and id history copied to `data/_backup_2026-11-12_pre036/` (RESTORE.txt). The database was recreated empty with `make db-reset` before the run, so the rule-version reset of the weekly's guard was not exercised here (it is covered by T016/T017); the database of branch 035 used for comparison is `data/_backup_2026-11-11_post035_run1/horizon.db` (its rebuild, rule version 5). A first attempt was stopped by the maintainer at 16:07 during the report phases and discarded; the run recorded here is the next one, from an empty database: 17:53-18:54, exit 0, 22 phases with exit 0, integrity ok, rule version 6. 17 of 435 curricula differ from the copy of branch 035.
  - Summary line of the run: `student names: title 1, link 1, work title 150, footnote 2, not a name 3, several 317, uncut 1` (T003 measured 4 texts that are not a name; 3 items reached the phase).
  - Fix 1: students of advisorships whose stored name the rule would still change: work_title 148, title 1, link 1, footnote 2, not_a_name 4 before -> none after; only `several` (309) and `uncut` (1) remain, as before. Persons 18,429 -> 18,330. Advisorships without a Student 0 -> 3 (ids 7918, 7919, 12251, each with its Supervisor); without a Supervisor 0 -> 0; with more than one Student 0; duplicate initiative names 0.
  - Fix 2: fellowships 20 -> 20; without a sponsor 2 -> 0 ("JTC" now CNPq, "PICTI" now Fapes).
  - Fix 3: advisorships with PDF data 4 -> 0; projects with PDF data 273 -> 274.
  - Other tables: advisorships 11,877 -> 11,881; projects 3,633 -> 3,633; articles 8,056 -> 8,058; professional activities 9,555 -> 9,557; academic educations 1,962; research groups 353; awards 183 (the small differences come with the 17 changed curricula).
  - Old ids (FR-023): person ids 156 no longer current and 57 new; of the old ones 155 more are reported as retired (2,039 -> 2,194) and 2 more as "key corrected" aliases (25 -> 27): the id of a person known by name only cannot be linked to the clean name, so it is retired, not aliased. Advisorship ids 164 no longer current and 168 new (the Lattes identity of an advisorship holds the student's name); advisorship aliases, which count the advisorship and its team id: retired 244 -> 543, key corrected 37 -> 51.
- [X] T022 Second local run (ask the maintainer first; keep a copy of the database of T021): quickstart.md section 3. Record under this task every difference between the two databases with its explanation; expected: one "JTC", no fellowship created, no advisorship with PDF data, no description rewritten for an unchanged source, and the document summary of the SigPesq projects.
  - Result (2026-11-12, passed): database of T021 copied to `data/_backup_2026-11-12_post036_run1/`; second weekly 18:56-19:41, exit 0, 22 phases with exit 0, integrity ok, rule version 6, no reset. Documents processed again: sigpesq_group 2 (351 skipped), sigpesq_project 2 (101 skipped), sigpesq_advisorship 60 (1,143 skipped), cnpq_group 6 (344 skipped), lattes_projects 90 (345 skipped), lattes_advisorships 49 (386 skipped).
  - Fix 2: `fellowships` identical in the two databases (20 rows, one "JTC" with sponsor CNPq); no advisorship changed fellowship apart from the two created again below.
  - Fix 3: 0 advisorships with PDF data; no `enrichment_json` changed on any initiative that exists in both databases; `description` changed on 0 advisorships and on 2 projects (3945, 3946), explained below.
  - Fix 4: the two SigPesq project rows processed again (8308, 7220) have the same content hash as in the first run; they were processed because their references had to be checked, not because of their content. The report of the first run is not kept (the folder is cleared before each download), so a reordered row between these two downloads cannot be shown directly; between the report of 2026-11-11 and the one of this run 18 rows have "Estudantes" in another order and 0 a real change, and none of them was processed. Evidence of the rule itself: the tests of T013.
  - Fix 1: `persons` 18,330 -> 18,329 (person 9884, named "D", from an academic education, no longer exists; it is one of the persons of TD-048); Student changed on 0 advisorships that exist in both databases; summary line of the 49 curricula processed again: `title 0, link 0, work title 56, footnote 1, not a name 1, several 34, uncut 0`, and none of those names was written again.
  - Other differences, all explained: 2 advisorships removed and created again. 11399 -> 15515 is the item of TD-046 (d), whose title is written another way, the same one of branch 035 (T027 and the fork runs). 14464 -> 15516 and the descriptions of projects 3945 and 3946 come from one curriculum (3453479685020198) whose download in this run brought "?" in place of the dash and the quotation marks, so the title of the advisorship and the two descriptions changed at the source. Supervisor changed on 44 advisorships (TD-047, older than this branch). Articles 8,058 -> 8,060 (changed curricula). Projects, professional activities and the advisorship names of every other advisorship: no difference.
- [ ] T023 Fork validation (ask the maintainer first; only on the RafaelDeps fork, never upstream; push without force): quickstart.md section 4, two weekly runs on this branch. Record the numbers of both runs under this task.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001; T002 -> T003. Blocks only US1.
- **US1 (Phase 3)**: after Phase 2. T004 -> T005 -> T006 -> T007.
- **US2 (Phase 4)**: after T001; independent of US1. T008, T009 -> T010.
- **US3 (Phase 5)**: after T001; independent. T011 -> T012.
- **US4 (Phase 6)**: after T001; independent. T013, T014 -> T015.
- **US5 (Phase 7)**: after US1 to US4, so the version changes only when every fix is in place. T016 -> T017.
- **Polish (Phase 8)**: after the stories; T021, T022 and T023 need the maintainer's approval, in that order.

### Within Each User Story

- Tests first, and seen failing where the task says so, before implementation.
- Tasks in the same file run in sequence: tests/test_initiative_handlers.py (T006, T009); src/core/logic/initiative_handlers.py (T006 if needed, T010); tests/test_project_loader_matching.py (T014); src/core/logic/project_loader.py (T015); tests/test_lattes_advisorships_loader_reuse.py (T006, T007).

### Parallel Opportunities

- T008 (new file) can run beside T009.
- T013 touches a different file from T014.
- T018 and T019 touch different files.
- US2, US3 and US4 touch different source files and can be done in any order.

---

## Parallel Example: User Story 4

```bash
Task: "T013 change_content tests in tests/test_sigpesq_project_mapping.py"
Task: "T014 loader tests in tests/test_project_loader_matching.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001, then T002-T003 (the rule).
2. T004-T007: the parser gives clean names and the flow reports the counts.
3. Stop and check: the listed tests pass. The database is not touched yet, because the rule version changes only in US5.

### Incremental Delivery

1. US1: clean student names.
2. US2: the fellowship keeps its sponsor.
3. US3: PDFs only on research projects.
4. US4: reordered lists are unchanged.
5. US5: the version changes, which is what makes the weekly rebuild an older database.
6. Polish: backlog, lint, full suite, then the three validations that need approval.

---

## Notes

- No table, column, export field or id rule changes; no change to third-party libraries, to the dashboard or to Docker.
- T008 is the only test against real entities; it exists because the cause of the fellowship defect was read from the library's code and not yet seen in a run.
- The rule version changes last (T017), so no test run before it can leave a local database half under the new rules.
- Commit only when the maintainer asks; never stage `data/`, `logs/`, `PLANO_*.md`, `RESUMO_*.md` or `data/exports/exports_canonical.zip`.
