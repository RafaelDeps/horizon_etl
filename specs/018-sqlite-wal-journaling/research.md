# Research: SQLite WAL Journaling for the ETL Database

All measurements on 2026-10-23, local machine, `db/horizon.db`-style files on an
NVMe ext4 disk unless stated otherwise.

## R1. Where the Lattes time goes

**Finding**: cProfile of both Lattes phases over 435 curricula, started from an
offline pre-Lattes snapshot (see R7):

| | `lattes_projects` (1 599 s profiled) | `lattes_advisorships` (1 721 s profiled) |
|---|---:|---:|
| `sqlite3.Connection.commit` (self time) | 670 s, 183 978 calls | 582 s, 160 977 calls |
| `Session.commit` (cumulative, includes flush) | 1 001 s (63%) | 892 s |
| `sqlite3.Cursor.execute` (self time) | 112 s | 510 s |
| `initiative_service.assign_team` → `get_by_id` (`research_domain`) | — | 416 s (24%) |
| `gc.collect()` per curriculum | 87 s | — |
| `PersonMatcher.match_or_create` | 42 s | 93 s |

Every `libbase` `SqlRepository.add()` runs `session.add(entity)` followed by
`session.commit()`. The calls come from `generic_service.create` (156 711 in
`lattes_projects`), the attribute assertions of the tracking recorder (88 707)
and source records (13 265). A commit costs 670 s / 183 978 = **3.6 ms**, which
matches the 3.3 ms measured for TD-018.

**Decision**: Reduce the cost of each commit, not their number. The number is
decided by `libbase`, which must not change.

## R2. Which setting

**Decision**: `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` on every
SQLite connection.

**Rationale**:
- In the default rollback-journal mode with `synchronous=FULL`, every commit
  writes the journal and the database and forces both to disk.
- In WAL mode with `synchronous=NORMAL`, a commit appends to `horizon.db-wal`
  and returns. The disk is forced only at checkpoints. SQLite documents that this
  combination is consistent: a power loss can roll back the last transactions,
  but cannot corrupt the database.
- The weekly rebuilds the database from scratch, so losing the last transactions
  of an interrupted run has no cost: the run is redone.

**Benchmark** (same snapshot, same machine and disk, phases run with and without
a wrapper that installs the listener):

| Phase | Baseline | WAL + NORMAL |
|---|---:|---:|
| `lattes_projects` | 1 298 s | 521 s |
| `lattes_advisorships` | 1 476 s | 875 s |

The resulting databases were identical (R7).

**Alternatives considered**:
- `synchronous=OFF`: faster still, but a crash or power loss mid-run can corrupt
  the database. Rejected: corruption is not acceptable.
- Keeping the rollback journal and only lowering `synchronous`: smaller gain,
  same durability trade-off. Rejected: WAL+NORMAL is the documented safe pairing.
- Batching commits (fewer, larger transactions): would need changes in `libbase`
  or wrapping its sessions. Rejected: the library must not change, and wrapping
  its sessions would change behaviour on errors.
- Running the database on tmpfs: TD-018 measured a similar gain, but the file
  would not survive the process and the CI layout. Rejected.

## R3. How the setting reaches connections the ETL does not create

**Finding**: horizon_etl creates no engine of its own (no `create_engine` call
in `src/`, `app.py` or `db/`). Engines come from the libraries, notably the
`eo_lib` `PostgresClient` singleton, which reads `DATABASE_URL`.

**Decision**: Listen to the SQLAlchemy `connect` event on the `Engine` class:
`event.listen(Engine, "connect", _apply_sqlite_settings)`. The handler checks
`isinstance(dbapi_connection, sqlite3.Connection)` and does nothing otherwise.

**Verified** (scratch check, SQLAlchemy 2.0.52 / SQLite 3.46.1 locally and
SQLAlchemy 2.1.6 / SQLite 3.53.1 in a Python 3.12 environment like the CI):
- an engine **created before** the listener was registered got
  `journal_mode=wal` and `synchronous=1` (NORMAL) on its first connection;
- an in-memory database (`sqlite://`) reports `journal_mode=memory` and raises
  no error;
- the `-wal` file appears next to the database, as expected.

**Alternatives considered**:
- Passing `connect_args` or an event to each engine: impossible without changing
  the libraries that create them.
- Setting the journal mode once at `db-init`: the journal mode persists in the
  file, but `synchronous` is per connection, and `db/create_db.py` would be one
  more place to keep in sync. Rejected; the listener covers both.

## R4. Where to install it

**Finding**: Every weekly phase that touches the database runs as
`python app.py <phase>` (mode `"app"` in `_PHASES`). The `"module"` phases
(`src.scripts.fetch_openalex_citations`, `rank_docentes_impact`,
`analyze_maturity`, `analyze_venues`, `generate_impacto_dashboard`,
`generate_ppp_edital_report`) do not open the database. `app.py` already
installs a process-wide SQLAlchemy hook, `install_lgpd_session_hooks()`, after
its imports.

**Decision**: Call `install_sqlite_connection_settings()` in `app.py`, next to
`install_lgpd_session_hooks()`. Make it idempotent with a module flag, like the
LGPD hook.

**Rationale**: Engines connect lazily, on the first query, so installing the
listener after the imports is still before the first connection. R3 showed that
even an engine created earlier gets the setting. The replay (quickstart §3)
checks that every DB-writing phase actually ran in WAL mode.

**Alternatives considered**:
- `src/__init__.py`: would also affect tests and every script that imports
  `src`, which is broader than needed and surprising. Rejected.
- `sitecustomize` or an environment variable: not portable between the local
  machine and the CI. Rejected.

## R5. Making the final file self-contained

**Finding** (same scratch check, both SQLAlchemy versions):
- While any other connection to the file is open, even an idle one in a
  SQLAlchemy pool, `PRAGMA journal_mode=DELETE` fails with
  `database is locked`.
- With no other connection open, `PRAGMA wal_checkpoint(TRUNCATE)` followed by
  `PRAGMA journal_mode=DELETE` returns `delete`, removes the `-wal` and `-shm`
  files, and a copy of the main file alone opens read-only from a read-only
  directory with all its rows.

**Decision**: `finalize_sqlite_database(database_url)` runs in the weekly
orchestrator (`run_weekly`) after the last phase subprocess has exited, when no
process holds the file. It opens one plain `sqlite3` connection, runs the
checkpoint and switches the journal back to `DELETE`. It is a no-op for
non-SQLite URLs, in-memory databases and missing files. Failures are logged as
ERROR and reported in the run summary, but do not change the exit code: the
exports, the real deliverable, are already written by then.

**Rationale**: Returning the file to the rollback journal means consumers of
the CI artifact need nothing special: no companion files and no write access to
the directory. The next run resets the database anyway, and the first phase
switches it to WAL again.

**Alternatives considered**:
- Only `wal_checkpoint(TRUNCATE)`: moves the data into the main file, but the
  header still says WAL, and some readers need to create `-shm` next to the file
  (fails on read-only locations). Rejected.
- Finalizing at the end of every phase: a phase cannot know whether another
  connection is open in its own process (library singletons), and SQLite
  already checkpoints when the last connection closes cleanly. Rejected as
  unnecessary churn.
- Uploading the `-wal` file with the artifact: puts the burden on every
  consumer. Rejected.

## R6. The `enrich_projects` `database is locked` failure

**Finding** (CI runs 39009721014 and 40002646510): the traceback ends in
`ProjectEnrichment._create_initiative` → `_record_tracking` →
`tracking_recorder.record_source_record` → `source_record_service` →
`database is locked` on an `INSERT INTO source_records`.

Reading the code:
- `ProjectEnrichment.run` keeps one long write transaction open in its own
  session (`self._session`): the `UPDATE initiatives …` rows are written in
  SAVEPOINTs and committed only at the very end.
- `tracking_recorder` writes through the repositories of its own controllers,
  which hold a **different** session and therefore a different connection.
- SQLite allows one writer at a time in **both** journal modes. The second
  writer waits for the default busy timeout (5 s) and then fails.

**Expectation**: WAL will **not** fix this failure. WAL lets readers proceed
while a writer works, but it does not allow two writers. The failure is a
two-sessions-in-one-process problem.

**Decision**: Treat User Story 4 as an investigation. Reproduce the failure
locally with the conditions of the CI runs (quickstart §5), run it with and
without WAL, and record in the validation report whether it changes and which
connection holds the lock. A fix, if needed, is a separate spec.

**Open point**: the same code completes locally (spec 017 run: "Enrichment
complete (applied, ingest_new=True)"). The difference between the local and the
CI inputs that triggers the second writer still has to be found during the
investigation.

## R7. Validation method

**Decision**: Controlled replay, as in specs 015–017, with no portal access:
1. Build a pre-Lattes snapshot offline: `db/create_db.py`; SigPesq persistence
   (`persist_research_groups`, `persist_projects`, `persist_advisorships`) from
   the local Excel reports in `data/raw/sigpesq/`; `sync_cnpq_groups_flow` with
   `CnpqCrawlerAdapter.get_group_data` patched to return the 350
   `cnpq_group_payload` source records of the last local run. This was done on
   2026-10-23 and gave 350/350 groups.
2. Copy the snapshot twice. Run `ingest_lattes_projects` and
   `lattes_advisorships` on one copy with the old code and on the other with the
   new code, both on disk.
3. Compare: counts of `teams`, `team_members`, `initiatives`,
   `initiative_teams`, `advisorships`, `persons`, `researchers`; initiative↔team
   links, team memberships and person names by name.

The 2026-10-23 benchmark already ran this comparison with a wrapper in place of
the new code: all identical.

## R8. Effect in the CI

**Expectation**: The GitHub runner writes to a local disk, so commits are also
forced there; the gain should appear. With today's 126 CI curricula the two
phases take ~5 min, so the absolute gain in CI is small now. It grows with the
number of curricula: ~6.3 s → ~3.2 s per curriculum in the two phases.
