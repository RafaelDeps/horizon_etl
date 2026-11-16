# Contract: how a phase processes a source document

Every per-document phase (`lattes_projects`, `lattes_advisorships`, `cnpq`,
the SigPesq loaders, `enrich_projects`) follows the same protocol through one
port, `src/core/ports/document_state_store.py`, and one helper in
`src/core/logic/document_skip.py`. The phase code keeps its current write
logic; it only wraps each document.

## Port `IDocumentStateStore`

| Method | Does |
|---|---|
| `load(source_system) -> dict[key, DocumentState]` | all states of a source, once per phase |
| `references(source_system, key) -> list[Reference]` | recorded references (R3) |
| `delta(state) -> Delta` | persons and initiatives created or renamed after the state was written |
| `item_count(source_system, key) -> int` | for the total-loss guard |
| `begin_document()` / `commit_document()` / `rollback_document()` | the document transaction on the shared connection (research R5) |
| `commit_processed(source_system, key, outcome)` | inside the open document transaction: replace items and references, delete removed items, write the state; the caller then commits |
| `record_failure(source_system, key, reason)` | after a rollback, in its own short transaction: the failure record `last_failure`, `last_failure_at`; never the processing state (FR-008) |
| `mark_listing(source_system, listed_keys, complete: bool)` | `last_seen_at`, `active`/`inactive` (R8) |

SQLite adapters: `src/adapters/database/document_state_store.py` (states,
references, listings), `src/adapters/database/document_item_store.py` (item
links, deletions), `src/adapters/database/document_transaction.py` (shared
connection; binds the session factories of the `eo_lib` and
`research_domain` clients to it with `join_transaction_mode="create_savepoint"`).

## Helper `DocumentSkip`

```python
skip = DocumentSkip(store, source_system="lattes_projects", rule_version=HORIZON_RULE_VERSION)

for path in files:
    key = lattes_id_of(path)
    with skip.document(key) as doc:          # sets current_document (context var)
        data = read(path)                    # raise DocumentFailed("unparsable")
        doc.check_readable(data)             # raises DocumentFailed("unidentified")
        if doc.unchanged(content=data):      # content hash + rule version + references (R3)
            continue                         # outcome: skipped, no transaction opened
        doc.begin()                          # document transaction (R5)
        process(data)                        # existing code; its commits release savepoints
        doc.require_complete()               # raises DocumentFailed("partial") if a section/row failed
    # on exit: processed -> commit_processed + commit_document;
    #          DocumentFailed or any exception -> rollback_document, phase caches
    #          reloaded, record_failure

skip.finish(listed_keys=all_listed_keys, complete=listing_ok and not partial_run)
skip.log_summary()                           # one line + report entry (R12)
```

## Rules

1. **Order**: documents keep today's deterministic order (sorted file names,
   report order, group list order).
2. **Collection**: while `current_document` is set, `record_entity_match`,
   `PersonMatcher.match_or_create`, `TeamSynchronizer` and the explicit
   `carry(item_type, item_ref)` calls add item links, and the resolvers add
   references. Outside a document they do nothing.
3. **Failures**: every exception or failure count that today is logged and
   swallowed inside a document marks the document `partial`. The document is
   rolled back whole, the phase reloads its in-memory indexes (person cache,
   `existing_by_*`, researcher index, team lookup), and continues with the
   next document, as today.
4. **Total loss**: checked by `commit_processed` before any delete; it rolls
   the document back. The count
   leaves out the document's own subject (the CV owner's researcher row, the
   CNPq group row), which every readable document carries. Zero new items and
   a stored `item_count > 0` → `failed:total_loss`, nothing written. It applies
   to Lattes CVs and CNPq pages; a SigPesq row or PJ file maps to one entity
   and has no such guard.
5. **Skipped documents** write nothing, not even `processed_at`.
   `last_seen_at` comes only from `finish` (listing).
6. **Concurrency**: CNPq fetches with 4 workers, but every write, including
   these, stays in the single writer loop (spec 017). SigPesq stays
   sequential.
7. **Partial runs** (`campus_name`, `limit`, `HORIZON_PROJECT_FILES_LIMIT`,
   missing `lattes.list`, a CNPq run whose SigPesq groups listing was not
   complete in the same weekly — research R8) call `finish(..., complete=False)`.
8. **One writer connection**: while a document transaction is open, no other
   connection may write (SQLite has one write lock). Every library session and
   the ETL's tracking sessions use the shared connection; raw `sqlite3`
   writers stay in their own phases. A test fails if a per-document phase
   opens another writing connection.
9. **Fallback** (only if the in-ETL proof of concept fails, R5): no document
   transaction; `commit_processed` runs in its own ETL transaction after the
   document's writes, and an interrupted document is processed again on the
   next run.
