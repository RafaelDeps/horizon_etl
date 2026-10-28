---

description: "Task list for permanent Horizon ids and idempotent tracking keys"
---

# Tasks: Permanent Horizon Ids and Idempotent Tracking Keys

**Input**: Design documents from `specs/020-horizon-id-idempotent-hash/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Requested by the spec (each user story's Independent Test, SC-001 to SC-008, quickstart). Test tasks come first in each story and must fail before the implementation.

**Organization**:
- **US1 (P1)**: every entity gets a stable `horizon_id`, published in a new id file.
- **US2 (P1)**: the same input processed again writes nothing (fixpoint).
- **US3 (P2)**: merges, upgrades, rebuilds and corrected keys keep old ids resolvable (aliases).
- **US4 (P2)**: existing tables and export files keep their format.
- **US5 (P3)**: a rule-version change triggers one clean rebuild.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task).
- **[Story]**: US1–US5.
- `$R` = `/tmp/claude-1000/-home-rafael-horizon-etl/5126d108-e5e4-4b9b-af2a-be2bc2b35557/scratchpad/replay020` (session scratchpad; nothing there is committed). If the session changes, use the new scratchpad and rebuild `$R` with Phase 1.
- `PY` = `/home/rafael/horizon_etl/.venv/bin/python`.
- Every replay runs with Telegram off: `export HORIZON_TELEGRAM_BOT_TOKEN= HORIZON_TELEGRAM_CHAT_ID= TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= HORIZON_QUIET_PREFECT=1 PREFECT_LOGGING_TO_API_ENABLED=false`.
- Never write `db/horizon.db`; every database experiment works on a copy under `$R`.

---

## Phase 1: Setup (baseline and replay assets, before any code change)

- [X] T001 Create `$R`; copy `db/horizon.db` to `$R/before.db`; copy the base code (`src/`, `app.py`, `db/create_db.py`) to `$R/base020_code/` (remove `__pycache__`), symlink `/home/rafael/horizon_etl/.env` into it, and write `git rev-parse HEAD` to `$R/BASE020.txt`.
- [X] T002 [P] Run `PY -m pytest -q` on the unchanged code and record the failing test ids in `$R/BASE020.txt` (spec 019 recorded 6 pre-existing failures; recount, do not assume).
- [X] T003 [P] Run both research scripts on `$R/before.db` (`PY -I specs/020-horizon-id-idempotent-hash/research-scripts/sim_horizon_ids.py $R/before.db` and `.../sim_tracking_keys.py $R/before.db`) and save their output to `$R/sim_before.txt`. Expected: 149 shared-id groups; tracking keys 1 005 today, 22 with the new keys.
- [X] T004 [P] Freeze the replay inputs in `$R/inputs/`: copy `data/raw/sigpesq/` (the SigPesq reports), `data/lattes_json/`, `data/exports/project_sigpesq_files_json/` and `data/exports/exports_canonical.zip`. Export the 350 CNPq payloads from `$R/before.db` (`source_records` where `source_entity_type='cnpq_group_payload'`: `source_file` is the group URL, `raw_payload_json` the page) to `$R/inputs/cnpq_payloads.json` as `{url: payload}`.
- [X] T005 Write the replay harnesses (depends on T004), following the specs 015–017 pattern described in `specs/017-cnpq-concurrent-sync/quickstart.md`:
  - `$R/replay_sigpesq.py`: runs the SigPesq ingestion flows on the frozen reports in `$R/inputs/sigpesq/` without downloading. Read `src/flows/sigpesq/` to find the loader entry points that take a file path.
  - `$R/replay_cnpq.py`: a Prefect flow that patches `CnpqCrawlerAdapter.get_group_data` to return `cnpq_payloads.json[url]` and then calls the CNPq sync flow.
  - `$R/replay_weekly.sh <code_dir> <db>`: `db/create_db.py` on a fresh database, then `replay_sigpesq.py`, `replay_cnpq.py`, and `app.py` with `ingest_lattes_projects`, `lattes_advisorships`, `enrich_projects`, `consolidate_duplicates`, then `export_canonical <out_dir>`. Every step runs with `PYTHONPATH=<code_dir>` and `DATABASE_URL=sqlite:///<db>`, from a working directory whose `data/` is a copy of `$R/inputs`.
- [X] T006 Base replay (depends on T005): run `$R/replay_weekly.sh $R/base020_code $R/base_a.db`, keeping its exports in `$R/base_a_exports/`. Then copy `$R/base_a.db` to `$R/base_rerun.db` and run `ingest_lattes_projects` on it three more times, saving a copy after each pass (`base_rerun_1.db` … `_3.db`). Record in `$R/BASE020.txt` the per-pass differences in `entity_change_logs`, `source_records` and `team_members` (expected for pass 1: +3 806, +23, 713 rewritten).
- [X] T007 [P] Write `$R/compare_dbs.py <a.db> <b.db> [--ignore-ids]`. It opens both read-only, and for every table present in both compares the row count and the row set (with `--ignore-ids`, excluding the `id` column and comparing `team_members` by `(person name, team name, role, start_date)`). It prints `IDENTICAL`/`DIFFERENT (n)` per table and `RESULT: …`, and exits 0 only when identical.

**Checkpoint**: Base references and harnesses exist; code changes may start.

---

## Phase 2: Foundational (blocking prerequisites)

- [X] T008 Add the six ETL-owned tables of [data-model.md](data-model.md) to `MIGRATIONS` in `src/db/migrations.py`, one migration id each (`0002_horizon_ids`, `0003_horizon_id_candidates`, `0004_horizon_id_aliases`, `0005_horizon_merge_log`, `0006_horizon_meta`, `0007_team_member_contributions`), all `CREATE TABLE IF NOT EXISTS` with the columns, primary keys and UNIQUE constraints listed there. Make `db/create_db.py` call `run_migrations` after `create_all`, so a reset database has them too.
- [X] T009 [P] Create `src/core/logic/horizon_identity.py` with only the shared primitives: `HORIZON_RULE_VERSION = 1`; `canonical(value)` (contract [tracking-keys.md](contracts/tracking-keys.md), "Payload hash"); `canonical_hash(payload)`; `hash12(*parts)` (SHA-256 of `"|".join(normalize_text(p))`, first 12 hex; import `normalize_text` from `src/core/logic/initiative_identity.py`); `slug(text)`; `normalize_doi(doi)` (lowercase, strip, drop `https://doi.org/` and `http://dx.doi.org/` / `https://dx.doi.org/`); `lattes_id_from_url(url)` (16 digits after `lattes.cnpq.br/`); `cnpq_group_id_from_url(url)` (after `espelhogrupo/`); `lattes_id_from_cv_path(path)` (16 digits before `.json`). No I/O, no imports from `src/adapters/`.
- [X] T010 [P] Create `tests/test_horizon_identity.py` with tests for T009's primitives: `canonical` treats `None`/NaN/`"nan"`/`""` alike and `600`/`600.0`/`"600"` alike, recursively; `hash12` is accent-, case- and punctuation-insensitive and 12 hex long; `normalize_doi` on the three URL prefixes; the three id extractors on real examples (`http://lattes.cnpq.br/9860697624155451`, `http://dgp.cnpq.br/dgp/espelhogrupo/4439471564090237`, `219_Karin-Satie-Komati_9860697624155451.json`) and on garbage (return `None`).
- [X] T011 Create the store port `src/core/ports/horizon_id_store.py` (an abstract class) with the methods the assigner needs: `iter_entities(entity_type)` returning plain dicts with the columns of each rule in [contracts/horizon-id-format.md](contracts/horizon-id-format.md); `iter_source_keys()` returning `(canonical_entity_type, canonical_entity_id, source_system, source_entity_type, source_record_id, source_file)` from `entity_matches` ⋈ `source_records`; `load_history()`, `load_merge_log()`, `replace_current(ids, candidates)`, `upsert_aliases(rows)`, `get_meta(key)`, `set_meta(key, value)`. Create the SQLite adapter `src/adapters/database/horizon_id_store.py` implementing it with `sqlite3` on the path from `DATABASE_URL` (same pattern as `src/core/logic/person_consolidator.py`), with `replace_current` in one transaction.

**Checkpoint**: Migrations apply on a fresh database (`PY db/create_db.py` on a temp `DATABASE_URL`, then `sqlite_master` lists the six tables); `pytest -q tests/test_horizon_identity.py` passes.

---

## Phase 3: User Story 1 - A consumer links the same entity across weeks and rebuilds (Priority: P1) 🎯 MVP

**Goal**: Every entity gets a `horizon_id` derived only from source data, unique and identical across rebuilds, published in `horizon_ids_canonical.json`.

**Independent Test**: Two fixture databases seeded in different orders give the same ids (T013), and `assign_horizon_ids` on the real database matches the simulation (T023); the full two-rebuild comparison is T049.

### Tests for User Story 1

- [X] T012 [P] [US1] In `tests/test_horizon_identity.py`, add rule tests for every row of [contracts/horizon-id-format.md](contracts/horizon-id-format.md): person with and without `lattes_id`; group with CNPq URL and SigPesq-only; initiative from `sigpesq project|6903`, from `PJ 2342`, from a Lattes identity key, from name only; advisorship from `sigpesq workplan|10045|4882`; article with DOI (three DOI spellings give one id) and without; production; education, activity, award and proficiency under a person; team under an initiative; fellowship with value (`fellowship:pibiti:700` ≠ `fellowship:pibiti:900`); reference slugs (`campus:serra`). Assert each rule also returns its full candidate list (a person with `lattes_id` also has the name candidate) and that no id or `natural_key` matches an e-mail, CPF (`\d{3}\.?\d{3}\.?\d{3}-?\d{2}`) or phone pattern.
- [X] T013 [P] [US1] Create `tests/test_horizon_id_assigner.py` with a temp-file SQLite fixture built by `db/create_db.py`'s schema plus migrations, seeded with a handful of rows per entity type and their `entity_matches`/`source_records`. Tests: (a) every seeded row gets exactly one `horizon_ids` row; (b) two fresh databases seeded in different insertion orders get the same `(entity_type, horizon_id, natural_key)` set (SC-001); (c) two persons named "Ana Paula Souza" without `lattes_id`, from different source documents, get two distinct ids with `~<hex6>` suffixes, identical in both orders; same document → `~2` by content hash (FR-008, SC-003); (d) the collision count appears in the returned report.

### Implementation for User Story 1

- [X] T014 [US1] In `src/core/logic/horizon_identity.py`, add one rule function per entity type of [contracts/horizon-id-format.md](contracts/horizon-id-format.md), each taking the entity's dict (and, for initiatives/advisorships, its source keys) and returning `IdDecision(horizon_id, rule, natural_key, parent_horizon_id, candidates)`. Child rules take the parent's `IdDecision` and build candidates from each parent candidate. Follow the measured rules of research R2 exactly (`research-scripts/sim_horizon_ids.py` is the reference implementation of the selection logic). Make T012 pass.
- [X] T015 [US1] In `src/core/logic/horizon_identity.py`, add `resolve_collisions(decisions, origin_document)` implementing research R4: group equal ids, append `~` + first 6 hex of `hash12(origin document)` (the smallest `source_file` among the entity's source records), then `~2`, `~3` in canonical-content-hash order for what still collides; return the report of groups per type.
- [X] T016 [US1] Create `src/core/logic/horizon_id_assigner.py` with `HorizonIdAssigner(store)` and `assign() -> report`: read entities through the port in dependency order (reference tables, persons, groups, initiatives and advisorships, articles, productions, then children and teams), apply T014 rules and T015, then `store.replace_current(...)`; `set_meta('rule_version', HORIZON_RULE_VERSION)` and `last_assigned_at`. History and aliases are added in US3; here, start from an empty history. Make T013 pass.
- [X] T017 [US1] Create the Prefect flow `assign_horizon_ids_flow` in `src/flows/maintenance/horizon_ids.py`, `@flow(name="Assign Horizon Ids", **telegram_flow_state_handlers())`, following `src/flows/maintenance/anonymize_backfill.py`: run migrations, build the SQLite store from `DATABASE_URL`, call the assigner, write the report to `data/reports/horizon_ids_report.json` (research R10) and log its summary line.
- [X] T018 [P] [US1] Create `tests/test_horizon_ids_flow.py` (constitution III: every new flow has a test): run `assign_horizon_ids_flow` on a temp-file database seeded as in `tests/test_horizon_id_assigner.py`, with `DATABASE_URL` pointing to it and the Telegram variables empty; assert the migrations ran, `horizon_ids` is filled, `data/reports/horizon_ids_report.json` (written under a temp directory passed to the flow) has the per-type counts, and the flow ends `Completed`.
- [X] T019 [US1] Register the entry point in `app.py` (`flow_to_run == "assign_horizon_ids"`, next to `consolidate_duplicates`) and add the phase `("assign_horizon_ids", ["assign_horizon_ids"], 900, False, "app")` to `_PHASES` in `src/flows/pipelines/weekly_orchestrator.py`, right after `consolidate_duplicates` and before `export_canonical`, with a comment on why it sits there (ids are computed on the final, consolidated state).
- [X] T020 [US1] Add the id-file writer: `write_id_file(store, output_dir)` in `src/core/logic/horizon_id_assigner.py`, reading `horizon_ids` through the store port (`current_ids()`), writing `{"rule_version", "generated_at", "ids": [...]}` sorted by `entity_type`, `horizon_id` with `atomic_write_json`. If the table is missing or empty, write nothing and log a WARNING, so `export_canonical` never fails because of it. *(Implemented outside `canonical_exporter.py`: that exporter reads through the ORM controllers and its sink only writes lists, while this file is an object read through the port.)*
- [X] T021 [US1] In `src/flows/exports/canonical_data.py`, add `export_horizon_ids_task(output_dir)` and call it in `export_canonical_data_flow` before `zip_exports_task`. The existing walk already puts the file in the zip; do not change `zip_exports_task`.
- [X] T022 [P] [US1] In `tests/test_export_canonical_data_flow.py`, add a test that runs the export on a fixture database with `horizon_ids` rows and asserts that `horizon_ids_canonical.json` exists in the output directory and in the zip, has one row per entity, and is byte-identical across two exports apart from `generated_at`.
- [X] T023 [US1] Run `assign_horizon_ids` on a copy of `$R/before.db` (`DATABASE_URL=sqlite:///$R/assign_check.db PY app.py assign_horizon_ids`). Check that the report counts match `$R/sim_before.txt` (149 collision groups, the same per-type rule counts), that `horizon_ids` has one row per entity, and that no `horizon_id` is shared. Record the timing.

**Checkpoint**: `pytest -q tests/test_horizon_identity.py tests/test_horizon_id_assigner.py tests/test_export_canonical_data_flow.py` passes; T023 matches the simulation.

---

## Phase 4: User Story 2 - Processing the same input twice changes nothing (Priority: P1)

**Goal**: Stable tracking keys, canonical hash, no no-op writes, order-independent team membership and person tie-break; the second and third passes are identical (fixpoint, FR-023b).

**Independent Test**: Three passes of each source phase on a populated copy; passes 2 and 3 identical (T038).

### Tests for User Story 2

- [X] T024 [P] [US2] Create `tests/test_idempotent_rerun.py` with a temp-file database and two small fixture CVs (JSON in the shape of `data/lattes_json/*.json`, built from `tests/` fixtures already used by `tests/test_ingest_lattes_projects_flow.py`). Run `ingest_lattes_projects_flow` three times on the same file; assert that passes 2 and 3 leave every table identical, ids included, with 0 new `entity_change_logs`, `source_records`, `entity_matches` and `attribute_assertions` rows (contract [tracking-keys.md](contracts/tracking-keys.md), "Idempotency").
- [X] T025 [P] [US2] In `tests/test_tracking_entities.py` (or a new `tests/test_tracking_keys.py`), test the new keys of [contracts/tracking-keys.md](contracts/tracking-keys.md): a CNPq member key uses the CNPq id from the URL and the dates; an education key uses `lattes:<cv>` and not `researchers.id`, and stays the same after a person merge; `600` and `"600"` give the same `payload_hash`; two items of the same CV with the same key → one source record, always the one with the smaller canonical hash.
- [X] T026 [P] [US2] In `tests/test_team_synchronizer.py`, add: two documents contributing different rosters and start dates to one team, processed in both orders and starting from an empty and from a populated team → the same final members (union) and `start_date` = earliest; re-syncing an unchanged document deletes and inserts nothing (count `team_members` ids before and after); two initiatives sharing a team by name keep both rosters.
- [X] T027 [P] [US2] In `tests/test_person_matcher.py`, add: two cached persons whose names tie on token-sort score ("Ciro Alexandre Torres Alves", "Ciro Alexandre Alves Torres") → the same one is returned whatever the insertion order, preferring the researcher with `lattes_id`, then the exact normalized name, then the smaller name-based candidate id.

### Implementation for User Story 2

- [X] T028 [US2] In `src/tracking/recorder.py`, make `stable_hash` hash `canonical(value)` from `horizon_identity` (keep `sort_keys`, `ensure_ascii=False`, `default=_json_default`). It applies to `payload_hash` and `value_hash` alike.
- [X] T029 [US2] In `src/core/logic/horizon_identity.py`, add the tracking-key builders of [contracts/tracking-keys.md](contracts/tracking-keys.md) (`cnpq_payload_key`, `cnpq_member_key`, `cnpq_line_key`, `lattes_education_key`, `lattes_article_key`, `lattes_initiative_key`, `lattes_advisorship_key`) and `dedupe_same_document(items, key_fn)`, which keeps per key the item with the smallest `canonical_hash`, in the original order, and returns the count dropped.
- [X] T030 [US2] Use the builders at the call sites: `src/flows/cnpq/groups.py:148` (key from `group_info["url"]`); `src/core/logic/strategies/cnpq_sync.py:275` and `:540` (pass the group URL down from `sync_single_group`; `sync_members` and `sync_knowledge_areas` already receive `source_file=url`); `src/flows/lattes/projects.py:391` and `:521` (the CV `lattes_id` from `source_file`); `src/core/logic/project_loader.py:372` for Lattes rows (prefix `lattes:<cv>` from `source_file`; leave SigPesq rows as they are). Apply `dedupe_same_document` to each CV's education, article, project and advisorship lists before processing, and log the dropped count per CV. Make T025 pass.
- [X] T031 [US2] Remove no-op writes (research R9.1). In `src/flows/lattes/projects.py` (~line 186–240), compare `citation_names`, `cnpq_url` and the scrubbed `resume` with the stored researcher values in canonical form, call `researcher_ctrl.update` and `record_change` only when one differs, and put only those fields in `changed_fields` with real `before`/`after`. In `src/core/logic/project_loader.py` (~line 520–575), for an existing initiative, snapshot the tracked attributes before the handler runs, and record `operation="update"` only for attributes whose canonical value changed (skip the log when none did). Keep `operation="create"` for new ones.
- [X] T032 [US2] Implement contribution-based membership (research R9.2, R9.3) in `src/core/logic/team_synchronizer.py`. `sync_members(team_id, members, document_key)` replaces that document's rows in `team_member_contributions`, recomputes the managed roles' desired set as the union over documents with `start_date` = MIN, and applies only the difference to `team_members` (add missing, remove members no document contributes, update `start_date` only when the minimum changed). `add_members` records contributions with its own `document_key`. In `src/core/logic/initiative_linker.py`, pass `document_key` = `lattes:<cv>#<initiative identity key>` for Lattes, `sigpesq:<identity key>` for SigPesq rows, `cnpq:<group id>` for CNPq groups. Read the callers of `sync_members`/`add_members` (`grep -rn "sync_members\|add_members" src`) and pass the key everywhere. Make T026 pass.
- [X] T033 [US2] In `src/core/logic/person_consolidator.py` (`consolidate_pair`, around `_merge_team_members`), also re-point `team_member_contributions.person_id` from loser to winner, dropping rows that would duplicate the primary key.
- [X] T034 [US2] Deterministic tie-break in `src/core/logic/person_matcher.py` (fuzzy step, ~line 280–320). Replace `extractOne` with `rapid_process.extract(..., limit=None, score_cutoff=89.5)`, keep the candidates with the maximum raw score, and choose among them by: a researcher with a `lattes_id` (from the person cache), then normalized name equal to the input, then the smallest `hash12(name)`. Keep the existing thresholds, strict-match rule and stats. Make T027 pass.
- [X] T035 [US2] Count first-pass resolution changes (FR-023b): (a) `fuzzy_ties` = fuzzy lookups where more than one candidate had the best score (resolved by T034's tie-break), logged by `log_match_summary` in `src/core/logic/person_matcher.py`; (b) persons resolved differently than in the previous pass are measured in the validation report by comparing the passes of T038 (`team_members` by person name, `entity_matches` per source record). *(Changed during implementation: (b) cannot be counted at run time for team members, because the linker's person resolution records no entity match; the pass comparison measures it for every table.)*
- [X] T036 [US2] Run `pytest -q tests/test_idempotent_rerun.py tests/test_tracking_entities.py tests/test_team_synchronizer.py tests/test_person_matcher.py` and the whole `pytest -q`; fix regressions (no new failures against `$R/BASE020.txt`).
- [X] T037 [US2] Feature replay (depends on T036): `$R/replay_weekly.sh /home/rafael/horizon_etl $R/feat_a.db` (exports in `$R/feat_a_exports/`). Run `sim_tracking_keys.py` on `$R/feat_a.db` and confirm 0 keys with more than one hash, plus the dropped same-CV duplicates in the log (~22). Also confirm SC-004's "no database id": every `source_record_id` of `cnpq_group_payload`, `cnpq_group_member`, `cnpq_research_line`, `academic_education`, `article` and Lattes `initiative`/`advisorship` starts with `cnpq:` or `lattes:` as in [contracts/tracking-keys.md](contracts/tracking-keys.md).
- [X] T038 [US2] Fixpoint check: copy `$R/feat_a.db` to `$R/feat_rerun.db` and run `ingest_lattes_projects`, `lattes_advisorships` and `replay_cnpq.py` on it three times, saving after each pass. `compare_dbs.py` of pass 2 vs pass 3 must print `RESULT: IDENTICAL` (only `ingestion_runs` may differ; exclude it). Record what pass 1 changed (expected: only person-resolution cases, far fewer than the base's 713/3 806/23 from T006).

**Checkpoint**: Passes 2 and 3 identical on real data; the unit tests pass.

---

## Phase 5: User Story 3 - Merges and better ids never break an old reference (Priority: P2)

**Goal**: Every id ever published stays current or becomes an alias (merge, upgraded key, rebuild, key corrected) and is published in `horizon_id_aliases_canonical.json`; history survives `db-reset` via the published zip.

**Independent Test**: Merge/upgrade/rebuild/key-corrected scenarios in `tests/test_horizon_id_assigner.py` (T039), and the rebuild replay (T049).

### Tests for User Story 3

- [X] T039 [P] [US3] In `tests/test_horizon_id_assigner.py`, add (one fixture database per scenario, history injected through the store or through a fake previous zip):
  - merge (a `lattes_id` person and a name-only person; `horizon_merge_log` entry) → survivor `person:lattes:…`, alias `merge`;
  - equal-priority merge → the alphabetically first id survives, whatever row survived;
  - upgrade (the history has `person:h:<name>`, the person now has a `lattes_id`) → alias `upgraded key`, and the children's old ids too;
  - rebuild (empty database tables, history only in a previous `exports_canonical.zip` containing the two new files) → every old id is current or an alias `rebuild` (SC-007);
  - key corrected (a DOI-less article title changed by one letter, same author) → alias `key corrected`; two similar candidates → no alias, counted;
  - rule-version change (history written with `rule_version` 1 and a different rule for one type; code at version 2) → each old id of that type is recomputed from its `natural_key` and becomes an alias `rebuild` of the new id;
  - history sources: tables present → used; tables absent and `db/horizon_id_history.json` present → snapshot used; both absent → zip used; snapshot and zip both present → merged;
  - an alias whose target becomes an alias is re-pointed (no chains);
  - a retired id that reappears becomes current again and leaves the alias table.

### Implementation for User Story 3

- [X] T040 [US3] In `src/adapters/database/horizon_id_store.py`, implement `load_history(snapshot_path='db/horizon_id_history.json', zip_path='data/exports/exports_canonical.zip')` (research R5): (1) the current `horizon_ids`, `horizon_id_candidates`, `horizon_id_aliases` and unconsumed `horizon_merge_log` rows, when non-empty; otherwise (2) the snapshot file and (3) `horizon_ids_canonical.json` + `horizon_id_aliases_canonical.json` from the zip, merged when both exist. Return rows with `horizon_id`, `entity_type`, `rule`, `natural_key`, `parent_horizon_id` and the source each came from. A missing snapshot, zip or file inside the zip is not an error.
- [X] T041 [US3] In `src/core/logic/person_consolidator.py` (`consolidate_pair`, before deleting the loser) and in `src/core/logic/reference_consolidator.py` (`_merge_knowledge_area`, `_merge_team`), insert a `horizon_merge_log` row with the loser's candidate ids, computed from the loser row with the rule functions of `horizon_identity` (no database id involved), and the winner's numeric id. Add a test case in `tests/test_person_consolidator.py` and `tests/test_reference_consolidator.py` asserting the row.
- [X] T042 [US3] Create `src/scripts/save_horizon_id_history.py` (an operational utility: it only reads the database, constitution III): when `DATABASE_URL`'s database exists and has `horizon_ids`, write `db/horizon_id_history.json` atomically (temp file + rename) in the shape of [data-model.md](data-model.md) "Id history snapshot", with each `horizon_merge_log` winner stored as its `horizon_id`; when there is nothing to save, log and exit 0; when writing fails, log a WARNING and exit 0 so the reset is never blocked. In the `Makefile`, make `db-reset` run it before `db-clean` (`db-reset: db-save-ids db-clean db-init`, new target `db-save-ids`); add `db/horizon_id_history.json` to `.gitignore`.
- [X] T043 [P] [US3] Create `tests/test_save_horizon_id_history.py`: a seeded temp database → the snapshot has the ids, candidates, aliases and merge log; a database without the tables → no file, exit 0; an unwritable target → WARNING, exit 0; the snapshot read back by `load_history()` (T040) resolves an upgraded-key id after the database is deleted and rebuilt.
- [X] T044 [US3] In `src/core/logic/horizon_id_assigner.py`, add history reconciliation (research R5): after computing the current ids, resolve every history id that is not current. Use the candidate lookup (`upgraded key`, or `rebuild` when it came only from the zip), then the merge log (`merge`, winner's current id = highest-priority candidate, ties alphabetical), then key corrected (T045); what remains becomes `retired`. Re-point aliases whose target is no longer current, remove alias rows for ids that are current again, and write through `upsert_aliases`.
- [X] T045 [US3] In `src/core/logic/horizon_id_assigner.py`, implement "key corrected" (research R8). Candidates are new computed ids of the same entity type that are not in the history and share the parent or source document (owner CV for Lattes children and projects, an author for articles, the CNPq group for members). Score with `rapidfuzz.fuzz.token_sort_ratio` on the `natural_key`, using the threshold `PersonMatcher` uses (share the constant; do not copy the number). Exactly one candidate ≥ threshold → alias; else count.
- [X] T046 [US3] Add `write_alias_file(store, output_dir)` next to `write_id_file` in `src/core/logic/horizon_id_assigner.py` (contract [export-files.md](contracts/export-files.md), sorted by `alias_horizon_id`, written even empty whenever ids were assigned), and call it from `export_horizon_ids_task` in `src/flows/exports/canonical_data.py`, which already runs before `zip_exports_task`. *(Implemented beside the id file writer rather than in `canonical_exporter.py`: both new files come from the same store.)*
- [X] T047 [US3] Add the alias counts per reason, retired ids and failed relinks to the report written by `src/flows/maintenance/horizon_ids.py` (research R10).
- [X] T048 [US3] Run `pytest -q tests/test_horizon_id_assigner.py tests/test_person_consolidator.py tests/test_reference_consolidator.py` and make T039 pass.
- [X] T049 [US3] Rebuild check (SC-001, SC-007): run `$R/replay_weekly.sh /home/rafael/horizon_etl $R/feat_b.db` with `assign_horizon_ids` (exports in `$R/feat_b_exports/`), where the working directory's `data/exports/exports_canonical.zip` is the one produced by `feat_a`. Compare `feat_a` and `feat_b` id files on `(entity_type, horizon_id, natural_key)`: they must be identical. Every id in `feat_a`'s file must be current or an alias in `feat_b`. *(2026-10-27: two rebuilds of the new code in different directories gave identical id and alias files (62,227 ids, 157 aliases). Against `feat_a`, built before the fix that hashes the source file name instead of its absolute path, 154 collision-suffixed ids stay retired: that rule was never published.)*

**Checkpoint**: All alias scenarios pass; two rebuilds give the same ids; nothing published is lost.

---

## Phase 6: User Story 4 - Existing consumers see no format change (Priority: P2)

**Goal**: Proof that no existing table and no existing export file changed shape.

**Independent Test**: Schema snapshot and field-set comparisons (T050–T053).

- [X] T050 [P] [US4] Create `tests/test_schema_compatibility.py`: build a database with the base schema (`Base.metadata.create_all` without migrations 0002+), snapshot `PRAGMA table_info` and `PRAGMA index_list`/`index_info` of every table, apply `run_migrations`, snapshot again, and assert that every pre-existing table is identical and only the six new tables were added (FR-014).
- [X] T051 [P] [US4] In `tests/test_export_canonical_data_flow.py`, add a test that compares the set of keys of the first record (and of the nested records) of every pre-existing `*_canonical.json` produced on the fixture database with and without `horizon_ids` rows. They must be equal (FR-015).
- [X] T052 [P] [US4] Add a test (in `tests/test_export_canonical_data_flow.py` or a new `tests/test_export_parquet.py`) that runs `src/scripts/export_parquet.py` on a folder with the two new files and asserts that `horizon_id`, `alias_horizon_id`, `parent_horizon_id` and `natural_key` stay text (FR-017). `_is_id_column` matches `*_id` but falls back on non-numeric values; the test pins that behaviour.
- [X] T053 [US4] Real-data field-set check: for every `*_canonical.json` in `$R/base_a_exports/` and `$R/feat_a_exports/`, compare the key sets (top level and nested). Only the two new files may be new. Record the result.

**Checkpoint**: Compatibility proven by tests and on real exports.

---

## Phase 7: User Story 5 - A change of rules triggers one clean rebuild (Priority: P3)

**Goal**: The database records `HORIZON_RULE_VERSION`; a different version makes the weekly reset once.

**Independent Test**: Version-guard test (T054).

- [X] T054 [P] [US5] In `tests/test_horizon_id_assigner.py` (or `tests/test_weekly_orchestrator.py` if one exists; check `tests/`), test `rule_version_requires_reset(db_path)`: no database → False (a fresh one is created anyway); `horizon_meta.rule_version` equal to the code's → False; different or missing on a database that has entity rows → True. *(Written as `tests/test_rule_version_guard.py`; `tests/conftest.py` stubs the guard in every other test, so a faked weekly never resets the repository's database.)*
- [X] T055 [US5] In `src/flows/pipelines/weekly_orchestrator.py`, call `rule_version_requires_reset` at the start of `run_weekly`; when it returns True, log why and run the reset (the same steps as `make db-reset`: `src/scripts/save_horizon_id_history.py` first, then remove `db/horizon.db` and its `-wal`/`-shm`, then `db/create_db.py`) before the phases. Put the helper in `src/flows/maintenance/horizon_ids.py` and use the store port to read `horizon_meta`. Today `make weekly-flows` already resets, so this only fires when spec B removes the unconditional reset; say so in a comment.

**Checkpoint**: Version-guard test passes.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T056 Old vs new replay (SC-008, quickstart step 4): `compare_dbs.py --ignore-ids $R/base_a.db $R/feat_a.db`. Expected differences, each counted and explained: (a) `team_members` of teams fed by several documents or shared by initiatives (union and earliest date), (b) attributes of the same-CV duplicates where the kept version differs, (c) `source_records` keys and fewer rows, (d) fewer `entity_change_logs`, (e) the new tables. Anything else is a bug: stop and fix it.
- [X] T057 [P] Run `make ci-check` (format-check, lint, test) and compare the test failures with `$R/BASE020.txt` (no new failures). The constitution's quality gate also lists mypy, which the `ci-check` target does not run; note that in the validation report instead of adding it here.
- [X] T058 [P] Write `docs/reports/2026-10-XX-horizon-id-validation.md` (actual date) with: the simulation numbers (T003), the per-type id counts and collisions (T023), the base rerun numbers (T006), the fixpoint result and pass-1 changes (T038), the rebuild comparison (T049), the compatibility checks (T050–T053), the old-vs-new differences (T056) and the timing of `assign_horizon_ids`.
- [X] T059 [P] Add to `docs/backlog.md` a new item for the 149 groups of duplicate rows found by the id rules (articles 73, professional activities 53, productions 8, knowledge areas 7, fellowships 4, groups 2, educations 2; examples in research R2), as a candidate for a deduplication spec. Also record that person resolution in fresh runs depends on the order of creation (research R9.3).
- [X] T060 Local weekly: `make weekly-flows > logs/weekly_020_validation.log 2>&1` with the Telegram variables empty. Check that `assign_horizon_ids` runs between `consolidate_duplicates` and `export_canonical` and exits 0, that `exports_canonical.zip` contains the two new files, and that `data/reports/horizon_ids_report.json` matches T023. CI comes only after this, with the maintainer's go-ahead (push to the fork, manual dispatch). _Done in an isolated copy of the project with an ephemeral Prefect server, so `db/horizon.db` and Docker were not touched; results in the validation report, section 8._
- [X] T061 After the maintainer's go-ahead and the first manual CI dispatch on the fork only (SC-006): download the run's artifact, extract `horizon_ids_canonical.json` from its `exports_canonical.zip`, and compare it with the local file of the same inputs on `(entity_type, horizon_id, natural_key)`; any difference means an id depends on the environment (for example on `HORIZON_PII_HMAC_KEY`), which FR-007 forbids. Record the result in the validation report.
- [X] T062 Update `PLANO_HASH_IDEMPOTENTE.md` section 7 (the note for the consuming team) with the final file names and fields from [contracts/export-files.md](contracts/export-files.md), including the three extra columns of the id file.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none. T005 needs T004; T006 needs T005.
- **Foundational (Phase 2)**: after Setup. T011 needs T008 and T009.
- **US1 (Phase 3)**: after Foundational.
- **US2 (Phase 4)**: after Foundational. T029 needs T009; T041 (US3) reuses T014's rule functions. US2 does not need US1 to pass its own tests, but T037/T038 run the full replay, which includes `assign_horizon_ids` once US1 is in.
- **US3 (Phase 5)**: after US1 (it extends the assigner and the exports).
- **US4 (Phase 6)**: T050 after T008; T051–T053 after T020/T046 and T037.
- **US5 (Phase 7)**: after T011 (store) and T019 (orchestrator phase).
- **Polish (Phase 8)**: after all stories.

### Within Each Story

- Tests first, failing; then implementation; then the real-data check.
- `src/core/logic/horizon_identity.py` is touched by T009, T014, T015 and T029: do them in that order, not in parallel.
- `src/core/logic/person_consolidator.py` is touched by T033 and T041: sequential.
- `src/flows/exports/canonical_data.py` and `canonical_exporter.py` are touched by T020/T021 and T046: sequential.

### Parallel Opportunities

- Setup: T002, T003, T004 and T007 together.
- Foundational: T009 and T010 together, while T008 is written.
- US1 tests T012 and T013 together; US2 tests T024–T027 together.
- After Foundational, US1 implementation (assigner, flow, export) and US2 implementation (tracking keys, no-op writes, team sync, matcher) touch different files, except `horizon_identity.py` (sequence T014 → T015 → T029).
- US4 tests T050–T052 together.

---

## Parallel Example: User Story 2

```bash
# Tests, together:
Task: "tests/test_idempotent_rerun.py — three passes, passes 2 and 3 identical"
Task: "tests/test_tracking_keys.py — new keys, canonical hash, same-CV duplicates"
Task: "tests/test_team_synchronizer.py — union of contributions, order-independent"
Task: "tests/test_person_matcher.py — deterministic tie-break"

# Implementation in different files, together:
Task: "src/tracking/recorder.py — canonical stable_hash"
Task: "src/core/logic/team_synchronizer.py + initiative_linker.py — contributions"
Task: "src/core/logic/person_matcher.py — tie-break"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Setup (T001–T007) and Foundational (T008–T011).
2. US1 (T012–T023): ids for every entity, the id file in the export.
3. **Stop and validate**: T023 matches the simulation; two fixture rebuilds give the same ids.

### Incremental Delivery

1. US1: the consuming team gets stable ids.
2. US2: reruns stop writing noise (the prerequisite of spec B, the persistent database).
3. US3: aliases; the id history survives rebuilds.
4. US4: compatibility proof.
5. US5: version guard.
6. Polish: replay, report, backlog, local weekly; CI after the maintainer's go-ahead.

---

## Notes

- Third-party libraries (`eo_lib`, `dgp_cnpq_lib`, scriptLattes) stay unchanged; Docker is not touched.
- Nothing goes to the upstream repository; commits stay on the fork until the maintainer's manager validates.
- Show the maintainer only code and documentation changes; generated exports under `data/` are not part of the change list.
- Stop at each checkpoint and report before continuing.
