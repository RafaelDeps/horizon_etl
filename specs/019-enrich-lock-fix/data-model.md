# Data Model: Enrichment Survives Cross-Type Title Collisions

No table, column or export changes.

## Entities involved

| Entity | Relevant fields | Rule |
|---|---|---|
| `initiatives` | `id`, `name`, `initiative_type_id`, `description`, `enrichment_json` | `name` is unique across **all** types (Research Project, Advisorship, …). |
| `initiative_types` | `id`, `name` | Locally and in CI: 1 = Research Project, 2 = Advisorship. |
| Project document (`PJ_*.json`) | `codigo`, `titulo`, `descricao`, `datas`, … | Unmatched rich documents become new Research Project initiatives. |
| Tracking (`source_records`, `entity_matches`, `attribute_assertions`, `entity_change_logs`) | per enriched or created initiative | Written through other sessions than the loader's. |

## Phase state (`_ingest_new`)

| Set | Before | After |
|---|---|---|
| `existing_names` | normalized names of Research Project initiatives (`name_index` keys) | normalized names of **all** initiatives, plus `name_index` keys |
| `seen_titles` | normalized titles created earlier in the run | unchanged |

A document whose normalized title is in either set is counted in
`skipped_duplicate` and creates nothing.

## Connection state per row (`_write_row`)

```text
SAVEPOINT (opens the SQLite transaction)
  ├─ row succeeds → RELEASE → committed, no lock held
  └─ row fails    → ROLLBACK TO SAVEPOINT → transaction still open, lock held
                    (new) session.commit() → transaction closed, lock released
next tracking write on another connection → succeeds
```

## Counters (unchanged keys)

`enriched`, `created`, `errors`, `skipped_duplicate`, `skipped_poor`,
`skipped_not_approved`, `skipped_no_match`, `skipped_collision`,
`needs_review`, `desc_filled`, `desc_kept_existing`, `by_code`,
`by_title_exact`, `by_title_fuzzy`.

Expected on the CI run 40002646510 database: enriched 251, created 17, errors 0,
`skipped_duplicate` 1.
