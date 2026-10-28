# Data Model: Permanent Horizon Ids and Idempotent Tracking Keys

**Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

No existing table changes (FR-014). Six ETL-owned tables are added through
`src/db/migrations.py` (`CREATE TABLE IF NOT EXISTS`, one migration id each).
Existing tables only change in content: `source_records.source_record_id`
values, fewer `entity_change_logs` rows, and `team_members` computed from all
contributions.

## New tables

### `horizon_ids`: the current id of each entity

| Column | Type | Rule |
|---|---|---|
| `entity_type` | TEXT NOT NULL | One of the types in [contracts/horizon-id-format.md](contracts/horizon-id-format.md) |
| `entity_id` | INTEGER NOT NULL | Numeric id of the row in its core table today |
| `horizon_id` | TEXT NOT NULL **UNIQUE** | Current id (FR-001 to FR-009) |
| `rule` | TEXT NOT NULL | Rule that produced it, e.g. `lattes_id`, `name`, `doi`, `title_year_type_venue`, `slug` |
| `natural_key` | TEXT NULL | Normalized text that was hashed; NULL for source ids and slugs |
| `parent_horizon_id` | TEXT NULL | For child items and teams |
| `collision_suffix` | TEXT NULL | `~<6 hex>` or `~2`… when FR-008 applied |
| `assigned_at` | TEXT NOT NULL | Run timestamp |

Constraints: UNIQUE(`entity_type`, `entity_id`); UNIQUE(`horizon_id`).
Rebuilt in full by every `assign_horizon_ids` run (it reflects the current
database), inside one transaction.

### `horizon_id_candidates`: every id an entity could be known by

| Column | Type | Rule |
|---|---|---|
| `horizon_id` | TEXT NOT NULL | The entity's current id (FK-like to `horizon_ids.horizon_id`) |
| `candidate_id` | TEXT NOT NULL | Any id the rules can derive for it: the winner plus lower-priority ones (a person with `lattes_id` also has the name-based one); for children, the ones built from each parent candidate |

Constraints: PRIMARY KEY(`candidate_id`, `horizon_id`). Rebuilt with
`horizon_ids`. Used to resolve previous ids (R5) without a merge log.

### `horizon_id_aliases`: ids that are no longer current

| Column | Type | Rule |
|---|---|---|
| `alias_horizon_id` | TEXT NOT NULL **PRIMARY KEY** | An id that was current before |
| `horizon_id` | TEXT NULL | Current id it resolves to; NULL when retired (unresolved) |
| `reason` | TEXT NOT NULL | `merge`, `upgraded key`, `rebuild`, `key corrected`, `retired` |
| `created_at` | TEXT NOT NULL | When the alias was first created |
| `updated_at` | TEXT NOT NULL | When `horizon_id` last changed (chain re-pointed) |

Rules:
- Never deleted. An alias may be re-pointed when its target becomes an alias
  itself, so no alias points to another alias (FR-012).
- An id present in `horizon_ids` is never in this table at the same time; if a
  retired id becomes current again (same source data reappears), its alias row
  is removed and it is current.

### `horizon_merge_log`: merges captured at merge time

| Column | Type | Rule |
|---|---|---|
| `id` | INTEGER PK | |
| `entity_type` | TEXT NOT NULL | The `horizon_ids.entity_type` of the merged rows: `person`, `knowledge_area`, `team` |
| `loser_candidate_ids` | TEXT NOT NULL | JSON list of the loser's candidate ids, computed with `horizon_identity` before deletion |
| `winner_entity_id` | INTEGER NOT NULL | Numeric id of the surviving row |
| `ingestion_run_id` | INTEGER NULL | Run that merged |
| `merged_at` | TEXT NOT NULL | |
| `consumed_at` | TEXT NULL | Set when `assign_horizon_ids` first turned the entry into aliases (audit) |

Written by `PersonConsolidator.consolidate_pair` and the
`ReferenceConsolidator` merges. Read by every `assign_horizon_ids`, consumed or
not: the winner keeps the highest-priority id among its own and the losers'
(FR-010) on every later run, and the loser's ids stay aliases of it. The first
run that reads an entry sets `consumed_at`; entries are kept (audit trail).

### `horizon_meta`: rule version

| Column | Type | Rule |
|---|---|---|
| `key` | TEXT PK | `rule_version`, `last_assigned_at` |
| `value` | TEXT NOT NULL | |

### `team_member_contributions`: who each document says is on a team

| Column | Type | Rule |
|---|---|---|
| `team_id` | INTEGER NOT NULL | |
| `person_id` | INTEGER NOT NULL | |
| `role_id` | INTEGER NOT NULL | |
| `document_key` | TEXT NOT NULL | Source document and initiative that contributed it: `lattes:<CV lattes_id>#<initiative identity key>`, `sigpesq:<report row key>`, `cnpq:<group id>`; the initiative part keeps two projects that share a team by name apart (research R9.3) |
| `start_date` | TEXT NULL | Date this document gives |

Constraints: PRIMARY KEY(`team_id`, `person_id`, `role_id`, `document_key`).
When a document is processed, its rows for that team are replaced by what it
says now. The team's `team_members` for the managed roles are then the union
over documents, with `start_date` = MIN over contributions. Only the
difference is written to `team_members` (R9.2). `consolidate_pair` re-points
`person_id` from loser to winner here, as it does for `team_members`.

## Id history snapshot (file, not a table)

`db/horizon_id_history.json`, written by `src/scripts/save_horizon_id_history.py`
when `make db-reset` runs (and before the rule-version reset of research R11),
**before** the database is deleted. It is git-ignored.

```json
{
  "saved_at": "2026-11-07T04:00:00Z",
  "rule_version": 1,
  "ids": [ { "entity_type": "...", "horizon_id": "...", "rule": "...",
             "natural_key": "...", "parent_horizon_id": null } ],
  "candidates": [ { "horizon_id": "...", "candidate_id": "..." } ],
  "aliases": [ { "alias_horizon_id": "...", "horizon_id": "...",
                 "reason": "...", "created_at": "..." } ],
  "merge_log": [ { "entity_type": "...", "loser_candidate_ids": ["..."],
                   "winner_horizon_id": "..." } ]
}
```

- Written only when the database exists and has a `horizon_ids` table; a
  failed write logs a WARNING and does not block the reset.
- `merge_log` stores the winner's `horizon_id`, not its numeric id, because
  numeric ids do not survive the reset.
- Read by `load_history()` as the second source (research R5): previous
  database tables first, then this snapshot, then the published zip. The
  snapshot and the zip are merged when both exist.

## Derived values (not stored as tables)

- **Canonical payload form** (FR-021): recursively, `None`/NaN/"nan"/"NaN"/""
  → `None`; integral floats → int; every scalar → `str(v).strip()`; dict keys
  sorted. `stable_hash` = SHA-256 of the JSON of that form. Used for
  `source_records.payload_hash` and `attribute_assertions.value_hash`.
- **Natural-key hash**: SHA-256 of the `|`-joined `normalize_text` parts,
  first 12 hex characters.

## State transitions of an id

```text
          derive (first time)
   none ─────────────────────────► current
                                     │
   ┌─────────────────────────────────┼─────────────────────────────────────┐
   │ higher-priority source id found │ merged into another entity          │
   │ (upgraded key)                  │ (merge)                             │
   │ natural key corrected, 1 match  │ previous db reset, found as         │
   │ (key corrected)                 │ candidate (rebuild)                 │
   ▼                                 ▼                                     ▼
 alias ──(target becomes alias)──► alias re-pointed to the new current id
   │
   │ no candidate, no merge, no match
   ▼
 retired (alias with horizon_id NULL) ──(same source data reappears)──► current
```

Invariants:
1. Every row of every core entity table has exactly one row in `horizon_ids`
   after `assign_horizon_ids` (SC-003).
2. `horizon_ids.horizon_id` and `horizon_id_aliases.alias_horizon_id` are
   disjoint.
3. Every non-NULL `horizon_id_aliases.horizon_id` is present in `horizon_ids`.
4. Every id ever written to a published id file is either current or an
   alias afterwards (SC-007).

## Validation rules (from the requirements)

| Rule | Requirement | Checked by |
|---|---|---|
| Id built only from source data and content | FR-002 | two-rebuild test; no reference to numeric ids in `horizon_identity` |
| No CPF, e-mail, phone in id or `natural_key` | FR-007 | unit test over rules; scan of the id file for e-mail/CPF/phone patterns |
| Unique ids | FR-008 | UNIQUE constraint; collision test with homonyms |
| Same rule version or rebuild | FR-024 | version-guard test |
| Existing schema untouched | FR-014 | schema snapshot test (`PRAGMA table_info` / `index_list` of every pre-existing table) |
