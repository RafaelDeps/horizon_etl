# Contract: SQLite Connection Settings and Final File

There is no external API change. `make weekly-flows`, `app.py <phase>` and the
CI workflow keep their current form. The CI artifact keeps the same paths.

## Module `src/adapters/database/sqlite_settings.py`

### `install_sqlite_connection_settings() -> None`

| Aspect | Contract |
|---|---|
| Effect | Registers one listener for the SQLAlchemy `connect` event on the `Engine` class. |
| Idempotence | Calling it more than once registers the listener only once (module flag, like `install_lgpd_session_hooks`). |
| Scope | Every SQLite DBAPI connection opened afterwards in the process, by any engine, including engines created before the call. |
| Per SQLite connection | Runs `PRAGMA journal_mode=WAL` then `PRAGMA synchronous=NORMAL`, using a cursor that is closed afterwards. |
| Non-SQLite connection | Nothing happens (`isinstance(dbapi_connection, sqlite3.Connection)` is false). |
| In-memory database | The journal mode stays `memory`; no error. |
| Errors | A failing PRAGMA is logged as WARNING and the connection is still returned: the old, slower mode is better than no connection. |
| Logging | One DEBUG line per process on first application is enough; no per-connection INFO lines (there are thousands). |

Called from `app.py`, right after `install_lgpd_session_hooks()`.

### `finalize_sqlite_database(database_url: Optional[str]) -> dict`

| Aspect | Contract |
|---|---|
| When | Once, at the end of `run_weekly`, after the last phase subprocess has exited. |
| Input | The `DATABASE_URL` the phases used (`os.getenv("DATABASE_URL")`). |
| No-op cases | URL is `None`, not SQLite, in-memory, or the file does not exist. Returns `{"finalized": False, "reason": …, "skipped": True}`. `skipped` tells "nothing to finalize" apart from a failure. |
| Steps | One plain `sqlite3` connection: `PRAGMA wal_checkpoint(TRUNCATE)`, then `PRAGMA journal_mode=DELETE`, then close. |
| Result | `{"finalized": True, "checkpoint": (busy, log, checkpointed), "journal_mode": "delete"}`. |
| Postcondition | `db/horizon.db` holds every committed row; no `-wal`/`-shm` file remains; the file opens read-only with no companion files. |
| Failure | Any `sqlite3.Error` (for example `database is locked` because a connection is still open) is logged as ERROR with the reason and returned as `{"finalized": False, "reason": …}`. It never raises and never changes the weekly exit code. |

## `run_weekly` (in `src/flows/pipelines/weekly_orchestrator.py`)

| Aspect | Contract |
|---|---|
| Phases | Unchanged: same order, timeouts, criticality and subprocess model. |
| Finalize | After the phase loop and before the summary, call `finalize_sqlite_database(os.getenv("DATABASE_URL"))`. It also runs when phases failed. |
| Summary | One extra INFO line: `SQLite finalize: …` with the result. A failed finalize (not `finalized`, not `skipped`) adds `⚠️ SQLite finalize falhou: <reason>` to the Telegram summary (`_notify(..., finalize=...)`). |
| Exit code | Unchanged rules (critical phases decide). |

The parent process that runs `run_weekly` does not open the database: importing
`app.py` was checked not to create or open the file, so the finalize step is the
only connection at that moment.

## `make db-clean`

| Before | After |
|---|---|
| `rm -f db/horizon.db` | `rm -f db/horizon.db db/horizon.db-wal db/horizon.db-shm` |

Docker targets (`docker-db-reset` and the rest) are unchanged.

## Documentation

- `docs/flows-and-entrypoints.md`: a short section on the SQLite connection
  settings, the finalize step and why the companion files may appear during a
  run.
- `docs/backlog.md`: TD-018 status and measured outcome.
