# Feature Specification: Skip Unchanged Source Documents on a Persistent Database

**Feature Branch**: `024-skip-unchanged-documents`

**Created**: 2026-10-28

**Status**: Draft

**Input**: User description: "Skip unchanged source documents on a persistent database, so a weekly run only processes what is new or changed."

## Context

The maintainer and their manager decided on 2026-10-26 that `db/horizon.db`
persists between runs and that a run only writes what is new or changed,
detected by comparing content hashes (constitution 2.0.0, "Data Integrity &
Persistent Incremental Ingestion"). This is the second of four specs (see
`PLANO_HASH_IDEMPOTENTE.md` at the repository root, a personal planning note):

- **Spec 020 (done)** gave every entity a permanent `horizon_id`, built every
  tracking key from source-native data and hashed a canonical form of each
  payload. Processing identical inputs twice on a populated database already
  writes nothing (fixpoint), but every document is still read and compared
  item by item.
- **This spec** keeps the database between local runs and skips every source
  document whose content did not change.
- **The next spec** restores the database between GitHub Actions runs.
- **The last spec** downloads only new documents plus a rotating share.

### What was measured

- In the 2026-10-24 local weekly, `lattes_projects` took 7.4 min and
  `lattes_advisorships` 12.4 min, re-processing all 435 CVs, although about 6%
  of curricula change per week (17% per month). CNPq re-syncs all ~350 group
  pages on each run.
- `make weekly-flows` always runs `db-reset` (the Makefile target depends on
  it), and `db/create_db.py` drops every table.
- Spec 020 already records the key/hash/id rule version in the database
  (`HORIZON_RULE_VERSION` in `src/core/logic/horizon_identity.py`) and
  rebuilds once when it differs (`rule_version_requires_reset` in
  `src/flows/maintenance/horizon_ids.py`, called by
  `_reset_if_rule_version_changed` in `src/flows/pipelines/weekly_orchestrator.py`).
  Its docstring already names this spec as the guard of the persistent
  database.
- Documents have collision-free source keys: 435 CVs with 435 distinct
  `lattes_id`; 350 CNPq group pages with 350 distinct CNPq group ids; SigPesq
  project and workplan codes.
- The list of CNPq groups to sync comes from the research groups that carry a
  CNPq URL (`get_groups_to_sync` in `src/flows/cnpq/groups.py`), which come
  from the SigPesq groups report. The list of CVs comes from the Lattes list
  (`data/lattes_run/lattes.list` locally).
- scriptLattes sometimes cannot read a CV and writes it with the name
  "[Nome-nao-identificado]" and no items (27 of 435 locally, TD-022). Between
  two CI runs on 2026-10-28, about 20 CVs became unreadable this way and their
  3 682 horizon_ids were retired. Such a CV looks like a CV whose author
  removed every item.
- The GitHub Actions database still starts empty on every run; restoring it is
  the next spec. Until then the skip saves time only locally, and a CI run
  behaves as a rebuild.

## Clarifications

### Session 2026-10-28

- Q: How is a document reprocessed when data from another source that it uses changed (person matching, links to SigPesq initiatives)? → A: Per-document dependency fingerprint: the skip decision covers the document's own content plus the data from other sources it actually uses; only the documents affected by a change are reprocessed.
- Q: What happens to a person who existed only because of an item removed from a document (a team member, student or co-author with no CV of their own)? → A: Same rule as items: the person is deleted when no document (CV, CNPq page, SigPesq row) references them any more, and their horizon_id is retired; a person with their own CV is never deleted this way.
- Q: Is a readable document that suddenly carries no items at all trusted (its items deleted) or treated as a failure? → A: Total-loss guard: a document that had items before and now arrives readable but with zero items counts as a failed document (FR-008); partial losses are normal changes.
- Q: Does the project enrichment phase (PJ files) also skip unchanged documents? → A: No. It stays as it is: it already writes nothing on unchanged inputs, takes about 12 s, and its per-row SAVEPOINT handling from spec 019 must not be moved.
- Q: When an item is deleted, does its tracking history (source records, entity matches, attribute assertions, change logs) go with it? → A: No. It stays as history, even though it then points at an entity id that no longer exists.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A weekly run with no source change finishes fast and writes nothing (Priority: P1)

The maintainer runs the weekly on a database kept from the previous run. No
CV, group page, SigPesq report or project file changed. Every document is
recognized as unchanged and skipped, so the per-document phases finish in
seconds and the database is left exactly as it was.

**Why this priority**: it is the gain this spec exists for (about 20 min of
Lattes processing every week) and the base the other stories build on.

**Independent Test**: on a copy of a populated database, run the weekly twice
with the same frozen inputs and compare the second run's phase times and the
database before and after it.

**Acceptance Scenarios**:

1. **Given** a populated database and inputs identical to those of its last
   run, **When** the weekly runs, **Then** every Lattes CV, CNPq group page,
   SigPesq row is reported as skipped and no row of any
   existing table is inserted, updated or deleted.
2. **Given** the same run, **When** it ends, **Then** consolidation, exports,
   marts and reports still ran in full and `exports_canonical` is identical to
   that of the previous run, apart from generation timestamps.
3. **Given** the same run, **When** the per-phase times are compared with the
   2026-10-24 baseline, **Then** `lattes_projects` plus `lattes_advisorships`
   take a small fraction of the 19.8 min they took then.

---

### User Story 2 - A changed document is reprocessed alone and the result equals a rebuild (Priority: P1)

One researcher added an article and removed another from their CV. Only that
CV is processed again. The new article appears, the removed one disappears
(or only loses its link to this CV when a co-author still lists it), and the
database matches what a rebuild from scratch on the same inputs would give.

**Why this priority**: skipping is only safe if the incremental result is the
same as a rebuild; otherwise the database drifts away from its sources.

**Independent Test**: from a populated database, change one CV in the frozen
inputs, run the weekly incrementally on one copy and from scratch on another,
and compare entities and `exports_canonical`.

**Acceptance Scenarios**:

1. **Given** a populated database and one changed CV, **When** the weekly
   runs, **Then** only that CV is processed by the Lattes phases and every
   other document is skipped.
2. **Given** that the changed CV dropped an article no other CV lists, **When**
   the run ends, **Then** the article row and its links are gone and its
   horizon_id is retired in the alias file.
3. **Given** that the changed CV dropped an article a co-author's CV still
   lists, **When** the run ends, **Then** the article stays and only its link
   to the changed CV's researcher is removed.
4. **Given** the incremental database and a rebuild from scratch on the same
   inputs, **When** both are compared, **Then** they have the same entities
   (by horizon_id) and the same `exports_canonical` files.

---

### User Story 3 - An unreadable or failed document never erases data (Priority: P1)

The Lattes portal returns an unreadable CV, a CNPq page fails to download, or
a file comes back empty. The ETL treats it as a failed download: the data
stored from the last good read stays, the document's state does not change,
and the run reports how many documents failed.

**Why this priority**: with a persistent database, wrongly treating a failure
as "the author removed everything" would delete real data, and nothing would
bring it back until the document is read again. This happened to about 20 CVs
between two CI runs on 2026-10-28.

**Independent Test**: from a populated database, replace one CV with an
unreadable one ("[Nome-nao-identificado]", no items) and make one CNPq page
fail, then run the weekly and compare the affected entities before and after.

**Acceptance Scenarios**:

1. **Given** a populated database and a CV that comes back without an
   identified name or without its lattes_id, **When** the weekly runs,
   **Then** none of that researcher's items is deleted, the stored hash and
   status of the CV are unchanged, and the run log counts it as a failed
   document.
2. **Given** a CV that had items in the previous run and now comes back with
   its name and lattes_id but zero items, **When** the weekly runs, **Then**
   it is treated as a failed document: nothing is deleted, its state is
   unchanged and the log counts it under the total-loss guard.
3. **Given** a CNPq group page whose download fails, **When** the weekly runs,
   **Then** the group, its members and research lines keep their stored data
   and the group stays active.
4. **Given** a document that failed in one run and reads correctly in the next,
   **When** the next run processes it, **Then** it is compared with its last
   good state and processed normally.

---

### User Story 4 - A document gone from its source stays visible as inactive (Priority: P2)

A research group leaves the SigPesq report, or a researcher leaves the Lattes
list. Its data stays in the database and in the exports, and a new export file
tells consumers which documents are no longer in their source and since when.

**Why this priority**: old data is better than none (decided 2026-10-26), but
consumers must be able to tell current data from data no longer confirmed by
its source.

**Independent Test**: from a populated database, remove one group from the
SigPesq groups report and one id from the Lattes list, run the weekly, and
read the new export file.

**Acceptance Scenarios**:

1. **Given** a group absent from a successfully loaded SigPesq groups report,
   **When** the weekly runs, **Then** the group's document is marked inactive
   with the date it was last seen, and the group and its data stay in the
   database and the existing exports.
2. **Given** a source listing that failed to load (download error, empty
   report), **When** the weekly runs, **Then** no document of that source is
   marked inactive.
3. **Given** an inactive document that reappears in its source, **When** the
   weekly runs, **Then** it becomes active again and is processed if its
   content changed.
4. **Given** any run, **When** `exports_canonical.zip` is produced, **Then** it
   contains `source_document_states_canonical.json` with the status and dates
   of every document, and no existing export file changed its fields.

---

### User Story 5 - The database persists by default and rebuilds only when it must (Priority: P2)

`make weekly-flows` keeps the database between runs. It rebuilds only when the
database is missing or was built under other rules, and `make full-refresh`
still rebuilds on demand.

**Why this priority**: without it the skip never has a previous state to
compare with.

**Independent Test**: run `make weekly-flows` twice on a copy of the database
and confirm the second run did not reset it; change the recorded rule version
and confirm the next run rebuilds once.

**Acceptance Scenarios**:

1. **Given** an existing database at the code's rule version, **When**
   `make weekly-flows` runs, **Then** the database is not reset.
2. **Given** no database, or one whose recorded rule version differs from the
   code's, **When** the weekly runs, **Then** it is rebuilt once from scratch,
   keeping the horizon_id history as `db-reset` does today.
3. **Given** any database, **When** `make full-refresh` runs, **Then** it is
   rebuilt from scratch.
4. **Given** a GitHub Actions run (empty database), **When** the weekly runs,
   **Then** it processes every document and produces the same exports as
   today, plus the new export file.

---

### Edge Cases

- **Interrupted run**: a document whose processing failed or was cut short has
  no new state, so the next run processes it again. A phase that crashed half
  way leaves no document marked as processed that was not fully written.
- **Item listed twice in the same CV**: kept once, as spec 020 decided; the
  document hash is computed on the parsed content, so the duplicate does not
  make the CV look changed.
- **Dependencies between sources**: some processing of a document depends on
  data from other sources (for example matching the persons of a CV or a CNPq
  page to researchers already in the database, or linking Lattes advisorships
  to SigPesq initiatives). A document whose own content is unchanged must
  still be processed again when an input that changes its result changed, so
  that the incremental result keeps matching a rebuild. The plan must list
  these inputs for each phase; the document's dependency fingerprint (FR-005)
  covers exactly them. Example: a new SigPesq initiative that matches an
  advisorship of an unchanged CV makes that CV, and only that CV, be processed
  again.
- **Partial runs**: a run limited to one campus, to a number of groups or
  files, or to a subset of CVs never marks a document outside that subset as
  inactive.
- **Merged persons**: when consolidation merges two persons, the CVs of both
  keep their own document state; skipping either CV must not undo or repeat
  the merge.
- **Rule change**: a change to the document hash, the item keys or the skip
  rules bumps the rule version, so the next run rebuilds instead of comparing
  hashes computed under different rules.
- **First run after this spec**: the existing database has no document states
  yet, so every document is processed once and its state recorded; no rebuild
  is needed for that.
- **Reappearing document with new content**: it becomes active and is processed
  as a changed document, including deletion of items it no longer carries.
- **Person left without references**: a team member, student or co-author who
  existed only through an item a changed CV dropped is deleted with that item,
  and their horizon_id is retired; if a later document mentions them again,
  the retired id becomes current again (spec 020 alias rule).
- **Inactive document data**: an inactive document's items are never deleted
  because of its absence; only a successful read of the document can remove
  its items.

## Requirements *(mandatory)*

### Functional Requirements

**Document state**

- **FR-001**: The system MUST keep, for every source document, a state with its
  source system, a source-native document key (lattes_id, CNPq group id,
  SigPesq project or workplan code), the canonical hash of
  its parsed content, its dependency fingerprint (FR-005), the rule version, the run that last processed it, when it
  was processed, when it was last seen in its source, and whether it is active.
  The pair source system + document key MUST be unique. The key MUST never be
  an internal database id.
- **FR-002**: The document state MUST live in a new ETL-owned table created by
  the ETL's migrations; no column, type or index of an existing table changes.
- **FR-003**: The document hash MUST be computed on the canonical parsed
  content (the spec 020 canonical form), so that formatting, key order or
  duplicate entries that do not change the stored data do not change the hash.

**Skipping**

- **FR-004**: The Lattes projects and advisorships phases, the CNPq group sync
  (before the group, member and knowledge area sync) and the SigPesq loaders
  MUST compare each document's hash with its stored
  state and skip the document when they are equal and none of the inputs listed
  under FR-005 changed.
- **FR-005**: For every phase, the inputs from other documents or sources that
  change how a document is processed MUST be identified. Each document MUST
  carry a dependency fingerprint: a canonical hash of the data from other
  sources that its processing actually used (for example the persons its names
  were matched to, the initiatives its advisorships were linked to). The
  document MUST be processed again when its own content hash or its dependency
  fingerprint changed; a change in another source that the document did not use
  MUST NOT cause it to be processed again. Reprocessing every document of a
  phase whenever an upstream source changed is not acceptable, since SigPesq
  changes almost every week.
- **FR-006**: A document's state MUST be written only after the document was
  fully processed without error, in the same unit of work as its data, so that
  an interrupted or failed document is processed again on the next run.
- **FR-007**: Each run MUST log, per phase, how many documents were processed,
  skipped, failed, newly inactive and reactivated.

**Failures**

- **FR-008**: A failed or unreadable document MUST be treated as a failed
  download, never as a content change. This covers a download error, an empty
  or unparsable file, and a Lattes CV without an identified name
  ("[Nome-nao-identificado]") or without its lattes_id. It also covers the
  total-loss guard: a document whose stored state shows it carried items and
  that now arrives readable but with zero items. A document that loses only
  part of its items is a normal change (FR-011). For such a document
  the system MUST keep its stored data and its processing state untouched:
  no deletion, no new content hash or dependency fingerprint, no change to its
  item links, no inactive mark. Only the failure itself (its reason and time)
  is recorded, so that it can be counted and reported.

**Disappeared documents and items**

- **FR-009**: A document absent from its source MUST be marked inactive, with
  the date it was last seen, only when the source listing was loaded
  successfully and the run covered that document's whole source (no campus,
  limit or subset filter excluded it). Its data MUST stay in the database and
  in the existing exports.
- **FR-010**: An inactive document that appears again in its source MUST
  become active again.
- **FR-011**: An item that disappears from a changed, successfully read
  document MUST be deleted. An item carried by several documents MUST only lose
  its link to the document it left, and its row MUST be deleted only when no
  document carries it any more. The system MUST therefore know which documents
  carry each item.
- **FR-011a**: Persons follow the same rule: a person MUST be deleted when no
  document (Lattes CV, CNPq group page, SigPesq row) references them any more
  after a successful read of the document that dropped them. A person who has
  their own Lattes CV in the source listing MUST never be deleted this way,
  even when no other document references them.
- **FR-011b**: Deleting an item MUST NOT delete its tracking history (source
  records, entity matches, attribute assertions, change logs): it stays as
  history and may point at an entity id that no longer exists. The deletion
  itself is recorded as a `delete` change log entry.
- **FR-012**: An entity deleted under FR-011 or FR-011a MUST have its horizon_id retired
  by the existing horizon_id assignment step; no horizon_id is ever reused.

**Persistence and rebuilds**

- **FR-013**: `make weekly-flows` MUST no longer reset the database. The
  database MUST be rebuilt only when it is missing or its recorded rule version
  differs from the code's, through the existing spec 020 guard.
- **FR-014**: There MUST be no separate hash version: any change to the document
  hash, item keys or skip rules MUST bump `HORIZON_RULE_VERSION`, which forces
  one rebuild.
- **FR-015**: `make full-refresh` MUST keep rebuilding from scratch. Every
  rebuild MUST keep the horizon_id history as `db-reset` does today.

**Exports**

- **FR-016**: `exports_canonical.zip` MUST contain a new file,
  `source_document_states_canonical.json`, with source system, document key,
  status (active/inactive), last seen date and processed date of every
  document. No existing export file changes its fields.
- **FR-017**: The new export MUST contain no personal data beyond what other
  exports already publish (lattes_id and source codes are public identifiers);
  never CPF, phone or e-mail.

**Unchanged behavior**

- **FR-018**: Consolidation, exports, marts and reports MUST keep running in
  full on every run.
- **FR-019**: CNPq MUST keep 4 workers and SigPesq MUST stay sequential.
  Third-party libraries (scriptLattes, dgp_cnpq_lib, eo_lib) stay unchanged.
  Docker is not touched.
- **FR-020**: The feature MUST work locally and in GitHub Actions. In GitHub
  Actions, where the database starts empty, a run MUST give the same results
  as today plus the new export file, apart from the unreadable-CV difference
  stated in SC-008.

**Validation**

- **FR-021**: Automated tests MUST cover:
  - unchanged inputs skip every document and write nothing;
  - one changed CV is the only document processed and yields the same
    entities and `exports_canonical` as a rebuild from scratch;
  - an unreadable CV, and a readable CV that lost every item, delete nothing;
  - a new SigPesq initiative that matches an unchanged CV makes only that CV
    be processed again (dependency fingerprint);
  - a person referenced only by a dropped item is deleted and their
    horizon_id retired, while a person with their own CV is kept;
  - a document missing from a successful listing becomes inactive, and a
    failed listing marks nothing;
  - several incremental runs over changing inputs yield the same
    `exports_canonical` as a rebuild from scratch on the last inputs, for the
    documents still active and readable.
- **FR-022**: Before merging, the feature MUST be validated locally on copies
  of the database (never writing `db/horizon.db`, Telegram variables empty),
  comparing an incremental run with a rebuild on the same frozen inputs and
  measuring each phase against the 2026-10-24 baseline.

### Key Entities

- **Source document**: one unit read from a source and processed as a whole: a
  Lattes CV (key: lattes_id), a CNPq group page (key: CNPq group id), a SigPesq
  report row (key: project or workplan code). It carries items. (Project
  enrichment files are out of this spec, clarification 2026-10-28.)
- **Document state**: the last known state of a source document: content hash,
  dependency fingerprint (hash of the data from other sources it used), rule
  version, last processing run and date, last seen date, active or
  inactive. One per source system + document key.
- **Item**: an entity written from a document (article, project, advisorship,
  education, award, team membership, research line, ...). An item can be
  carried by several documents; it is deleted only when none carries it.
- **Source listing**: the list that says which documents exist in a source (the
  Lattes list, the SigPesq reports, the groups with a CNPq URL). Only a listing
  loaded successfully and in full can mark a document inactive.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On unchanged inputs and a populated database, 100% of documents
  are skipped and zero rows of existing tables are inserted, updated or
  deleted, apart from the one `ingestion_runs` row that each phase opens for
  its run; in the new tables only the documents' last-seen dates change.
- **SC-002**: On unchanged inputs, `lattes_projects` plus `lattes_advisorships`
  take at most 2 min locally, against 19.8 min on 2026-10-24 (a reference
  target, not a blocker).
- **SC-003**: With one changed CV, exactly one CV is processed by the Lattes
  phases, and the entities and `exports_canonical` equal those of a rebuild
  from scratch on the same inputs, compared as defined in "How equivalence is
  measured" below.
- **SC-004**: An unreadable CV, a readable CV that lost every item, or a failed
  CNPq page leads to zero deleted rows and no change to the document's content
  hash, dependency fingerprint, item links or status (only its failure reason
  and time are recorded).
- **SC-005**: A failed source listing marks zero documents inactive; a
  successful listing marks exactly the absent documents inactive.
- **SC-006**: After at least three incremental runs over changing inputs,
  `exports_canonical` equals that of a rebuild from scratch on the last inputs
  for every active, readable document, compared as defined in "How
  equivalence is measured" below.

**How equivalence is measured** (SC-003, SC-006, FR-021): numeric ids differ
between an incremental database and a rebuild, because rows are created in a
different order, so entities are matched by `horizon_id` and every reference
to another entity is compared through the target's `horizon_id`. Left out:
generation timestamps; the tracking tables and their exports (ingestion runs,
source records, entity matches, attribute assertions, change logs), which keep
history in a persistent database by design; the new state tables and file; the
items of inactive and failed documents. Two known differences are counted and
listed instead of failing the comparison: team rows that differ only because
fuzzy person resolution depends on which persons already exist (spec 020,
research R9.3), and reference rows (campus, organization, knowledge area,
types, roles, languages) that no document uses any more and are kept.
- **SC-007**: No existing table changes its schema and no existing export file
  changes its fields; the only new export file is
  `source_document_states_canonical.json`.
- **SC-008**: A GitHub Actions weekly run on an empty database completes with
  the same results as before this spec, plus the new export file, except for
  the expected difference of the unreadable CVs (see Assumptions): the single
  "[Nome-nao-identificado]" person they produce today is no longer created.

## Assumptions

- Spec 020 is merged into this branch: horizon_ids, aliases, source-native
  tracking keys, the canonical hash and the rule version guard are available.
- Documents are still downloaded in full every run (scriptLattes regenerates
  the Lattes JSONs from `cache/`, CNPq pages are fetched again). Downloading
  only what is missing, with a rotation, is the last spec; this spec only skips
  processing.
- Restoring the database between GitHub Actions runs is the next spec; until
  then the gain is local only.
- Introducing this spec does not by itself require a rebuild: a database
  without document states processes every document once and records them. The
  rule version is bumped only if this spec changes item keys or hashes already
  stored.
- The fix of the 27 unnamed CVs (TD-022) is out of scope; this spec only makes
  sure such CVs never erase data. Checked on 2026-10-28: all 27 local files
  named "Nome-nao-identificado" carry zero items, so treating them as failed
  loses no item. The only visible change is that the one merged
  "[Nome-nao-identificado]" person they produce today (TD-022) is no longer
  created, and its horizon_id is retired.
- Equivalence with a rebuild is defined over active, readable documents: a
  rebuild has no data for documents that are inactive or unreadable, while the
  persistent database keeps their last good data on purpose.
- Time targets are references, not blockers; the absolute gain is what matters.
