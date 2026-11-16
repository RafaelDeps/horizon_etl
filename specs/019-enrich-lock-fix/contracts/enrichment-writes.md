# Contract: Enrichment Writes

No external interface changes. `app.py enrich_projects`, the flow
`enrich_projects_flow` and the statistics dict it logs keep their form and keys.

## `ProjectEnrichmentLoader._ingest_new(unmatched, name_index, rejected_codes=None) -> dict`

| Aspect | Contract |
|---|---|
| Taken names | `name_index` keys **plus** `normalize_text(name)` of every row of `initiatives`, read once at the start of the call. |
| Duplicate | A candidate whose `normalize_text(titulo)` is in the taken names or in `seen_titles` is counted in `skipped_duplicate` and creates nothing. |
| Order of checks | Unchanged: rejected code → not ingestable → duplicate → create. |
| Dry run | Same checks and counters; nothing written. |
| Return | Same keys as today. |

## `ProjectEnrichmentLoader._write_row(fn) -> bool`

| Case | Behaviour |
|---|---|
| `fn` succeeds | Unchanged: runs inside `session.begin_nested()`, returns `True`. |
| `fn` raises | Logs `Row write failed, skipping: <exc>` (unchanged), then commits the session to end the transaction that `ROLLBACK TO SAVEPOINT` left open, and returns `False`. |
| The release commit raises | Logs a WARNING with the error, rolls the session back, returns `False`. Never raises. |

Postcondition after a `False`: the loader's connection holds no SQLite
transaction, so a write from any other connection does not wait.

## `ProjectEnrichmentLoader.run(pj_dir, *, ingest_new=False) -> dict`

Behaviour unchanged. Its docstring and the comment above the write block state
that, on SQLite, each successful row is committed when its savepoint is
released, that a failed row is skipped and the database released, and that an
exception propagating out of `run()` does not undo rows already written.
