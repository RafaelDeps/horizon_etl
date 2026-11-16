# Implementation Plan: Skip Unchanged Source Documents on a Persistent Database

**Branch**: `024-skip-unchanged-documents` | **Date**: 2026-10-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/021-skip-unchanged-documents/spec.md`

## Summary

The database stops being reset by `make weekly-flows`, and every per-document
phase skips the documents whose content, rule version and cross-source
resolutions did not change. A changed document is processed by today's code
and the items it no longer carries are deleted, unless another document still
carries them. A failed or unreadable document never deletes anything. The
change is additive: three new ETL tables and one new export file; no existing
table or export changes. The plan has seven parts:

0. **One transaction per document** (research R5): without editing the
   libraries, the session factories of the `eo_lib` and `research_domain`
   clients are bound to one shared connection with
   `join_transaction_mode="create_savepoint"`, plus SQLAlchemy's documented
   pysqlite savepoint workaround in `sqlite_settings.py`. Each document runs in
   one transaction: the libraries' commits become savepoint releases, a failed
   document is rolled back whole. Proved on a scratch database with the real
   `libbase` repository; the first task repeats the proof inside the ETL, and
   the earlier design (state written last, document redone after a crash) is
   the fallback.
1. **Document state and skip helper** (research R1, R2): table
   `source_document_states`, port `IDocumentStateStore` with a SQLite adapter,
   and a pure helper `DocumentSkip` in `src/core/logic/document_skip.py` that
   wraps each document of a phase (contract
   [document-processing.md](contracts/document-processing.md)).
2. **Dependency fingerprint** (R3): each document records the resolutions it
   made (CV owner, person names, initiative identities) with their
   outcomes as source-derived stable keys. Before a skip, the outcomes are
   checked against the targets that changed and against only the persons and
   initiatives created or renamed since the document was processed, using the
   same exact and fuzzy rules as the resolvers.
3. **Failure classification** (R4): every phase reports `processed`,
   `skipped` or `failed:<reason>` per document. Today's swallowed errors
   (section failures, failed rows, empty CNPq payloads) become `partial`, the
   `Nome-nao-identificado` CVs become `unidentified`, and a document that drops
   to zero items becomes `total_loss`. A failed document is rolled back whole
   and the phase reloads its in-memory indexes.
4. **Item links and deletion** (R6, R7): table `source_document_items` holds
   what each document carries; on `processed`, removed links are deleted and an
   item with no link left is deleted with its dependent rows, persons included
   (except owners of an active CV). Deletions use ETL SQL in an adapter, like
   `PersonConsolidator`; merges re-point the links.
5. **Listings and inactive documents** (R8): each phase marks documents absent
   from a complete, successfully loaded listing as inactive and listed ones as
   seen. The CNPq listing becomes the groups whose SigPesq group document is
   active.
6. **Persistence, export, report** (R9, R10, R12): `make weekly-flows` uses a
   new `db-ensure`; the weekly runs migrations and the spec 020 rule-version
   guard first; `export_canonical` writes
   `source_document_states_canonical.json`; each phase writes its counts to
   `data/reports/source_document_states_report.json`.

`HORIZON_RULE_VERSION` stays 1: the first run after this spec processes every
document once (no states yet), deletes nothing and fills the states and
links (R9).

## Technical Context

**Language/Version**: Python 3.12 in CI; 3.14 locally.

**Primary Dependencies**: SQLAlchemy, pysqlite (standard library), Prefect,
loguru, rapidfuzz/thefuzz (already used by `PersonMatcher`), `eo_lib`,
scriptLattes, dgp_cnpq_lib (all unchanged). No new dependency.

**Storage**: SQLite `db/horizon.db`, now kept between local runs. New
ETL-owned tables via `src/db/migrations.py`: `source_document_states` (0008),
`source_document_items` (0009, index 0010) and `source_document_references` (0011)
([data-model.md](data-model.md)). Existing tables unchanged.

**Testing**: pytest on temporary SQLite files with small frozen inputs
(Lattes JSON, SigPesq rows, CNPq payloads, PJ files): skip, change, deletion,
shared items, persons, failures, listings, dependency changes, merges,
interruption, persistence, export ([quickstart.md](quickstart.md) §1). Local
validation on database copies: unchanged inputs, one changed CV and several
rounds compared with a rebuild by a comparison script keyed by `horizon_id`
(R11), and a timed weekly.

**Target Platform**: Linux, locally and on GitHub Actions `ubuntu-latest`.

**Project Type**: Batch ETL (Prefect flows run as weekly phase subprocesses).

**Performance Goals**: `lattes_projects` + `lattes_advisorships` at most about
2 min together on unchanged inputs locally, against 19.8 min on 2026-10-24
(SC-002, a reference, not a blocker). The R3 check must stay a small fraction
of that: it compares each reference with the delta only.

**Constraints**:
- No existing table changes schema; no existing export file changes fields
  (FR-002, FR-016, SC-007).
- `eo_lib`, scriptLattes and dgp_cnpq_lib unchanged; Docker untouched.
- CNPq keeps 4 fetch workers and one writer; SigPesq stays sequential.
- Must work on an empty database (CI today) and on a populated one.
- Validation never writes `db/horizon.db`; Telegram variables empty in replays.

**Scale/Scope**: measured in `source_records` of the local database: 435 CVs
× 2 Lattes phases, 350 CNPq groups, 1 160 SigPesq rows (704 advisorships, 103
projects, 353 groups), so about 2 400 document states (the 277 PJ files of the
enrichment phase are out of this spec, decided 2026-10-28). Item links: of the order of the ~63 000
entities spec 020 counted, plus link rows. 5 phases touched; 9 tracking call sites already exist.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment | Result |
|---|---|---|
| I. Ports & Adapters | `DocumentSkip` and the R3 check are pure logic in `src/core/logic/`; all reads and writes of the new tables go through `src/core/ports/document_state_store.py`, implemented in `src/adapters/database/document_state_store.py` and `document_item_store.py`. The shared connection and session binding (R5) live in an adapter, `src/adapters/database/document_transaction.py`, reached through the same port. Flows wire them. The merge re-pointing of item links is an adapter function injected into `PersonConsolidator` as a hook by the flow, so `src/core/logic/` gains no SQL and no adapter import (R6). Pre-existing, not widened: `person_consolidator.py` already uses `sqlite3` and imports `record_merge` from an adapter (spec 020); recorded as TD-025. | Pass (pre-existing deviation recorded) |
| II. Domain-First Data Modeling | No domain entity is redefined. The three tables are ETL bookkeeping, the same category as `source_records` and `team_member_contributions` (justified below). | Pass (justified) |
| III. Prefect Flow Orchestration | No new flow: the existing phase flows wrap their documents. `db/ensure_db.py` only creates the schema, like `db/create_db.py`. Telegram hooks unchanged. | Pass |
| IV. Audit-Driven Data Quality | Per-phase counts in the log and in `data/reports/source_document_states_report.json`, failed documents listed by key and reason; equivalence with a rebuild checked by a script (R11). | Pass |
| V. LGPD Compliance | The new export holds keys, statuses and dates only; content hashes are taken from the source documents and never exported; deletions remove rows, they never write PII. | Pass |
| Data Integrity & Persistent Incremental Ingestion | Rule 1: persistent database, only changed documents written. Rule 2: hashes and reference outcomes come only from source data (stable keys from the spec 020 rules, never database ids); skipped documents write nothing. Rule 3: `make full-refresh` and the rule-version guard keep rebuilds; equivalence measured (R11). Rule 4: id history untouched. Rule 5: raw inputs untouched (spec D). Rule 6: `last_seen_at`/`processed_at` are published; download dates proper are spec D. Rule 7: no artifact feeds the run. | Pass |
| Quality Gates | `make ci-check` with no new failures (recount the baseline before starting; spec 020 recorded 580 passed). | Pass |

**Post-design re-check**: Pass. FR-006 is met as written: one transaction per
document, the state in the same transaction as the data (R5). If the
in-ETL proof of concept fails, the fallback meets FR-006 only in intent, and
that would be recorded here before implementation continues. One deviation
from the letter of the spec stays, recorded so `/speckit-analyze` and the
review see it:

- **Equivalence with a rebuild (SC-003, SC-006)**: fuzzy person resolution
  depends on which persons exist when it runs (spec 020 R9.3), so a few team
  rows can differ from a rebuild. They are counted and listed, as spec 020
  did for its fixpoint, together with orphan reference rows (R6, R11).

## Project Structure

### Documentation (this feature)

```text
specs/021-skip-unchanged-documents/
├── plan.md               # This file
├── research.md           # Phase 0: decisions R1–R13
├── data-model.md         # Phase 1: new tables, decision flow, transitions
├── quickstart.md         # Phase 1: tests, replay, comparison, weekly, CI
├── contracts/
│   ├── document-processing.md          # port, helper and rules per phase
│   └── source-document-states-export.md # the new export file
├── research-scripts/
│   └── compare_with_rebuild.py         # R11 (written during implementation)
├── checklists/
│   └── requirements.md
└── tasks.md              # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/core/ports/document_state_store.py      # new: IDocumentStateStore
src/core/logic/document_skip.py             # new: DocumentSkip, outcomes, R3 check,
                                            #   total-loss guard, summary
src/adapters/database/document_state_store.py  # new: SQLite states, references, delta,
                                            #   listings, commit_processed
src/adapters/database/document_item_store.py   # new: item links, deletion per item type
src/adapters/database/document_transaction.py  # new: shared connection, binds both library
                                            #   session factories, begin/commit/rollback per document
src/adapters/database/sqlite_settings.py    # + pysqlite savepoint workaround (R5 step 3)
src/tracking/context.py                     # + current_document context variable
src/tracking/recorder.py                    # record_entity_match also carries the item
src/db/migrations.py                        # + 0008–0011
db/ensure_db.py                             # new: create the schema only if the file is missing
Makefile                                    # weekly-flows: db-ensure instead of db-reset
src/flows/pipelines/weekly_orchestrator.py  # migrations at start, before the version guard
src/flows/lattes/projects.py                # wrap each CV; outcomes; carry items
src/flows/lattes/advisorships.py            # wrap each CV; outcomes
src/flows/cnpq/groups.py                    # wrap each group before sync_group; listing from
                                            #   active SigPesq groups; outcomes
src/core/logic/strategies/cnpq_sync.py      # carry member / research line items
src/core/logic/project_loader.py            # per-row skip for SigPesq rows; failed rows → partial;
                                            #   initiative references
src/core/logic/research_group_loader.py     # per-row skip for SigPesq groups
src/core/logic/person_matcher.py            # record person_name references; carry persons
src/core/logic/researcher_resolution.py     # record researcher_owner references
src/core/logic/team_synchronizer.py         # carry team / member items
src/core/logic/person_consolidator.py       # + optional merge_hooks (no new SQL, no adapter import)
src/flows/maintenance/                      # consolidate_duplicates passes repoint_person_links
src/flows/sigpesq/*.py                      # listing completeness per report
src/flows/exports/canonical_data.py         # + source_document_states_canonical.json
src/scripts/export_parquet.py               # + new file, no integer id column
tests/test_document_skip.py                 # new: helper, outcomes, R3 check
tests/test_document_state_store.py          # new: adapter, listings, deletion, merges
tests/test_incremental_lattes.py            # new: skip / change / failures end to end
tests/test_incremental_cnpq_sigpesq.py      # new: CNPq and SigPesq rows
tests/test_ensure_db.py                     # new: db-ensure and version guard
tests/test_export_canonical_data_flow.py    # + the new file
docs/flows-and-entrypoints.md               # weekly no longer resets; when to bump the rule version
docs/reports/2026-XX-XX-skip-unchanged-validation.md  # measurements
```

**Structure Decision**: Single project, existing layout. The new logic gets
its own modules (port, helper, two adapters). Existing modules only change at
the points listed above, mostly by wrapping each document and adding `carry`
calls.

## Complexity Tracking

| Item | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| ETL-only tables `source_document_states`, `source_document_items`, `source_document_references` (Principle II) | They describe provenance and processing of ETL input, the category of `source_records` and `team_member_contributions`, not a domain concept | Columns in domain tables are forbidden (FR-002) and would change `eo_lib`; `source_records`/`entity_matches` cannot say what a document still carries (R6) |
| Dependency references with a delta check (R3) | Clarification Q1 chose a per-document fingerprint; SigPesq changes almost weekly, so a per-phase invalidation would lose the gain | Re-running every resolution read-only costs about what the skip saves and would duplicate the resolvers' create paths |
| Rebinding the libraries' session factories to one shared connection (R5) | FR-006 asks for one unit of work per document; the libraries commit inside every write and cannot be edited | Writing the state last (kept as fallback) leaves half-written documents after a failure until the next run; editing the libraries is not allowed. The rebinding touches a private attribute (`_SessionLocal`) of two singletons, so a test pins it against library upgrades |
| ETL SQL deletion routines per item type | FR-011/FR-011a require deleting dropped items and their dependent rows | `eo_lib` has no cascade for these relations; the ETL already deletes this way in `PersonConsolidator`, and the routine reuses its table list |
