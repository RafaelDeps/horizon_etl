# Data Model: SQLite WAL Journaling for the ETL Database

No table, column or export changes. This feature changes how the database file
is written on disk. The "entities" are the files and their journal states.

## Files

| File | Exists when | Contents |
|---|---|---|
| `db/horizon.db` | Always, after `make db-init` | The database. After `finalize_sqlite_database`, it holds every row on its own. |
| `db/horizon.db-wal` | While the file is in WAL mode and has changes not yet checkpointed | Committed transactions not yet copied into the main file. |
| `db/horizon.db-shm` | While the file is in WAL mode and a connection is or was open | Shared-memory index of the WAL file. No data of its own. |

Both companion files are already ignored by git (`.gitignore`: `db/*.db-*`).

## Journal states of `db/horizon.db` during a weekly run

```text
make db-clean        → no files (db/horizon.db, -wal, -shm all removed)
make db-init         → horizon.db, journal_mode = delete
first DB-writing phase
  (first connection)  → journal_mode = wal  (persists in the file header)
                        -wal / -shm appear; every connection: synchronous = NORMAL
… every later phase   → stays wal; each new connection sets synchronous = NORMAL
phase killed mid-run  → wal recovery on the next open; committed work kept
run_weekly ends
  finalize_sqlite_database
    wal_checkpoint(TRUNCATE) → all committed rows copied into horizon.db
    journal_mode = DELETE    → -wal and -shm removed
                     → horizon.db alone, journal_mode = delete, complete
CI upload            → db/horizon.db (complete)
```

## Validation rules (from the spec)

- **FR-001/FR-004**: every new connection to a SQLite file gets
  `journal_mode=wal` and `synchronous=1` (NORMAL); a non-SQLite connection is
  left untouched; an in-memory database stays `memory` without error.
- **FR-005**: after the replay, the old and new databases have equal counts in
  `teams`, `team_members`, `initiatives`, `initiative_teams`, `advisorships`,
  `persons`, `researchers`, and equal by-name rows for initiative↔team links,
  team memberships and person names.
- **FR-006**: after `run_weekly`, `PRAGMA journal_mode` on `db/horizon.db`
  returns `delete`, no `-wal`/`-shm` file exists, and a copy of the main file
  alone opens read-only with the same row counts.
- **FR-007**: after `make db-clean`, none of the three files exists.

## Pre-Lattes snapshot (validation input)

Built offline for the replay (research R7):

| Table | Rows (2026-10-23 snapshot) |
|---|---:|
| persons | 7 184 |
| researchers | 6 685 |
| teams | 1 158 |
| team_members | 11 469 |
| initiatives | 809 |
| advisorships | 590 |
