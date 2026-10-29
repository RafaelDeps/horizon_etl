# Data Model: Skip Unchanged Source Documents on a Persistent Database

All tables are new and ETL-owned, created by `src/db/migrations.py`. No
existing table changes (FR-002).

## Table `source_document_states` (migration `0008_source_document_states`)

One row per source document (research R1).

| Column | Type | Rule |
|---|---|---|
| `source_system` | TEXT NOT NULL | one of `lattes_projects`, `lattes_advisorships`, `cnpq_group`, `sigpesq_project`, `sigpesq_advisorship`, `sigpesq_group` (no `sigpesq_pj`: the enrichment phase is out of this spec) |
| `document_key` | TEXT NOT NULL | source-native key (R1); never an internal id |
| `content_hash` | TEXT | `stable_hash` of the parsed document (R2); NULL until first processed |
| `dependency_fingerprint` | TEXT | `stable_hash` of the sorted references (R3) |
| `rule_version` | INTEGER NOT NULL | `HORIZON_RULE_VERSION` when processed |
| `max_person_id` | INTEGER | highest `persons.id` when processed (R3 delta) |
| `max_initiative_id` | INTEGER | highest `initiatives.id` when processed (R3 delta) |
| `item_count` | INTEGER NOT NULL DEFAULT 0 | number of item links other than the document's own subject (the CV owner, the CNPq group) — the R4 total-loss guard |
| `last_ingestion_run_id` | INTEGER | `ingestion_runs.id` of the run that last processed it |
| `processed_at` | TEXT | ISO-8601 UTC, last successful processing |
| `last_seen_at` | TEXT NOT NULL | ISO-8601 UTC, last run whose complete listing contained it |
| `status` | TEXT NOT NULL | `active` or `inactive` |
| `last_failure` | TEXT | failure record, not processing state (FR-008): reason of the last failed attempt (`download`, `unparsable`, `unidentified`, `total_loss`, `partial`), NULL after a success |
| `last_failure_at` | TEXT | ISO-8601 UTC |

`PRIMARY KEY (source_system, document_key)`.

## Table `source_document_items` (migration `0009_source_document_items`)

The current link set of each processed document (R6).

| Column | Type | Rule |
|---|---|---|
| `source_system` | TEXT NOT NULL | as above |
| `document_key` | TEXT NOT NULL | as above |
| `item_type` | TEXT NOT NULL | `person`, `researcher`, `initiative`, `advisorship`, `team`, `article`, `production_author`, `research_production`, `academic_education`, `award`, `proficiency`, `professional_activity`, `fellowship`, `research_group`, `initiative_knowledge_area`, `group_knowledge_area`, `initiative_enrichment` |
| `item_ref` | TEXT NOT NULL | row id, or `<table>:<id>:<id>` for composite keys |
| `is_subject` | INTEGER NOT NULL DEFAULT 0 | 1 for the document's own subject (the CV owner's researcher row, the CNPq group row), left out of `item_count` |

`PRIMARY KEY (source_system, document_key, item_type, item_ref)` and an index
(migration `0010_source_document_items_index`) on `(item_type, item_ref)` for the "does any document still carry it?" check.

## Table `source_document_references` (migration `0011_source_document_references`)

The resolutions a document made (R3).

| Column | Type | Rule |
|---|---|---|
| `source_system`, `document_key` | TEXT NOT NULL | as above |
| `kind` | TEXT NOT NULL | `researcher_owner`, `person_name`, `initiative`, `pj_claim` |
| `lookup_key` | TEXT NOT NULL | the key the resolver used (lattes_id, normalized name, identity key, title) |
| `outcome` | TEXT NOT NULL | target stable key (base `horizon_id` from the spec 020 rules, no suffix), `created:<stable key>` or `not_found`; never a database id |
| `score` | REAL | best fuzzy score, NULL for exact kinds |

`PRIMARY KEY (source_system, document_key, kind, lookup_key)`.

## Decision per document (one run)

```text
listed?  ── no ──► (listing complete and loaded) ? mark inactive : leave as is
   │yes
   ▼
last_seen_at = now; status inactive → active (reactivated)
   ▼
read + parse ── fails ──► failed:download | unparsable | unidentified
   ▼                       (state, items, data unchanged; last_failure set)
content_hash == stored  AND  rule_version == stored  AND  references still hold (R3)
   │yes ──► skipped
   │no
   ▼
BEGIN document transaction (R5; library commits become savepoint releases)
process (existing code, collecting items and references)
   ├─ any section/row failed ──► ROLLBACK, reload phase caches ──► failed:partial
   ├─ new item set empty and item_count > 0 ──► ROLLBACK ──► failed:total_loss
   └─ ok ──► same transaction:
              replace items and references, delete removed items (R6/R7),
              update content_hash, fingerprint, max ids, item_count,
              run id, processed_at, clear last_failure
         COMMIT ──► processed
(process dies at any point ──► nothing of the attempt is in the database)
```

A failure is recorded (`last_failure`, `last_failure_at`) in a short
transaction of its own, after the rollback. These two columns are the failure
record of FR-008, not processing state: a failure never changes
`content_hash`, `dependency_fingerprint`, `rule_version`, the max ids,
`item_count`, `processed_at`, `status`, the item links or the references. The
listing step may still update `last_seen_at` of a failed document that is
listed (it was seen in its source; it only could not be read).

## State transitions of `status`

| From | Event | To |
|---|---|---|
| (none) | first time listed | `active` |
| `active` | absent from a complete, successfully loaded listing | `inactive` |
| `inactive` | listed again | `active` |
| any | listing failed or partial | unchanged |
| any | document failed | unchanged |

`inactive` never deletes anything. Only a `processed` document can remove its
own items.

## Deletion of a removed item

For each `(item_type, item_ref)` in old set − new set:

1. delete the `source_document_items` row of this document;
2. if no row with the same `(item_type, item_ref)` remains:
   - `person` and `researcher` are the same row id (a researcher is a
     person): the "does any document still carry it?" check looks for links
     of **both** types with that id (CNPq members are carried as
     `researcher` through `record_entity_match`, team members and students as
     `person` through `PersonMatcher`). Skip if the person owns an active
     Lattes CV document (FR-011a); else delete it with every
     person-referencing row (the `PersonConsolidator` table list);
   - other types: delete the row and its dependent rows (teams and members of
     an initiative, authors of an article, links of a knowledge area link);
   - reference tables are never deleted (R6).

`team_member_contributions` rows of a removed initiative row are deleted and
the team recomputed by the existing union rule.

## Merge (`consolidate_duplicates`)

`consolidate_pair(winner, loser)` (its own phase, raw `sqlite3`, no document
transaction open) calls a merge hook that the flow injects (constitution I:
the consolidator does not write these tables itself). The hook,
`repoint_person_links(conn, winner, loser)` in
`src/adapters/database/document_item_store.py`, runs on the consolidator's
connection, in its transaction:

- `UPDATE OR IGNORE source_document_items SET item_ref = winner WHERE item_type IN ('person','researcher') AND item_ref = loser`, then delete what is left for the loser;
- the same for `source_document_references.outcome` pointing at the loser's
  stable key is not needed: the outcome stores stable keys, and R3 check 1
  sees that the loser's key no longer exists, so the documents that resolved
  to it are processed again once.
