---

description: "Task list for the fixed rule for fields written by several documents"
---

# Tasks: Fixed Rule for Fields Written by Several Documents

**Input**: Design documents from `specs/030-deterministic-field-merge/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/field-merge.md, quickstart.md

**Tests**: the spec measures the feature with tests:
- SC-002: the same documents loaded in three or more orders;
- SC-003: an unchanged second pass writes nothing;
- SC-004: the TD-029 collision.

Each story therefore starts with its tests, which must fail before the code
is written. They use in-memory SQLite databases and fixture documents. No test
touches the network or `db/horizon.db`.

Branch and spec numbers differ up to branch 028. "Branch 024 (spec 021)" names
the branch first and the `specs/` folder second.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md

`$R` is this session's scratchpad. Copies of databases and artifacts go
there. The real `db/horizon.db` is never written without a restorable backup
of it and of `data/` first.

---

## Phase 1: Setup

- [X] T001 Record the baseline in `$R/e/E_BASE.txt`:
  - run `.venv/bin/python -m pytest -q` in the main checkout and save the
    list of failing tests (expected: the 6 known failures: chromedriver ×3,
    `test_loader_mapping`, SigPesq 429, the cron string);
  - copy the TD-028 numbers of `docs/reports/2026-10-29-skip-unchanged-validation.md`
    section 8: about 130 initiatives, 5 fellowships and 123 advisorships.
- [X] T002 [P] Download the artifact of CI run 40952053776 into
  `$R/td029/`, never into `db/`:
  `gh run download 40952053776 --repo RafaelDeps/horizon_etl -n weekly-etl-artifacts -D $R/td029`.
  Record its database path and the `data/lattes_json` file of CV
  `1703547133505721` in `$R/e/E_BASE.txt` (quickstart §2).

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the claims table, its port and adapter, the pure resolver, and
the document-end hook that every writer uses.

### Tests

- [X] T003 [P] Write `tests/test_field_merge.py` for the pure core
  (contract field-merge.md, data-model "Resolution rule"):
  - `claim_sort_key`: a dated claim beats an undated one; the later date wins;
    at the same date, Lattes (rank 0) beats SigPesq (1) and CNPq (2); between
    Lattes CVs with the same date, the lowest Lattes id wins; between SigPesq
    rows, the highest Id wins; a SigPesq report row beats the PDF of the same
    project;
  - `is_empty`: `None`, `""`, whitespace and status `"Unknown"` are empty;
  - `resolve`: empty claims never win; with all claims empty there is no
    resolution for the field; values that differ only in spaces or case count
    as one value; `decided_by` is `single`, `by_date`, `by_source` or
    `by_tiebreak` as data-model defines;
  - every permutation of a 4-claim fixture gives the same result
    (`itertools.permutations`, SC-002);
  - `lattes_document_date`: `{"informacoes_pessoais": {"atualizacao_cv":
    "30/10/2026"}}` → `"2026-10-30"`; missing or unreadable → `None`.
- [X] T004 [P] Write `tests/test_field_claim_store.py` for the SQLite adapter
  on an in-memory database with the migrations applied:
  - `replace_document_claims` replaces only that document's claims and
    returns the touched entities (added, removed, changed value), and no
    entity when nothing changed;
  - `drop_document_claims` and `drop_entity_claims` remove claims and return
    the touched entities;
  - `claims_for` returns the claims of every source;
  - `move_claims` moves claims to the winner, keeping one row per primary
    key;
  - a rollback of the `DocumentTransaction` discards the claims written in
    it;
  - values are PII-scrubbed: a CPF in a description is stored scrubbed, like
    `attribute_assertions`.

### Implementation

- [X] T005 Add migration `0013_source_field_claims` to
  `src/db/migrations.py`, after `0012_source_document_downloaded_at`. It
  creates the table and the index of data-model.md:
  - primary key `(source_system, document_key, entity_type, entity_id,
    field)`;
  - index `(entity_type, entity_id, field)`.

  The `CREATE TABLE IF NOT EXISTS` makes it idempotent, like the other
  migrations.
- [X] T006 [P] Create `src/core/ports/field_claim_store.py`. It holds
  `FieldClaim` (frozen dataclass), `IFieldClaimStore` and `IFieldWriter`, as
  in contracts/field-merge.md. Make `IFieldWriter` read and write the stored
  value of one field of an `initiative`, `advisorship` or `fellowship`.
- [X] T007 Create `src/core/logic/field_merge.py` (depends on T006). It holds:
  - `claim_sort_key`, `is_empty`, `resolve`, `Resolution` and
    `lattes_document_date`;
  - `FieldMergeStats`, with the counts of research R10 and `dates_missing`;
  - `FieldMergeApplier`.

  `resolve` is pure. `FieldMergeApplier.apply` writes only the fields whose
  winner differs from the stored value after `canonical()` comparison
  (research R5), and leaves the stored value as it is when every claim is
  empty. It imports no adapter (Principle I). T003 passes.
- [X] T008 Create `src/adapters/database/field_claim_store.py` (depends on
  T005, T006). It holds `SqliteFieldClaimStore` and `SqliteFieldWriter`, both
  on the connection of `DocumentTransaction`
  (`src/adapters/database/document_transaction.py`), so a document rollback
  discards them. Scrub values with `scrub_pii_deep` from
  `src/tracking/recorder.py`'s import path before writing. T004 passes.
- [X] T009 Hook the claims into `src/core/logic/document_skip.py`:
  - `Document` gets `claim(entity_type, entity_id, field, value, *,
    doc_date, source_rank, tie_key)`, which collects claims, plus a
    module-level `claim(...)` helper like `carry(...)`;
  - in `DocumentSkip._commit`, before `commit_processed`, call
    `replace_document_claims` for the document, then
    `FieldMergeApplier.apply(touched)`;
  - for every deletion that `commit_processed` returns, call
    `drop_entity_claims` and add the entity to the next `apply`;
  - a document that collected no claims does nothing new.

  Pass the store and the applier in from `src/flows/document_phase.py`
  (`document_phase` and `document_phases` build them on the same
  transaction).
- [X] T010 Run the existing branch 024 (spec 021) tests,
  `tests/test_document_skip*.py` and `tests/test_document_phase*.py` (if
  present), and the full suite. They pass unchanged, because no writer
  collects claims yet.

**Checkpoint**: claims can be stored and resolved, and nothing writes them yet.

---

## Phase 3: User Story 1 - A shared initiative gets the same values in any run (Priority: P1) 🎯 MVP

**Goal**: description, status, start date and end date of an initiative come
from the rule, whatever documents a run reprocesses.

**Independent Test**: load an initiative from two Lattes CVs with different
update dates and a SigPesq row, in every order and with only one document
reprocessed. The stored values are always the same.

### Tests for User Story 1

- [X] T011 [P] [US1] Write `tests/test_field_merge_loaders.py::TestInitiatives`
  with the 6 acceptance scenarios of US1. Each test:
  - loads fixture CVs (`informacoes_pessoais.atualizacao_cv` set) through the
    `lattes_projects` loader path, and a SigPesq project row through the
    SigPesq loader path, on an in-memory database with `document_phase`;
  - does so in every order;
  - then reprocesses only one document.

  It asserts the stored description, status and dates, and that the second
  unchanged pass writes 0 change log rows (SC-003).
- [X] T012 [P] [US1] In the same file, write `TestEmptyValues`:
  - a document with no status never turns a stored status into `"Unknown"`;
  - a newer CV with an empty end date does not win the end date;
  - a project removed from a CV stops taking part (FR-009), and the field
    falls back to the other documents' winner.
- [X] T013 [P] [US1] In the same file, write `TestProjectFiles`:
  - the PDF description fills an initiative whose Lattes and SigPesq claims
    are all empty;
  - it never replaces a Lattes or report-row description.

### Implementation for User Story 1

- [X] T014 [US1] In `src/flows/lattes/projects.py`, read the CV date with
  `lattes_document_date` once per CV (the JSON is already loaded in
  `_ingest_researcher_file`). Give the loader the date, `source_rank=0` and
  `tie_key=` the 16-digit Lattes id. When the date is missing, count it in
  `FieldMergeStats.dates_missing`.
- [X] T015 [US1] In `src/flows/sigpesq/projects.py` (and the strategy
  `src/core/logic/strategies/sigpesq_projects.py` if the Id is not in
  `project_data` yet), give the loader `doc_date=None`, `source_rank=1` and
  `tie_key="0|"` followed by the zero-padded negated SigPesq Id (research R4).
- [X] T016 [US1] In `src/core/logic/project_loader.py::_process_row`, after
  `handler.create_or_update` returns an initiative (not an advisorship),
  claim `status`, `description`, `start_date` and `end_date` from
  `project_data` with the document's date, rank and tie key (T014, T015).
  Keep matching and creation unchanged.
- [X] T017 [US1] In `src/core/logic/initiative_handlers.py::StandardProjectHandler.create_or_update`,
  on update, stop passing `status="Unknown"`, `description=None` and empty
  dates over stored values. Pass only the non-empty values, and let the
  resolver set the rest. On create, keep today's values.
- [X] T018 [US1] In `src/core/logic/project_enrichment.py::_enrich_winners`,
  turn the PDF description into a claim:
  - `source_system="sigpesq_project_files"`, `document_key=` the PJ code,
    `source_rank=1`, `tie_key="1|<code>"`;
  - call `replace_document_claims` and `FieldMergeApplier.apply` for the
    initiative, in the same session it commits;
  - drop the `write_desc` shortcut, because the rule decides;
  - keep `enrichment_json` and its `prior` carry-forward as they are
    (research R6).
- [X] T019 [US1] *(Not applicable: research R9, corrected. No phase merges initiatives.)* In `src/core/logic/reference_consolidator.py`, next to the
  `source_document_items` move (lines 268–291), move `source_field_claims`
  from the merged initiative to the winner (`UPDATE OR IGNORE`, then
  `DELETE`). Then resolve the winner's fields again with
  `FieldMergeApplier.apply` (research R9).
- [X] T020 [P] [US1] Add `"source_field_claims"` to `SKIP_TABLES` in
  `specs/021-skip-unchanged-documents/research-scripts/compare_with_rebuild.py`.
- [X] T021 [US1] Run T011–T013 and the full suite. Only the T001 failures are
  allowed.

**Checkpoint**: initiatives are order-free. US2–US4 can follow in any order.

---

## Phase 4: User Story 2 - A shared fellowship gets the same values in any run (Priority: P2)

**Goal**:
- the fellowship value comes from the rule;
- the advisorship's status, description and dates come from the rule.

**Independent Test**: load a fellowship from two SigPesq workplans with
different values in both orders. The value is the one of the workplan with
the highest SigPesq Id.

### Tests for User Story 2

- [X] T022 [P] [US2] Write `tests/test_field_merge_loaders.py::TestFellowships`
  with the 2 acceptance scenarios of US2:
  - two workplans with values 600 and 700 (Ids 4882 and 5120) in both orders
    → 700;
  - a Lattes CV with another end date → the Lattes end date, and the SigPesq
    value is kept.

  It also asserts that the advisorships keep pointing at the same fellowship
  row.

### Implementation for User Story 2

- [X] T023 [US2] In `src/flows/sigpesq/advisorships.py` and
  `src/flows/lattes/advisorships.py`, give the loader the document's date,
  rank and tie key:
  - SigPesq: the workplan Id, as in T015;
  - Lattes: the CV date and id, as in T014.
- [X] T024 [US2] In `src/core/logic/initiative_handlers.py::AdvisorshipHandler`:
  - after create or update, claim the advisorship's `status`, `description`,
    `start_date` and `end_date`;
  - in `_ensure_fellowship`, stop writing `value` on an existing fellowship,
    and instead claim `fellowship.value` for SigPesq workplans only (Lattes
    has no value);
  - on a new fellowship, keep the creation value;
  - apply the T017 "no empty overwrite" change to the advisorship update.
- [X] T025 [US2] Run T022 and the full suite.

**Checkpoint**: fellowships and advisorships are order-free.

---

## Phase 5: User Story 3 - A project with an identical stored name no longer fails its CV (Priority: P3)

**Goal**: TD-029. A Lattes project whose title is a stored initiative name
joins it, and a name held by an advisorship is reported without failing the
CV.

**Independent Test**: store an initiative, then load a CV with a project of
the same title that the identity lookup does not find. The CV is not partial.

### Tests for User Story 3

- [X] T026 [US3] Reproduce TD-029 on a copy of the T002 database, in `$R/td029/`:
  - load CV `1703547133505721` through `lattes_projects` against it, before
    any US3 change;
  - record in `$R/e/E_TD029.txt` which path of research R7 fails: an
    identical name held by an advisorship, or a rename onto a name another
    initiative holds;
  - record the title and the two ids involved.
- [X] T027 [US3] Write `tests/test_title_collision.py`:
  - an identical name of the same kind resolves to the stored initiative;
  - a project whose title is held by an advisorship is stored with the plain
    name, and the advisorship is renamed to
    `_build_disambiguated_advisorship_title` of its own data;
  - `AdvisorshipHandler.find_existing` with that advisorship's data finds the
    renamed row (no duplicate);
  - a rename onto a name another initiative holds keeps the persisted name.

### Implementation for User Story 3

- [X] T028 [US3] In `src/core/logic/project_loader.py`, before creating a
  project whose exact name is held by an advisorship, rename that advisorship
  to its disambiguated title. Build the title from its latest tracking
  assertions (`student_names`, `start_date`) and, for SigPesq workplans, the
  workplan Id, with the same `_build_disambiguated_advisorship_title`. Log
  `title collision: ... advisorship <id> renamed to '<title>'`, count
  `collisions_resolved`, and refresh the loader's name indexes. Keep the
  persisted name when a project resolved by identity would be renamed onto a
  name another initiative holds.
- [X] T029 [US3] Run T027. On a fresh copy of the T002 database, load CV
  `1703547133505721` through `lattes_projects`, then through
  `lattes_advisorships`. It is not partial, all 71 projects are stored, and
  the advisorship count does not grow (SC-004).
  Record the result in `$R/e/E_TD029.txt`.

**Checkpoint**: TD-029 is fixed.

---

## Phase 6: User Story 4 - The reviewer can see the rule working (Priority: P4)

**Goal**: one log line per phase with the counts of FR-013.

**Independent Test**: run a load with conflicting documents and read the log.

### Tests for User Story 4

- [X] T030 [P] [US4] Write `tests/test_field_merge_loaders.py::TestMergeLog`:
  - with conflicting documents, the line
    `field merge <phase>: fields=… by_date=… by_source=… by_tiebreak=… collisions_resolved=… collisions_reported=…`
    is logged once;
  - `by_date + by_source + by_tiebreak` equals the number of fields with more
    than one different non-empty value (SC-005);
  - with no conflicts, every count is 0 and no other log line changes.

### Implementation for User Story 4

- [X] T031 [US4] Make `FieldMergeStats` in `src/core/logic/field_merge.py`
  count the decisions of `FieldMergeApplier.apply` and the collisions of
  T028. Log the line from `src/flows/document_phase.py` after
  `skip.log_summary()`, and at the end of `ProjectEnrichmentLoader.run`. Add
  `dates_missing=<n>` only when it is not zero.
- [X] T032 [US4] Run T030 and the full suite.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T033 Raise `HORIZON_RULE_VERSION` from 1 to 2 in
  `src/core/logic/horizon_identity.py` (FR-014, research R8). Add a short
  comment naming the reason (field claims, branch 030). Update any test that
  pins the value, for example in `tests/test_horizon_identity.py`.
- [X] T034 [P] Update `docs/backlog.md`:
  - TD-028 and TD-029 get status `Done (branch 030)`, with one line each on
    the fix;
  - if T026 or the replay finds a known exception (for example `enrichment_json`
    rows, research R6), add it as a new TD.
- [X] T035 [P] Update `docs/flows-and-entrypoints.md` (or the doc that
  describes the weekly phases) with a short paragraph on the field claims and
  the `field merge` log line.
- [X] T036 Run `make ci-check` (flake8, black, isort, mypy, pytest). Fix new
  findings only. The failures of T001 are allowed.
- [X] T037 Replay on the real database (quickstart §3, SC-001, SC-003). **Only
  when the maintainer asks for it** (decision of 2026-11-05: on
  `db/horizon.db`, not on copies; never started on our own). It rebuilds the
  database, so back up `db/horizon.db` and `data/` first, in
  `data/_backup_2026-11-XX_pre030/`:
  1. rebuild;
  2. a second weekly pass (it downloads SigPesq again and refreshes a share
     of Lattes and CNPq, so it is not unchanged; `REFRESH_SHARE=0` is
     rejected);
  3. an unchanged pass with the local phases only (`ingest_lattes_projects`,
     `lattes_advisorships`, `enrich_projects`): every document skipped, no
     table changed apart from `ingestion_runs` and `last_seen_at`;
  4. change two CVs and one SigPesq row, then the same local phases;
  5. rebuild from the final inputs into `$R/rebuild_b.db`;
  6. run `compare_with_rebuild.py`. Expected: 0 rows differ in
     `initiatives`, `advisorships` and `fellowships`.

  Record the timings (SC-006) and the `field merge` lines in
  `$R/e/E_REPLAY.txt`.

  Found on 2026-11-06 (pass 3): the enrichment, run alone, rewrote the dates
  and status of 28 parent projects, undoing `recalculate_parent_projects`,
  because a document resolved every merged field of the entity and not only
  the fields it claimed. Fixed: `replace_document_claims` returns the claimed
  fields and `FieldMergeApplier.apply` resolves only those. The database was
  restored to the pass 2 copy. Pass 3 run again after the fix: 435/435
  skipped in both Lattes phases, and 0 differences in every table (SC-003).

  Pass 4 (two CVs edited: a description, a status) reprocessed only those two
  CVs and changed exactly two initiatives. Rebuild B (offline: SigPesq from the
  stored spreadsheets, CNPq from the stored pages) compared with
  `compare_with_rebuild.py`: initiatives 40, advisorships 8, fellowships 2/1
  (before the feature about 130, 123 and 5). None is in a merged field except
  `advisorships.cancelled`, written by both rows of a workplan whose student
  was replaced; it was added to the merged fields (highest SigPesq Id wins).
  The rest is in `docs/backlog.md` (TD-033 to TD-037). The comparison runs
  again after this change, on a database rebuilt with it. Restore the backup at the end if the maintainer asks.
- [X] T038 Ask the maintainer before dispatching. Then run the fork run of
  `weekly-etl.yml` on `030-deterministic-field-merge` (quickstart §6). It is
  the first run of the branch, so it starts from scratch. Check:
  - every phase exits 0;
  - the `field merge` lines appear;
  - the line `SQLite finalize: {'finalized': True, …}` appears.

  Done on 2026-11-09. Run 42616860871 started from scratch and run
  42634852240 restored its state. Both ended with every phase at exit 0,
  the `field merge` lines, rule version 2 and `finalized: True`. Comparing
  both databases by horizon_id: no entity type lost rows, `cancelled` was
  equal everywhere (46), and only 3 initiative fields changed, each with a
  known cause. Most documents processed by the second run had the same
  content; their references to projects created later in the first run went
  from not found to found, once. The id of PJ 4911 became PJ 4742, kept as
  an alias: the PDF of PJ 4742 failed to download in the first run, and the
  lower code wins.
- [ ] T039 Write `docs/reports/2026-11-XX-deterministic-field-merge-validation.md`
  with:
  - the baseline;
  - the tests;
  - the TD-029 reproduction and fix;
  - the replay comparison;
  - the timings against SC-006;
  - the fork run;
  - the residual risk.

  Use the branch number first, then the spec folder.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependency. T002 is needed only by US3.
- **Foundational (Phase 2)**: depends on Setup and blocks every story.
  - T005 comes before T008.
  - T006 comes before T007 and T008.
  - T007 and T008 come before T009.
- **US1 (Phase 3)**: depends on Phase 2.
- **US2 (Phase 4)**: depends on Phase 2. It shares T017's change with US1,
  so do it after US1 or apply T017 first.
- **US3 (Phase 5)**: depends on Phase 2 and T002. Its code (T028) touches
  `project_loader.py` like T016, so do it after T016.
- **US4 (Phase 6)**: depends on T007 and on the collisions counted in T028.
- **Polish (Phase 7)**: after the stories. T033 comes before T037 and T038,
  so the replay and the fork run use rule version 2.

### Within Each User Story

- Tests are written first and fail.
- Then the flow wiring (dates, ranks, tie keys).
- Then the loader and handler changes.
- Then the full suite.

### Parallel Opportunities

- T001 and T002.
- T003 and T004, and T006 while they are written.
- T011, T012 and T013 are classes in one test file. Split them only if
  several people work on it.
- T020 runs alongside any US1 task.
- T034 and T035.

---

## Parallel Example: Foundational

```bash
Task: "Write tests/test_field_merge.py (T003)"
Task: "Write tests/test_field_claim_store.py (T004)"
Task: "Create src/core/ports/field_claim_store.py (T006)"
```

## Parallel Example: User Story 1

```bash
Task: "Write TestInitiatives, TestEmptyValues, TestProjectFiles (T011–T013)"
Task: "Skip source_field_claims in compare_with_rebuild.py (T020)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 and Phase 2.
2. Phase 3 (US1). This fixes most of TD-028: about 130 initiatives.
3. **Stop and validate:**
   - T011 to T013 pass;
   - a short replay on a copy shows 0 initiative differences.

### Incremental Delivery

1. Foundation, then US1: initiatives are order-free.
2. US2: fellowships and advisorships are order-free.
3. US3: TD-029 is fixed.
4. US4: the log line.
5. Polish: the rule version 2 rebuild, the replay, the fork run and the
   report.

---

## Notes

- Only code and documentation are staged, with explicit `git add` paths.
  Never stage `cache/`, `data/`, `logs/` or the personal `PLANO_*.md` /
  `RESUMO_*.md`.
- Commit only when the maintainer asks.
- Third-party libraries stay unchanged (eo_lib, research_domain,
  scriptLattes, dgp_cnpq_lib, agent_sigpesq).
- Do not change Docker.
- SigPesq stays sequential, and CNPq keeps 4 workers.
