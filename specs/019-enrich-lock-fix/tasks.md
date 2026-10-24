---

description: "Task list for the enrichment lock fix"
---

# Tasks: Enrichment Survives Cross-Type Title Collisions

**Input**: Design documents from `specs/019-enrich-lock-fix/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/enrichment-writes.md](contracts/enrichment-writes.md), [quickstart.md](quickstart.md)

**Tests**: Requested by the spec (FR-008, SC-004). Test tasks come first in each story and must fail before the implementation.

**Organization**:
- **US1 (P1)**: duplicate check across all initiative types.
- **US2 (P1)**: a failed row releases the database lock.
- **US3 (P3)**: comments describe the real commit behaviour.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task).
- **[Story]**: US1–US3.
- `$R` = `~/.cache/horizon_wal_replay` (on disk, outside the repository; created by spec 018). It already holds `ci_artifact/` (artifact of CI run 40002646510), `ci_pre_enrich.db` (copy of that run's database) and `base.db` (local database right after both Lattes phases, before `enrich_projects`). Nothing under `$R` is committed.
- Every replay runs with Telegram off: `export HORIZON_TELEGRAM_BOT_TOKEN= HORIZON_TELEGRAM_CHAT_ID= TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= HORIZON_QUIET_PREFECT=1 PREFECT_LOGGING_TO_API_ENABLED=false`.

---

## Phase 1: Setup (replay assets, before any code change)

- [X] T001 Check that `$R/ci_artifact/data/exports/project_sigpesq_files_json/` (≈ 297 `PJ_*.json`), `$R/ci_pre_enrich.db` and `$R/base.db` exist; if `ci_artifact` is missing, re-download it with `gh run download 40002646510 -R RafaelDeps/horizon_etl -n weekly-etl-artifacts -D $R/ci_artifact` (≈ 281 MB). Copy the **base** code (`src/`, `app.py`) to `$R/base019_code/` (remove `__pycache__`), symlink `/home/rafael/horizon_etl/.env` into it, and write `git rev-parse HEAD` to `$R/BASE019.txt`.
- [X] T002 [P] Write `$R/compare_enrich.py <a.db> <b.db>`: opens both read-only and compares (1) the sorted rows `(name, initiative_type_id, coalesce(description,''), coalesce(enrichment_json,''))` of `initiatives`, (2) `source_records` counts grouped by `(source_system, source_entity_type)`, (3) row counts of `entity_matches`, `attribute_assertions` and `entity_change_logs` (read the existing table names with `sqlite_master`; skip absent ones). Prints each as `IDENTICAL`/`DIFFERENT (n)` and `RESULT: IDENTICAL`/`DIFFERENT`; exit 0 only when identical.
- [X] T003 Base replays (depends on T001). (a) CI: working directory `$R/w019_base` with a copy of `$R/ci_artifact/data`, database `$R/ci019_base.db` copied from `$R/ci_pre_enrich.db`; run `PYTHONPATH=$R/base019_code DATABASE_URL=sqlite:///$R/ci019_base.db .venv-python $R/base019_code/app.py enrich_projects` from that directory, where `.venv-python` is `/home/rafael/horizon_etl/.venv/bin/python`; expect exit 1 with `database is locked`. (b) Local: working directory `$R/l019_base` with `data/exports/project_sigpesq_files_json/` copied from the repository, database `$R/loc019_base.db` copied from `$R/base.db`; run the same command; expect exit 0. Record both outcomes and the `Enrichment finished` line in `$R/BASE019.txt`.

**Checkpoint**: Base references exist; code changes may start.

---

## Phase 2: Foundational

No blocking prerequisite: both stories change different methods of the same file and have their own tests.

---

## Phase 3: User Story 1 - A project titled like an initiative of another type is skipped (Priority: P1) 🎯 MVP

**Goal**: `_ingest_new` treats a title already used by any initiative type as a duplicate.

**Independent Test**: The dry-run test below, then the CI replay (T008).

### Tests for User Story 1

- [X] T004 [US1] In `tests/test_project_enrichment_db.py`, add `test_title_of_another_initiative_type_is_a_duplicate`: insert an `initiative_types` row `(2, 'Advisorship')` and an initiative `(id=50, name='Mapeamento dos dados do ENEM', initiative_type_id=2)`; write one unmatched, ingestable PJ document titled `'Mapeamento dos dados do ENEM'` (give it a code that matches nothing, a description and the other fields `is_ingestable` requires; read `is_ingestable` to set them); set `loader.dry_run = True` and call `loader.run(str(tmp_path), ingest_new=True)`. Assert `stats["skipped_duplicate"] == 1` and `stats["created"] == 0`. Also add `test_title_differing_only_by_accents_and_case_is_a_duplicate` with the advisorship named `'Mapeamento dos Dados do ENEM'` and the document `'mapeamento dos dados do enem'`. Run them and confirm they fail with the current code (`created == 1`).

### Implementation for User Story 1

- [X] T005 [US1] In `src/core/logic/project_enrichment.py`, `_ingest_new`: replace `existing_names = set(name_index.keys())` with a set that also holds `normalize_text(name)` for every row of `SELECT name FROM initiatives` (skip empty normalized values), read once at the start of the method through `self._session.execute(text(...))`. Add a short comment: initiative names are unique across all types, so a new project cannot reuse an advisorship's title either. Make T004 pass; keep every other counter and the check order unchanged.

**Checkpoint**: `pytest -q tests/test_project_enrichment_db.py` passes.

---

## Phase 4: User Story 2 - A failed row never locks out the tracking writes (Priority: P1)

**Goal**: After `_write_row` catches a failure, the loader's connection holds no transaction.

**Independent Test**: The two-session tests below.

### Tests for User Story 2

- [X] T006 [US2] Create `tests/test_project_enrichment_lock.py` (module docstring: why a file database and two sessions are needed; spec 019). Fixture: `create_engine(f"sqlite:///{tmp_path/'lock.db'}", connect_args={"timeout": 0.5})`; create `CREATE TABLE initiatives (id INTEGER PRIMARY KEY, name TEXT UNIQUE)` and `CREATE TABLE source_records (id INTEGER PRIMARY KEY, x TEXT)`; insert initiative `'dup'`; build the loader with `ProjectEnrichmentLoader.__new__` and a `SimpleNamespace` controller chain around session A (same pattern as `tests/test_project_enrichment_db.py`); run one `SELECT` on session A first, so it is mid-transaction like in `run()`. Tests:
  - `test_failed_row_releases_the_lock`: `_write_row` with a function that inserts `'dup'` returns `False`; then session B (`Session(engine)`) inserts into `source_records` and commits without error, and `session_a.connection().connection.dbapi_connection.in_transaction` is `False`.
  - `test_rows_written_before_a_failure_are_kept`: `_write_row` inserting `'a'` returns `True`, then one inserting `'dup'` returns `False`; a fresh `sqlite3.connect` on the file sees `'a'`.
  - `test_failed_release_does_not_raise`: patch `session_a.commit` to raise `sqlite3.OperationalError`; `_write_row` with the failing insert still returns `False` and logs a WARNING (capture with a loguru sink).

  Run them and confirm the first one fails with the current code (`database is locked`).

### Implementation for User Story 2

- [X] T007 [US2] In `src/core/logic/project_enrichment.py`, `_write_row`: after the existing `logger.warning(f"Row write failed, skipping: {exc}")`, end the transaction left open by `ROLLBACK TO SAVEPOINT` with `self._session.commit()`; if that raises, log a WARNING with the error, call `self._session.rollback()` inside its own `try`, and still return `False`. Update the docstring as in `contracts/enrichment-writes.md`. Make T006 pass.

**Checkpoint**: both test files pass.

### Replays

- [X] T008 [US1] [US2] CI replay with the new code (quickstart §2): working directory `$R/w019_feature` with a copy of `$R/ci_artifact/data`, database `$R/ci019_feature.db` copied from `$R/ci_pre_enrich.db`; `PYTHONPATH=/home/rafael/horizon_etl DATABASE_URL=sqlite:///$R/ci019_feature.db /home/rafael/horizon_etl/.venv/bin/python /home/rafael/horizon_etl/app.py enrich_projects`. Expect exit 0, `Enrichment finished` with `enriched 251, created 17, errors 0, skipped_duplicate 1`, and no `database is locked` in the log (SC-001). Record in `$R/BASE019.txt`.
- [X] T009 [US1] [US2] Local replay with the new code (quickstart §3): working directory `$R/l019_feature` with the repository's `data/exports/project_sigpesq_files_json/`, database `$R/loc019_feature.db` copied from `$R/base.db`; run the same command; expect exit 0. Then `python $R/compare_enrich.py $R/loc019_base.db $R/loc019_feature.db` must print `RESULT: IDENTICAL` (SC-002). Run T003(b) and T009 on the same day.

---

## Phase 5: User Story 3 - The code describes what really happens (Priority: P3)

- [X] T010 [US3] In `src/core/logic/project_enrichment.py`, rewrite the docstring of `run()` and the comment block above its `try`: on SQLite each successful row is committed when its savepoint is released; a failed row is skipped and the database released; an exception propagating out of `run()` does not undo rows already written; the final `commit()` closes the ambient transaction. Keep the existing warning that reintroducing `begin()` or moving the writes above the index loads breaks the phase.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T011 Lint and tests: `black --check` and `isort --check` on `src/core/logic/project_enrichment.py`, `tests/test_project_enrichment_db.py`, `tests/test_project_enrichment_lock.py`; `flake8 . --count --select=E9,F63,F7,F82 --statistics`; `PYTHONPATH=. .venv/bin/python -m pytest -q tests/` with no new failures beyond the 6 pre-existing ones (SC-004). Also run the two enrichment test files on Python 3.12 with SQLAlchemy 2.1 (a throwaway `uv venv --python 3.12` with `requirements.txt`).
- [X] T012 [P] In `docs/backlog.md`, set TD-020 to **Fixed** with the date, the CI replay result (T008), the local equivalence (T009) and a pointer to the report.
- [X] T013 Write `docs/reports/2026-10-XX-enrich-lock-validation.md` (real date), in the style of the spec 015–018 reports: summary; success criteria table (SC-001–SC-005, SC-005 marked as pending the next CI weekly); the base and feature replays (T003, T008, T009); the tests (T004, T006, T011).
- [X] T014 In `specs/019-enrich-lock-fix/spec.md`, set **Status** to `Implemented` once T011–T013 pass.

---

## Dependencies & Execution Order

- **Setup**: T001 → T003; T002 in parallel with T001. Must finish before code changes.
- **US1**: T004 → T005.
- **US2**: T006 → T007. Independent of US1 in code (different methods), but both edit `src/core/logic/project_enrichment.py`, so T005 and T007 run one after the other.
- **Replays**: T008 and T009 need T005 and T007.
- **US3**: T010 after T007 (same file region).
- **Polish**: T011 after T010; T012 ∥ T013 after T008/T009; T014 last.

### Parallel Opportunities

- T002 ∥ T001.
- T004 ∥ T006 (different test files).
- T012 ∥ T013.

## Parallel Example

```bash
# Tests of both stories can be written together:
Task: "T004 cross-type duplicate tests in tests/test_project_enrichment_db.py"
Task: "T006 lock tests in tests/test_project_enrichment_lock.py"
```

## Implementation Strategy

### MVP (US1 + US2)

US1 removes the known cause; US2 makes any future row failure harmless. Either
one alone completes the CI phase, but only both together meet the spec. Ship
them together, then US3 (comments) and the polish.

1. Setup and base replays.
2. US1 tests → fix. US2 tests → fix.
3. CI and local replays (SC-001, SC-002).
4. US3, lint and tests, docs, report.

## Notes

- Never run the replays against the real `db/horizon.db`; always copies under `$R`, each in its own working directory.
- Third-party libraries unchanged; Docker untouched.
- SC-005 (the next CI weekly reports `enrich_projects` as successful) is checked after the branch is merged into the fork and the weekly runs.
