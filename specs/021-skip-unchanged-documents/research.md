# Research: Skip Unchanged Source Documents on a Persistent Database

Phase 0 of the plan. Every decision below was checked against the code on
branch `024-skip-unchanged-documents` (spec 020 merged) on 2026-10-28.

## R1. Document units and keys per source

**Decision**: one document state per unit that a phase reads and writes as a
whole, keyed by a source-native key.

| `source_system` | Phase | Unit | `document_key` | Where it is read today |
|---|---|---|---|---|
| `lattes_projects` | `lattes_projects` | one CV JSON | `lattes_id` (last `_` field of the file name) | `_ingest_researcher_file`, `src/flows/lattes/projects.py:120` |
| `lattes_advisorships` | `lattes_advisorships` | one CV JSON | `lattes_id` | `ingest_advisorships_file_task`, `src/flows/lattes/advisorships.py:31` |
| `cnpq_group` | `cnpq` | one group page payload | CNPq group id (16 digits of the mirror URL, `cnpq_payload_key`) | `sync_single_group`, `src/flows/cnpq/groups.py:118` |
| `sigpesq_project` | `sigpesq` | one row of the research projects report | the row's tracking key (SigPesq project code) | `ProjectLoader._process_row`, `src/core/logic/project_loader.py:468` |
| `sigpesq_advisorship` | `sigpesq` | one row of an advisorships report | tracking key (workplan code + row) | same |
| `sigpesq_group` | `sigpesq` | one row of the research groups report | the group's tracking key | `ResearchGroupLoader`, `src/core/logic/research_group_loader.py:167` |
| `sigpesq_pj` | `enrich_projects` | one `PJ_*.json` | normalized project code | `ProjectEnrichmentLoader.run`, `src/core/logic/project_enrichment.py:501` |

The two Lattes phases keep separate states for the same CV. They run as
separate subprocesses, read different sections, and one can fail while the
other succeeds; a shared state would let one phase skip work the other never
did.

The keys are the ones spec 020 already uses for `source_records`
(contracts/tracking-keys.md of spec 020), so no new identity rule is needed.
Measured: 435 CV files, 435 distinct `lattes_id`; 350 distinct CNPq ids.

**Alternatives considered**: one state per CV for both Lattes phases (rejected:
see above); keying SigPesq per report file (rejected: the reports are
re-downloaded whole every run, so a file-level key would always differ and a
changed row could not be told from an unchanged one).

## R2. What the content hash covers

**Decision**: `content_hash = stable_hash(<parsed document>)`, the spec 020
canonical hash (`src/tracking/recorder.py:36`).

- **Lattes**: the whole CV JSON. It holds `informacoes_pessoais.atualizacao_cv`
  (the date the researcher last edited the CV, real source data) and no
  extraction timestamp, so an unchanged CV hashes the same. Sections that no
  phase reads (`bancas`, `eventos`, `estatisticas`) are included; a change
  there reprocesses a CV needlessly but never wrongly.
- **CNPq**: the payload dict returned by `CnpqCrawlerAdapter.get_group_data`,
  the same object already hashed into `source_records.payload_hash`.
- **SigPesq rows**: the row dict, the same object hashed into
  `source_records.payload_hash` today.
- **PJ files**: the parsed JSON.

**To verify during implementation** (task, not a design question): two fetches
of the same unchanged CNPq page give the same hash. If the payload carries a
volatile field, it is dropped before hashing and the field is named in the
report.

**Code changes**: a change to the parsers or loaders that alters what an
unchanged document produces must bump `HORIZON_RULE_VERSION`, which rebuilds
the database once (FR-014). Otherwise unchanged documents would keep the old
output. This is recorded in `docs/flows-and-entrypoints.md` as a rule for
maintainers.

## R3. Dependency fingerprint (FR-005, clarification Q1)

The result of a document also depends on data from other sources, through
four resolutions:

| Resolution | Code | Index it reads | Kind |
|---|---|---|---|
| CV owner → researcher | `resolve_researcher_from_lattes`, `resolve_or_create_researcher` (`src/core/logic/researcher_resolution.py`) | researcher index (`load_researcher_index`) | exact by lattes_id / cnpq_url, then by name |
| Person name → person (team members, students, CNPq members) | `PersonMatcher.match_or_create` (`src/core/logic/person_matcher.py:235`) | person name cache | exact normalized, then fuzzy (`token_sort_ratio`, deterministic tie-break of spec 020) |
| Project or advisorship row → existing initiative | `ProjectLoader._resolve_existing_initiative` (`project_loader.py:729`) | `existing_by_identity`, `existing_by_name`, exact SQL name, `existing_by_norm_name` | exact |
| PJ file → initiative | `match_pj` + `resolve_claims` (`project_enrichment.py:215,257`) | code index, research project names | exact, then a global claim resolution |

**Decision**: every document records its **references**: for each resolution
it made, the kind, the lookup key the code used (lattes_id, normalized name,
identity key, title) and the outcome: the target's **stable key**, plus, for
fuzzy matches, the best score; or "created" / "not found". The stable key is
the base `horizon_id` that the spec 020 rules (`src/core/logic/horizon_identity.py`,
pure functions) give the target's current row, without collision suffix. It
is computed the same way whether or not `assign_horizon_ids` already ran for
the target, and it comes only from source data (constitution rule 2), never
from a database id. The **dependency fingerprint** is `stable_hash` of the
sorted references.

Before skipping a document whose content hash is unchanged, the phase checks
whether any reference could resolve differently now. A reference can only
change outcome if:

1. its target no longer exists or no longer has the same stable key (deleted,
   merged by `consolidate_duplicates`, renamed); or
2. an entity **created or renamed after the document's last processing** now
   matches the lookup key at least as well as the recorded outcome.

Check 1 is a lookup per reference. Check 2 only compares the references
against the **delta**: the persons and initiatives created since the
document's last processing (ids above the maximum id recorded with the
document state, since `eo_lib` ids are autoincrement) plus those with an
`entity_change_logs` update of a name field since then. For the exact kinds
the check is a key comparison. For fuzzy person matching it runs the same
scorer and threshold as `PersonMatcher` against the delta only, so it costs
O(references × delta), not O(references × all persons). A document fails the
check, and is processed again, when any reference fails.

After processing, the new references and fingerprint replace the old ones.

**Cost** (measured 2026-10-28 on the SigPesq step): the set of current target
keys is read once per phase and then only extended with the rows created
after each write (ids above the last seen); it is read again in full only
after a rollback. A key processed earlier in the same run (498 of the 1 202
SigPesq advisorship rows repeat across the yearly report files with identical
content) is skipped without checking its references, which were resolved
minutes before. Before these two rules the check cost about 81 s of a 250 s
profiled SigPesq step; after, the whole per-document bookkeeping costs about
3 s.

**Why not reprocess per phase when a source changed**: SigPesq changes almost
every week, so the whole Lattes skip would be lost (clarification Q1, option B
rejected).

**Why not re-run every resolution read-only**: fuzzy matching every reference
of 435 CVs against ~17 000 persons every week costs minutes, about what the
skip saves, and the read-only paths of the resolvers would duplicate their
create paths.

**Limits that stay**: spec 020 R9.3 showed that fuzzy person resolution in a
fresh run depends on which persons exist at that moment (25 team rows on the
2026-10-24 data differed between a rebuild and a rerun). The incremental
database inherits that order dependence, so the equivalence check (R11)
counts these rows and lists them, as spec 020 did, instead of requiring zero.

**Enrichment** (decided 2026-10-28: left out of this spec): `resolve_claims`
decides between all PJ files at once, and `ProjectEnrichmentLoader.run` keeps
its own per-row SAVEPOINT handling from spec 019, which its comments say must
not be moved. The phase takes about 12 s and already writes nothing on
unchanged inputs, so it keeps running in full; no `sigpesq_pj` document state
is written.

**Writes outside the skipped phases** (found by T028, fixed): on unchanged
inputs three steps still wrote every run — `assign_horizon_ids` rewrote all
`horizon_ids` rows to refresh `assigned_at`; the enrichment logged 277
"update enrichment" change logs with no data change; and 41 parent projects
changed dates or status, because `recalculate_all_parent_statuses` ran at the
end of the SigPesq phase, where a rebuild saw only SigPesq advisorships and the
Lattes phases then overwrote the parents. The first two now write only real
differences; the recalculation runs once after every source phase
(`recalculate_parent_projects`), so a rebuild and an incremental run agree.

## R4. Failed and unreadable documents (FR-008, clarification Q3)

Today a document failure is often logged and swallowed:

- `_ingest_researcher_file` catches every exception and returns (`projects.py:351`);
- each Lattes section (awards, languages, ...) logs a warning and continues
  (`projects.py:330-349`);
- `ProjectLoader.process_records` counts `failed` rows and continues
  (`project_loader.py:301-308`);
- `sync_single_group` returns `success: False` when the payload is empty.

**Decision**: each document's processing returns an **outcome**: `processed`,
`skipped`, or `failed:<reason>`. The state, the references and the item links
are written only for `processed`. Reasons:

| Reason | Detected by |
|---|---|
| `download` | CNPq page missing after retries; a lattes_id of `lattes.list` with no JSON file in `data/lattes_json/` after `lattes_download` |
| `unparsable` | JSON that does not load; empty file |
| `unidentified` | Lattes file name or JSON name `Nome-nao-identificado` (27 local files, e.g. `130_Nome-nao-identificado_1191009329970047.json`; checked on 2026-10-28: all 27 carry zero items, so nothing is lost by not processing them, but the merged "[Nome-nao-identificado]" person of TD-022 is no longer created), or no lattes_id in the file name |
| `total_loss` | a document whose stored state has at least one item link and that now yields zero items (clarification Q3) |
| `partial` | any section or row of the document failed (a warning above, `stats["failed"] > 0`) |

`partial` is a failure too: the items of the failed section are missing from
the new link set, and treating the document as processed would delete them.
A failed document is rolled back as a whole (R5): its stored data, items and
processing state stay exactly as before the attempt; only the failure record
(`last_failure`, `last_failure_at`) is written afterwards (FR-008). It is counted per reason and
processed again on the next run.

The `total_loss` check runs before any delete, from the stored link count, so
it costs nothing extra.

## R5. One transaction per document (FR-006)

**Finding**: the libraries commit inside every write
(`libbase/infrastructure/sql_repository.py:34,62,73`,
`eo_lib/.../postgres_team_repository.py:23,35`), and all their sessions come
from two `PostgresClient` singletons (`eo_lib` and `research_domain`), each a
`scoped_session(sessionmaker(...))` over its own engine
(`.../infrastructure/database/postgres_client.py:37-45`). The ETL's tracking
services do **not** use that scoped session: `TrackingServiceFactory._session`
builds a new `sessionmaker(bind=client._engine)` session per controller
(`src/tracking/service_factory.py:22-30`), i.e. its own pooled connection
(found during implementation, 2026-10-28).

**Decision**: one transaction per document, without editing the libraries.

1. **Shared connection**: at phase start the ETL opens one SQLAlchemy
   `Connection` on the database and replaces the session factory of both
   singletons with `scoped_session(sessionmaker(bind=<that connection>,
   join_transaction_mode="create_savepoint", autoflush=False,
   expire_on_commit=False))`, the same options the libraries use plus the join
   mode. Both clients must share the connection: two connections would block
   each other on SQLite's single write lock (the TD-020 `database is locked`).
   The ETL's own `TrackingServiceFactory._session` (ETL code, so it may change)
   binds to the same connection while a `DocumentTransaction` is active.
2. **Per document**: the shared connection is **always** inside an outer
   transaction while the phase runs, so every session that joins it works on
   savepoints and none ever owns the real transaction; the outer transaction
   is committed (or rolled back) only at document boundaries, and what is
   written between documents (the ingestion run, setup rows) is committed
   when the next document starts. (Found by the in-ETL proof of concept: with
   a transaction opened only per document, a tracking session autobegan the
   connection between documents and the next `begin()` failed.)
   `DocumentSkip.document()` marks the start of a document on the
   connection. Every `commit()` inside the libraries and the ETL then only
   releases a savepoint, and a `rollback()` (for example
   `ProjectLoader._rollback_session` after a failed row, or the tracking
   recorder's `IntegrityError` path) only rolls back to the last savepoint. On
   `processed`, the state, items, references and deletions are written on the
   same connection and the transaction is committed once. On any failure, or
   if the process dies, the transaction is rolled back and nothing of the
   attempt remains. Outside a document the connection has no open
   transaction, and the sessions commit normally (the join mode only applies
   when the connection is already in a transaction).
3. **pysqlite workaround**: the standard `sqlite3` driver issues its own
   `BEGIN`/`COMMIT` and breaks savepoints. The documented SQLAlchemy recipe
   (`isolation_level = None` on connect, `BEGIN` emitted on the engine's
   `begin` event) is applied **only to a dedicated engine** that
   `DocumentTransaction` creates for the shared connection, through
   `sqlite_settings.install_savepoint_support(engine)`. Applying it to every
   engine would change the transaction behaviour of every phase: a read would
   open a snapshot transaction, and a later write from that connection could
   fail with `database is locked` (SQLITE_BUSY_SNAPSHOT) when another
   connection wrote in between — the TD-020 class of failure. The global spec
   018 WAL listener still applies to the dedicated engine.
4. **In-memory caches**: the phases keep indexes of what they wrote
   (`PersonMatcher` name cache, `ProjectLoader.existing_by_*`, the researcher
   index, the team lookup). After a document rollback these may point at rows
   that no longer exist, so the phase reloads them after every rollback.
   Rollbacks are rare: the unreadable CVs are detected before any write.
5. **No raw `sqlite3` writer** may run inside a per-document phase while a
   document transaction is open. Today raw writers only run in their own
   phases (`consolidate_duplicates`, `assign_horizon_ids`,
   `anonymize_backfill`); a test pins this.

**Proof of concept** (2026-10-28, scratchpad, SQLAlchemy 2.0.52, the real
`libbase.GenericSqlRepository`): two library `add()` calls inside an open
document transaction were invisible to another connection; a failed row rolled
back alone and the session kept working; an outer rollback left 0 rows; an
outer commit wrote them. Without the pysqlite workaround the library's
commits were durable at once, so step 3 is required.

**First implementation task**: repeat the proof inside the ETL on one CV
(`lattes_projects`) and one CNPq group, comparing the resulting tables with
today's code. If it fails and cannot be fixed without editing a library, fall
back to writing the state in an ETL transaction after the document's writes
(the earlier design): an interrupted document is then processed again, which
spec 020's fixpoint makes safe, and FR-006 is met only in intent.

**Side effect to measure**: a Lattes phase issues about 180 000 commits for 435
CVs today (spec 018); with one transaction per document it issues about 435.
With WAL and `synchronous=NORMAL` commits are already cheap, so the gain on
processed documents is measured, not assumed.

**Alternatives considered**: keeping the library commits and writing the state
last (the fallback above; leaves half-written documents after a failure until
the next run); editing the libraries to make the commit optional (rejected:
third-party libraries stay unchanged; can be proposed to their maintainer);
writing the entities with ETL SQL instead of the libraries (rejected:
reimplements the libraries).

## R6. Which documents carry each item (FR-011)

Deleting what a changed document dropped needs, for every item, the documents
that carry it. `source_records` + `entity_matches` do not give it: a source
record is written once per (key, payload hash) and never says that a later
run still carried the item, and many item kinds have no entity match
(awards, languages, professional activities, technical productions, team
members, advisorship members, persons).

**Decision**: a new ETL table `source_document_items` holds the current link
set of each processed document: (`source_system`, `document_key`,
`item_type`, `item_ref`). `item_ref` is the row id for tables with an integer
key, and a composite text key for link tables (for example
`initiative_knowledge_areas:<initiative_id>:<area_id>`).

The links are collected while the document is processed, through a context
variable set by the phase around each document (`current_document`, next to
`current_ingestion_run_id` in `src/tracking/context.py`):

- `TrackingRecorder.record_entity_match` adds its target automatically;
- the ingest functions without an entity match add theirs explicitly
  (awards, languages/proficiencies, professional activities, technical
  productions, article authors, education, fellowships);
- `TeamSynchronizer` adds the team and member rows it writes or keeps;
- `PersonMatcher.match_or_create` adds the person it returns.

On `processed`, the new set replaces the stored one. **Removed** = old set −
new set. For each removed link:

1. delete the link row;
2. if no link row of any document still references the item, delete the item
   and its dependent rows.

Team membership already has its own per-document table,
`team_member_contributions` (spec 020): removing a dropped row's
contributions and recomputing the team with the existing union rule
(`TeamSynchronizer._sync_contributions`) covers members.

**Deletion code**: an ETL adapter (`src/adapters/database/document_item_store.py`)
behind a port, with one delete routine per item type that knows the dependent
rows. It uses SQL like `PersonConsolidator` already does
(`src/core/logic/person_consolidator.py:290-683`); it reuses that class's list
of person-referencing tables instead of keeping a second one. Unlike the
consolidator, it runs on the shared connection inside the document
transaction (R5), never on a raw `sqlite3` connection, so a deletion is undone
with the rest of a failed document. No `eo_lib` code changes.

**Merges**: `PersonConsolidator.consolidate_pair` re-points
`team_member_contributions` today (`person_consolidator.py:290-300`). The
links of `source_document_items` are re-pointed from the loser to the winner
too, so a merged person keeps the links of both CVs. Constitution I forbids
`src/core/logic/` from writing the database or importing adapters, so this is
not added to the consolidator's own SQL: the consolidator accepts merge hooks
(`Callable[[connection, winner_id, loser_id], None]`), the
`consolidate_duplicates` flow passes `repoint_person_links` from
`src/adapters/database/document_item_store.py`, and the hook runs on the
consolidator's connection inside its transaction. The references of R3 need
no re-pointing: check 1 sees that the loser's stable key no longer exists.

The consolidator already breaks the same rule: it uses `sqlite3` directly and
imports `record_merge` from `src/adapters/database/horizon_id_store.py`
(spec 020). That is recorded as backlog item TD-025 and is not widened here.

**Persons are carried under two item types**: a researcher's row id is its
person id, and CNPq members are carried as `researcher` (through
`record_entity_match`) while team members and students are carried as
`person` (through `PersonMatcher`). Every "still carried?" check for a person
looks at both types.

**Tracking history** (clarification 2026-10-28, FR-011b): deleting an item
never deletes its rows in `source_records`, `entity_matches`,
`attribute_assertions` or `entity_change_logs`; they stay as history and may
point at a `canonical_entity_id` that no longer exists. Each deleted item gets
one `entity_change_logs` row with `operation = 'delete'` and its last values in
`before_json` (scrubbed like every change log), written in the document
transaction through `tracking_recorder.record_change`.

**Reference tables** (campus, organizations, knowledge areas, types, roles,
languages) are shared vocabulary and are never deleted by this spec, even when
no document references them any more. The equivalence check lists orphan
reference rows separately.

**Bootstrap**: on the first run after this spec no document has a state or
links, so every document is processed, nothing is deleted, and the links are
filled. Deletion starts on the second run.

## R7. Persons (FR-011a, clarification Q2)

**Decision**: a person is an item like any other. It is deleted when no link
of any source references it after a removal, except when it is the owner of a
Lattes CV whose document is in the current Lattes list (active). Deleting a
person uses the consolidator's list of person-referencing tables, so no
dangling row remains. Its `horizon_id` is retired by the next
`assign_horizon_ids` (spec 020 alias rule); if a later document creates the
person again, the retired id becomes current again.

## R8. Listings and disappeared documents (FR-009, FR-010)

| Source | Listing | Listing loaded successfully when | Partial run (never marks inactive) |
|---|---|---|---|
| Lattes (both phases) | `data/lattes_run/lattes.list` (versioned in git) | the file exists and yields at least one id | none today |
| CNPq | the groups with a CNPq URL whose SigPesq group document is active (`get_groups_to_sync`) | the SigPesq groups listing of the **same weekly** was complete: at least one `sigpesq_group` state has `last_seen_at` at or after the start of the current weekly (the orchestrator passes its start time to every phase as `HORIZON_WEEKLY_STARTED_AT`; a standalone `cnpq_sync` run without that variable treats its listing as incomplete and marks nothing inactive) | `campus_name` filter, `limit`/`offset` |
| SigPesq rows | the downloaded report files | each report downloaded and parsed with at least one row | — |
| PJ files | `data/exports/project_sigpesq_files_json/PJ_*.json` | the `extract_project_files` phase finished without error | `HORIZON_PROJECT_FILES_LIMIT` set |

**Decision**: after a phase processed its listing, every active document of
that `source_system` absent from a successfully loaded, complete listing
becomes `inactive` (its `last_seen_at` stays the last date it was seen);
every listed document gets `last_seen_at` = now and becomes `active` again if
it was inactive. A failed or partial listing changes no status.

The CNPq listing comes from the database, not from the portal, so a group
that left the SigPesq report would stay in it forever. Deriving it from the
active SigPesq group documents fixes that: a group whose SigPesq row is
inactive is not fetched and its CNPq document becomes inactive too. Its data
stays (old data is better than none).

When `data/lattes_run/lattes.list` is missing, `download_lattes_flow` builds
the list from the database (`src/flows/lattes/download.py:559-567`). With a
persistent database that list would contain every researcher ever seen, so in
that case no Lattes document is marked inactive (logged).

## R9. Persistence and rebuilds (FR-013–FR-015)

**Decision**:

- `make weekly-flows` depends on a new `db-ensure` target instead of
  `db-reset`. It runs a small script (`db/ensure_db.py`, next to
  `db/create_db.py`; schema only, no ingestion, constitution III) that
  resolves the file from `DATABASE_URL` (`sqlite_path_from_url`, as the
  rule-version guard does) and runs the `db/create_db.py` setup only when that
  file does not exist. `db-init` keeps dropping and creating (it is a reset);
  `db-ensure` never calls it on an existing file. Resolving the path from
  `DATABASE_URL` matters: `db-clean` hardcodes `db/horizon.db`, so a check on
  that path would be wrong for the validation copies.
- `run_weekly` runs the migrations at start (today they run lazily in
  `assign_horizon_ids` and `enrich_projects`), then the existing guard
  `_reset_if_rule_version_changed`. The new tables reach an existing database
  through migrations `0008`–`0011`.
- `make full-refresh` keeps `db-reset` (with `db-save-ids`).
- `HORIZON_RULE_VERSION` stays 1. This spec adds tables and changes no stored
  key or hash, and a database without document states simply processes every
  document once (R6 bootstrap). A rebuild is not needed to introduce it.
- In GitHub Actions the database file is absent at the start of the job, so
  `db-ensure` creates it and the run is a rebuild, as today.

## R10. The new export file (FR-016, FR-017)

**Decision**: `export_canonical` (`src/flows/exports/canonical_data.py:275`)
writes `source_document_states_canonical.json` next to the two spec 020
files, through the same store pattern. Format in
[contracts/source-document-states-export.md](contracts/source-document-states-export.md).
It carries keys, statuses and dates only. `lattes_id`, CNPq ids and SigPesq
codes are already published by other exports; no name, CPF, phone or e-mail.
`src/scripts/export_parquet.py` gets an entry for it with no integer id
column.

`content_hash` and the references are not exported: they are internal
bookkeeping and would change every time the rule version changes.

## R11. How equivalence with a rebuild is measured (SC-003, SC-006)

Numeric ids differ between an incremental database and a rebuild (rows are
created in a different order), and the tracking tables accumulate history in
the incremental one. **Decision** for the comparison script
(`specs/021-skip-unchanged-documents/research-scripts/compare_with_rebuild.py`):

- entities are matched by `horizon_id` (from `horizon_ids`), and every
  foreign key is replaced by the target's `horizon_id` before comparing;
- the tracking tables (`ingestion_runs`, `source_records`, `entity_matches`,
  `attribute_assertions`, `entity_change_logs`) and their exports are left
  out; `source_document_states` is left out (dates);
- documents that are inactive or failed in the incremental database are left
  out, with their items (a rebuild has no data for them by design);
- orphan reference rows (R6) and the person-resolution order differences of
  spec 020 R9.3 are counted and listed, not failed.

## R12. Observability and audit (FR-007, constitution IV)

**Decision**: each phase logs one summary line
`documents: processed=… skipped=… failed=… (download=… unparsable=… unidentified=… total_loss=… partial=…) inactive=… reactivated=… deleted_items=…`,
and writes the same counts, with the failed documents listed by key and
reason, to `data/reports/source_document_states_report.json` (one entry per
phase, replaced each run).

## R13. Expected gain

From the 2026-10-24 baseline, with ~6% of CVs changing per week: the Lattes
phases spend their time in `eo_lib` writes and lookups per CV (TD-016,
TD-021), not in reading JSON. Skipping 94% of CVs should take
`lattes_projects` + `lattes_advisorships` from 19.8 min to about 1–2 min plus
the R3 checks. CNPq still downloads every page (spec D), so its gain is only
the database part. SigPesq (1.6 min) and enrichment (7 s) gain little. The
real numbers are measured in the validation (quickstart §4) and are
references, not blockers.
