---

description: "Task list for spec 035: one advisorship per student when titles repeat"
---

# Tasks: One advisorship per student when titles repeat

**Input**: Design documents from `specs/035-one-advisorship-per-student/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/advisorship-matching.md, quickstart.md

**Tests**: Included. The constitution's development workflow requires tests,
and the plan writes them before the change (they must fail first).

**Organization**: Tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)

Code: `src/core/logic/advisorship_matching.py` (new, the rule),
`src/core/logic/project_loader.py` (index and lookup),
`src/core/logic/initiative_handlers.py` (student of an item, stored name kept),
`src/core/logic/horizon_identity.py` (rule version).
Tests: `tests/test_advisorship_matching.py` (new),
`tests/test_advisorship_same_title.py` (new),
`tests/test_project_loader_matching.py`, `tests/test_initiative_handlers.py`,
`tests/test_rule_version_guard.py`.

Terms used below (contracts/advisorship-matching.md, data-model.md):

- **Base title**: the name before the last ` | Orientacao`.
- **Years**: the range `(first, last)` from the start year to the end year; `None` when there is neither.
- **Years differ**: both ranges exist and share no year.
- **Same student**: same person id, or equal non-empty normalized names.
- **Index**: `loader._advisorship_index`, a dict `base title -> list of StoredAdvisorship`.

The loader tests follow the style of `tests/test_project_loader_matching.py`:
a `ProjectLoader` built with `ProjectLoader.__new__` (helper
`_loader_sem_banco`), mocked controllers and a stub handler; no real database.

---

## Phase 1: Setup

**Purpose**: Confirm the starting point.

- [X] T001 Run `.venv/bin/python -m pytest -q tests/test_project_loader_matching.py tests/test_initiative_handlers.py tests/test_rule_version_guard.py tests/test_lattes_advisorships_loader_reuse.py tests/test_sigpesq_advisorship_mapping.py` on branch `035-one-advisorship-per-student` and record the result (passed / failed counts) under this task in specs/035-one-advisorship-per-student/tasks.md; all must pass before any change.
  - Result (2026-11-11): 34 passed, 0 failed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The pure rule every story uses (research R3, R4, R7).

- [X] T002 Create tests/test_advisorship_matching.py with one parametrized test per table of specs/035-one-advisorship-per-student/contracts/advisorship-matching.md, every row of each table as a case: `test_base_title`, `test_year_range` (inputs as `datetime`, `date`, ISO text, `int` year and `None`), `test_years_differ`, `test_same_student`, `test_pick_match` (candidates built as `StoredAdvisorship(id, name, student_id, student_name, years)`; the expected result compared by `id`). Add `test_pick_match_never_returns_another_student` (10 candidates of other students, item with a student: `None`). Run it and see it fail on the import.
  - Result: failed on the import (`ModuleNotFoundError: src.core.logic.advisorship_matching`) before T003. Three more tests were added: the bare title then the lowest id as tie-breaks, and the person id deciding when the names differ.
- [X] T003 Create src/core/logic/advisorship_matching.py (pure: standard library plus `normalize_text` from `src.core.logic.initiative_identity`; no import from `src/adapters`, no database) with a module docstring naming spec 035, the constant `SUFFIX_MARK = " | Orientacao"`, the frozen dataclass `StoredAdvisorship(id, name, student_id, student_name, years)`, and the functions `base_title(name)`, `year_range(start, end)`, `years_differ(a, b)`, `same_student(item_id, item_name, stored_id, stored_name)` and `pick_match(item_student_id, item_student_name, item_years, candidates)` exactly as the contract states (order of preference a, b, c, d of `pick_match`; rule 2 for a candidate without a student; rule 3 for an item without a student). Run tests/test_advisorship_matching.py until it passes.
  - Result: 41 passed. The module needs no `normalize_text`; names arrive normalized. A helper `widen(a, b)` (the range that covers both) was added for the index.

**Checkpoint**: one module says when an item is a stored advisorship.

---

## Phase 3: User Story 1 - Every student keeps their advisorship when the title repeats (Priority: P1) 🎯 MVP

**Goal**: an item of another student is no longer written over a stored advisorship of the same title (FR-001, FR-004, FR-005, FR-006).

**Independent Test**: two items with the same title and different students reach the handler as two creations; the first advisorship keeps its student.

### Tests for User Story 1

- [X] T004 [US1] In tests/test_project_loader_matching.py add, using `_loader_sem_banco()` with `loader._advisorship_index` set by hand: `test_orientacao_de_outro_aluno_nao_casa_pelo_titulo` (index holds the title with student "ana"; `_lookup_existing_initiative(model_class=Advisorship, title=..., identity_key=None, project_data={"title": ..., "student_names": ["Bia"]}, existing_by_name={title: that advisorship}, existing_by_identity={})` returns `None`, even with the advisorship present in `existing_by_name`); `test_orientacao_do_mesmo_aluno_casa_pelo_titulo` (student "ANA" with accents and case changed: returns the stored advisorship); `test_identidade_vista_no_processo_tem_precedencia` (identity key present in `existing_by_identity`: that advisorship is returned without looking at the index); `test_projeto_nao_usa_o_indice_de_orientacoes` (model `Initiative`: resolved by name as before, the index is not read). Stub `loader._item_student` to return `(None, normalized name)` and `loader._load_advisorship` to return the candidate object by id. Run and see the first test fail.
  - Result: written after T006-T009 by mistake; checked against the code of branch 034 with the two source files stashed: the five new tests fail there (a fifth test, `test_orientacao_do_mesmo_aluno_em_outro_ano_nao_casa`, was added) and pass on this branch.
- [X] T005 [P] [US1] Create tests/test_advisorship_same_title.py with a helper that builds a loader as in tests/test_project_loader_matching.py (`_loader_sem_banco`, stub handler whose `create_or_update` returns a new `MagicMock(spec=Advisorship)` with `id` and with `name` equal to the title when no advisorship of that base title exists in `loader._advisorship_index`, else `f"{title} | Orientacao {student} | {year}"`; `tracking_recorder` patched; empty index). Tests: `test_alunos_diferentes_viram_orientacoes_diferentes` (the same title processed with `_process_row` for 49 different students: 49 calls with `existing_initiative=None`, `stats["created"] == 49`, 49 entries under that base title in the index, each with its own student name); `test_o_primeiro_fica_com_o_titulo_e_os_outros_com_nome_distinto` (the stub's names: one bare, 48 containing ` | Orientacao `); `test_segundo_item_do_mesmo_aluno_atualiza` (the same title and student twice: second call receives the first advisorship as `existing_initiative`, `stats["updated"] == 1`). Run and see them fail.
  - Result: written after T006-T009 by mistake; checked against the code of branch 034 with the two source files stashed: all fail there, all pass on this branch. The handler stub is a small class (`_Handler`) and one more test was added, `test_item_de_outro_aluno_nao_toca_a_orientacao_existente` (a third item of the first student goes back to the first advisorship, not to the last written).

### Implementation for User Story 1

- [X] T006 [US1] In src/core/logic/initiative_handlers.py add to `AdvisorshipHandler` the method `item_student(project_data) -> tuple[Optional[int], str]`: the person id from `self.person_matcher.match_or_create(student_names[0], email=student_emails[0], strict_match=True)` passed through `_coerce_to_person` (the same call `_resolve_advisorship_people` makes; `None` when the item has neither name nor e-mail or the matcher returns nothing) and `normalize_text(student_names[0] or "")`. Make `_resolve_advisorship_people` use it for the student so the matcher is asked in one place.
  - Result: done; `_student_person` holds the matcher call and `item_student` returns `(person id, normalized name)`.
- [X] T007 [US1] In src/core/logic/project_loader.py add the index: attribute `self._advisorship_index = None` in `__init__`; `_ensure_advisorship_index()` that fills it on first use with one query through `self.controller._service._repository._session` (`SELECT i.id, i.name, i.start_date, i.end_date, m.person_id, p.name FROM initiatives i JOIN advisorships a ON a.id = i.id LEFT JOIN advisorship_members m ON m.advisorship_id = a.id AND m.role_name = 'Student' LEFT JOIN persons p ON p.id = m.person_id`), building one `StoredAdvisorship` per advisorship (first Student row when there is more than one) under `base_title(name)`; `_remember_advisorship(initiative, title, student_id, student_name, years)` that adds the advisorship to the index or replaces its entry, keeping a stored student when the item has none and widening the stored years with the item's years; `_item_student(project_data)` that calls the advisorship handler's `item_student`; `_load_advisorship(advisorship_id)` that returns `self.adv_controller.get_by_id(id)`; and clear the index in `reset_caches`.
  - Result: done. The index is also read through `getattr`, because tests build loaders with `__new__`. `_item_student` keeps its answer in `project_data["_item_student"]`, so the matcher is asked once per item by the loader.
- [X] T008 [US1] In src/core/logic/project_loader.py change `_lookup_existing_initiative` and `_resolve_existing_initiative` to accept `project_data=None`, and pass `project_data` from the advisorship call in `_process_row` (the parent lookup keeps `model_class=Initiative` and passes none). For `model_class is Advisorship`: keep the identity-key step; then call `_ensure_advisorship_index()`, take the candidates of `title`, call `pick_match` with `_item_student(project_data)` and `year_range(project_data.get("start_date"), project_data.get("end_date"))`, and return `_load_advisorship(match.id)` or `None`; do not fall through to `existing_by_name`, `_lookup_existing_by_exact_name` or the normalized name. Other model classes run the existing steps unchanged. Replace the Portuguese comment about advisorships in that method with one English sentence pointing to spec 035.
  - Result: done (`_match_stored_advisorship`). A matched advisorship that can no longer be loaded is dropped from the index and the item is treated as new.
- [X] T009 [US1] In src/core/logic/project_loader.py, in `_process_row`, after `handler.create_or_update` returns an advisorship (both the created and the updated branch), call `_remember_advisorship` with the returned advisorship, the item's title, student and years. Leave `_register_existing_initiative` and `_register_identity` as they are.
  - Result: done; `_remember_advisorship` keys the entry by the base title of the stored name.
- [X] T010 [US1] Run `.venv/bin/python -m pytest -q tests/test_advisorship_matching.py tests/test_project_loader_matching.py tests/test_advisorship_same_title.py tests/test_initiative_handlers.py tests/test_lattes_advisorships_loader_reuse.py`; fix until all pass. `test_segunda_orientacao_de_mesmo_titulo_e_criada_e_nao_atualizada` and `test_orientacao_nao_casa_por_nome_normalizado` must still pass; if they need the new stubs (`_advisorship_index`, `_item_student`), add them without changing what they assert.
  - Result: 88 passed over the listed files plus tests/test_sigpesq_advisorship_mapping.py. Two existing tests received stubs only (`_advisorship_index` in `test_resolve_existing_initiative_prefers_same_model_when_identity_hits_wrong_type`; `handler.item_student` in `test_segunda_orientacao_de_mesmo_titulo_e_criada_e_nao_atualizada`); their assertions are unchanged.

**Checkpoint**: different students give different advisorships.

---

## Phase 4: User Story 2 - A replaced SigPesq student and the cancelled one each have an advisorship (Priority: P1)

**Goal**: a cancelled row and the row of the student who replaced it give two advisorships, in any row order (FR-010, TD-037).

**Independent Test**: two SigPesq rows with the same title, one cancelled with student A and one active with student B, give two creations, each with its own `cancelled` value.

### Tests for User Story 2

- [X] T011 [US2] In tests/test_advisorship_same_title.py add, with rows mapped by the real `SigPesqAdvisorshipMappingStrategy` (fields `Id`, `CodPT`, `TituloPT`, `Orientado`, `OrientadoEmail`, `Orientador`, `OrientadorEmail`, `Inicio`, `Fim`, `Cancelado`, `Programa`; invented names and e-mails): `test_aluno_substituido_e_cancelado_ficam_com_orientacoes_proprias` (row 1 cancelled with student A, row 2 active with student B, same `TituloPT`: two creations; the `project_data` of the first has `cancelled is True` and of the second `cancelled is False`; a `claim` spy shows the `cancelled` claims on two different advisorship ids); `test_ordem_das_linhas_nao_muda_o_resultado` (the same two rows in the opposite order: again two creations with the same student and `cancelled` pairs); `test_mesmo_aluno_cancelado_e_reativado_fica_em_uma_orientacao` (two rows of the same student with periods 2025-2026 and 2026-2026: one creation and one update).
  - Result: three tests added; they pass.

### Implementation for User Story 2

- [X] T012 [US2] Run tests/test_advisorship_same_title.py. The rule of US1 should satisfy T011 with no new code; if a test fails, fix the cause in src/core/logic/project_loader.py (index update or the values passed to `pick_match`), not in the SigPesq strategy, and record under this task what was needed.
  - Result: no new code was needed; the rule of US1 covers the three cases.

**Checkpoint**: SigPesq replacements no longer share an advisorship.

---

## Phase 5: User Story 3 - The same work recorded twice stays one advisorship (Priority: P2)

**Goal**: only different students or different years split; a matched advisorship keeps its name (FR-001a, FR-007, FR-008, FR-011, research R8).

**Independent Test**: the same title and student from two curricula give one advisorship, and the second item does not rename it.

### Tests for User Story 3

- [X] T013 [US3] In tests/test_advisorship_same_title.py add: `test_orientador_e_coorientador_ficam_em_uma_orientacao` (two Lattes items mapped by `LattesAdvisorshipMappingStrategy` for two different advisors, same title, student and year: one creation, one update); `test_lattes_e_sigpesq_do_mesmo_aluno_ficam_em_uma_orientacao` (a SigPesq row 08/2025 to 07/2026, then a Lattes item of the same title and student with year 2026: one creation, one update); `test_anos_diferentes_do_mesmo_aluno_viram_duas` (Lattes items of 2019 and 2020: two creations); `test_item_sem_ano_fica_na_orientacao_existente` (an item with a year, then one with `start_date` and `end_date` `None`: one creation, one update); `test_o_indice_e_carregado_do_banco` (the session stub returns rows `(id, name, start_date, end_date, person_id, person_name)` including one with a distinct name: after `_ensure_advisorship_index()` both are under the same base title with the right student and years, and an item of the stored student of the distinct-name row matches that row, not the bare one).
  - Result: five tests added; they pass.
- [X] T014 [P] [US3] In tests/test_initiative_handlers.py add, with `_advisorship_handler()`: `test_matched_advisorship_keeps_its_distinct_name` (`existing_initiative` named `"T | Orientacao Ana | 2019"`, item title `"T"` with another year and a `sigpesq_id`, bare title in use by another row: `update_initiative` is called with `name="T | Orientacao Ana | 2019"`); `test_matched_advisorship_keeps_its_bare_title` (`existing_initiative` named `"T"`: name stays `"T"`); `test_matched_advisorship_with_a_new_title_is_renamed_as_before` (`existing_initiative` named `"Old"`, item title `"T"`: the name is the one `_resolve_persisted_title` gives today). The existing `test_advisorship_handler_disambiguates_title_when_name_is_already_taken` must keep passing unchanged. Run and see the first test fail.
  - Result: three tests added; `test_matched_advisorship_keeps_its_distinct_name` fails on the code of branch 034 and passes here; the existing disambiguation test is unchanged and passes.

### Implementation for User Story 3

- [X] T015 [US3] In src/core/logic/initiative_handlers.py, in `AdvisorshipHandler.create_or_update`: when `existing_initiative` is given and `base_title(existing_initiative.name) == title`, use the stored name as `persisted_title` instead of calling `_resolve_persisted_title`; every other case is unchanged (new advisorship: bare title when free, else the distinct name; matched advisorship with another title: as today).
  - Result: done (written together with T006).
- [X] T016 [US3] Run `.venv/bin/python -m pytest -q tests/test_advisorship_same_title.py tests/test_initiative_handlers.py tests/test_project_loader_matching.py`; fix in src/core/logic/project_loader.py or src/core/logic/initiative_handlers.py until all pass, including `test_reconhecer_por_grafia_diferente_nao_renomeia_o_registro` and `test_projeto_casa_por_nome_normalizado` (projects unchanged, FR-011).
  - Result: all pass, including the two project tests named in the task.

**Checkpoint**: correct matches stay matches; names are stable.

---

## Phase 6: User Story 4 - A database that already holds the merged advisorships is repaired (Priority: P3)

**Goal**: a database written before this branch is rebuilt once (FR-014, FR-015, research R9).

**Independent Test**: a database recorded under rule version 4 needs a reset; one recorded under 5 does not.

### Tests for User Story 4

- [X] T017 [US4] In tests/test_rule_version_guard.py add `test_a_database_written_before_spec_035_needs_a_reset`, following `test_a_database_written_before_spec_034_needs_a_reset`: a database recorded under version 4 needs a reset, and `HORIZON_RULE_VERSION == 5`. Run and see it fail.
  - Result: failed before T018 (1 failed, 7 passed).

### Implementation for User Story 4

- [X] T018 [US4] In src/core/logic/horizon_identity.py set `HORIZON_RULE_VERSION = 5` and add the comment line for branch 035 after the line for branch 034: an advisorship item matches a stored advisorship of the same title only for the same student and years, so advisorships merged by title are split by one rebuild. Change no id rule.
  - Result: done.
- [X] T019 [US4] Run `.venv/bin/python -m pytest -q tests/test_rule_version_guard.py tests/test_horizon_identity.py tests/test_horizon_id_assigner.py`; update any test that pins the version to 4 and record which under this task.
  - Result: 90 passed; no test pinned the version to 4.

**Checkpoint**: the weekly will rebuild an older database.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T020 [P] In docs/backlog.md: mark TD-037 as fixed by branch 035 (implemented; validation pending); add an entry for this defect (same-title advisorships of different students merged; cause in research R1 and R2; numbers 10,260 -> about 11,890) with the next free TD number; add entries, each with the next free number, for (a) the `| Orientacao ...` suffix in advisorship names (needs the unique-name rule of the domain library to change), (b) the source identity of an initiative not being stored (research R2), (c) the limits of research R11 (7 pairs depending on the order across sources; 11 advisor/co-advisor pairs with different years). Keep TD-038 open. No blank line before a new entry beyond the file's own pattern; use only numbers that appear in research.md.
  - Result: TD-037 marked as implemented; new entries TD-043 (this defect), TD-044 (suffix in names), TD-045 (source identity not stored), TD-046 (limits of the rule). TD-038 stays open.
- [X] T021 [P] Run `.venv/bin/python -m black`, `isort` and `flake8` on src/core/logic/advisorship_matching.py, src/core/logic/project_loader.py, src/core/logic/initiative_handlers.py, src/core/logic/horizon_identity.py and the five test files; record under this task the flake8 count of the repository before and after (579 on branch 034) and that `make ci-check` fails on the repository before this branch (spec 033 T026).
  - Result: black and isort applied to the nine files; flake8 on the touched files: 12 findings before and 12 after, all in lines this branch did not write (unused imports and older code in project_loader.py and initiative_handlers.py); the new files have none. Repository: 579 findings (579 on branch 034). `make ci-check` fails on the repository before this branch (spec 033 T026).
- [X] T022 Run the full suite `.venv/bin/python -m pytest -q > logs/pytest_035_full.log 2>&1` and record passed / skipped / failed under this task (branch 034: 1188 passed, 10 skipped, 0 failed). Read the result line with `grep -n "passed" logs/pytest_035_full.log`, not from the last line of the log.
  - Result: 1250 passed, 10 skipped, 0 failed (logs/pytest_035_full.log, line 29); 62 more tests than branch 034.
- [X] T023 First local run per specs/035-one-advisorship-per-student/quickstart.md section 2. Ask the maintainer first. Before it, copy `db/horizon.db` and `data/` to `data/_backup_2026-11-11_pre035/` and check the copy opens. Run the weekly in the background with keep-awake, then run the quickstart checks and record every number of the expected table under this task, plus the count of advisorship ids that became aliases and the count retired. Never print a CPF or a phone number.
  - Result (2026-11-11): backup in `data/_backup_2026-11-11_pre035/` (database checked: integrity ok, 10,260 advisorships, rule version 4). The weekly started at 15:52, reset the database (rule version changed) and was stopped by the maintainer at 16:52, during `export_canonical`; every load phase, `consolidate_duplicates` and `assign_horizon_ids` had finished with exit 0. With the maintainer's choice, the remaining phases (`export_canonical` to `anonymize_backfill`) were run by hand in the weekly's order (logs/weekly_035_run1_tail.log) instead of repeating the whole run.
  - Numbers (before -> after): rule version 4 -> 5; advisorships 10,260 -> 11,877 (expected about 11,890); advisorships with more than one Student 0 -> 0; without a Student 0 -> 0; without a Supervisor 0 -> 0; duplicate initiative names 0 -> 0; distinct names 652 -> 2,268; "Estágio Supervisionado Obrigatório" 1 advisorship -> 49 advisorships of 48 students; cancelled advisorships 46 -> 117 (143 SigPesq rows are cancelled); 0 `UNIQUE constraint` errors and no failed phase in the log.
  - Items whose student has no advisorship of that title, by name: SigPesq 92 -> 0; Lattes 1,581 -> 106. The 106 were checked through their recorded match and none is a lost advisorship: 101 are attached to an advisorship of the same title whose student is the same person stored under another form of the name (96 one name contained in the other, 4 same first and last name, 1 spelling variant; lowest similarity 89), and 5 are attached to an advisorship whose title differs only in case or punctuation (same identity key in the same curriculum).
  - Items whose student has an advisorship of the title only in other years: SigPesq 10 -> 0; Lattes 186 -> 6. The 6 are attached to an advisorship: 5 belong to a SigPesq row of 08/2015-07/2016 (or 2019-2020) that also holds the curriculum's item of the other year, and the stored dates follow the newest document; 1 is attached to an advisorship whose student name has another form.
  - Other tables: projects 3,633 -> 3,633 (initiatives minus advisorships); articles 8,056 -> 8,056; professional activities 9,555 -> 9,555; academic educations 1,962 -> 1,962; research groups 353 -> 353; persons 18,428 -> 18,429.
  - Ids: advisorship ids by rule: Lattes identity 11,199, SigPesq workplan 676, PJ code 2 (TD-038), name 0. Of the 10,260 advisorship ids published before, 10,251 are still current; 8 became aliases (reason `rebuild`) and 1 was retired. Id report of the run: 75,806 entities, 30 collision groups, 22 new aliases.
  - The twelve remaining phases finished with exit 0 between 18:50 and 19:03; the database numbers above were read again after them and are the same.
- [X] T024 Second local run per quickstart.md section 3 (same approval; copy the database of T023 first): record that no advisorship whose sources did not change was written or renamed, and explain every difference.
  - Result (2026-11-11, NOT passed): database of T023 copied to `data/_backup_2026-11-11_post035_run1/`; second weekly 19:04-19:57, exit 0, no failed phase, no rule-version reset; 2 of 435 curricula changed on download. Documents processed again: lattes_advisorships 48 (387 skipped), sigpesq_advisorship 60 (1,143 skipped).
  - Defect found: 5 advisorships were created again as duplicates (ids 15511, 15513-15516). Each is a curriculum item of 2015 (or 2019) whose advisorship (143, 145, 153, 154, 283) also holds a SigPesq row of 08/2015-07/2016 and the curriculum's item of 2016. The field merge of branch 030 stored the dates of the newest document (2016-01-01 to 2016-12-31), so the stored years shrank from 2015-2016 to 2016, and when the curriculum was processed again its 2015 item no longer matched. The SigPesq dates are still in `source_field_claims`. This is the limit of research R11 reached through the stored dates, and it breaks FR-012 and SC-007. Fixed in T026; the run is repeated in T027.
  - Other differences, explained: 3 advisorships removed and 3 created by the 2 changed curricula and by one curriculum processed again (ids 9100, 14459, 11393 -> 15512, 15518, 15517); Student of an existing advisorship changed: 0 (24 between the two runs of branch 034); Supervisor changed on 44 advisorships, all fed by two curricula (advisor and co-advisor; the last curriculum processed keeps the single Supervisor), which already happened before this branch (61 between the two runs of branch 034); member start date changed on 6 advisorships (the five above and one more). Projects, professional activities: no difference; articles: 1 new, from a changed curriculum.
- [X] T026 Fix found in T024 (approved by the maintainer on 2026-11-11): in tests/test_advisorship_same_title.py add `test_os_anos_guardados_incluem_as_datas_que_cada_fonte_informou` (stored dates of 2016, claims of 2015-08-01 to 2016-12-31: the index gives years (2015, 2016), a 2015 item of the same student matches, a 2018 item is new), with the session stub answering the claims query; in src/core/logic/project_loader.py make `_ensure_advisorship_index` read `entity_id, value_json` of `source_field_claims` for `entity_type = 'advisorship'` and the fields `start_date` and `end_date`, and widen the years of each stored advisorship with them. Update research.md (R4, R11), data-model.md and the contract.
  - Result: the test failed before the change (years (2016, 2016)) and passes after it; 97 passed over the seven related test files; full suite 1251 passed, 10 skipped, 0 failed (logs/pytest_035_full.log, line 29); flake8 unchanged (7 older findings in project_loader.py, 579 in the repository). Simulation on the database of T023 (read only, the item's student taken as the person of its advisorship): 11,523 of 11,531 Lattes items pick the advisorship they are attached to; the 8 others are the two limits added to research R11 (6 titles that differ in case or punctuation, 2 persons merged after the load).
- [X] T027 Repeat the second local run after T026 (ask the maintainer first): restore `data/_backup_2026-11-11_post035_run1/horizon.db` to `db/horizon.db`, run the weekly, and compare as in T024. Expected: no advisorship created again; every difference explained.
  - Result (2026-11-11, passed): database of T023 restored (integrity ok, 11,877 advisorships, rule version 5); weekly 20:30-21:19, exit 0, no failed phase, no reset; 7 of 435 curricula differ from the copy taken after T023. Documents processed again: lattes_advisorships 52 (383 skipped), sigpesq_advisorship 60 (1,143 skipped).
  - No advisorship was created again: the five advisorships of T024 (143, 145, 153, 154, 283) are unchanged and have no twin. Advisorships 11,877 -> 11,876; 0 with more than one Student, 0 without a Student or a Supervisor, 0 duplicate names; "Estágio Supervisionado Obrigatório" still 49 advisorships of 48 students.
  - Differences, all explained: 4 advisorships removed and 4 created by changed curricula (9100 -> 15511, 14459 -> 15513, 14524 -> 15514, 11393 -> 15512); 15512 is one of the six items of research R11 whose title is written another way, has no twin, and its id now comes from type + name; advisorship 6397 was removed and its item moved to its twin 513 (the persons-merged limit of research R11); Student of an existing advisorship changed: 0; Supervisor changed on 44 advisorships fed by two curricula (TD-047, older than this branch); member start date changed on 2 advisorships (513 and 373). Projects: no difference; professional activities 3 removed and 5 added, articles 1 added, from the changed curricula.
- [X] T025 Fork validation per quickstart.md section 4, for specs 034 and 035 together (also closes T030 of specs/034-keep-professional-activities/tasks.md). Ask the maintainer first; only on the RafaelDeps fork, never upstream; push with a temporary worktree and cherry-pick if the fork branch received a zip commit, never with force. Two weekly runs; record the numbers of both.
  - Result (2026-11-12, passed): branch pushed to the RafaelDeps fork at `a8f3227`; two runs of `weekly-etl.yml` on `035-one-advisorship-per-student`, both with every step and all 16 ingestion runs successful.
  - Run 1 (43126636616, 2026-11-12 00:21-02:13 UTC, no earlier database of this branch, so a rebuild): rule version 5; 11,875 advisorships (11,877 in the local rebuild of T023), 0 duplicate names, 2,266 names with the suffix, "Estágio Supervisionado Obrigatório" 49 advisorships; status Concluded 10,829, In Progress 865, Cancelled 113, Active 68; advisorship ids by rule: lattes_identity 11,198, sigpesq_workplan 676, pj_code 1; 9,557 professional activities, 0 with `institution_country` in capitals; projects 3,630, articles 8,057, academic educations 1,962, awards 183, groups 353.
  - Run 2 (43140259318, 02:16-03:00 UTC, over the restored database of run 1): rule version 5, no reset; 11,875 advisorships, 0 duplicate names, "Estágio Supervisionado Obrigatório" still 49; same status counts; 9,557 professional activities, 0 with the country in capitals.
  - Run 1 against run 2: professional activities identical (0 rows and 0 id rows differ; this closes T030 of branch 034); projects, articles, academic educations, awards and groups: 0 id rows differ. Advisorships: 1 removed and 1 created (11392 -> 15506, "A dimensão Ambiental na Educação: perspectiva e desafios da sustentabilidade", 2016, same student, same supervisor, same dates; its id now comes from type + name and the name gained the suffix). It is the same item as 11393 -> 15512 of T027, one of the six of research R11 whose title is written another way (TD-046 d). No other advisorship was created again; Student changed on 0 kept advisorships; Supervisor changed on 44 (TD-047, older than this branch).
  - Seen in both environments and older than this branch (already in the database saved before T023): the fellowship "JTC" (value 0, no sponsor) is stored a second time by the second run (ids 15 and 21), which moves one advisorship to the new row and changes the collision suffix of that fellowship id and of one person id. Registered as TD-048 in docs/backlog.md.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001; blocks every story (T002 -> T003).
- **US1 (Phase 3)**: after Phase 2. T004, T005 -> T006 -> T007 -> T008 -> T009 -> T010.
- **US2 (Phase 4)**: after US1 (it is the same rule seen from SigPesq). T011 -> T012.
- **US3 (Phase 5)**: after US1. T013, T014 -> T015 -> T016.
- **US4 (Phase 6)**: after US1, US2 and US3, so the version changes only when the whole rule is in place. T017 -> T018 -> T019.
- **Polish (Phase 7)**: after the stories; T023, T024 and T025 need the maintainer's approval, in that order.

### Within Each User Story

- Tests first, and seen failing where the task says so, before implementation.
- Tasks in the same file run in sequence: tests/test_advisorship_same_title.py (T005, T011, T013); src/core/logic/project_loader.py (T007, T008, T009); src/core/logic/initiative_handlers.py (T006, T015); tests/test_project_loader_matching.py (T004).

### Parallel Opportunities

- T005 touches a different file from T004.
- T014 touches a different file from T013.
- T020 and T021 touch different files.

---

## Parallel Example: User Story 1

```bash
Task: "T004 lookup tests in tests/test_project_loader_matching.py"
Task: "T005 same-title tests in tests/test_advisorship_same_title.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001, then T002-T003 (the rule).
2. T004-T010: an item of another student creates a new advisorship.
3. Stop and check: the listed tests pass. The database is not touched yet, because the rule version changes only in US4.

### Incremental Delivery

1. US1: different students, different advisorships.
2. US2: the SigPesq replacement case, with tests only if the rule already covers it.
3. US3: the same work stays one advisorship and keeps its name; different years split.
4. US4: the version changes, which is what makes the weekly rebuild an older database.
5. Polish: backlog, lint, full suite, then the three validations that need approval.

---

## Notes

- No table, column, export field or id rule changes; no change to third-party libraries, to the dashboard or to Docker; the SigPesq and Lattes strategies and flows are not edited.
- The loader tests use stubs, as the existing loader tests do; the evidence over a real database is the two local runs (T023, T024).
- The rule version changes last (T018), so no test run before it can leave a local database half under the new rules.
- Commit only when the maintainer asks; never stage `data/`, `logs/`, `PLANO_*.md`, `RESUMO_*.md` or `data/exports/exports_canonical.zip`.
- The weekly (T023, T024, T025) is never run without asking first.
