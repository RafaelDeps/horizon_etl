# Data Model: Fixed Rule for Fields Written by Several Documents

**Branch**: `030-deterministic-field-merge` | **Date**: 2026-11-05

No domain entity changes. The feature adds one ETL bookkeeping table and
changes how existing columns get their values.

## New table: `source_field_claims`

This is ETL bookkeeping, like `source_document_items` of branch 024 (spec
021). It is not a domain entity, and it is not exported. It is created by
migrations `0013_source_field_claims` and `0014_source_field_claims_index` in `src/db/migrations.py`.

| Column | Type | Meaning |
|---|---|---|
| `source_system` | TEXT, not null | document source system: `lattes_projects`, `lattes_advisorships`, `sigpesq_project`, `sigpesq_advisorship`, `sigpesq_project_files` |
| `document_key` | TEXT, not null | the document key of `source_document_states` (Lattes id, SigPesq row key, PJ code) |
| `entity_type` | TEXT, not null | `initiative`, `advisorship` or `fellowship` |
| `entity_id` | INTEGER, not null | the row the claim is about |
| `field` | TEXT, not null | one of the fields below |
| `value_json` | TEXT | the value the document gives, JSON; PII-scrubbed like `attribute_assertions` (branch 029) |
| `doc_date` | TEXT | ISO date of the document (Lattes CV update date, CNPq last submission), or NULL |
| `source_rank` | INTEGER, not null | 0 Lattes, 1 SigPesq, 2 CNPq |
| `tie_key` | TEXT, not null | within-source tie key (research R4) |

- **Primary key:** `(source_system, document_key, entity_type, entity_id, field)`.
- **Index:** `(entity_type, entity_id, field)`, used by the resolver.

### Fields covered (FR-006)

| entity_type | fields |
|---|---|
| `initiative` | `status`, `description`, `start_date`, `end_date` |
| `advisorship` | `status`, `description`, `start_date`, `end_date` |
| `fellowship` | `value` |

`name` is not ranked. It stays the identity of the row, and the guards of
research R7 decide it. `enrichment_json` is not ranked either (research R6).

### Lifecycle

```
document processed ─► claims of (source_system, document_key) replaced
                      inside the document's transaction
document failed    ─► transaction rolled back: claims and values as before
document deleted / ─► its claims deleted (same step that deletes its items);
item dropped          the affected entities are resolved again
duplicates merged  ─► claims moved to the winner (UPDATE OR IGNORE, DELETE)
db-reset           ─► table recreated empty, filled again by the rebuild
```

## Resolution rule

For one `(entity_type, entity_id, field)`:
1. Drop the claims whose value is empty: `None`, blank, or `"Unknown"` for
   status.
2. When none is left, keep the stored value. Write nothing.
3. Otherwise the winner is the claim with the smallest
   `(doc_date IS NULL, doc_date DESC, source_rank, tie_key)`.
4. When the winner's value equals the stored value, after canonical
   comparison (research R5), write nothing.
5. Otherwise write the winner's value. The change log gets one `update`
   entry, with `before` and `after`.

The decision kind is counted only when at least two different non-empty
values took part:
- `by_date`: the winner's date is strictly later than the best date of any
  other value;
- `by_source`: otherwise, the winner's `source_rank` is lower;
- `by_tiebreak`: otherwise, the tie key decided.

## Changed values in existing tables

| Table.column | Before | After |
|---|---|---|
| `initiatives.status`, `description`, `start_date`, `end_date` | last writer | resolved |
| `advisorships` (same four columns, through `initiatives`) | last writer | resolved |
| `advisorships.cancelled` | last writer | resolved (SigPesq only; highest Id wins) |
| `fellowships.value` | last non-zero writer | resolved |
| `horizon_meta.rule_version` | `1` | `2` (forces one rebuild, research R8) |

Parent projects (`recalculate_parent_projects`) keep deriving their status and
dates from their children, after the children are resolved. A document only
resolves the fields it claims, so a project PDF (description only) leaves the
recalculated dates and status alone. A CV or SigPesq row that claims the dates
of a parent still sets them when it is reprocessed; the recalculation, which
runs after every source phase, sets them back in the same weekly. The final
value is the same, but those rows are written twice in that run.
