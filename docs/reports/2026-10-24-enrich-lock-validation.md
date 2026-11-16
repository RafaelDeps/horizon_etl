# Enrichment Lock Fix — Validation Report (spec 019)

Date: 2026-10-24 · Spec: `specs/019-enrich-lock-fix/` · Branch:
`022-enrich-lock-fix` · Machine: the maintainer's local machine.

## 1. Summary

- **The CI failure is gone** (SC-001). On a copy of the database from CI run
  40002646510, with that run's project documents, `enrich_projects` used to fail
  with `database is locked`; it now ends with exit 0: 251 enriched, 17 created,
  0 errors, 1 duplicate skipped.
- **Nothing changes without a collision** (SC-002). On a local database taken
  right before the phase, the old and the new code produce identical
  initiatives, enrichment payloads and tracking records.
- **Two fixes, both in `src/core/logic/project_enrichment.py`**:
  - new project titles are checked against the names of **all** initiatives, so
    a project titled like an advisorship is skipped as a duplicate;
  - after any failed row, the transaction left open by `ROLLBACK TO SAVEPOINT`
    is ended, so the tracking writes can never be locked out.

## 2. Success criteria

| Criterion | Target | Result | Status |
|---|---|---|---|
| SC-001 CI database replay | exit 0, 251 / 17 / 0, no lock | exit 0, enriched 251, created 17, errors 0, `skipped_duplicate` 1, 0 `database is locked`, 0 failed rows | Met |
| SC-002 local replay without collisions | 0 differences | Identical initiatives (name, type, description, `enrichment_json`), source records by type, entity matches, attribute assertions, change logs | Met |
| SC-003 next tracking write after a failed row | does not wait | Test: a second session writes immediately (0.5 s timeout) and the loader's connection has no open transaction | Met |
| SC-004 test suite | no new failures; new tests fail with the old code | 500 passed, 6 failed (the same pre-existing 6). The new tests failed before the fix (`skipped_duplicate` 0 instead of 1; open transaction; no warning on a failed release) | Met |
| SC-005 next CI weekly | `enrich_projects` successful | Pending: needs a CI weekly run on the fork after merge | Pending |

## 3. Replays

Inputs outside the repository, in `~/.cache/horizon_wal_replay/`:
- **CI**: the database of run 40002646510 (artifact `weekly-etl-artifacts`) and
  its `data/exports/project_sigpesq_files_json/` (297 documents).
- **Local**: the spec 018 replay database right after both Lattes phases (the
  state `enrich_projects` sees in a weekly run) and the repository's 322
  documents.
- **Base code**: a copy of the tree at `4b36b86`, taken before any change.

| Replay | Base code | New code |
|---|---|---|
| CI database | exit 1, `database is locked` after `UNIQUE constraint failed: initiatives.name` | exit 0; enriched 251, created 17, errors 0, `skipped_duplicate` 1 |
| Local database | exit 0; enriched 239, created 38, errors 0 | exit 0; enriched 239, created 38, errors 0; **identical** to base |

The CI result also matches, table by table, the database produced on the same
inputs by the throwaway fix tested during spec 018.

## 4. Tests

- `tests/test_project_enrichment_db.py` (+3): a title taken by an advisorship is
  a duplicate; a title differing only by accents and case is a duplicate; a new
  title is still created. Run in dry-run mode, as the phase's own checks are the
  same there.
- `tests/test_project_enrichment_lock.py` (new, 3 tests on a SQLite **file**
  with two sessions): a failed row releases the lock; rows written before a
  failure are kept; a failure while releasing is logged and does not raise.
- Full suite on Python 3.14 / SQLAlchemy 2.0.52: 500 passed, 6 failed (the
  pre-existing Lattes download, loader mapping, SigPesq adapter and weekly
  workflow tests). The three enrichment test files (56 tests) also pass on
  Python 3.12 / SQLAlchemy 2.1.6, the CI combination.
- black, isort and flake8 (`E9,F63,F7,F82`) pass on every changed file.

## 5. Behaviour now documented in the code

`ProjectEnrichmentLoader.run()` and `_write_row()` now state that, on SQLite,
each successful row is committed when its savepoint is released, that a failed
row is skipped and the database released, and that an exception leaving
`run()` does not undo rows already written. The previous comments described a
single unit of work that SQLite does not provide.

## 6. Not covered

- **The GitHub Actions run** (SC-005): the fix is validated on a copy of the CI
  database, not on a new CI weekly.
- **Linking a duplicate project to the existing initiative**: out of scope; the
  project is skipped, as same-type duplicates already were.
