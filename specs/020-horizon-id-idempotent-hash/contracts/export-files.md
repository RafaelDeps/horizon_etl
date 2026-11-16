# Contract: new export files

Both files are written by `export_canonical` into the output directory
(`data/exports/` by default) and are therefore included in
`exports_canonical.zip` by the existing walk. **No existing export file
changes** (FR-015): same file names, same fields, numeric `id` with the same
meaning.

## `horizon_ids_canonical.json`

One object with metadata and one row per entity currently in the database.

```json
{
  "rule_version": 1,
  "generated_at": "2026-11-07T04:12:09Z",
  "ids": [
    {
      "entity_type": "person",
      "id": 1,
      "horizon_id": "person:h:3f9a0c1b2d4e",
      "rule": "name",
      "natural_key": "carlos roberto pires campos",
      "parent_horizon_id": null
    },
    {
      "entity_type": "research_group",
      "id": 1,
      "horizon_id": "group:cnpq:4439471564090237",
      "rule": "cnpq_id",
      "natural_key": null,
      "parent_horizon_id": null
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `entity_type` | Names the kind of row the `id` belongs to: `person` (the `persons.id` used by `researchers_canonical`, `students_canonical`, `outside_ifes_canonical`, `null_researchers_canonical` and the graphs; researchers share the person id), `research_group`, `initiative`, `advisorship`, `article`, `research_production`, `academic_education`, `professional_activity`, `award`, `proficiency`, `team`, `fellowship`, `knowledge_area`, `organization`, `campus`, `initiative_type`, `production_type`, `role`, `language`, `education_type` |
| `id` | The numeric id used in the existing export files, so a consumer joins on what they already read |
| `horizon_id` | The permanent id ([horizon-id-format.md](horizon-id-format.md)) |
| `rule` | Which rule produced it |
| `natural_key` | Normalized text the hash was taken from (names, titles: already public in the existing exports); `null` for source ids and slugs |
| `parent_horizon_id` | For child items and teams |

Rows are sorted by `entity_type`, then `horizon_id`, so that two exports of the
same data are byte-identical apart from `generated_at`.

The six columns are required by FR-016 (decided 2026-10-27). `rule`,
`natural_key` and `parent_horizon_id` let a history read back from this file
resolve rebuilds, rule-version changes and corrected keys (research R5, R8).

## `horizon_id_aliases_canonical.json`

```json
{
  "rule_version": 1,
  "generated_at": "2026-11-07T04:12:09Z",
  "aliases": [
    {
      "alias_horizon_id": "person:h:3f9a0c1b2d4e",
      "horizon_id": "person:lattes:9860697624155451",
      "reason": "upgraded key",
      "created_at": "2026-11-07T04:12:09Z"
    },
    {
      "alias_horizon_id": "article:h:0c4e9a1f7b2d",
      "horizon_id": null,
      "reason": "retired",
      "created_at": "2026-11-14T04:10:51Z"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `alias_horizon_id` | An id that is no longer current |
| `horizon_id` | Current id it resolves to (never another alias); `null` when retired |
| `reason` | `merge`, `upgraded key`, `rebuild`, `key corrected`, `retired` |
| `created_at` | First time the alias was published |

Sorted by `alias_horizon_id`. The file only grows: an alias is never removed
except when the same id becomes current again.

## Consumer usage

- To follow an entity across weeks or rebuilds: read `horizon_id` from the id
  file by (`entity_type`, `id`), and resolve old ids through the alias file.
- Existing consumers that ignore these files keep working unchanged.

## Parquet

If `src/scripts/export_parquet.py` is run on the export folder, both files are
object-wrapped lists: the converter must convert `ids` / `aliases` and keep
`horizon_id`, `alias_horizon_id`, `parent_horizon_id` and `natural_key` as
text, never pinned to an integer type (FR-017).
