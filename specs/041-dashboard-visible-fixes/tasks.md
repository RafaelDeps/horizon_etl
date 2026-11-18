---

description: "Task list for spec 041: dashboard-visible data fixes and Slack notices on main only"
---

# Tasks: Dashboard-visible data fixes and Slack notices on main only

**Input**: Design documents from `specs/041-dashboard-visible-fixes/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/dashboard-fixes.md, quickstart.md

**Tests**: Included. The constitution's development workflow requires tests,
and the plan writes them before the change (they must fail first).

**Organization**: Tasks are grouped by user story (spec.md):

| Story | Priority | Subject |
|---|---|---|
| US1 | P1 | Slack only on main |
| US2 | P1 | Only real people with whole names |
| US3 | P2 | Teams and graphs show each relation once, never a self-relation |
| US4 | P2 | Titles and years read correctly |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 to US4)

**Code**:

| File | What changes |
|---|---|
| `src/scripts/notify_slack.py` | Branch gate |
| `.github/workflows/weekly-etl.yml` | `curl` fallback gate |
| `src/core/logic/person_name_rules.py` | New: `is_name_fragment`, `advisor_name` |
| `src/core/logic/title_rules.py` | New: `fix_lost_dash`, `plausible_year` |
| `src/core/logic/student_name_rules.py` | Split and citation |
| `src/adapters/sources/lattes_parser.py` | Students, titles, years |
| `src/core/logic/strategies/lattes_advisorships.py` | Every student, joined key |
| `src/core/logic/strategies/lattes_projects.py` | Fragment members skipped |
| `src/core/logic/initiative_handlers.py` | Several Student members |
| `src/flows/lattes/projects.py` | Advisor of a degree |
| `src/flows/lattes/advisorships.py` | Summary line |
| `src/core/logic/people_collaboration_graph_generator.py` | No self-edge |
| `src/core/logic/canonical_exporter.py` | One entry per person in a team |
| `src/core/logic/horizon_identity.py` | Rule version 6 -> 7 |

**Tests**:

- New:
  - `tests/test_person_name_rules.py`
  - `tests/test_title_rules.py`
  - `tests/test_lattes_projects_strategy.py`
  - `tests/test_people_collaboration_graph_generator.py`
- Extended:
  - `tests/test_notify_slack.py`
  - `tests/test_weekly_etl_workflow.py`
  - `tests/test_student_name_rules.py`
  - `tests/test_lattes_parser.py`
  - `tests/test_lattes_advisorships_loader_reuse.py`
  - `tests/test_initiative_handlers.py`
  - `tests/test_ingest_lattes_projects_flow.py`
  - `tests/test_canonical_exporter.py`
  - `tests/test_rule_version_guard.py`

**Terms used below** (contracts/dashboard-fixes.md, data-model.md):

- **Fragment**: a text for which `is_name_fragment` is true (contract 1).
- **Degree description**: `formacao_academica[].descricao` of a curriculum. It holds the "Orientador:" and "Coorientador:" parts.
- **Split field**: a student text that `clean_student_name` turns into several students (`kinds` holds `split`).
- **Lost dash**: a "?" with a space on each side and a letter or digit next to those spaces (contract 4).

**Rules for every task**:

- No change to third-party libraries, to the dashboard or to Docker.
- Never read or print `.env`, and never print the Slack webhook.
- Checks print counts and public names only, never a CPF or a phone number.
- The weekly, `full-refresh` and `db-reset` never run without asking the maintainer first.
- Push only to the RafaelDeps fork (origin), never upstream, never with force.
- No commit until the maintainer asks.

---

## Phase 1: Setup

**Purpose**: a known starting point.

- [X] T001 Record the starting point in this file under this task. No code change.
  - The branch `041-dashboard-visible-fixes` and its commit (`git log --oneline -1`).
  - The full suite result before any change: `.venv/bin/python -m pytest -q > logs/pytest_041_before.log 2>&1`.
  - The flake8 count of the repository: `.venv/bin/python -m flake8 src tests | wc -l`.
  - Result: branch `041-dashboard-visible-fixes` at `c5ffe55` (fork main after the overnight runs of 2026-11-17); full suite before any change: 1553 passed, 10 skipped, 0 failed in 8m11 (logs/pytest_041_before.log); flake8 on `src tests`: 580.

---

## Phase 2: Foundational (Blocking Prerequisites)

None. Each story has its own files. The rule version (Phase 7) changes only
after every story is in place.

---

## Phase 3: User Story 1 - Weekly runs on feature branches stay quiet in Slack (Priority: P1) 🎯 MVP

**Goal**: runs on main notify as in spec 040; runs on any other branch send
nothing and say so in the log.

**Independent Test**: the tests of T002 and T003; then one weekly on this
branch (T037) sends no message and logs the notice.

### Tests for User Story 1

> Write these tests first and see them fail.

- [X] T002 [P] [US1] Add branch-gate tests to tests/test_notify_slack.py, one per row of contracts/dashboard-fixes.md section 6.
  - Run `main(["start"])` and `main(["end"])` with `GITHUB_REF_NAME` set to `main`, to `041-dashboard-visible-fixes` and to empty or unset, and with the webhook set and unset.
  - Patch `send` to record calls.
  - Assert: no call off main; the exact `::notice::Slack pulado: a branch <name> não é a main.` line (`(desconhecida)` when empty); the spec 040 behaviour on main; return value 0 in every case; and the webhook value never appears in the captured output.
- [X] T003 [P] [US1] Extend tests/test_weekly_etl_workflow.py: the run block of the step "Notify Slack: end" sends with `curl` only inside a test of `$GITHUB_REF_NAME` against `main`, and otherwise prints the same notice as T002. Check that the step keeps `if: always()` and `continue-on-error: true`, and that "Notify Slack: start" still runs `python3 -m src.scripts.notify_slack start` with no step-level `if` on the branch (the notice must reach the log, research R2).

### Implementation for User Story 1

- [X] T004 [US1] In src/scripts/notify_slack.py add the constant `NOTIFY_BRANCH = "main"` and a branch check in `main()`.
  - The check comes after the message is built and before the webhook is read. When `GITHUB_REF_NAME` (trimmed) is not `NOTIFY_BRANCH`, print `::notice::Slack pulado: a branch {name or "(desconhecida)"} não é a main.` and return 0.
  - `--dry-run` keeps printing the text regardless of the branch.
  - The start event keeps writing `WEEKLY_STARTED_AT`.
  - Update the module docstring.
  - T002 passes.
- [X] T005 [US1] In .github/workflows/weekly-etl.yml, in the run block of "Notify Slack: end", wrap the `curl` fallback in `if [ "$GITHUB_REF_NAME" = "main" ]; then … else echo "::notice::Slack pulado: a branch ${GITHUB_REF_NAME:-(desconhecida)} não é a main."; fi`.
  - Keep the missing-webhook warning for main.
  - Add one comment line naming spec 041.
  - T003 passes.
- [X] T006 [US1] Update docs/operations/automation.md, section "Aviso no Slack (spec 040)", in Portuguese like the rest of the file.
  - Messages are sent only by runs on `main`, including the scheduled run.
  - Runs on other branches send nothing and log "Slack pulado".
  - The reason: validation runs on feature branches should not disturb the channel.

**Checkpoint**: US1 works alone; nothing else is needed for the branch runs to stay quiet.

---

## Phase 4: User Story 2 - The people list shows only real people with whole names (Priority: P1)

**Goal**:

- No person is named with a title or a fragment.
- A field with several students gives one person per student.
- A citation gives only the name.
- Degrees point to their real advisor.

**Independent Test**: the tests of T007-T019; then, after the rebuild (T035),
the people checks of quickstart.md section 3.

### Tests for User Story 2

- [X] T007 [P] [US2] Create tests/test_person_name_rules.py with every row of contracts/dashboard-fixes.md section 1 (`is_name_fragment`) and section 2 (`advisor_name`, both `co=False` and `co=True`), parametrized.
- [X] T008 [P] [US2] Extend tests/test_student_name_rules.py with every row of contracts/dashboard-fixes.md section 3. Also assert:
  - `names[0] == name` whenever `names` is not empty;
  - `names == ()` when `name` is `None`;
  - every existing row of the 036 contract still gives the same `name` and `kinds`, except rows now listed in section 3.
- [X] T009 [P] [US2] Create tests/test_lattes_projects_strategy.py. For `LattesProjectMappingStrategy("Anderson Mathias Holtz").map_row(row)`:
  - with `raw_members` `[{"nome": "Anderson Mathias Holtz", "papel": "Coordenador"}, {"nome": "D", "papel": "Integrante"}, {"nome": "J", "papel": "Integrante"}, {"nome": "Graciela", "papel": "Integrante"}]`, assert "D" and "J" are in no list and "Graciela" stays a researcher;
  - with no fragment, assert the output is unchanged.
- [X] T010 [P] [US2] Extend tests/test_lattes_parser.py for both advisorship paths (`_parse_items` and `_parse_generic_advisorships`):
  - an item whose `orientando` is "Gladston Campos/Niase Borjaille" gives `student_name` "Gladston Campos" and `student_names` `["Gladston Campos", "Niase Borjaille"]`;
  - an item with one student gives `student_names == [student_name]`;
  - an item whose text is not a name keeps `student_names == []`.
- [X] T011 [P] [US2] Extend tests/test_lattes_advisorships_loader_reuse.py (the file that already builds `LattesAdvisorshipMappingStrategy`):
  - `map_row` of a row with `student_names` of two names returns both in `student_names`;
  - its `identity_key`, after `normalize_text`, equals the key the joined source text "Gladston Campos/Niase Borjaille" gave before the change (research R5);
  - a row with one student keeps today's key.
- [X] T012 [P] [US2] Extend tests/test_initiative_handlers.py:
  - an advisorship item with two `student_names` ends with two Student members (two persons) and one Supervisor;
  - a second pass with the same data writes no member row (the same rows are kept, spec 020 FR-022);
  - a later pass with one of the two names removes only that Student;
  - an item with one student behaves as today, in both the direct and the deferred (`defer_members`) paths.
- [X] T013 [P] [US2] Extend tests/test_ingest_lattes_projects_flow.py:
  - the academic education step stores, as advisor and co-advisor, the persons `advisor_name` returns for a degree description "Orientador: Prof. Dr. José Antônio da Silva. Coorientador: Dr. Wanderley Cardoso Celeste.";
  - it stores no advisor for "Orientador: -.";
  - no person named "Prof", "Dr" or "-" is created.

  Mock the researcher resolution the way the file already does.

### Implementation for User Story 2

- [X] T014 [US2] Create src/core/logic/person_name_rules.py (pure, standard library only) with:
  - `is_name_fragment(text) -> bool`, following research R4;
  - `advisor_name(description, co=False) -> Optional[str]`, following research R3.
    - Capture after "Orientador:" not preceded by "co"/"co-" (or after "Coorientador:"/"Co-orientador:" when `co`), up to the next label (`Coorientador:`, `Bolsista`, `Palavras-chave:`, `Grande área:`, `Título:`, `Área:`), `;`, `)` or the end.
    - Drop leading academic titles, repeated and in any case, and a leading enumeration.
    - Keep the first person.
    - Cut at the first ". " that ends the name: reuse the initial test of `student_name_rules._head_before_work_title`, moved or imported, not duplicated.
    - Treat "Não Definido" as no name.
    - Return `None` for a fragment.

  Module docstring pointing to contracts/dashboard-fixes.md sections 1-2. T007 passes.
- [X] T015 [US2] In src/core/logic/student_name_rules.py:
  - add `names: Tuple[str, ...]` to `CleanedName`;
  - before the `several` check, cut a citation: the text before "(orientador"/"(coorientador", then the existing work-title cut;
  - then split on "/" when every part, after the same cleaning, is a name of two or more words; drop parts that are fragments (`is_name_fragment`);
  - add the kinds `split` and `citation`;
  - otherwise keep `several` and the text as written, as today.

  Update the module docstring. T008 passes.
- [X] T016 [US2] In src/adapters/sources/lattes_parser.py, in `_parse_items` and `_parse_generic_advisorships`, add `"student_names": list(student.names)` next to `student_name`. The condition that keeps an item is unchanged. T010 passes.
- [X] T017 [US2] In src/core/logic/strategies/lattes_advisorships.py:
  - `student_names = row.get("student_names") or ([student_name] if student_name else [])`;
  - the identity key uses `" / ".join(student_names)` in place of `student_name` when there is more than one name, so the normalized key equals today's.

  T011 passes.
- [X] T018 [US2] In src/core/logic/initiative_handlers.py, give `_sync_advisorship_member` a list form for the Student role:
  - a `persons` argument, with the deferred queue holding the list per `(initiative id, role)`;
  - keep one member per person, keep rows of the same person, role and day, and remove Student members not in the list;
  - in the member sync of the advisorship, build the list from `_student_person` (first name, unchanged) plus `person_matcher.match_or_create(name, strict_match=True)` for each further name of `student_names`.

  `_student_person` and `item_student` keep using the first name. T012 passes.
- [X] T019 [US2] Apply the fragment and advisor rules:
  - In src/core/logic/strategies/lattes_projects.py, skip a member whose `nome` is a fragment before sorting members into coordinator, researchers and students (T009 passes).
  - In src/flows/lattes/projects.py (academic education step, around line 680), replace the two `re.search` calls with `advisor_name(description)` and `advisor_name(description, co=True)`, keeping `resolve_or_create_researcher` and leaving the id empty for `None` (T013 passes).
  - In src/flows/lattes/advisorships.py, add `split` and `citation` to the labels of the student-name summary line.

**Checkpoint**: US2 is in the code. The stored data changes only after the
rule version (Phase 7) and a rebuild (T035).

---

## Phase 5: User Story 3 - Teams and graphs show each relation once and never a self-relation (Priority: P2)

**Goal**: no person twice in an initiative team, and no edge from a person to
themselves.

**Independent Test**: the tests of T020-T021; then the team and graph checks
of quickstart.md section 3 on the exports.

### Tests for User Story 3

- [X] T020 [P] [US3] Create tests/test_people_collaboration_graph_generator.py.
  - `_add_evidence(G, a, a, advisorship_count=1)` adds no edge and changes no edge.
  - `generate(...)` on two people, where one has an advisorship whose `person_id` is their own id, gives no self-edge and keeps the real edge between the two.
  - The same holds for each subclass (researchers only, students, outside IFES, null researchers): `issubclass` and one generate call each.
- [X] T021 [P] [US3] Extend tests/test_canonical_exporter.py with an initiative whose two non-research-group teams both hold person 396 as Coordinator, with start 2020-01-01 in one and 2019-01-01 in the other.
  - The exported `team` has one entry for 396, with `start_date` 2019-01-01 and `roles == ["Coordinator"]`.
  - With roles Coordinator and Researcher in the two teams, `roles` holds both.
  - With an end date in one row and none in the other, `end_date` is `None`.
  - An initiative with one team is exported as today.

### Implementation for User Story 3

- [X] T022 [US3] In src/core/logic/people_collaboration_graph_generator.py, `_add_evidence` returns at once when `a == b`, with a one-line comment naming spec 041 and research R6. T020 passes.
- [X] T023 [US3] In src/core/logic/canonical_exporter.py (initiatives section, the `person_map` block), build `person_map` once per initiative across all non-research-group teams.
  - `roles` is the union, in first-seen order.
  - `start_date` is the earliest non-empty date.
  - `end_date` is `None` when any row has none, otherwise the latest.
  - The output keys and their order do not change.

  T021 passes.

**Checkpoint**: US3 works on any database; it does not need the rebuild.

---

## Phase 6: User Story 4 - Titles, years and dates read correctly (Priority: P2)

**Goal**: a lost dash in a Lattes title shows as "–"; no article has a year
outside 1950 to the current year plus one. Source errors (the titleless
article, workplans that end before they start) stay.

**Independent Test**: the tests of T024-T025; then the title and year checks
of quickstart.md section 3.

### Tests for User Story 4

- [X] T024 [P] [US4] Create tests/test_title_rules.py with every row of contracts/dashboard-fixes.md section 4: `fix_lost_dash`, and `plausible_year` with the current year taken from `datetime.date.today()`.
  - Add a property-style loop over the titles of the contract plus 20 titles with real question marks: `normalize_text(fix_lost_dash(t)) == normalize_text(t)` (from src/core/logic/initiative_identity.py) and `LattesParser().normalize_title(fix_lost_dash(t)) == LattesParser().normalize_title(t)`.
- [X] T025 [P] [US4] Extend tests/test_lattes_parser.py. A curriculum fixture with a lost dash in:
  - a research project `nome`;
  - an advisorship `titulo` (both parser paths);
  - an article `titulo`;
  - a conference paper `titulo`;
  - a technical production title.

  Assert each parsed title has " – " and that a title ending in "entrar?" is unchanged. A conference paper with `"ano": 0` and an article with `"ano": "1890"` give `year is None`; `"ano": 2015` gives 2015.

### Implementation for User Story 4

- [X] T026 [US4] Create src/core/logic/title_rules.py (pure, standard library only) with:
  - `fix_lost_dash(title)`: replace each `(?<=\w) \? (?=\w)` with " – "; leave `None` and empty values unchanged;
  - `plausible_year(value) -> Optional[int]`: an int between 1950 and `date.today().year + 1`, else `None`.

  Module docstring pointing to contracts/dashboard-fixes.md section 4. T024 passes.
- [X] T027 [US4] In src/adapters/sources/lattes_parser.py:
  - apply `fix_lost_dash` to the title read in `_parse_generic_projects` (`name`), `_parse_items` and `_parse_generic_advisorships` (`titulo`), `parse_articles`, `parse_conference_papers` and `parse_technical_productions`;
  - ~~use `plausible_year` for the year in `parse_articles` and `parse_conference_papers`~~ (reverted by T038: `articles.year` is NOT NULL).

  `normalized_title` is computed from the fixed title, which gives the same value. T025 passes.

**Checkpoint**: US4 is in the code; stored titles and years change after the rebuild.

---

## Phase 7: Rule version (cross-cutting, after US2 and US4)

**Purpose**: make the weekly rebuild a database written under version 6, so
the fixes of US2 and US4 reach every curriculum (research R1). It goes last,
so no test run before it leaves a local database half under the new rules.

- [X] T028 Extend tests/test_rule_version_guard.py.
  - `HORIZON_RULE_VERSION == 7`.
  - `rule_version_requires_reset` is true for a database recorded with 6 and false for one recorded with 7.
  - Update any test that pins version 6.
- [X] T029 In src/core/logic/horizon_identity.py, set `HORIZON_RULE_VERSION = 7` and add the comment line: `# 7 (branch 041): advisors of academic degrees, students split on "/", project members, Lattes titles and article years are read by new rules, so a database written before is rebuilt once.` T028 passes.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T030 [P] Update docs/backlog.md.
  - Check first that no entry uses the numbers below, and renumber if needed.
  - Mark as implemented by branch 041, with "validation pending":
    - TD-048, the advisor fields of academic educations and the project members;
    - TD-051, student fields with several people.
  - Add after TD-056, each with Status: Open:
    - `TD-057 — One-word texts kept as students of Lattes advisorships` ("Vários", "FAPEC", "Inovafiltros", a link, comma lists with no spaces; research R4);
    - `TD-058 — Two students joined by " e "` (research R5);
    - `TD-059 — "?" in place of quotation marks and broken encoding in Lattes titles` (research R8);
    - `TD-060 — Initiatives with two teams holding the same person` (the export merges them since branch 041; the second team is still stored; research R7).
- [X] T031 [P] Run black, isort and flake8 on the touched files only (the files of the Code table and the touched tests), with `--check`/`--diff` first.
  - Apply the formatters only where they change lines of this branch.
  - Record the flake8 count of the repository; it must not grow from T001.
  - Result: black reformatted only lines of this branch in `canonical_exporter.py` and five test files that were clean before; `strategies/lattes_advisorships.py` and `strategies/lattes_projects.py` already failed black and isort before this branch and were not reformatted (the new lines were wrapped by hand). flake8 on the touched source files: the same counts as before, except one E402 in `src/flows/lattes/projects.py` (the new import sits with the 26 imports that already follow code in that file). Repository: 580 (580 at T001).
- [X] T032 Run the full suite (`.venv/bin/python -m pytest -q > logs/pytest_041_full.log 2>&1`) and record the result under this task.
  - Expected: every test of T001 still passes, plus the new ones, with 0 failed.
  - Result: 1845 passed, 10 skipped, 0 failed in 7m08 (logs/pytest_041_full.log): the 1553 of T001 plus 292 new. The formatters of T031 ran before it. `make ci-check` was not run again; it fails on the repository before this branch (spec 033 T026).
  - Record `make ci-check` as in spec 033 T026.
- [X] T033 Measure the baseline of quickstart.md section 2 on the exports of fork main (`c5ffe55`) with a read-only script in the session scratchpad, and record every value under this task. Read-only; needs no approval.
  - Result (read-only, scratchpad `baseline41.py` on the canonical archive of `c5ffe55`): people 18,338; one-word people 49, of which 21 are fragments ("-", "1", "2", "A", "D", "Dr", "Dra", "Drª", "G", "H", "J", "L", "Licenciatura", "M", "Ph", "Pro", "Prof", "Profa", "Profª", "R", "xxx"); people whose name holds "/" 54; degrees whose advisor or co-advisor is a fragment 115; initiatives repeating a person in the team 1; self-edges 9 in `people_collaboration_graph` and 9 in `researchers_only_collaboration_graph` (0 in the other three); lost dashes: 238 initiatives, 57 productions, 81 articles; articles with a year outside 1950 to next year 3; titleless articles 1 and initiatives ending before they start 3 (source errors, kept); counts: initiatives 15,547, articles 8,084, research productions 3,734, research groups 353.
- [X] T034 Ask the maintainer before T035. Then back up `db/horizon.db` and `data/` to `data/_backup_<date>_pre041/` with a RESTORE.txt.
- [X] T035 First local run, the rebuild (only after the go-ahead of T034): quickstart.md section 3. Record under this task:
  - the rule-version reset by the weekly's guard;
  - the student-name summary line;
  - every check of section 2 with the measured value;
  - the counts of the other tables against the backup;
  - the person, advisorship and academic-education ids that became aliases or were retired;
  - the spot checks of section 3.
  - **Result of attempt 1 (2026-11-17, 17:26–18:32, exit 0): not accepted.**
    - The weekly guard rebuilt the database once ("Database rule version differs from the code's").
    - Student names: title 1, link 1, work title 154, footnote 2, not a name 3, several 262, uncut 1, split 52, citation 2.
    - Horizon ids: 75,828 entities, rule version 7; aliases 10,568 (298 new).
    - Checks against c5ffe55: fragment people 21→0, degrees with a fragment advisor 115→0, people with "/" 54→2, initiatives repeating a person 1→0, self-edges 9/9→0/0, lost dashes 238/57/81→0/0/0, articles with a bad year 3→0. Kept by decision: 1 titleless article, 3 workplans that end before they start.
    - The 2 "/" people left are both advisors, not students: "Félix O. García / Mario Piattini" and "João Paulo A. Almeida / Giancarlo Gizzardi".
    - **Defect found:** `plausible_year` gives `None`, but `articles.year` is NOT NULL. The insert failed 3 times, and the session was not rolled back after the failure, so the whole curriculum failed. lattes_projects reported failed=3 (partial): Lattes 9137066636997530, 5161006787984996 and 6834022741356193. Their projects, articles and other items are missing from this database (examples: "Bule Cheio - Produzir + Agro", "Verticalização Litorânea"). This explains most of the lower counts: initiatives 15,547→15,538, articles 8,084→8,070, productions 3,734→3,732.
  - **Result of attempt 2 (after T038; backup of T034 restored; 2026-11-17, 19:27–20:36, exit 0): accepted.**
    - The guard rebuilt the database once; lattes_projects and lattes_advisorships processed 435 curricula each, failed 0. The 3 curricula of attempt 1 are back.
    - Lattes downloads: refreshed 106, reused 326, 3 kept from the cache after an access check page (6563795137628376, 8155773475663050, 9478445196688883).
    - Student names: title 1, link 1, work title 154, footnote 2, not a name 3, several 262, uncut 1, split 52, citation 2.
    - Horizon ids: 75,928 entities, rule version 7; aliases 10,467 (193 new; per reason: upgraded key 355, retired 3,388, key corrected 182, rebuild 6,516, merge 26).
    - Checks against c5ffe55: fragment people 21→0; degrees with a fragment advisor 115→0; people with "/" 54→2 (both advisors, see attempt 1); initiatives repeating a person 1→0; self-edges 9/9→0/0; lost dashes 238/57/81→0/0/0; articles with a bad year 3→0. Kept by decision: 1 titleless article, 3 workplans that end before they start.
    - Export counts against c5ffe55: people 18,338→18,439; initiatives 15,547→15,548; articles 8,084→8,082; productions 3,734→3,732; advisorships 190 and research groups 353 unchanged.
    - The lower counts are records that are no longer in the curricula; the persistent database had kept them, and a rebuild only holds what the sources give:
      - "Cultura do Coco" (2007) and "Cultura do cacau" (2007);
      - "VALIAÇÃO DO POTENCIAL ACARICIDA…", now spelled "AVALIAÇÃO…";
      - two "Death Rate Outbreak" projects.
      Two spellings of "Extracts of plant residues from soursop peels…" with the same DOI are now one article.
    - Database against the backup: persons 18,335→18,439; articles 8,079→8,082; initiatives 15,550→15,548; advisorships 11,910→11,908; advisorship_members 23,817→23,889; team_members 49,611→49,647; ingestion_runs 112→8 (the rebuild).
- [X] T038 Fix the defect found by T035 (research R9, revised):
  - src/adapters/sources/lattes_parser.py: article and conference years are read as before (the source digits, 0 included);
  - src/core/logic/canonical_exporter.py: `export_articles` passes the year through `plausible_year`, so the export gives `null` for a year outside 1950 to the current year plus one;
  - src/flows/lattes/projects.py: `ingest_articles_task` calls `session.rollback()` when an article fails, so one bad article never fails the rest of the curriculum;
  - tests: tests/test_lattes_parser.py (years kept as the source gives them), tests/test_canonical_exporter.py (`test_export_articles_blanks_implausible_years`), tests/test_lattes_articles.py (`test_a_failed_article_rolls_back_and_the_next_one_is_ingested`).
  - Result: full suite 1847 passed, 10 skipped, 0 failed; flake8 580 (unchanged).
  - Next: restore the backup of T034 and repeat T035 (attempt 2), then T036.
- [X] T036 Second local run (ask the maintainer first; keep a copy of the database of T035): quickstart.md section 4.
  - Record every difference between the two databases, with its explanation.
  - Expected: none apart from `ingestion_runs` and curricula downloaded again with new content.
  - **Result (2026-11-17, 20:37–21:30, exit 0; copy of the T035 database in `data/_backup_2026-11-17_run1_041/`): accepted with known differences.**
    - Documents processed / skipped:
      - SigPesq groups 2/351, projects 2/101, advisorships 58/1,145;
      - CNPq groups 4/346;
      - lattes_projects 93/342, lattes_advisorships 50/385;
      - failed 0.
    - Of the processed documents, 9 have new content: 4 curricula in each Lattes phase and 1 CNPq group. The others only had a new dependency fingerprint: lattes_projects 89, SigPesq advisorships 58, lattes_advisorships 46, CNPq groups 3, SigPesq projects 2.
    - Lattes downloads: refreshed 108, reused 326, 1 kept from the cache after an access check page.
    - Table differences against the T035 database:
      - from new content: academic_educations +1 and professional_activities +1 (curriculum 1550469618701292);
      - ingestion_runs 8→16;
      - bookkeeping: source_document_items 106,720→106,698 and source_document_references 49,508→49,501 (item refs of the T035 run that named a person merged afterwards, such as researcher 10509 for 9070, are written again with the surviving id);
      - attribute_assertions +8, entity_change_logs +13, entity_matches +1, source_records +2.
    - Known difference, pre-existing and out of scope (backlog TD-061): about 40 `team_members` rows now point to the curriculum owner instead of a citation-form duplicate ("FONTES, Alexandre Gomes" → "Alexandre Gomes Fontes"; also D'Azeredo Orlando and Maxwell Monteiro).
    - The same pass replaced one Lattes advisorship by a name-keyed copy (advisorship:lattes:h:b2d5d5635c9f retired, advisorship:h:fb16cfe336dd back). The curriculum holds four near-duplicate entries of that work.
    - Horizon ids: 75,930 entities (+2), aliases 10,467 (unchanged), history from the database.
    - No change in persons, initiatives, articles, advisorships or any 041 check.
- [X] T037 Fork validation (ask the maintainer first; only on the RafaelDeps fork, never upstream; push without force): quickstart.md section 5.
  - Two weekly runs on `041-dashboard-visible-fixes`. Record for each:
    - the run id and result;
    - that the Slack channel got no message (the maintainer confirms);
    - the `::notice::Slack pulado` lines in both notice steps;
    - the checks of section 3 on the run's archives;
    - `grep -c hooks.slack.com` on the log (expected 0).
  - After the maintainer merges into fork main, record that one run on main sent both messages.
  - **Run 1** (44211232427, 2026-11-18, commit 6fea3c3): success, 1 h 45 min.
    - Slack: `::notice::Slack pulado: a branch 041-dashboard-visible-fixes não é a main.` in both notice steps; `grep -c hooks.slack.com` = 0.
    - First run on the branch, so there was no earlier database to restore ("restore: rebuilt — no successful run"). The database was rebuilt, with id history from the zip.
    - The Lattes portal served its access check page for 28 curricula. 25 came from the cache; 3 had no data (processed 432, failed 3, download). This is not a 041 effect.
    - Horizon ids: 74,512 entities; 11,632 aliases.
    - Checks (section 3): fragment people 0; degrees with a fragment advisor 0; "/" people 2 (both advisors, as in T035); repeated team person 0; self-edges 0 in the 5 graphs; lost dashes 0; bad years 0; kept by decision: 1 titleless article and 3 workplans ending before they start.
    - Counts: people 18,311; initiatives 15,166; articles 7,694; productions 3,732 → 3,681. They are lower because of the 3 curricula above.
  - **Run 2** (44224995587, 2026-11-18): success, 53 min.
    - Slack: the same notice in both steps; `grep -c hooks.slack.com` = 0.
    - Restored run 1's database, raw files and cache; incremental. Lattes: 435 curricula, 0 failed (projects processed 94, skipped 341; advisorships processed 50, skipped 385).
    - Horizon ids: 75,926 entities (T035: 75,928); 10,220 aliases; history from the database.
    - The same checks as run 1, with the same results.
    - Counts: people 18,444; initiatives 15,544; articles 8,078; productions 3,732. All equal or higher than run 1, and within ±5 of the local T035 run (sources one day later).
  - **Merge**: fork main was fast-forwarded to the branch (c5ffe55..633278b), without force and with no merge commit.
  - **Run on main** (44284207136, 2026-11-18): success, 58 min.
    - Slack: both notice steps ran on main with the webhook set. Neither printed "Slack pulado" or a warning, so both messages were sent. `grep -c hooks.slack.com` = 0.
    - It restored the database of the last main run (44030931902). The rule-version guard rebuilt it once (6 → 7). Lattes: 435 curricula, 0 failed.
    - Horizon ids: 75,926 entities; 10,222 aliases.
    - Checks (section 3): the same results as the two branch runs.
    - Counts: people 18,443; initiatives 15,545; articles 8,079; productions 3,732.
  - The maintainer confirmed that the channel got only the two messages of the main run and none from the branch runs. Accepted.

- [X] T039 Fix the CI lint failure found after the merge into fork main.
  - The CI run of the push (44284192954) failed in "Run Linting": the format check covers the changed `.py` files, and 3 of the 27 were not formatted.
    - `src/core/logic/strategies/lattes_advisorships.py` and `src/core/logic/strategies/lattes_projects.py`: black and isort. This was already the case before 041; the check showed it because 041 changed these files.
    - `tests/test_canonical_exporter.py`: black, for the new year test of T038. Its import order was already wrong before 041.
  - Fix: `isort` and `black` on the 3 files. Only spacing, line breaks and import order change.
  - Check: black and isort pass on all 27 `.py` files changed since c5ffe55; `flake8 --select=E9,F63,F7,F82` gives 0; full suite 1847 passed, 10 skipped.

---

## Dependencies & Execution Order

### Phase Dependencies

| Phase | Depends on | Order inside |
|---|---|---|
| Setup (Phase 1) | nothing | |
| US1 (Phase 3) | T001; independent of the others | T002, T003 -> T004 -> T005 -> T006 |
| US2 (Phase 4) | T001 | Tests T007-T013 first. Then T014 -> T015 -> T016 -> T017; T018 after T017; T019 after T014. |
| US3 (Phase 5) | T001; independent | T020, T021 -> T022, T023 |
| US4 (Phase 6) | T001 | T024, T025 -> T026 -> T027 |
| Rule version (Phase 7) | US2 and US4 | T028 -> T029 |
| Polish (Phase 8) | every phase above | T030-T033 in any order; then T034 -> T035 -> T036 -> T037, each needing the maintainer's go-ahead |

**Note on US4**: T027 and T016 touch the same file
(src/adapters/sources/lattes_parser.py), so T027 runs after T016.

### Within Each User Story

- Tests first, and seen failing, before the implementation.
- Tasks in the same file run in sequence:

| File | Tasks |
|---|---|
| tests/test_lattes_parser.py | T010, T025 |
| src/adapters/sources/lattes_parser.py | T016, T027 |
| src/core/logic/student_name_rules.py | T015 (and T014 if the initial test is moved) |

### Parallel Opportunities

- T002 and T003, and T020 and T021: different files.
- T007, T008, T009, T011, T012 and T013: different test files.
- US1 and US3 touch no file of US2 or US4, so they can be done in any order.

---

## Parallel Example: User Story 2

```bash
Task: "T007 tests/test_person_name_rules.py (contract sections 1-2)"
Task: "T008 tests/test_student_name_rules.py (contract section 3)"
Task: "T009 tests/test_lattes_projects_strategy.py (fragment members)"
Task: "T012 tests/test_initiative_handlers.py (several Student members)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001, then T002-T006.
2. Stop and check: the tests pass, and a run on this branch would send nothing. Every later fork run of this and the next specs stays quiet from here on.

### Incremental Delivery

1. US1: Slack only on main.
2. US2: real people and advisors.
3. US3: teams and graphs, working on any database.
4. US4: titles and years.
5. Phase 7: the version changes, which makes the weekly rebuild an older database.
6. Polish: backlog, lint, full suite, baseline, then the three validations that need approval.

---

## Notes

- No table, column, export field or id rule changes. Only the rule version changes. No change to third-party libraries, to the dashboard or to Docker.
- Source errors stay as they are (clarifications of 2026-11-17): the titleless article, the 3 workplans that end before they start, and a curriculum owner listed as their own student. Only the self-edge it caused is hidden.
- The first fork run after the rebuild can miss items of curricula whose download failed; compare the second run (quickstart.md section 5).
- Commit only when the maintainer asks. Never stage `data/`, `logs/`, `PLANO_*.md`, `RESUMO_*.md` or export zips.
