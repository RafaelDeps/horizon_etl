---

description: "Task list for skipping unchanged source documents on a persistent database"
---

# Tasks: Skip Unchanged Source Documents on a Persistent Database

**Input**: Design documents from `specs/021-skip-unchanged-documents/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Requested by the spec (FR-021, each user story's Independent Test, SC-001 to SC-008, quickstart §1). Test tasks come first in each story and must fail before the implementation.

**Organization**:
- **US1 (P1)**: a run with no source change skips every document and writes nothing.
- **US3 (P1)**: a failed or unreadable document never erases data (implemented before US2, so no deletion path exists without its guards).
- **US2 (P1)**: a changed document is reprocessed alone, dropped items are deleted, and the result equals a rebuild.
- **US4 (P2)**: a document gone from its source stays, marked inactive, and the new export file publishes the statuses.
- **US5 (P2)**: the database persists by default and rebuilds only when it must.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task).
- **[Story]**: US1–US5.
- `$R` = `/tmp/claude-1000/-home-rafael-horizon-etl/5126d108-e5e4-4b9b-af2a-be2bc2b35557/scratchpad/replay021` (session scratchpad; nothing there is committed). If the session changes, use the new scratchpad and rebuild `$R` with Phase 1.
- `PY` = `/home/rafael/horizon_etl/.venv/bin/python`.
- Every replay runs with Telegram off: `export HORIZON_TELEGRAM_BOT_TOKEN= HORIZON_TELEGRAM_CHAT_ID= TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= HORIZON_QUIET_PREFECT=1 PREFECT_LOGGING_TO_API_ENABLED=false`.
- Replays and experiments work on copies under `$R`. Only T059 (the local weekly) writes `db/horizon.db`, by the maintainer's decision of 2026-10-28, after the backup in `data/_backup_2026-10-28_pre021/` (restore: `cp -p data/_backup_2026-10-28_pre021/db/horizon.db db/horizon.db`). Never run `make db-reset` or `make db-clean` on a copy: `db-clean` deletes `db/horizon.db` whatever `DATABASE_URL` says.
- Third-party libraries (`eo_lib`, `libbase`, `research_domain`, scriptLattes, dgp_cnpq_lib) are never edited. Docker is not touched.

---

## Phase 1: Setup (baseline and replay assets, before any code change)

- [X] T001 Create `$R`; copy `db/horizon.db` to `$R/base.db`; copy the base code (`src/`, `app.py`, `db/create_db.py`) to `$R/base021_code/` (remove `__pycache__`), symlink `/home/rafael/horizon_etl/.env` into it, and write `git rev-parse HEAD` to `$R/BASE021.txt`.
- [X] T002 [P] Run `PY -m pytest -q` on the unchanged code and record the result and any failing test ids in `$R/BASE021.txt` (spec 020 recorded 580 passed; recount, do not assume).
- [X] T003 [P] Freeze the replay inputs in `$R/inputs/`: copy `data/raw/sigpesq/`, `data/lattes_json/`, `data/lattes_run/lattes.list`, `data/exports/project_sigpesq_files_json/` and `data/exports/exports_canonical.zip`. Export the 350 CNPq payloads from `$R/base.db` (`source_records` where `source_entity_type='cnpq_group_payload'`: `source_file` is the group URL, `raw_payload_json` the page; keep the most recent row per URL) to `$R/inputs/cnpq_payloads.json` as `{url: payload}`.
- [X] T004 Write the replay harnesses (depends on T003), rebuilding the ones described in `specs/020-horizon-id-idempotent-hash/quickstart.md` §2 and `tasks.md` T005 (they were not committed):
  - `$R/replay_sigpesq.py`: runs the SigPesq ingestion flows on the frozen reports without downloading (loader entry points in `src/flows/sigpesq/projects.py:16`, `groups.py:23`, `advisorships.py:19`).
  - `$R/replay_cnpq.py`: a Prefect flow that patches `CnpqCrawlerAdapter.get_group_data` to return `cnpq_payloads.json[url]` (or `None` for a URL listed in `$R/inputs/cnpq_fail.txt`, to simulate failures) and then calls `sync_cnpq_groups_flow`.
  - `$R/replay_weekly.sh <code_dir> <db> <inputs_dir> [--fresh]`: with `--fresh`, `DATABASE_URL=sqlite:///<db> PY db/create_db.py` first; then `replay_sigpesq.py`, `replay_cnpq.py`, and `app.py` with `ingest_lattes_projects`, `lattes_advisorships`, `enrich_projects`, `consolidate_duplicates`, `assign_horizon_ids`, then `export_canonical <out_dir>`. Every step runs with `PYTHONPATH=<code_dir>` and `DATABASE_URL=sqlite:///<db>`, from a working directory whose `data/` is a copy of `<inputs_dir>`. It prints the elapsed time of each step.
- [X] T005 [P] Write `specs/021-skip-unchanged-documents/research-scripts/compare_with_rebuild.py <incremental.db> <rebuild.db>` following research R11: open both read-only; map every entity row to its `horizon_id` through `horizon_ids` and replace every foreign key by the target's `horizon_id`; compare every existing domain table as a row set; leave out `ingestion_runs`, `source_records`, `entity_matches`, `attribute_assertions`, `entity_change_logs` and the three new tables; leave out the items of documents that are `inactive` or have `last_failure` set in the incremental database; list orphan reference rows and team rows whose only difference is person resolution (spec 020 R9.3) in separate sections; also compare the `sqlite_master` definitions (columns, types, indexes) of every table that exists in `$R/base.db` and fail if any changed (FR-002, SC-007); print `IDENTICAL`/`DIFFERENT (n)` per table and `RESULT: …`; exit 0 only when every remaining table and every existing schema is identical.
- [X] T006 Base references (depends on T004): run `$R/replay_weekly.sh $R/base021_code $R/base_a.db $R/inputs --fresh`, keep its exports in `$R/base_a_exports/` and its step times in `$R/BASE021.txt`. Copy `$R/base_a.db` to `$R/base_a2.db` and run the replay again without `--fresh`; record the step times of this second pass (today's cost of an unchanged rerun, the number this spec reduces).

**Checkpoint**: Base references, harnesses and the comparison script exist; code changes may start.

---

## Phase 2: Foundational (blocking prerequisites)

**⚠️ CRITICAL**: T007–T009 are the in-ETL proof of concept of research R5. If T009 fails and cannot be fixed without editing a library, stop, switch the plan to the fallback (contract [document-processing.md](contracts/document-processing.md) rule 9), record it in [plan.md](plan.md) "Post-design re-check", and tell the maintainer before continuing.

- [X] T007 Add `install_savepoint_support(engine)` to `src/adapters/database/sqlite_settings.py`: for that engine only (not the `Engine` class), a `connect` listener that sets `dbapi_connection.isolation_level = None` and a `begin` listener that runs `conn.exec_driver_sql("BEGIN")` (the recipe in SQLAlchemy's pysqlite "Serializable isolation / Savepoints / Transactional DDL" section). The global WAL listener stays as it is. Explain in the module docstring why it is per engine (research R5 step 3), in the style of the existing docstring.
- [X] T008 Create `src/adapters/database/document_transaction.py` (research R5 steps 1–2): a class `DocumentTransaction` that, given the `DATABASE_URL`, creates a dedicated engine with `install_savepoint_support` (T007), opens one `Connection`, and replaces `_SessionLocal` of both `PostgresClient` singletons (`eo_lib` and `research_domain.infrastructure.database.postgres_client`) with `scoped_session(sessionmaker(bind=<connection>, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False))`; `begin()`, `commit()`, `rollback()` on the connection; `close()` restores the original factories and closes the connection. Before replacing, call `remove()` on the old scoped sessions so no session keeps the old binding. If either singleton lacks `_SessionLocal`, raise a clear error naming the library version (the attribute is private; research R5). Also make `TrackingServiceFactory._session` in `src/tracking/service_factory.py` return a session bound to the active `DocumentTransaction` connection (same join mode) when one is active, and today's session otherwise.
- [X] T009 Proof of concept (depends on T007, T008): write `tests/test_document_transaction.py` with a temporary SQLite database and the real libraries:
  - inside `begin()`, two `PersonController().create(...)` calls (they commit) are invisible to an independent `sqlite3` connection; after `commit()` they are visible;
  - after `rollback()`, none of them remain, and a following `begin()`/`commit()` cycle works;
  - a `session.rollback()` inside the document (a failed row) undoes only the last savepoint and the session keeps working;
  - controllers of both libraries (`eo_lib` and `research_domain`, e.g. `AdvisorshipController`) get sessions bound to the same connection;
  - after `close()`, controllers commit normally again.
  Then, on copies of `$R/base_a.db`, run `ingest_lattes_projects` limited to one CV and `replay_cnpq.py` limited to one group, once with the document transaction wrapped by hand around the document and once without, and compare every table of the two copies as row sets (a short `$R/compare_tables.py <a.db> <b.db>` that prints per table `IDENTICAL`/`DIFFERENT (n)`): identical. Inject an exception after the CV's first writes: no row of the attempt remains. Record the result in `$R/BASE021.txt`.
- [X] T010 Add migrations `0008_source_document_states` and `0009_source_document_items` to `MIGRATIONS` in `src/db/migrations.py` with the three tables of [data-model.md](data-model.md) (`source_document_states`; `source_document_items` with its index on `(item_type, item_ref)`; `source_document_references`), all `CREATE TABLE IF NOT EXISTS`. `0009` holds two tables and one index: split the SQL into separate migration entries (`0009_source_document_items`, `0010_source_document_items_index`, `0011_source_document_references`) because `run_migrations` executes one statement per entry.
- [X] T011 [P] Add `current_document: ContextVar[tuple[str, str] | None]` (source system, document key) to `src/tracking/context.py`, next to `current_ingestion_run_id`.
- [X] T012 Create the port `src/core/ports/document_state_store.py` (an abstract class `IDocumentStateStore`) with the methods of the contract [document-processing.md](contracts/document-processing.md): `load`, `references`, `delta`, `item_count`, `begin_document`, `commit_document`, `rollback_document`, `commit_processed`, `record_failure`, `mark_listing`; plus small dataclasses `DocumentState`, `Reference`, `Delta`, `DocumentOutcome` in the same module. No imports from `src/adapters/`.
- [X] T013 Create the SQLite adapter `src/adapters/database/document_state_store.py` implementing the port's state, reference, listing and transaction methods (items and deletions come in US2), on the shared connection of `DocumentTransaction` (T008) through SQLAlchemy `text()`, never a raw `sqlite3` connection. `commit_processed` writes the state row (upsert) inside the open document transaction; `record_failure` runs after a rollback in its own short transaction. Dates are ISO-8601 UTC strings.
- [X] T014 Create `src/core/logic/document_skip.py` with `DocumentSkip(store, source_system, rule_version)`, `DocumentFailed(reason)` and the per-document context manager of the contract: sets `current_document`; `unchanged(content)` compares `stable_hash(content)` and `rule_version` with the stored state (references come in US1 T020); `begin()`; on normal exit `commit_processed` + `commit_document` (outcome `processed`); on `DocumentFailed` or any exception `rollback_document`, a phase-supplied `on_rollback` callback (to reload caches), `record_failure` (outcome `failed:<reason>`, unknown exceptions → `partial`); counters per outcome and reason; `finish(listed_keys, complete)` (calls `mark_listing`; US4 fills its effect) and `log_summary()` (the R12 line). Import `stable_hash` from `src/tracking/recorder.py` and `HORIZON_RULE_VERSION` from `src/core/logic/horizon_identity.py`.
- [X] T015 [P] Create `tests/test_document_skip.py` for T014 with an in-memory fake store: first sight → processed; same content and rule version → skipped (no store write at all); different content → processed; different rule version → processed; exception inside → rolled back, `failed:partial`, `on_rollback` called; `DocumentFailed("unidentified")` → `failed:unidentified`; the summary counts match.
- [X] T016 Run the migrations at the start of `run_weekly` in `src/flows/pipelines/weekly_orchestrator.py`, before `_reset_if_rule_version_changed` (today they only run lazily in `assign_horizon_ids` and `enrich_projects`), reusing `_run_migrations` from `src/flows/maintenance/horizon_ids.py`.

**Checkpoint**: `PY -m pytest -q tests/test_document_transaction.py tests/test_document_skip.py` passes; on a fresh temp `DATABASE_URL`, `PY db/create_db.py` creates the new tables.

---

## Phase 3: User Story 1 - A weekly run with no source change finishes fast and writes nothing (Priority: P1) 🎯 MVP

**Goal**: every per-document phase skips documents whose content, rule version and cross-source resolutions did not change (FR-001–FR-005, FR-007).

**Independent Test**: on a copy of a populated database, run the replay twice with the same frozen inputs; the second pass skips every document, every table is identical before and after it, and the Lattes phases take a fraction of their baseline time.

### Tests for User Story 1

- [X] T017 [P] [US1] Create `tests/test_incremental_lattes.py` with two fixture CVs (small JSONs in `tests/fixtures/incremental/lattes/`, file names `<n>_<Name>_<16-digit id>.json`) on a temporary database: run `ingest_lattes_projects_flow` and `ingest_lattes_advisorships_flow` twice; on the second run every CV is `skipped` in both phases and a dump of every table is identical before and after, except the `ingestion_runs` rows each phase opens and `source_document_states.last_seen_at` (SC-001); `source_document_states` has one row per CV and phase.
- [X] T018 [P] [US1] Create `tests/test_incremental_cnpq_sigpesq.py` with two CNPq payloads, a small SigPesq projects/advisorships/groups report and two PJ files: second run skips every CNPq group, every SigPesq row and every PJ apply, and every table is identical before and after, with the same two exceptions as T017.
- [X] T019 [P] [US1] Add to `tests/test_incremental_lattes.py` the dependency cases of FR-005: (a) a new initiative whose identity or exact name matches an advisorship or project of an unchanged CV is created by a SigPesq row between the two runs → only that CV is processed, the other is skipped; (b) a new person whose name fuzzy-matches a team member of an unchanged CV with a higher score than the recorded match → only that CV is processed; (c) a new person with an unrelated name → no CV is processed.

### Implementation for User Story 1

- [X] T020 [US1] Add the references to `src/core/logic/document_skip.py` (research R3): `doc.reference(kind, lookup_key, outcome, score=None)`; at document end the sorted references give `dependency_fingerprint = stable_hash(...)` and are passed to `commit_processed`; `unchanged()` also requires that every stored reference still holds: check 1 (target stable key still exists, through the store) and check 2 (no entity of the store's `delta(state)` matches the lookup key at least as well: exact kinds compare normalized keys; `person_name` runs the `PersonMatcher` scorer and threshold against the delta names only). Stable keys are base `horizon_id`s computed by the rule functions of `src/core/logic/horizon_identity.py` from the target's current row, never database ids. Extend `tests/test_document_skip.py` for both checks.
- [X] T021 [US1] Implement `references` and `delta` in `src/adapters/database/document_state_store.py`: references read/replace for one document; `delta(state)` returns persons with `id > state.max_person_id` and initiatives with `id > state.max_initiative_id`, plus persons/initiatives with an `entity_change_logs` update touching a name field in a run newer than `state.last_ingestion_run_id`; also a lookup `stable_key_exists(kind, key)` (implemented as `target_keys()`: the stable keys of every current person and initiative, read once and refreshed after each write). `commit_processed` stores `max_person_id`/`max_initiative_id` as of commit time.
- [X] T022 [US1] Record references in the resolvers, only while `current_document` is set: `resolve_researcher_from_lattes` / `resolve_or_create_researcher` in `src/core/logic/researcher_resolution.py` (`researcher_owner`, lookup key = lattes_id or normalized name); `PersonMatcher.match_or_create` in `src/core/logic/person_matcher.py` (`person_name`, normalized input, outcome and best fuzzy score, `created:` when it creates); `ProjectLoader._resolve_existing_initiative` in `src/core/logic/project_loader.py:729` (`initiative`, identity key or title, outcome or `not_found`). The recording goes through a small function in `src/core/logic/document_skip.py` that reads `current_document`, so the resolvers stay free of store imports.
- [X] T023 [US1] Wrap each CV in `src/flows/lattes/projects.py` (`ingest_lattes_projects_flow`, the loop at `:1013`) with `DocumentSkip(source_system="lattes_projects")`: key = lattes_id from the file name; content = the loaded JSON; skip before `_ingest_researcher_file` when unchanged; `on_rollback` reloads `researcher_index` and the loader caches (`ProjectLoader._existing_*`, `PersonMatcher` cache, team lookup). Move the JSON load out of `_ingest_researcher_file` so the content is read once. Create the `DocumentTransaction` (T008) at flow start and close it at the end.
- [X] T024 [US1] Same wrapping in `src/flows/lattes/advisorships.py` (`ingest_lattes_advisorships_flow`, the loop after `:150`) with `source_system="lattes_advisorships"`.
- [X] T025 [US1] Wrap each group in `src/flows/cnpq/groups.py` (`sync_cnpq_groups_flow`, the writer loop) with `source_system="cnpq_group"`: key = `cnpq_payload_key(url)`; content = the fetched payload; skip before `record_source_record`/`sync_group`. Fetching stays as it is (4 workers, spec 017); only the writer loop is wrapped. Verify with two fetches of the same unchanged page (or two stored payloads of the same URL in `$R/base.db`) that the payload hash is stable; if a volatile field exists, drop it before hashing and name it in `research.md` R2.
- [X] T026 [US1] Per-row skip for SigPesq in `src/core/logic/project_loader.py` (`_process_row`, `:468`) and `src/core/logic/research_group_loader.py` (`:167`): when a `DocumentSkip` is attached to the loader (SigPesq flows only: `source_system` `sigpesq_project`, `sigpesq_advisorship`, `sigpesq_group`), each row is one document keyed by its tracking key, content = the row dict; skip unchanged rows before the tracking record. The Lattes flows keep calling `process_records` without row-level documents (their document is the CV). Attach it in `src/flows/sigpesq/projects.py`, `groups.py` and `advisorships.py`.
- [X] T027 [US1] (Dropped 2026-10-28 by the maintainer: enrichment stays out of the skip, spec FR-004 and clarification updated; nothing to implement. `ProjectEnrichmentLoader.run` has its own per-row SAVEPOINT handling from spec 019, which its comments say must not be moved; the phase takes ~12 s and already writes nothing on unchanged inputs. T018 covers SigPesq rows and CNPq pages, not PJ files.) Skip unchanged PJ applies in `src/core/logic/project_enrichment.py` (research R3, "Enrichment"): keep reading every `PJ_*.json` and running `resolve_claims`; around `_apply` for each winner, a `DocumentSkip(source_system="sigpesq_pj")` document keyed by the normalized project code, content = the PJ JSON, plus a `pj_claim` reference whose outcome is the winning initiative's stable key; skip `_apply` when unchanged.
- [X] T028 [US1] Real-data check: copy `$R/base_a.db` to `$R/us1.db`; run `$R/replay_weekly.sh <repo> $R/us1.db $R/inputs` twice. First pass: every document `processed` (bootstrap). Second pass: every document `skipped` in all five phases; compare every table before and after the second pass (identical apart from the `ingestion_runs` rows and `last_seen_at`, SC-001); record the step times next to T006's in `$R/BASE021.txt`.

- [X] T028a [US1] Writes found by T028 on unchanged inputs, fixed 2026-10-28 with the maintainer's approval: `assign_horizon_ids` writes only the differences of `horizon_ids`/candidates and keeps `assigned_at` (`src/adapters/database/horizon_id_store.py`, test in `tests/test_horizon_ids_flow.py`); the enrichment change log is written only on a real change (`src/core/logic/project_enrichment.py`, `_record_tracking(changed=...)`, SAVEPOINT handling untouched); `recalculate_all_parent_statuses` moved out of the SigPesq advisorships phase into a new phase `recalculate_parent_projects` after every source (`src/flows/maintenance/parent_projects.py`, wired in `app.py`, `weekly_orchestrator.py`, `pipelines/weekly.py`, `pipelines/unified.py`; `tests/conftest.py` keeps tests off the real database); SigPesq workplans merged into one advisorship recorded as TD-027.

**Checkpoint**: US1 tests pass; the second replay pass writes nothing and is much faster.

---

## Phase 4: User Story 3 - An unreadable or failed document never erases data (Priority: P1)

**Goal**: failure reasons, whole-document rollback, total-loss guard (FR-008, clarification Q3).

**Independent Test**: from a populated copy, replace one CV with an unreadable one and make one CNPq page fail; nothing of either is deleted and their states are unchanged.

### Tests for User Story 3

- [X] T029 [P] [US3] Add to `tests/test_incremental_lattes.py`: a CV file named `<n>_Nome-nao-identificado_<id>.json` with no items → `failed:unidentified`, no row deleted, processing state unchanged (only `last_failure`/`last_failure_at` set); a CV with its name and lattes_id but zero items after having items → `failed:total_loss`, nothing written; an unparsable JSON → `failed:unparsable`; a lattes_id in `lattes.list` with no JSON file → `failed:download` and its stored data kept; an exception injected in the awards section → `failed:partial`, every write of that CV rolled back, the next CV processed correctly; the next run with a good file processes the CV normally.
- [X] T030 [P] [US3] Add to `tests/test_incremental_cnpq_sigpesq.py`: a CNPq payload that is `None` → `failed:download`, the group's members and research lines unchanged, group still `active`; a SigPesq row that raises inside `_process_row` → only that row rolled back and `failed:partial`.

### Implementation for User Story 3

- [X] T031 [US3] Readability checks in `src/core/logic/document_skip.py` (`check_readable`) and their use in the Lattes flows: `unidentified` when the file name's name part or the JSON name is `Nome-nao-identificado`, or the file name has no 16-digit lattes_id; `unparsable` when the JSON does not load or is empty. Both run before `begin()`, so no transaction is opened.
- [X] T032 [US3] Turn swallowed errors into `partial` (research R4): in `src/flows/lattes/projects.py` the `except` around each section (`:330-349`) and the outer `except` of `_ingest_researcher_file` (`:351`) re-raise as `DocumentFailed("partial")` when `current_document` is set (keep today's logging); in `src/core/logic/project_loader.py` `process_records` raises `DocumentFailed("partial")` at the end when `stats["failed"] > 0` and a document is open; in `src/flows/cnpq/groups.py` `sync_single_group` raises `DocumentFailed("download")` for an empty payload when a document is open. Outside a document (callers that do not use `DocumentSkip`) behaviour stays as today.
- [X] T033 [US3] Total-loss guard in `src/adapters/database/document_state_store.py` `commit_processed`: before any delete, if the new item set (excluding the document's own subject) is empty and the stored `item_count > 0`, raise `DocumentFailed("total_loss")` so `DocumentSkip` rolls back. Applies to `lattes_projects`, `lattes_advisorships` and `cnpq_group` only.
- [X] T034 [US3] Real-data check (round 1): copy `$R/inputs` to `$R/inputs_round1`; replace one CV by a copy of a `Nome-nao-identificado` file renamed to its lattes_id, empty the item sections of another CV, delete the JSON of a third, and list one CNPq URL in `cnpq_fail.txt`. Run the incremental replay on a copy of `$R/us1.db` (`$R/inc1.db`): the four documents are failed with the right reasons (`unidentified`, `total_loss`, `download`, `download`), no row of them is deleted, and a table-by-table comparison with `$R/us1.db` shows no change apart from `ingestion_runs`, `last_seen_at` and the failure records.

**Checkpoint**: US3 tests pass; no failure path deletes data.

---

## Phase 5: User Story 2 - A changed document is reprocessed alone and the result equals a rebuild (Priority: P1)

**Goal**: item links per document, deletion of dropped items and orphan persons, merges that keep links (FR-011, FR-011a, FR-012).

**Independent Test**: from a populated copy, change one CV, run incrementally on one copy and from scratch on another; only that CV is processed and `compare_with_rebuild.py` reports identical.

### Tests for User Story 2

- [X] T035 [P] [US2] Add to `tests/test_incremental_lattes.py`: a CV drops an article only it carries → the article, its authors and its link rows are gone, its `source_records`/`entity_matches` rows stay, and one `delete` change log is written (FR-011b); a CV drops an article that a second fixture CV also lists → the article stays and only the first CV's links are removed; a CV drops a project → its `team_member_contributions` are removed and the team recomputed; only the changed CV is `processed`.
- [X] T036 [P] [US2] Add to `tests/test_incremental_lattes.py` the person rule (FR-011a): a student or team member referenced only by a dropped item is deleted; a person who owns an active CV document is kept even with no other reference; a CNPq member (carried as `researcher`) who is also a team member dropped by a CV (carried as `person`) is kept while the CNPq page still lists them; `assign_horizon_ids` after the run retires the deleted person's id, and a later run that brings the person back makes the retired id current again.
- [X] T037 [P] [US2] Create `tests/test_document_state_store.py` for the item store: replacing a document's link set computes removed = old − new; an item linked by another document is not deleted; reference rows (campus, organization, knowledge area, types, roles, languages) are never deleted; after `PersonConsolidator.consolidate_pair(winner, loser)` the loser's links point at the winner and the documents that resolved to the loser fail reference check 1 once.

### Implementation for User Story 2

- [X] T038 [US2] Create `src/adapters/database/document_item_store.py` (research R6, data model "Deletion of a removed item"): `replace_items(source_system, key, items) -> removed`; `is_carried(item_type, item_ref)`; one delete routine per item type of the data model, removing the row and its dependent rows (initiative → teams, team members, `team_member_contributions`, knowledge-area links, fellowships; article → `production_authors`; person → every person-referencing table, taken from `PersonConsolidator`'s list in `src/core/logic/person_consolidator.py`, not a second copy), all on the shared connection inside the document transaction. Tracking rows of a deleted item are never deleted (FR-011b); each deletion writes one `entity_change_logs` row with `operation='delete'` and the item's last values in `before_json`, through `tracking_recorder.record_change`. For a person, `is_carried` looks at links of both item types `person` and `researcher` with that id (data model, "Deletion of a removed item"). Expose it through `IDocumentStateStore` (`commit_processed` calls it before writing the state).
- [X] T039 [US2] Collect item links while `current_document` is set: in `src/tracking/recorder.py`, `record_entity_match` adds its target; add a `carry(item_type, item_ref)` function in `src/core/logic/document_skip.py` and call it in `src/flows/lattes/projects.py` (`ingest_awards_task`, `ingest_languages_task`, `ingest_professional_activities_task`, `ingest_technical_productions_task`, `ingest_articles_task` for authors, `ingest_education_task`), in `src/core/logic/team_synchronizer.py` (teams and member rows written or kept), in `src/core/logic/person_matcher.py` (`match_or_create` result), in `src/core/logic/strategies/cnpq_sync.py` (members and research lines) and in `src/core/logic/project_loader.py` (initiatives, advisorships, fellowships). The document's own subject (CV owner researcher, CNPq group) is carried with a flag that excludes it from `item_count`.
- [X] T040 [US2] Implement the person exception in `src/adapters/database/document_item_store.py`: a person is not deleted when it owns a `lattes_projects` or `lattes_advisorships` document with `status = 'active'` (match by the researcher's Lattes id from `cnpq_url`).
- [X] T041 [US2] Re-point links on merge without new SQL in `src/core/logic/` (constitution I, research R6 "Merges"): add `repoint_person_links(conn, winner_id, loser_id)` to `src/adapters/database/document_item_store.py` (`UPDATE OR IGNORE source_document_items SET item_ref = <winner> WHERE item_type IN ('person','researcher') AND item_ref = <loser>`, then delete what remains for the loser, guarded by a table-exists check); give `PersonConsolidator` in `src/core/logic/person_consolidator.py` an optional constructor argument `merge_hooks: list[Callable[[connection, int, int], None]]`, called in `consolidate_pair` inside its transaction next to the `team_member_contributions` update (`:290-300`); pass `[repoint_person_links]` from the `consolidate_duplicates` flow (`src/flows/maintenance/`). The consolidator imports nothing new from `src/adapters/`.
- [X] T042 [US2] Real-data check (round 2): copy `$R/inputs_round1` to `$R/inputs_round2`, restore the three failed CVs and the CNPq page of round 1, and edit one other CV (add one article, remove one article only it carries, remove one co-authored article). Run the incremental replay on a copy of `$R/inc1.db` (`$R/inc2.db`) and a fresh replay on `$R/rebuild2.db`, both with `$R/inputs_round2`; run `compare_with_rebuild.py`. Expected: only the edited CV processed; `RESULT: IDENTICAL` apart from the listed R9.3 rows and orphan reference rows. Record numbers in `$R/BASE021.txt`.

**Checkpoint**: US2 tests pass; one changed CV gives the same database as a rebuild.

---

## Phase 6: User Story 4 - A document gone from its source stays visible as inactive (Priority: P2)

**Goal**: listings, inactive/reactivated documents, CNPq listing from active SigPesq groups, the new export file (FR-009, FR-010, FR-016, FR-017).

**Independent Test**: from a populated copy, remove one group from the SigPesq report and one id from the Lattes list; both become inactive, their data stays, and the new export file shows them.

### Tests for User Story 4

- [X] T043 [P] [US4] Add to `tests/test_incremental_cnpq_sigpesq.py`: a group absent from a successfully loaded SigPesq groups report → its `sigpesq_group` and `cnpq_group` documents become `inactive` with `last_seen_at` unchanged, and its data stays; an empty or missing report → no status changes; the group back in the report → `active`; a run with `campus_name` set → no status changes.
- [X] T044 [P] [US4] Add to `tests/test_incremental_lattes.py`: an id removed from `lattes.list` → both Lattes documents `inactive`, the researcher and items kept; missing `lattes.list` → no status changes (logged).
- [X] T045 [P] [US4] Add to `tests/test_export_canonical_data_flow.py`: `source_document_states_canonical.json` is written, matches [contracts/source-document-states-export.md](contracts/source-document-states-export.md) (fields, `null` `processed_at` for a never-processed document, sorting), contains no name, CPF, phone or e-mail, and the existing export files keep their fields.

### Implementation for User Story 4

- [X] T046 [US4] Implement `mark_listing` in `src/adapters/database/document_state_store.py` (research R8, data model "State transitions"): listed keys get `last_seen_at = now` and `active` (count reactivations); with `complete=True`, active documents of the source not listed become `inactive`; with `complete=False`, only `last_seen_at` of listed keys is updated. A listed key with no state gets a state row with `status='active'` and `content_hash` NULL.
- [X] T047 [US4] Call `skip.finish(...)` with the right completeness in each phase: Lattes (`src/flows/lattes/projects.py`, `advisorships.py`) with the ids of `data/lattes_run/lattes.list`, `complete` only if the file exists and is non-empty; a listed id with no JSON file in `data/lattes_json/` is recorded as `failed:download` (research R4) and keeps its data; SigPesq loaders with the rows of each report, `complete` only if the report was downloaded and parsed with at least one row; CNPq (`src/flows/cnpq/groups.py`) with the listed groups, `complete=False` when `campus_name`, `limit` or `offset` is set or when the SigPesq groups listing of the same weekly was not complete (research R8: no `sigpesq_group` state with `last_seen_at` at or after `HORIZON_WEEKLY_STARTED_AT`; without that variable, `complete=False`). Make `run_weekly` in `src/flows/pipelines/weekly_orchestrator.py` set `HORIZON_WEEKLY_STARTED_AT` (ISO-8601 UTC) in the environment of every phase subprocess; (enrichment is out of this spec: no PJ listing).
- [X] T048 [US4] Change `get_groups_to_sync` in `src/flows/cnpq/groups.py:36` so a group is synced only when its `sigpesq_group` document is `active` (or, on a database with no `sigpesq_group` states yet, as today); a group whose SigPesq document is inactive is not fetched and its `cnpq_group` document is marked inactive by `finish`.
- [X] T049 [US4] Write `source_document_states_canonical.json` in `src/flows/exports/canonical_data.py` next to `write_id_file`/`write_alias_file` (`:275`), through a `write_states_file(store, output_dir)` function in `src/core/logic/document_skip.py` that formats the rows as the contract says. Add the file to `src/scripts/export_parquet.py` with `documents` as the row list and no integer id column.
- [X] T050 [US4] Real-data check (round 3): copy `$R/inputs_round2` to `$R/inputs_round3`; remove one group row from the SigPesq groups report and one id from `lattes.list`. Run the incremental replay on a copy of `$R/inc2.db`: both become inactive, their data is still in the database and in `researchers_canonical.json` / `research_groups_canonical.json`, and the new export lists them as `inactive`. Then run `compare_with_rebuild.py` against a fresh rebuild on `$R/inputs_round3` (inactive documents left out by the script): `RESULT: IDENTICAL` apart from the listed exceptions (SC-006, three rounds).

**Checkpoint**: US4 tests pass; inactive documents are kept and published.

---

## Phase 7: User Story 5 - The database persists by default and rebuilds only when it must (Priority: P2)

**Goal**: `make weekly-flows` stops resetting; the rule-version guard and `make full-refresh` keep rebuilds (FR-013–FR-015, FR-020).

**Independent Test**: `make weekly-flows` twice on a copy does not reset the database; a changed rule version rebuilds it once.

### Tests for User Story 5

- [X] T051 [P] [US5] Create `tests/test_ensure_db.py`: `db/ensure_db.py` on a missing file creates the schema with the new tables; on an existing populated file it changes nothing (same row counts and `schema_migrations` plus pending migrations only); it resolves the path from `DATABASE_URL`, not `db/horizon.db`; with a recorded `rule_version` different from `HORIZON_RULE_VERSION`, `_reset_if_rule_version_changed` rebuilds and keeps the id history.

### Implementation for User Story 5

- [X] T052 [US5] Create `db/ensure_db.py`: read `DATABASE_URL`, resolve the file with `sqlite_path_from_url` (`src/adapters/database/horizon_id_store.py`), and call `setup_database()` from `db/create_db.py` only when the file does not exist; otherwise only run the migrations. Print what it did.
- [X] T053 [US5] In `Makefile`, add `db-ensure: ## Create the local database only if it does not exist (keeps a persistent database)` running `$(PYTHON) db/ensure_db.py`, and make `weekly-flows` depend on `db-ensure prefect-server` instead of `db-reset prefect-server`; update its `##` description. `full-refresh` keeps `db-reset`. Check that `.github/workflows/weekly-etl.yml:81` (`make weekly-flows`) still creates the database on a fresh runner.
- [X] T054 [US5] Update the docstring of `_reset_if_rule_version_changed` in `src/flows/pipelines/weekly_orchestrator.py` (it says `make weekly-flows` still resets) and the module docstring of `src/adapters/database/sqlite_settings.py` (it says the weekly rebuilds from scratch) to describe the persistent database.

**Checkpoint**: US5 tests pass; the weekly keeps the database.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T055 [P] Write `data/reports/source_document_states_report.json` from `DocumentSkip.log_summary()` in `src/core/logic/document_skip.py` (research R12): one entry per phase, replaced each run, with the counts and the failed documents by key and reason; keep the one-line log. Add a test in `tests/test_document_skip.py`.
- [X] T056 [P] Add a test in `tests/test_document_transaction.py` that fails when a per-document phase opens a second writing connection while a document transaction is open (contract rule 8), and one that pins the `_SessionLocal` rebinding against the installed `eo_lib` and `research_domain` versions.
- [X] T057 [P] Update `docs/flows-and-entrypoints.md`: `make weekly-flows` no longer resets; `make db-ensure`; `make full-refresh` for a rebuild; what a skipped, failed and inactive document means; when to bump `HORIZON_RULE_VERSION` (any parser or loader change that alters what an unchanged document produces, research R2). Update the constitution follow-up note only if the maintainer asks.
- [X] T058 Run `make ci-check` and compare with T002: no new failures.
- [X] T059 Local weekly on the real database (quickstart §4; decided 2026-10-28: the maintainer allows `make weekly-flows` to write `db/horizon.db`, because `consolidate_duplicates` and `anonymize_backfill` ignore `DATABASE_URL` (TD-026) and a backup exists in `data/_backup_2026-10-28_pre021/`, checked with `sha256sum -c data/_backup_2026-10-28_pre021/SHA256SUMS.original` before starting): run `make weekly-flows` twice with Telegram off; the second run does not reset, its report shows skips, and the Lattes phases' times are compared with 2026-10-24 (`lattes_projects` 7.4 min, `lattes_advisorships` 12.4 min; reference target SC-002: at most about 2 min together). Also record the first run's times (one commit per document).
- [X] T060 Write `docs/reports/2026-XX-XX-skip-unchanged-validation.md` with the results of T009, T028, T034, T042, T050 and T059 per success criterion SC-001 to SC-008, the schema check of `compare_with_rebuild.py` (SC-007), the R9.3, orphan-reference and "[Nome-nao-identificado]" exceptions with counts, and the timings.
- [X] T061 CI (only after T058–T060 and the maintainer's go-ahead): push to the fork and dispatch the weekly workflow; the run starts with no database, so it is a rebuild; check it succeeds with the same exports as the last CI run plus `source_document_states_canonical.json` (SC-008), and add the result to the report.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none. T004 needs T003; T006 needs T004.
- **Foundational (Phase 2)**: after Setup. T009 needs T007 and T008 and decides between the main design and the fallback. T013 needs T008, T010, T012. T014 needs T011, T012.
- **US1 (Phase 3)**: after Foundational. T020 needs T014; T021 needs T013; T022 needs T020; T023–T027 need T014 and T022.
- **US3 (Phase 4)**: after US1 (it wraps the same phases). T031 needs T014; T033 needs T013; its real-data check T034 needs T028.
- **US2 (Phase 5)**: after US3, so every deletion path is guarded from the start. T038 needs T013; T039 needs T014; T040 and T041 need T038; T042 needs T034.
- **US4 (Phase 6)**: after US1. T048 needs T046 and the SigPesq wrapping (T026); T050 needs T034.
- **US5 (Phase 7)**: after Foundational; independent of US1–US4.
- **Polish (Phase 8)**: after all stories.

### Within Each Story

- Tests first, failing; then implementation; then the real-data check.
- `src/core/logic/document_skip.py` is touched by T014, T020, T022, T031, T039, T049 and T055: sequential.
- `src/adapters/database/document_state_store.py` is touched by T013, T021, T033, T046: sequential.
- `src/flows/lattes/projects.py` is touched by T023, T032, T039, T047: sequential.
- `src/core/logic/project_loader.py` is touched by T022, T026, T032, T039: sequential.
- `src/flows/cnpq/groups.py` is touched by T025, T032, T047, T048: sequential.

### Parallel Opportunities

- Setup: T002, T003 and T005 together.
- Foundational: T011 and T015 while T012–T014 are written.
- US1 tests T017–T019 together; US3 tests T029–T030; US2 tests T035–T037; US4 tests T043–T045.
- US5 (T051–T054) can run beside US2–US4: different files, except `src/flows/pipelines/weekly_orchestrator.py`, which T016, T047 and T054 touch in that order.
- Polish: T055, T056, T057 together.

---

## Parallel Example: User Story 1

```bash
# Tests, together:
Task: "tests/test_incremental_lattes.py — two CVs, second run skips both, tables identical"
Task: "tests/test_incremental_cnpq_sigpesq.py — CNPq groups, SigPesq rows and PJ applies skipped"

# Implementation in different files, after T020-T022:
Task: "src/flows/lattes/advisorships.py — wrap each CV"
Task: "src/flows/cnpq/groups.py — wrap each group in the writer loop"
Task: "src/core/logic/project_enrichment.py — skip unchanged PJ applies"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Setup (T001–T006) and Foundational (T007–T016), with the proof of concept T009 as the go/no-go point.
2. US1 (T017–T028): unchanged documents skipped.
3. **Stop and validate**: T028 — the second pass writes nothing and is faster. Report to the maintainer.

US1 alone never deletes anything, so it is safe to use before US2–US4: a changed document is processed by today's code, and only dropped items are left behind (as today).

### Incremental Delivery

1. US1: the weekly gets fast on unchanged weeks.
2. US3: failures never erase data. It comes before US2 on purpose: when deletion arrives, every failure path already rolls back.
3. US2: dropped items are deleted and the database equals a rebuild.
4. US4: inactive documents and the new export file.
5. US5: `make weekly-flows` keeps the database.
6. Polish: report, docs, local weekly, validation report; CI after the maintainer's go-ahead.

---

## Notes

- Third-party libraries stay unchanged; Docker is not touched.
- Nothing goes to the upstream repository; commits stay on the fork until the maintainer's manager validates.
- `PLANO_*.md` and `RESUMO_*.md` at the repository root are personal: never stage them.
- Show the maintainer only code and documentation changes; generated exports under `data/` are not part of the change list.
- Stop at each checkpoint and report before continuing.
