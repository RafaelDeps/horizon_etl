---

description: "Task list for SQLite WAL journaling"
---

# Tasks: SQLite WAL Journaling for the ETL Database

**Input**: Design documents from `specs/018-sqlite-wal-journaling/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/sqlite-settings.md](contracts/sqlite-settings.md), [quickstart.md](quickstart.md)

**Tests**: Requested by the spec (FR-010, SC-005) and by the constitution (new behaviour needs tests). Test tasks come first in each story and must fail before the implementation.

**Organization**:
- **US1 (P1)**: every connection uses WAL + NORMAL, with identical data.
- **US2 (P1)**: the final `db/horizon.db` is complete and self-contained.
- **US3 (P2)**: the reset removes the companion files; direct readers keep working.
- **US4 (P3)**: investigate the `enrich_projects` `database is locked` failure.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task).
- **[Story]**: US1–US4.
- `$R` = `~/.cache/horizon_wal_replay`, a scratch directory **on disk** (not tmpfs), outside the repository. Nothing under `$R` is committed.
- Every replay command runs **from the repository root** (so relative paths such as `data/raw/sigpesq/` and `data/lattes_json/` resolve), with Telegram off:
  `export HORIZON_TELEGRAM_BOT_TOKEN= HORIZON_TELEGRAM_CHAT_ID= TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= HORIZON_QUIET_PREFECT=1 PREFECT_LOGGING_TO_API_ENABLED=false`.

---

## Phase 1: Setup (replay assets, built before any code change)

**Purpose**: Freeze the base code and the replay inputs, and build the comparison tools.

- [X] T001 Create `$R`. Copy the **base** code (the current tree, before this feature: `src/`, `app.py`, `lattes.config`, `db/create_db.py`) to `$R/base_code/` (`cp -r`, then delete every `__pycache__`). Write `git rev-parse HEAD` and `git status --short` to `$R/BASE.txt`. Check that `db/horizon.db` exists and holds 350 rows in `source_records` with `source_entity_type = 'cnpq_group_payload'`, that `data/raw/sigpesq/` holds the three report folders, and that `data/lattes_json/` holds 435 JSON files; write the three facts to `BASE.txt`.
- [X] T002 [P] Write `$R/build_pre_lattes.py <payload_db>`, which builds a pre-Lattes database offline:
  1. read every `(source_path, raw_payload_json)` from `source_records` where `source_entity_type = 'cnpq_group_payload'` in `<payload_db>` (read-only) into a dict keyed by `source_path`;
  2. patch `src.adapters.sources.cnpq_crawler.CnpqCrawlerAdapter.__init__` to do nothing and `CnpqCrawlerAdapter.get_group_data` to return `PAYLOADS.get(normalize_cnpq_url(url))`;
  3. inside one throwaway Prefect flow, call `persist_research_groups()`, `persist_projects()`, `persist_advisorships()` (from `src.flows.sigpesq.groups`, `.projects`, `.advisorships`);
  4. call `src.flows.cnpq.groups.sync_cnpq_groups_flow(campus_name=None)` and print its summary.
- [X] T003 [P] Write `$R/compare_lattes.py <a.db> <b.db>`. It opens both databases read-only and compares:
  - row counts of `teams`, `team_members`, `initiatives`, `initiative_teams`, `advisorships`, `persons`, `researchers`;
  - the sorted rows `(initiative name, team name)` from `initiative_teams ⋈ initiatives ⋈ teams`;
  - the sorted rows `(team name, person name, role name)` from `team_members ⋈ teams ⋈ persons ⟕ roles`;
  - the sorted person names.

  It prints each comparison as `IDENTICAL` or `DIFFERENT (n rows)` and a final `RESULT: IDENTICAL` / `RESULT: DIFFERENT`, and exits 0 only when everything is identical.
- [X] T004 Build the pre-Lattes snapshot with the base code (depends on T001, T002):
  1. `export DATABASE_URL=sqlite:///$R/pre_lattes.db PYTHONPATH=$R/base_code` (a fresh file);
  2. `.venv/bin/python $R/base_code/db/create_db.py`;
  3. `.venv/bin/python $R/build_pre_lattes.py db/horizon.db > $R/pre_lattes.log 2>&1`.

  Expect `success_count: 350` and counts close to `data-model.md` (persons ≈ 7 184, teams ≈ 1 158). Record them in `BASE.txt`.
- [X] T005 Produce the **base** replay result (depends on T004):
  1. `cp $R/pre_lattes.db $R/base.db`, `export DATABASE_URL=sqlite:///$R/base.db PYTHONPATH=$R/base_code`;
  2. `.venv/bin/python $R/base_code/app.py ingest_lattes_projects > $R/base_projects.log 2>&1` and then `.venv/bin/python $R/base_code/app.py lattes_advisorships > $R/base_advisorships.log 2>&1`, timing each command.

  Record both wall times in `BASE.txt` (reference: 1 298 s and 1 476 s).

**Checkpoint**: The base reference exists, and code changes may start.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create the adapter package that US1 and US2 share.

- [X] T006 Create `src/adapters/database/__init__.py` (empty) and `src/adapters/database/sqlite_settings.py` with only the module docstring (why WAL + NORMAL, the measured gain, the TD-018 reference, and that the weekly rebuilds the database so losing the last transactions on power loss is acceptable) and the imports it will need (`os`, `sqlite3`, `typing.Optional`, `loguru.logger`, `sqlalchemy.event`, `sqlalchemy.engine.Engine`, `sqlalchemy.engine.make_url`).

**Checkpoint**: `python -c "import src.adapters.database.sqlite_settings"` works.

---

## Phase 3: User Story 1 - Commits stop waiting for the disk, with identical data (Priority: P1) 🎯 MVP

**Goal**: Every SQLite connection opened in a phase process, including those opened by `eo_lib` and `research_domain`, uses `journal_mode=WAL` and `synchronous=NORMAL`; the Lattes phases get faster and the data stays identical.

**Independent Test**: Replay `lattes_projects` and `lattes_advisorships` from `$R/pre_lattes.db` with the new code and compare with `$R/base.db` (quickstart §3–4).

### Tests for User Story 1

- [X] T007 [US1] Write `tests/test_sqlite_settings.py` with these tests (they must fail before T008):
  - `install_sqlite_connection_settings()` then a new `create_engine(f"sqlite:///{tmp_path/'a.db'}")`: `PRAGMA journal_mode` returns `wal` and `PRAGMA synchronous` returns `1`;
  - an engine created **before** the call gets the same settings on its first connection;
  - an in-memory engine (`sqlite://`) reports `memory` and raises nothing;
  - the listener function called directly with a non-`sqlite3.Connection` object (a `MagicMock`) does not call `cursor()` on it;
  - calling `install_sqlite_connection_settings()` twice registers the listener once (`sqlalchemy.event.contains(Engine, "connect", <listener>)` is true and a connect runs the PRAGMAs once; count with a wrapped cursor or check the module flag);
  - if the PRAGMA raises `sqlite3.OperationalError` (listener called with a fake `sqlite3.Connection` subclass whose cursor raises), the listener logs a WARNING and does not raise.

  Remove the listener in a fixture teardown (`event.remove(Engine, "connect", ...)` and reset the module flag), so the other test files are not affected.

### Implementation for User Story 1

- [X] T008 [US1] In `src/adapters/database/sqlite_settings.py`, implement the private listener `_apply_sqlite_settings(dbapi_connection, connection_record)` and `install_sqlite_connection_settings()` exactly as in `contracts/sqlite-settings.md`: `isinstance(dbapi_connection, sqlite3.Connection)` guard; `PRAGMA journal_mode=WAL` then `PRAGMA synchronous=NORMAL` on a cursor closed in `finally`; `sqlite3.Error` caught and logged as WARNING; module flag `_installed` for idempotence; `event.listen(Engine, "connect", _apply_sqlite_settings)`. No per-connection INFO log. Make T007 pass.
- [X] T009 [US1] In `app.py`, import `install_sqlite_connection_settings` from `src.adapters.database.sqlite_settings` and call it right after `install_lgpd_session_hooks()` (same place, same style). Keep isort order.
- [X] T010 [US1] Feature replay (depends on T005, T009):
  1. `cp $R/pre_lattes.db $R/feature.db`, `export DATABASE_URL=sqlite:///$R/feature.db PYTHONPATH=.`;
  2. `.venv/bin/python app.py ingest_lattes_projects > $R/feature_projects.log 2>&1`, timing it; while it runs, confirm from another shell that `$R/feature.db-wal` exists and that `PRAGMA journal_mode` on `$R/feature.db` returns `wal`;
  3. `.venv/bin/python app.py lattes_advisorships > $R/feature_advisorships.log 2>&1`, timing it.

  Record both wall times next to the base ones in `$R/BASE.txt` (reference: 521 s and 875 s).
- [X] T011 [US1] Run `.venv/bin/python $R/compare_lattes.py $R/base.db $R/feature.db`. It must print `RESULT: IDENTICAL` (SC-002). If not, stop and investigate before any other story.

**Checkpoint**: US1 is done: faster Lattes phases, identical data.

---

## Phase 4: User Story 2 - The final database file is complete and self-contained (Priority: P1)

**Goal**: After `run_weekly`, `db/horizon.db` holds every row, is back in the rollback journal, and opens alone, read-only, with no companion files.

**Independent Test**: Finalize a WAL database, copy only the main file to a read-only directory, open it read-only and compare row counts (quickstart §6, last bullet).

### Tests for User Story 2

- [X] T012 [US2] Add to `tests/test_sqlite_settings.py` (after T007, same file) tests for `finalize_sqlite_database` (they must fail before T014):
  - a WAL database on `tmp_path` with a table and rows, all connections closed: the result is `{"finalized": True, "journal_mode": "delete", ...}`, no `-wal`/`-shm` file remains, and a copy of the main file alone, in a directory made read-only (`chmod 0o555`, restored in teardown), opened with `sqlite3.connect("file:…?mode=ro", uri=True)`, returns all rows;
  - with a second `sqlite3` connection still open on the file: returns `finalized: False` with a reason containing `locked`, and does not raise;
  - no-op cases, each returning `finalized: False` and touching nothing: `None`, `"postgresql://u:p@h/db"`, `"sqlite://"` (in-memory), and a SQLite URL whose file does not exist.
- [X] T013 [P] [US2] Write `tests/test_weekly_orchestrator_finalize.py`: patch `src.flows.pipelines.weekly_orchestrator._run_phase` to return fixed result dicts (one critical phase failing in one test, all passing in another), patch `_notify`, and patch `finalize_sqlite_database` as imported in the orchestrator. Assert that `run_weekly()`:
  - calls `finalize_sqlite_database` exactly once, with `os.getenv("DATABASE_URL")` (set via `monkeypatch.setenv`), **after** all phases (check the call order with a shared `MagicMock` manager);
  - still calls it when phases fail;
  - returns the same exit code as before (1 with a failed critical phase, 0 otherwise), also when finalize returns `finalized: False`;
  - passes a failed finalize to the Telegram summary (`_notify` receives it and adds a line).

### Implementation for User Story 2

- [X] T014 [US2] In `src/adapters/database/sqlite_settings.py`, implement `finalize_sqlite_database(database_url: Optional[str]) -> dict` as in `contracts/sqlite-settings.md`: resolve the path with `make_url(database_url)`; return `{"finalized": False, "reason": ...}` for `None`, non-SQLite drivers, in-memory (`database` empty or `":memory:"`) and missing files; otherwise one `sqlite3.connect(path)`, `PRAGMA wal_checkpoint(TRUNCATE)`, `PRAGMA journal_mode=DELETE`, close in `finally`; on `sqlite3.Error` log ERROR and return `finalized: False` with `str(exc)`; on success log one INFO line and return `{"finalized": True, "checkpoint": <tuple>, "journal_mode": <str>}`. Never raise. Make T012 pass.
- [X] T015 [US2] In `src/flows/pipelines/weekly_orchestrator.py`:
  - import `finalize_sqlite_database` from `src.adapters.database.sqlite_settings`;
  - in `run_weekly`, right after the phase loop and before `=== Weekly pipeline summary ===`, call `finalize = finalize_sqlite_database(os.getenv("DATABASE_URL"))` and log `SQLite finalize: {finalize}` at INFO;
  - give `_notify` an optional `finalize: Optional[dict] = None` parameter; when `finalize` is given and `finalized` is false with a reason other than the no-op reasons, append `⚠️ SQLite finalize falhou: <reason>` to the message;
  - keep the exit-code rules unchanged. Make T013 pass.
- [X] T016 [US2] On the replay database from T010: `.venv/bin/python -c "from src.adapters.database.sqlite_settings import finalize_sqlite_database as f; print(f('sqlite:///$R/feature.db'))"`. Check that it prints `finalized: True`, that `$R/feature.db-wal` and `-shm` no longer exist, and that a copy of `$R/feature.db` alone in a read-only directory opens read-only with the same counts as `$R/base.db` (re-run T011 against the copy).

**Checkpoint**: US1 and US2 are done; the feature is safe for the CI artifact.

---

## Phase 5: User Story 3 - Database reset and direct readers keep working (Priority: P2)

**Goal**: `make db-clean` removes the companion files; ETL code that opens the file with `sqlite3.connect` behaves as before on a WAL database.

**Independent Test**: quickstart §7, plus the direct-reader comparison below.

- [X] T017 [US3] In `Makefile`, change the `db-clean` recipe from `@rm -f db/horizon.db` to `@rm -f db/horizon.db db/horizon.db-wal db/horizon.db-shm`. Do not touch any `docker-*` target.
- [X] T018 [US3] Verify the reset: create empty `db/horizon.db-wal` and `db/horizon.db-shm` next to an existing `db/horizon.db` (back up the real `db/horizon.db` to `$R/horizon.db.bak` first), run `make db-clean`, and check with `ls db/` that none of the three files remains. Restore the backup afterwards.
- [X] T019 [US3] Direct readers on WAL vs rollback mode: copy `$R/feature.db` (finalized in T016, so in rollback mode) to `$R/direct_delete.db`, and copy it again to `$R/direct_wal.db` and switch that copy to WAL (`PRAGMA journal_mode=WAL` with a plain `sqlite3` connection). On each copy (`<mode>` = `delete` or `wal`), with `PYTHONPATH=.`, call the functions directly with the copy's path. **Do not use `app.py` here**: `app.py consolidate_duplicates` and `app.py anonymize_backfill` ignore `DATABASE_URL` and always open the real `db/horizon.db` (their `db_path` defaults to it).
  - `src.scripts.consolidate_duplicates.run_person_dedup(db_path="$R/direct_<mode>.db", report_dir="$R/dedup_<mode>")`, keeping the returned report;
  - `src.flows.maintenance.anonymize_backfill.anonymize_backfill_flow(db_path="$R/direct_<mode>.db")`, keeping the returned counts;
  - `src.scripts.etl_load_report.generate_report(db_path="$R/direct_<mode>.db")`, keeping the returned dict.

  The two dedup reports, the anonymisation counts, the two load reports and the row counts (via `compare_lattes.py`) must match.

**Checkpoint**: US3 is done.

---

## Phase 6: User Story 4 - Know whether this fixes the `database is locked` failure (Priority: P3)

**Goal**: A documented answer, with evidence, on whether WAL changes the `enrich_projects` failure, and which connections hold the lock if it persists.

**Independent Test**: quickstart §5.

- [X] T020 [US4] Get the CI inputs. The maintainer downloads the artifact of run 40002646510: `gh run download 40002646510 -R RafaelDeps/horizon_etl -n weekly-etl-artifacts -D $R/ci_artifact` (≈ 281 MB). Copy its `db/horizon.db` to `$R/ci_pre_enrich.db`. Note in `$R/BASE.txt` that this database already went through `consolidate_duplicates`, `export_canonical` and `anonymize_backfill`, so the reproduction is approximate.
- [X] T021 [US4] Run `enrich_projects` with the base code and with the feature code, each on its own copy of `$R/ci_pre_enrich.db`, with `data/exports/project_sigpesq_files_json/` taken from `$R/ci_artifact/data/exports/project_sigpesq_files_json/` (copy the repository's folder aside first and restore it afterwards):
  `PYTHONPATH=<code> DATABASE_URL=sqlite:///$R/<copy>.db .venv/bin/python <code>/app.py enrich_projects`. Record whether each run hits `database is locked`.
- [X] T022 [US4] If either run fails with `database is locked`: in a **throwaway copy** of the code under `$R/` (never in the repository), add temporary logging of `id(self._session)`, `id(self._session.connection())` in `ProjectEnrichment._record_tracking` and of the tracking repository session in `src/tracking/recorder.py` `record_source_record`, rerun, and record which two sessions/connections write. Also try to find why the same code passes locally (compare `ingest_new` candidates between the local run and the CI inputs).
- [X] T023 [US4] Write the US4 outcome (failure reproduced or not, base vs feature, the two writers if found, the local-vs-CI difference) into the validation report draft `$R/us4_findings.md`, to be merged into the report in T028.

**Checkpoint**: All user stories are done.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T024 [P] In `docs/flows-and-entrypoints.md`, add a section "SQLite connection settings" covering: what is set (WAL + NORMAL) and why (per-record commits in `libbase`, the measured gain); where it is installed (`app.py`); the finalize step at the end of `run_weekly` and its `SQLite finalize: …` log line; why `horizon.db-wal` / `-shm` may exist during a run; that `make db-clean` removes them; and that standalone entry points other than the weekly leave the file in WAL mode, which is harmless.
- [X] T025 [P] In `docs/backlog.md`, update TD-018: status **Fixed** with the date, the replay times (base vs feature), the weekly times from T027, and a pointer to the validation report. Add a new backlog item for the `enrich_projects` two-writers issue if T021–T023 confirmed it, and one for the `research_domain` `assign_team` → `get_by_id` cost (24% of `lattes_advisorships`, research R1) as a candidate for a later spec.
- [X] T026 Lint and tests: `black --check` and `isort --check` on every changed `.py` file; `flake8 . --count --select=E9,F63,F7,F82 --statistics`; `PYTHONPATH=. .venv/bin/python -m pytest -q tests/`. Expected: no new failures beyond the 6 pre-existing ones (SC-005). Also run `tests/test_sqlite_settings.py` and `tests/test_weekly_orchestrator_finalize.py` in a Python 3.12 environment with SQLAlchemy 2.1 (the CI combination), for example a throwaway `uv venv --python 3.12` with `requirements.txt` installed.
- [X] T027 Full local weekly (quickstart §6): `make weekly-flows 2>&1 | tee logs/weekly_018_validation.log`. Check exit 0, the same critical-phase results as the spec 017 run, the Lattes phase times against 21.1 / 24.7 min, the `SQLite finalize: … finalized: True …` line, and afterwards that `db/` holds only `horizon.db`, `PRAGMA journal_mode` returns `delete`, and a lone read-only copy has the same counts (SC-003, SC-004).
- [X] T028 Write `docs/reports/2026-10-XX-sqlite-wal-validation.md` (use the real date), in the style of the spec 015–017 reports: summary table of success criteria (SC-001–SC-006) with measured values; the replay (T005, T010, T011); the finalize check (T016); the reset and direct-reader checks (T018, T019); the US4 findings (T023); the full weekly timings (T027); the test results (T026).
- [X] T029 In `specs/018-sqlite-wal-journaling/spec.md`, set **Status** to `Implemented` once T026–T028 pass.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies. T002 and T003 run in parallel; T004 needs T001+T002; T005 needs T004. Must finish **before** any code change, so the base replay uses the base code.
- **Foundational (Phase 2)**: after Setup. Blocks US1 and US2.
- **US1 (Phase 3)**: after Foundational. T007 → T008 → T009 → T010 → T011.
- **US2 (Phase 4)**: after Foundational. Its tests and implementation do not need US1, but T016 uses the database produced by T010. T012 must follow T007 (same file).
- **US3 (Phase 5)**: T017–T018 are independent of US1/US2. T019 needs T016.
- **US4 (Phase 6)**: needs T009 (feature code installs WAL). Independent of US2/US3.
- **Polish (Phase 7)**: after the stories. T027 needs T009, T015 and T017. T028 needs T023 and T027.

### Within Each User Story

- Tests first, failing; then implementation; then the replay or manual check.

### Parallel Opportunities

- T002 ∥ T003 (Setup).
- T013 ∥ T007/T012 (different test files).
- T017 ∥ any US1/US2 task (Makefile only).
- T020 (artifact download) can run while US1 is being implemented.
- T024 ∥ T025 (different docs).

---

## Parallel Example: User Story 2

```bash
# Tests in different files can be written together:
Task: "T012 finalize tests in tests/test_sqlite_settings.py (after T007)"
Task: "T013 run_weekly finalize tests in tests/test_weekly_orchestrator_finalize.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 + User Story 2)

US1 alone already gives the speed-up, but a WAL file left behind makes the CI
artifact incomplete. Ship US1 **together with** US2:

1. Setup (base replay) → Foundational.
2. US1: listener, `app.py`, replay, identical comparison.
3. US2: finalize, orchestrator call, lone-copy check.
4. **Stop and validate**: SC-001, SC-002, SC-003.

### Incremental Delivery

1. US1 + US2 → MVP, safe for the CI.
2. US3 → clean reset, direct readers verified.
3. US4 → the lock investigation, documented.
4. Polish → docs, full weekly, validation report.

---

## Notes

- [P] tasks = different files, no dependencies.
- Never run replay or reproduction commands against the real `db/horizon.db`; always use copies under `$R`.
- Temporary instrumentation (T022) lives only in a throwaway copy under `$R`.
- Do not touch Docker files or `docker-*` Makefile targets.
- Third-party libraries (`libbase`, `eo_lib`, `research_domain`, `dgp_cnpq_lib`) are not modified.
