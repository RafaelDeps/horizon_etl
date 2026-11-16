# SQLite WAL Journaling — Validation Report (spec 018)

Date: 2026-10-24 · Spec: `specs/018-sqlite-wal-journaling/` · Branch:
`021-sqlite-wal-journaling` · Machine: the maintainer's local machine, database
on an NVMe ext4 disk.

## 1. Summary

- **Equivalence is proven** (SC-002). A controlled replay of `lattes_projects`
  and `lattes_advisorships` from the same offline pre-Lattes snapshot produced
  **identical** databases with the base and the new code.
- **The two Lattes phases take 54% of their previous time** in the replay
  (46.1 → 25.1 min), and **1 h 04 min** is the new full local weekly run
  (1 h 37 min after spec 017; 8 h 04 min before spec 015).
- **The final `db/horizon.db` is self-contained** (SC-003): after the weekly it
  is back in the rollback journal, no `-wal`/`-shm` file remains, and a lone copy
  opened read-only has the same row counts in all 42 tables.
- **WAL does not fix the `enrich_projects` `database is locked` failure**
  (SC-006). It was reproduced on the CI database and its cause was found: a
  failed insert inside a SAVEPOINT keeps the write lock while another session
  writes. Recorded as TD-020, for a separate spec.

## 2. Success criteria

| Criterion | Target | Result | Status |
|---|---|---|---|
| SC-001 Lattes phases vs baseline, same machine | ≤ 60% | **54%** in the replay (2 767 s → 1 504 s); 41% in the full run against the spec 017 run | Met |
| SC-002 replay identical | 0 differences | Identical counts and by-name rows (section 3) | Met |
| SC-003 lone copy of the final database | 100% of rows, no companion files | 42 tables, 484 469 rows, identical; `journal_mode=delete`; only `horizon.db` in `db/` | Met |
| SC-004 full weekly | same critical results, Lattes faster than 21.1 / 24.7 min | Exit 0 on all 19 phases; 7.4 / 12.4 min | Met |
| SC-005 test suite | no new failures | 494 passed, 6 failed (the same pre-existing 6); new tests also pass on Python 3.12 + SQLAlchemy 2.1.6 | Met |
| SC-006 `database is locked` answered | with evidence | Not fixed by WAL; cause found and two fixes tested (section 6) | Met |

## 3. Controlled replay

**Inputs** (no portal access):
- **Snapshot**: `db/create_db.py`, the SigPesq persistence
  (`persist_research_groups`, `persist_projects`, `persist_advisorships`) from
  the local reports in `data/raw/sigpesq/`, and `sync_cnpq_groups_flow` with
  `CnpqCrawlerAdapter.get_group_data` patched to return the 350
  `cnpq_group_payload` source records of the previous local run (350/350 groups).
  Result: 7 184 persons, 6 685 researchers, 1 158 teams, 11 469 team members,
  809 initiatives, 590 advisorships.
- **Curricula**: the 435 JSONs in `data/lattes_json/`.
- **Base code**: a copy of the tree at `dfa9513`, taken before any change.

**Times** (same machine and disk, one run after the other):

| Phase | Base | New code | Speed-up |
|---|---:|---:|---:|
| `lattes_projects` | 1 295 s | 579 s | 2.2× |
| `lattes_advisorships` | 1 472 s | 925 s | 1.6× |
| **Both** | **46.1 min** | **25.1 min** | 1.8× |

While each phase of the new code ran, `feature.db-wal` existed and
`PRAGMA journal_mode` returned `wal`.

**Comparison** (base vs new):

| Check | Result |
|---|---|
| teams / team_members / initiatives / initiative_teams | 11 785 / 39 665 / 11 685 / 11 755 — identical |
| advisorships / persons / researchers | 8 680 / 17 516 / 7 645 — identical |
| initiative↔team links, by name | identical |
| team memberships (team, person, role), by name | identical |
| person names | identical |

## 4. Final file, reset and direct readers

- **Finalize on the replay database**: `{'finalized': True, 'checkpoint': (0, 0,
  0), 'journal_mode': 'delete'}`. The file went from `wal` to `delete`, no
  companion files remained, and a lone copy in a read-only directory compared
  identical to the base database.
- **Reset**: with empty `horizon.db-wal` and `horizon.db-shm` next to
  `horizon.db`, `make db-clean` removed all three.
- **Direct readers**: the same database in rollback mode and in WAL mode gave
  identical results for `run_person_dedup`, `anonymize_backfill_flow` and
  `generate_report`, and identical row counts afterwards. They were called with
  explicit paths: through `app.py`, `consolidate_duplicates` and
  `anonymize_backfill` always open `db/horizon.db`, whatever `DATABASE_URL` says.

## 5. Full local weekly run

`make weekly-flows`, Telegram disabled, log in
`logs/weekly_018_validation.log`. Exit 0, 3 850 s.

| Phase | Spec 017 run (min) | Spec 018 run (min) |
|---|---:|---:|
| sigpesq | 3.5 | 1.6 |
| cnpq | 28.3 | 26.4 (350/350, 1 retry) |
| lattes_download | 2.0 | 1.6 |
| lattes_projects | 21.1 | **7.4** |
| lattes_advisorships | 24.7 | **12.4** |
| extract_project_files | 6.4 | 4.6 |
| enrich_projects | — | 0.1 (exit 0) |
| consolidate_duplicates | 2.6 | 2.6 |
| export_canonical | 3.7 | 3.7 |
| other phases | 4.9 | 3.7 |
| **Total** | **97** | **64** |

Per-curriculum cost: 1.01 s (`lattes_projects`) and 1.68 s
(`lattes_advisorships`), against ~3 s each before. The ratio between the last
and the first 50 curricula is 1.19 and 1.50, the same flat-to-mild growth
measured by specs 015 and 016.

The final line `SQLite finalize: {'finalized': True, 'checkpoint': (0, 0, 0),
'journal_mode': 'delete'}` was logged after the last phase. No
`database is locked` appears in the run.

## 6. The `enrich_projects` `database is locked` failure (US4)

**Reproduced** on a copy of the database from CI run 40002646510's artifact,
with the base code and with the new code: both fail with `database is locked`
on `INSERT INTO source_records`. **WAL does not fix it.**

**Cause** (confirmed by instrumentation in a throwaway copy of the code, and by
a minimal script on SQLAlchemy 2.0.52 / SQLite 3.46 and 2.1.6 / 3.53):
1. The new project "Mapeamento dos dados do ENEM por município do Espírito
   Santo" has the same title as initiative 435, an **Advisorship**.
   `_ingest_new` checks duplicates against Research Project initiatives only,
   while `UNIQUE(initiatives.name)` spans every type, so the insert fails inside
   `_write_row`'s SAVEPOINT.
2. `ROLLBACK TO SAVEPOINT` undoes the row but leaves the SQLite transaction, and
   its write lock, open on the loader's connection.
3. `tracking_recorder` writes through other sessions; the next
   `record_source_record` waits the 5 s busy timeout and fails. The phase aborts.

**Impact**: with pysqlite, each successful SAVEPOINT already commits, so the
rows written before the collision are kept (251 enriched initiatives in the CI
database). The new initiatives after it are lost (17), and the phase is
reported as failed. It does not happen locally because the local inputs produce
no such title pair.

**Two fixes tested on copies of the CI database**: (a) check new titles against
all initiative names; (b) end the open transaction after a failed row. Each
completes the phase (exit 0, 251 enriched, 17 created, 0 errors) with identical
results. Tracked as **TD-020**, for a separate spec.

## 7. Tests

- New: `tests/test_sqlite_settings.py` (listener on a file database, on an
  engine created before installation, in-memory, non-SQLite, idempotent
  installation, failing pragma; finalize success, open connection, no-op cases)
  and `tests/test_weekly_orchestrator_finalize.py` (finalize after every phase,
  also on failure, exit code unchanged, Telegram line only on a real failure).
- `tests/test_weekly_orchestrator.py` now patches the finalize step, so its
  faked weekly runs never touch the real `db/horizon.db`.
- Full suite on Python 3.14 / SQLAlchemy 2.0.52: 494 passed, 6 failed (the
  pre-existing Lattes download, loader mapping, SigPesq adapter and weekly
  workflow tests). The 30 tests of the three files above also pass on Python
  3.12 / SQLAlchemy 2.1.6, the CI combination.
- black, isort and flake8 (`E9,F63,F7,F82`) pass on every changed file.

## 8. Not covered

- **The GitHub Actions run**: not repeated after the change. The runner writes
  to a local disk, so the gain is expected there too, but it is not measured.
- **Standalone commands** (`make sync-cnpq`, `make ingest-lattes-projects`, …)
  leave the file in WAL mode with its companion files; only the weekly runs the
  finalize step. This is documented and harmless.
