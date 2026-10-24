# Research: Enrichment Survives Cross-Type Title Collisions

Evidence gathered on 2026-10-24 during spec 018 (its validation report, section
6) and while writing this spec. Replay assets live outside the repository in
`~/.cache/horizon_wal_replay/` (`$R` below).

## R1. The failure, step by step

**Finding** (CI run 40002646510, artifact `weekly-etl-artifacts` downloaded to
`$R/ci_artifact`; its database copied to `$R/ci_pre_enrich.db`):
- `app.py enrich_projects` on that database, with the run's
  `data/exports/project_sigpesq_files_json/`, fails with the base code and with
  the spec 018 code alike: `database is locked` on
  `INSERT INTO source_records`, ~5 s after
  `Row write failed, skipping: UNIQUE constraint failed: initiatives.name`.
- Instrumentation in a throwaway copy of the code (`$R/instr_code`) logged the
  loader connection's `in_transaction` flag:
  - before each tracking write after a successful row: `False`;
  - right after the failed row: `True`;
  - at the next `_record_tracking`: `True`, then `database is locked`.
- The colliding row: new project "Mapeamento dos dados do ENEM por município do
  Espírito Santo" against initiative 435, type 2 (`Advisorship`); the new
  project is type 1 (`Research Project`).

**Mechanism**:
- `ProjectEnrichmentLoader._session` is the session of its
  `InitiativeController`. `_write_row` runs each row in
  `session.begin_nested()`.
- With pysqlite, the `SAVEPOINT` statement opens the SQLite transaction and its
  `RELEASE` commits it, so a successful row leaves no lock.
- On failure, SQLAlchemy issues `ROLLBACK TO SAVEPOINT` only, which undoes the
  row but keeps the SQLite transaction and its write lock.
- `tracking_recorder` writes through sessions built by
  `TrackingServiceFactory._session()` (a new `sessionmaker` session per
  controller), so it uses another pooled connection and waits on that lock.

**Minimal reproduction** (`$R/lock_repro.py`, plain SQLAlchemy sessions on a
SQLite file, SQLAlchemy 2.0.52 / SQLite 3.46.1 and 2.1.6 / 3.53.1): a successful
nested write leaves `in_transaction=False` and the other session writes; a
UNIQUE failure leaves `True` and the other session gets `database is locked`.

## R2. Fix for the cause: check names across all types

**Finding**: `_ingest_new` builds `existing_names` from `name_index`, which
`_load_research_project_names` fills with Research Project initiatives only.
`UNIQUE(initiatives.name)` covers every type.

**Decision**: seed `existing_names` with `normalize_text(name)` for **every**
row of `initiatives`, plus the research project keys already there. A match is
counted in `skipped_duplicate`.

**Rationale**:
- It removes the known cause before the insert is attempted.
- It reuses the normalization already applied to research project titles, so
  one rule covers both cases.
- Measured on the current data: no new project matches an advisorship only after
  normalization (0 of 38 created locally, 0 of 33 in the CI database), so
  local and CI outputs do not change apart from the collision itself.

**Tested** (`$R/code_fixa`, on `$R/ci_pre_enrich.db`): exit 0, enriched 251,
created 17, errors 0, `skipped_duplicate` 1.

**Alternatives considered**:
- Compare exact names only, for other types: closer to what the database
  enforces, but two rules for one concept; and normalized equality across types
  is a strong sign of the same work. Rejected for simplicity; it can be revisited
  if a real case appears.
- Link the document to the existing initiative of the other type: changes the
  meaning of an advisorship. Out of scope (maintainer's default: skip).

## R3. Safety net: release the lock after any failed row

**Decision**: in `_write_row`'s `except`, after logging, call
`self._session.commit()` so the transaction left open by `ROLLBACK TO
SAVEPOINT` ends and its lock is released. If that commit itself fails, log it
and roll back, and still return `False`.

**Rationale**:
- Any other row failure (another constraint, a bad value) would hit the same
  lock. The loader already intends to "skip the row and continue".
- Nothing new is committed: the failed row was rolled back to its savepoint,
  and on SQLite every earlier row was already committed when its savepoint was
  released.
- `dry_run` never calls `_write_row`, so simulations are unaffected (verified in
  `_enrich_winners` and `_ingest_new`).

**Tested** (`$R/code_fixb`, on `$R/ci_pre_enrich.db`): exit 0, enriched 251,
created 17, errors 0 (the colliding row is logged as a failed write). Its
database is identical to the one from R2's fix: 4 377 initiatives, 268 with
`enrichment_json`, 268 tracking source records, same names/types/descriptions
hash.

**Alternatives considered**:
- Route the tracking writes through the loader's own session: removes the second
  connection, but changes `tracking_recorder`, which every loader uses. Larger
  change for the same result. Rejected.
- Raise the SQLite busy timeout: the lock is never released until the end of
  the phase, so waiting longer cannot help. Rejected.
- Wrap the whole phase in one real transaction (`BEGIN IMMEDIATE`): would make
  the documented "unit of work" true, but the tracking sessions would then be
  locked out for the whole phase. Rejected.

## R4. What the code comments claim

**Finding**: `run()`'s docstring says all writes "are committed once at the end"
and that "on error the session is rolled back". On SQLite that is not true:
each row is committed when its savepoint is released (R1), and the CI database
after the failed phase still holds the 251 rows written before the collision.

**Decision**: rewrite the docstring of `run()` and the comment block above its
`try`, and `_write_row`'s docstring, to state the real behaviour. Keep the
existing warning about not reintroducing `begin()`.

## R5. Tests

**Decision**:
- **Cross-type duplicate** (US1): extend `tests/test_project_enrichment_db.py`
  with an `Advisorship` type and an initiative titled like an unmatched project
  document; `run(ingest_new=True)` in `dry_run` (which needs no ORM insert)
  must report `skipped_duplicate == 1`, `created == 0`. With the current code it
  reports `created == 1`.
- **Lock release** (US2): new `tests/test_project_enrichment_lock.py` on a
  temporary SQLite **file** with `UNIQUE(name)`: a loader on session A whose
  `_write_row` gets a function inserting a duplicate name, then session B (same
  engine, `timeout` of 0.5 s) inserts a row. It must succeed. A second test:
  rows written by successful `_write_row` calls before the failure are still
  there afterwards. With the current code, session B gets `database is locked`.

**Rationale**: the existing DB tests use an in-memory database with no UNIQUE
constraint and no second connection, which is why they never caught this.

## R6. Equivalence without collisions

**Decision**: replay `enrich_projects` with the base and the new code on two
copies of a local database taken right before the phase: `$R/base.db` (the spec
018 replay database after both Lattes phases, which precede
`extract_project_files` and `enrich_projects`), with the local
`data/exports/project_sigpesq_files_json/` (322 documents). Compare initiatives
(name, type, description, `enrichment_json`) and tracking records by type.
