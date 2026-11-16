---

description: "Task list for spec 034: every professional activity is kept, with the right institution"
---

# Tasks: Every professional activity is kept, with the right institution

**Input**: Design documents from `specs/034-keep-professional-activities/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/activity-rules.md, quickstart.md

**Tests**: Included. The constitution's development workflow requires tests,
and the plan writes them before the change (they must fail first).

**Organization**: Tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)

Code: `src/core/logic/professional_activity_rules.py` (new, the two rules),
`src/adapters/sources/lattes_parser.py` (parser output),
`src/flows/lattes/projects.py` (what is stored),
`src/core/logic/horizon_identity.py` (id fields and rule version),
`src/adapters/database/horizon_id_store.py` (columns read for the id).
Tests: `tests/test_professional_activity_rules.py` (new),
`tests/test_lattes_professional_activities.py` (new),
`tests/test_lattes_parser.py`, `tests/test_horizon_identity.py`,
`tests/test_horizon_id_assigner.py`, `tests/test_incremental_lattes.py`,
`tests/test_rule_version_guard.py`.

Field lists used below (contracts/activity-rules.md, research R3 and R4):

- **13 stored fields**: `institution`, `institution_name`, `institution_acronym`, `institution_country`, `period`, `start_year`, `end_year`, `bond`, `classification`, `work_regime`, `role_function`, `activity_type`, `current`.
- **7 detail fields**: `period`, `start_year`, `end_year`, `bond`, `classification`, `work_regime`, `role_function`.

---

## Phase 1: Setup

**Purpose**: Confirm the starting point.

- [X] T001 Run `.venv/bin/python -m pytest -q tests/test_lattes_parser.py tests/test_horizon_identity.py tests/test_horizon_id_assigner.py tests/test_rule_version_guard.py tests/test_incremental_lattes.py` on branch `034-keep-professional-activities` and record the counts (passed, skipped) before any change (baseline). Result (2026-11-11): 94 passed, 1 skipped.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The module and the one definition of "equal activities" that the parser, the ingestion and the tests share (research R1, R3).

- [X] T002 Create tests/test_professional_activity_rules.py with `test_activity_key_reads_a_dict_and_a_row_alike`: `activity_key` of a dictionary with the 13 stored fields equals `activity_key` of a `types.SimpleNamespace` with the same values as attributes; the result is a tuple of 13 values in the order of `STORED_FIELDS`; a missing field counts as `None`; `current` is returned as a `bool` (`0`/`1`/`None` from a database row become `False`/`True`/`False`); two items that differ in any one of the 13 fields give different keys (parametrized over the 13 names). See it fail (the module does not exist). Result: written with T004 and T011 in one file; collection failed before the module existed.
- [X] T003 Create src/core/logic/professional_activity_rules.py (pure, standard library only, no import from `src/adapters`) with a module docstring naming spec 034, the constants `STORED_FIELDS` (the 13 names, in the order listed above) and `DETAIL_FIELDS` (the 7 names), and `activity_key(activity) -> tuple`, which reads each of `STORED_FIELDS` from a mapping (`.get`) or from an object (`getattr(..., None)`) and returns `bool(value)` for `current`. T002 passes. Result: module created; the tests of T002 pass.

**Checkpoint**: one function says when two activities are equal.

---

## Phase 3: User Story 1 - Every different activity of a researcher is stored (Priority: P1) 🎯 MVP

**Goal**: two activities of one researcher at the same institution and start year that differ in any stored field are two rows; exact repeats stay one row; an institution-only item is stored only when the curriculum has no filled activity at that institution.

**Independent Test**: parse one curriculum with two activities at the same institution and start year that differ in the period, and ingest it with a stub controller; two activities are created, each with its own period; ingesting it again creates nothing.

### Tests for User Story 1

- [X] T004 [US1] In tests/test_professional_activity_rules.py add tests for `distinct_activities` with a helper `_item(institution="Universidade X, UX, Brasil", **fields)` that fills the 13 stored fields (unset ones `None`, `activity_type="Atuação profissional"`, `current=False`): the five rows of the `distinct_activities` example table of contracts/activity-rules.md (two different periods -> both; the same item twice -> one; two institution-only items -> one; institution-only plus a filled item at the same institution -> only the filled one; a filled item plus an institution-only item at another institution -> both); `test_order_of_first_appearance_is_kept`; `test_current_and_type_do_not_count_as_detail` (an item whose 7 detail fields are `None` is institution-only even with `activity_type` set); `test_items_that_differ_in_one_field_are_both_kept`, parametrized over `period`, `end_year`, `bond`, `classification`, `work_regime`, `role_function`, `current`; `test_the_input_list_is_not_changed`. See them fail. Result: seen failing (module missing), with T002.
- [X] T005 [P] [US1] In tests/test_lattes_parser.py add, building the curriculum dictionary inside each test (the `extras_data` fixture and `test_parse_professional_activities_current_and_closed` stay as they are and must keep passing): `test_activities_that_differ_only_in_the_period_are_both_parsed` (two `atuacao_profissional` items with `instituicao` "Universidade X, UX, Brasil", `ano_inicio` "2010" and `periodo` "2010 - 2012" / "2010 - 2015" -> 2 items); `test_an_exact_repeat_is_parsed_once`; `test_institution_only_items_give_one_item` (three items with only `instituicao` -> 1 item); `test_an_institution_only_item_beside_a_filled_one_is_dropped` (-> only the filled item); `test_an_institution_only_item_at_another_institution_is_kept`. See the first, second, third and fourth fail. Result: 4 of the 5 failed before the change, as expected (the period test already passed at the parser).
- [X] T006 [P] [US1] Create tests/test_lattes_professional_activities.py for `ingest_professional_activities_task` of src/flows/lattes/projects.py. Stub the controller with `monkeypatch.setattr("src.flows.lattes.projects.ProfessionalActivityController", ...)`: a class whose `create_professional_activity(researcher_id, **fields)` appends the call to a list and returns a `SimpleNamespace(id=<next number>, **fields)`. Stub the session with an object whose `query(...).filter_by(researcher_id=...).all()` returns a given list of `SimpleNamespace` rows. The researcher is `SimpleNamespace(id=7, name="R")`. Tests: `test_two_activities_at_one_institution_and_start_year_are_both_created` (items differ in `period`; 2 creates); `test_an_activity_equal_to_a_stored_row_is_not_created` (the stored row has the same 13 fields; 0 creates); `test_an_activity_that_differs_from_the_stored_row_is_created`, parametrized over `period`, `end_year`, `bond`, `classification`, `work_regime`, `role_function`, `current` (stored row and item share institution and start year; 1 create); `test_a_second_pass_creates_nothing` (ingest, feed the created rows back as the stored rows, ingest again; 0 creates on the second pass); `test_a_stored_current_flag_of_1_equals_true` (stored row with `current=1`, item with `current=True`; 0 creates). See the first and the parametrized test fail. Result: 9 tests failed before the change (the first, the 7 parametrized cases and the second pass).

### Implementation for User Story 1

- [X] T007 [US1] In src/core/logic/professional_activity_rules.py add `distinct_activities(items) -> list` following contracts/activity-rules.md: keep the first item of each `activity_key`; an item is institution-only when every one of `DETAIL_FIELDS` is `None`; drop an institution-only item when another kept item with the same `institution` is not institution-only; return a new list in the order of first appearance. T004 passes. Result: done; T004 passes.
- [X] T008 [US1] In src/adapters/sources/lattes_parser.py make `parse_professional_activities` return `distinct_activities(parsed)` (import from `src.core.logic.professional_activity_rules`) and extend its docstring: exact repeats are returned once and an item that carries only the institution is returned only when the curriculum has no filled activity there (spec 034). T005 passes and `test_parse_professional_activities_current_and_closed` still passes. Result: done; T005 and the existing parser test pass.
- [X] T009 [US1] In src/flows/lattes/projects.py change `ingest_professional_activities_task`: build `seen` as `activity_key(row) -> row.id` for the stored rows of the researcher, look each item up with `activity_key(act)`, and keep the create, `carry` and `mark_partial` calls as they are; replace the docstring line "Deduped by (researcher_id, institution, start_year, activity_type)" by one saying that an item is a repeat only when it equals a stored row of the researcher in every stored field (spec 034, FR-001). T006 passes. Result: done (`activity_key` imported at module level, beside the other core imports); T006 passes.
- [X] T010 [US1] Run `.venv/bin/python -m pytest -q tests/test_professional_activity_rules.py tests/test_lattes_parser.py tests/test_lattes_professional_activities.py` and record the counts. Result (2026-11-11): 107 passed in the three files (77 rules, 19 parser, 11 ingestion).

**Checkpoint**: no activity is dropped because it shares institution and start year with another.

---

## Phase 4: User Story 2 - Name, acronym and country of the institution are the right ones (Priority: P1)

**Goal**: name, acronym and country are read from the full institution text; a final full stop is ignored; no part of the text lands in a field it does not belong to.

**Independent Test**: parse an activity whose `instituicao` is "Instituto Federal de Educação, Ciência e Tecnologia do Espírito Santo, IFES, Brasil" with the swapped library fields; the item has the full name, acronym "IFES" and country "Brasil".

### Tests for User Story 2

- [X] T011 [US2] In tests/test_professional_activity_rules.py add `test_split_institution_contract`, one parametrized test with the 11 rows of the `split_institution` example table of contracts/activity-rules.md (expected `institution` is the text without the final full stop), plus: `None`, `""` and `" . "` -> `("", None, None, None)`; a text ending in `". "` and one ending in `".."` lose every final full stop and space; a full stop inside the name is kept ("... Ltda., IMPER, Brasil."); a two-part text whose last part is a known country written with another case or without accents ("X, BRASIL" is step 5 and gives the acronym "BRASIL"; "X, brasil" gives the country "brasil"); `test_split_institution_is_stable` (applying it to its own `institution` output returns the same four values, for every example); `test_no_part_is_returned_in_two_fields` (for every example with an acronym or a country, neither is contained in the name as a whole comma part); `test_split_institution_applies_the_column_limits` (a 600-character one-part text gives `institution` of 500 and `name` of 255 characters). See them fail. Result: seen failing with T002 (module missing); 11 contract rows plus the edge cases.
- [X] T012 [P] [US2] In tests/test_lattes_parser.py add `test_institution_fields_come_from_the_full_text` (an item with `instituicao` "Instituto Federal de Educação, Ciência e Tecnologia do Espírito Santo, IFES, Brasil", `instituicao_nome` "Instituto Federal de Educação", `instituicao_sigla` "Ciência e Tecnologia do Espírito Santo", `instituicao_pais` "IFES" and a period -> `institution_name` is the full name, `institution_acronym` "IFES", `institution_country` "Brasil") and `test_a_final_full_stop_does_not_make_another_activity` (two items equal but for "..., UFES, Brasil." and "..., UFES, Brasil" -> 1 item, whose `institution` has no final full stop). See them fail. Result: both failed before the change.

### Implementation for User Story 2

- [X] T013 [US2] In src/core/logic/professional_activity_rules.py add `split_institution(text) -> tuple` following the 9 steps of contracts/activity-rules.md and research R2: a module constant with the 22 known country names of research R2, compared after `normalize_text` of `src.core.logic.horizon_identity` (case and accents ignored); "has a lowercase letter" is `any(ch.islower() for ch in part)`; the name is the text before the comma that precedes the parts taken as acronym or country (use `rsplit(",", n)`, so commas and spacing inside the name stay as written); apply the limits 500 / 255 / 100 / 100. T011 passes. Result: done; T011 passes.
- [X] T014 [US2] In src/adapters/sources/lattes_parser.py make `parse_professional_activities` take `institution`, `institution_name`, `institution_acronym` and `institution_country` from `split_institution(item.get("instituicao") or item.get("instituicao_nome"))` instead of the library fields `instituicao_nome`, `instituicao_sigla` and `instituicao_pais`; an item whose resulting `institution` is empty is skipped, as today; note in the docstring that the library splits the text at every comma and that the three fields are read again from the full text (spec 034, FR-003 to FR-005). T012 passes; the tests of T005 and `test_parse_professional_activities_current_and_closed` still pass. Result: done; T012, T005 and the existing parser test pass.
- [X] T015 [US2] Run the read-only script of quickstart.md section 2 over `data/lattes_json/` and record the result here: items to store (about 9,555 expected), institution-only items (about 163), the six most frequent countries ("Brasil" about 8,918) and that "IFES" is not among the countries. No database is read or written. Result (2026-11-11, 435 curricula, no database): 9,555 items to store, 163 institution-only; countries Brasil 8,918, none 555, Estados Unidos 25, Portugal 13, Peru 7, Alemanha 6; "IFES" as the country 0; countries in capitals 0. Equal to the prototype of research.md.

**Checkpoint**: the parser returns the right institution fields for every shape of the text.

---

## Phase 5: User Story 3 - The permanent id of an activity follows the corrected data (Priority: P2)

**Goal**: the id hashes the fields that tell two activities apart, uses the full institution text, and keeps the old-rule id as a candidate so old ids resolve as aliases.

**Independent Test**: `child_decision` for two activities of one parent that differ only in the period returns two different ids.

### Tests for User Story 3

- [X] T016 [US3] In tests/test_horizon_identity.py: in the existing child test (the `child_decision("professional_activity", ...)` call near line 337) replace the row by one with the new fields (`institution` "Instituto Federal do Espírito Santo, IFES, Brasil", `period` "2010 - Atual", `start_year` "2010", `end_year` None, `bond` "Servidor", `classification` None, `work_regime` None, `role_function` "Professor", `current` True) and keep the assertion on `/activity:h:`. Add `test_activity_id_tells_two_activities_apart`, parametrized over `period`, `end_year`, `bond`, `classification`, `work_regime`, `role_function`, `current` (two rows equal but for that field get different `horizon_id`); `test_activity_id_uses_the_full_institution` (two rows whose `institution` differs only after the first comma get different ids; `institution_name` in the row does not change the id); `test_activity_rule_label` (`rule == "parent+institution+period+start_year+end_year+bond+classification+work_regime+role_function+current"`); `test_activity_keeps_the_old_rule_id_as_a_candidate` (for a parent with two candidates, `candidates` holds four ids: the two new ones first, then `f"{p}/activity:h:{hash12('Instituto Federal do Espírito Santo', '2010', None, 'Professor', 'Servidor')}"` for each parent candidate; an education and an award get no extra candidate). See the new tests fail. Result: 7 new tests failed before the change (period, classification, work regime, current, full institution, rule label, legacy candidate).
- [X] T017 [P] [US3] In tests/test_horizon_id_assigner.py change the `professional_activities` table of the schema fixture to the columns the id reads (`id`, `researcher_id`, `institution`, `institution_name`, `period`, `start_year`, `end_year`, `bond`, `classification`, `work_regime`, `role_function`, `current`) and add `test_an_old_activity_id_becomes_an_alias_of_the_one_row_that_owns_it` (one researcher with one activity; the history holds the old-rule id of that activity as a current id; after `assign`, `horizon_id_aliases` maps the old id to the new id) and `test_an_old_activity_id_shared_by_two_rows_is_retired` (two activities of one researcher with the same first comma part of the institution, start year, end year, role and bond, differing in the period; the old id is recorded with reason `retired` and no target). Follow the way `test_upgraded_key_aliases_the_person_and_its_children` and `test_rule_change_recomputes_old_ids_from_their_natural_key` build their history. See them fail. Result: both alias tests failed before the change.

### Implementation for User Story 3

- [X] T018 [US3] In src/core/logic/horizon_identity.py set the fields of `professional_activity` in `_CHILD_PARTS` to `("institution", "period", "start_year", "end_year", "bond", "classification", "work_regime", "role_function", "current")`, and in `child_decision` append, for `professional_activity` only, one candidate per parent candidate with the old-rule tail `activity:h:<hash12(first comma part of institution, start_year, end_year, role_function, bond)>` (research R8), after the new candidates; extend the docstring with one sentence on this legacy candidate (spec 034, FR-010). T016 passes. Result: done, with the helper `_activity_tail_before_spec_034`; T016 passes.
- [X] T019 [US3] In src/adapters/database/horizon_id_store.py change the `professional_activity` query to `SELECT id, researcher_id AS parent_id, institution, period, start_year, end_year, bond, classification, work_regime, role_function, current FROM professional_activities`. T017 passes. Result: done; T017 passes.
- [X] T020 [US3] Run `.venv/bin/python -m pytest -q tests/test_horizon_identity.py tests/test_horizon_id_assigner.py tests/test_canonical_exporter.py tests/test_export_canonical_data_flow.py` and record the counts; a failure in the two export files means a fixture builds `professional_activities` with the old columns and is fixed in that test file, in the same way as T017. Result (2026-11-11): 111 passed in the four files; the two export test files needed no change.

**Checkpoint**: two stored activities never share an id because of a field the id ignores, and old ids are not lost without a record.

---

## Phase 6: User Story 4 - A database filled before the fix is repaired, and nothing else moves (Priority: P3)

**Goal**: a database written under rule version 3 is rebuilt before use; an incremental database and a rebuild hold the same activities.

**Independent Test**: `rule_version_requires_reset` is true for a database whose recorded version is 3.

### Tests for User Story 4

- [X] T021 [US4] In tests/test_rule_version_guard.py add `test_a_database_written_before_spec_034_needs_a_reset`, built like `test_a_database_written_before_spec_033_needs_a_reset`: set `rule_version` to `'3'`, assert `HORIZON_RULE_VERSION >= 4` and that `rule_version_requires_reset` is true, with a comment saying that version 3 collapsed professional activities by institution and start year. See it fail on the `>= 4` assertion. Result: failed on the `>= 4` assertion before T023.
- [X] T022 [P] [US4] In tests/test_incremental_lattes.py change the `professional_activities` entry of `COMPARED` to select the 13 stored fields (`SELECT institution, institution_name, institution_acronym, institution_country, period, start_year, end_year, bond, classification, work_regime, role_function, activity_type, current FROM professional_activities`), so the comparison of an incremental database with a rebuild covers every field of an activity (FR-007). Result: done.

### Implementation for User Story 4

- [X] T023 [US4] In src/core/logic/horizon_identity.py set `HORIZON_RULE_VERSION = 4` and add to the comment above it one line: `4 (branch 034)`: a professional activity is identified by every stored field and by the full institution text, so activities collapsed by institution and start year are split by one rebuild. T021 passes. Result: done; T021 passes.
- [X] T024 [US4] Run `.venv/bin/python -m pytest -q tests/test_rule_version_guard.py tests/test_incremental_lattes.py` and record the counts, and whether tests/test_incremental_lattes.py ran or was skipped (it needs local curricula in `data/lattes_json/`). Result (2026-11-11): tests/test_rule_version_guard.py 7 passed; tests/test_incremental_lattes.py ran with the local curricula: 6 passed, 1 skipped ("no local unidentified CV", the same skip as the baseline), so an incremental database and a rebuild hold the same activities in all 13 fields.

**Checkpoint**: the fix reaches a persistent database through one rebuild.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T025 [P] Add three entries to docs/backlog.md after TD-039: `TD-040 — Different professional activities stored as one, and institution fields swapped` (the two defects; the numbers of 2026-11-11: 13,420 items, 7,855 rows, 2,923 different activities dropped, 2,260 rows with "IFES" as the country; the two rules in one sentence each; the institution-only decision of the clarification; the id fields and the legacy candidate; rule version 4; status "Implemented; local and fork validation pending"); `TD-041 — Tasks and courses of a professional activity are not stored` (the `atividades` list in 3,580 items and the `disciplinas` list in 54; the domain library's table has no column; status Ready); `TD-042 — Institution texts that arrive already cut` (480 items such as "Universidade Federal de", cut by the third-party curriculum library; cannot be recovered in the ETL; status Open, depends on the library) (FR-012). Result: TD-040, TD-041 and TD-042 added.
- [X] T026 [P] Run `.venv/bin/black --check`, `.venv/bin/isort --check-only` and `.venv/bin/flake8` on src/core/logic/professional_activity_rules.py, src/core/logic/horizon_identity.py, src/adapters/sources/lattes_parser.py, src/adapters/database/horizon_id_store.py, src/flows/lattes/projects.py and the test files touched; fix what these tasks introduced and record the findings that already existed. Result (2026-11-11): black and isort clean on the 12 files. flake8 on these files: 32 findings, 31 before; the one new finding is E402 on the new `activity_key` import of src/flows/lattes/projects.py, placed in the file's existing import block, where the 25 imports beside it already report E402. No finding in the new module or the two new test files.
- [X] T027 Run the full suite `.venv/bin/python -m pytest -q` and record the counts against the 1080 passed, 10 skipped of branch 033; then run `make ci-check` and record its result (it fails on the repository before this branch: 46 files to reformat and 578 lint findings on branch 033); do not fix files this branch did not touch. Result (2026-11-11): 1188 passed, 10 skipped, 0 failed (108 new tests). `make ci-check` does not pass on this repository, before or after this branch: `make format-check` wants to reformat 46 files (the same 46) and `make lint` reports 579 findings (578 before; the extra one is the E402 of T026). Not fixed here.
- [X] T028 Local validation per quickstart.md sections 3 and 4 (ask the maintainer first; back up `db/horizon.db` and `data/` before): one `make weekly-flows` rebuilds the database because of the rule version; record the "rebuilding it once" log line, the `Horizon ids:` line (rule version 4, aliases per reason), and the results of the read-only check: row count (about 9,555; 7,855 before), 0 curriculum items missing (SC-001), institution-only rows (about 163) and 0 beside a filled row (SC-002), 0 countries in capitals and the IFES example (SC-003), ids with a collision suffix (SC-004; 114 before), the counts of awards, academic educations, articles, research productions, initiatives and advisorships against the backup, explaining any difference by the curricula that changed between downloads (SC-005), and a sample of old activity ids found in `horizon_id_aliases` with a target or as retired (FR-010). Then set TD-040 in docs/backlog.md to the validated status. Result (2026-11-11, local, backup in data/_backup_2026-11-11_pre034/): `make weekly-flows` exit 0, 09:32 to 10:36, the 22 phases exit 0. Log: "Database rule version differs from the code's; rebuilding it once before the phases"; "Horizon ids: 72558 entities, 30 collision groups, rule version 4; aliases 9784 (7874 new, 2756 retired, per reason {'upgraded key': 367, 'key corrected': 150, 'retired': 2756, 'rebuild': 6486, 'merge': 25})". Read-only check: 9,555 rows (7,855 before); SC-001: 9,555 curriculum items checked, 0 missing, 0 rows that no curriculum carries; 163 institution-only rows, 0 beside a filled row (SC-002); 0 countries in capitals, Brasil 8,918, and the IFES example stores the full name, "IFES" and "Brasil" (SC-003); 6 ids with a collision suffix, 114 before (SC-004); rule version 4. SC-005: awards 183, academic educations 1,962, research productions 3,727, initiatives 13,888, advisorships 10,257 and research groups 353 equal the backup; articles 8,053 -> 8,054 and persons 18,424 -> 18,426, with 6 curricula changed between the two downloads. Old ids (FR-010): of the 7,855 activity ids of the backup, 5,871 are aliases with reason `rebuild` and 1,984 are recorded as `retired`; none is without a record. One ERROR line in the log, `cnpq_group_url_invalid` for 1 group, a SigPesq registration problem that exists without this branch.
- [X] T029 Second local run per quickstart.md section 5 (same approval; copy `db/horizon.db` and `data/lattes_json/` first): `make weekly-flows`; record that for the curricula whose file did not change the rows of `professional_activities` and their ids in `horizon_ids` are identical to the copy, and that every activity created or removed belongs to a curriculum whose file changed (SC-006; User Story 4, scenarios 2 and 3). Result (2026-11-11, local, copy of the rebuilt database in data/_backup_2026-11-11_post034_run1/): `make weekly-flows` exit 0, 10:37 to 11:24, the 22 phases exit 0, no rebuild ("Horizon ids: 72575 entities, 30 collision groups, rule version 4 ... history from ['database']"). 6 curricula changed between the two downloads. Activities: 9,555 rows before and after. For the 429 unchanged curricula, 0 differences in any row, field, database id or permanent id (SC-006). In 2 of the changed curricula 9 rows were removed and 9 created: the downloaded file now writes the bond as "Servidor Público" where it wrote "Servidor público"; the permanent ids of these 9 activities are the same before and after, because the id ignores case. The other writes of the run are not about activities: 19 initiative updates, 11 advisorship entries, 4 article entries, from the changed curricula and from the defects already registered (project fields rewritten by the last curriculum processed, TD-038).
- [X] T030 Fork validation per quickstart.md section 6 (ask the maintainer first; only on the RafaelDeps fork, never upstream): the first weekly of the branch and a second one over the restored database; record that `professional_activities_canonical.json` has no `institution_country` in capitals in both runs, the row counts of both runs, and that the activity rows of `horizon_ids_canonical.json` are identical between the runs apart from changed curricula (SC-007 is covered by T021 and by the local rebuild of T028, because the branch's first fork run has no earlier database to restore). Deferred (maintainer's decision of 2026-11-11): the fork is validated once at the end of the batch, on the last stacked branch (033 -> 034 -> 035), which covers this one.
  - Result (2026-11-12, passed, validated on branch 035, which is stacked on this one): runs 43126636616 (rebuild) and 43140259318 (over the restored database) of the RafaelDeps fork, both successful. `professional_activities_canonical.json`: 9,557 rows in both runs, 0 with `institution_country` in capitals (0 "IFES"); the rows and the professional-activity rows of `horizon_ids_canonical.json` are identical between the runs (0 differ). Details in T025 of specs/035-one-advisorship-per-student/tasks.md.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001; blocks every story (T002 -> T003).
- **US1 (Phase 3)**: after Phase 2. T004-T006 -> T007 -> T008 -> T009 -> T010.
- **US2 (Phase 4)**: after Phase 2. It can be built without US1, but both change `parse_professional_activities`, so it runs after T008. T011-T012 -> T013 -> T014 -> T015. T015 gives the expected numbers only when US1 is also done.
- **US3 (Phase 5)**: after Phase 2; independent of US1 and US2 (it reads the stored columns). T016-T017 -> T018 -> T019 -> T020.
- **US4 (Phase 6)**: after US1, US2 and US3, because the version must change only once every rule of this branch is in place. T021-T022 -> T023 -> T024.
- **Polish (Phase 7)**: after the stories; T028, T029 and T030 need the maintainer's approval, in that order.

### Within Each User Story

- Tests first, and seen failing where the task says so, before implementation.
- Tasks in the same file run in sequence: tests/test_professional_activity_rules.py (T002, T004, T011); src/core/logic/professional_activity_rules.py (T003, T007, T013); tests/test_lattes_parser.py (T005, T012); src/adapters/sources/lattes_parser.py (T008, T014); src/core/logic/horizon_identity.py (T018, T023); docs/backlog.md (T025, T028).

### Parallel Opportunities

- T005 and T006 touch different files from T004 and from each other.
- T012 touches a different file from T011.
- T017 touches a different file from T016.
- T022 touches a different file from T021.
- T025 and T026 touch different files.

---

## Parallel Example: User Story 1

```bash
Task: "T004 distinct_activities tests in tests/test_professional_activity_rules.py"
Task: "T005 parser tests in tests/test_lattes_parser.py"
Task: "T006 ingestion tests in tests/test_lattes_professional_activities.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001, then T002-T003 (the definition of equal activities).
2. T004-T010: every different activity is stored.
3. Stop and check: the tests of the three files pass. The database is not touched yet, because the rule version changes only in US4.

### Incremental Delivery

1. US1: no activity is dropped.
2. US2: the institution fields are right; T015 shows the numbers over the real curricula without a database.
3. US3: ids follow the new rows and old ids resolve.
4. US4: the version changes, which is what makes the weekly rebuild an older database.
5. Polish: backlog, lint, full suite, then the three validations that need approval.

---

## Notes

- No table, column or export field changes; the dashboard code is not touched.
- The rule version changes last (T023), so no test run before it can leave a local database half under the new rules.
- Commit only when the maintainer asks; never stage `data/`, `logs/`, `PLANO_*.md`, `RESUMO_*.md` or `data/exports/exports_canonical.zip`.
- The weekly (T028, T029, T030) is never run without asking first.
