# Data Model: Every professional activity is kept, with the right institution

**Feature**: `034-keep-professional-activities` | **Date**: 2026-11-11

No table, column or export field is added or removed. The feature changes
which rows exist in `professional_activities`, the values of three of its
columns and the key of its permanent id.

## Professional activity (`professional_activities`, domain library entity)

| Field | Type | Source | Change |
|-------|------|--------|--------|
| `id` | integer | database | none |
| `researcher_id` | integer | the curriculum's researcher | none |
| `organization_id` | integer, optional | not filled by the ETL | none |
| `institution` | text, 500 | `instituicao` | full stops and spaces at the end are removed |
| `institution_name` | text, 255 | read from `institution` (R2) | was `instituicao_nome` |
| `institution_acronym` | text, 100 | read from `institution` (R2) | was `instituicao_sigla` |
| `institution_country` | text, 100 | read from `institution` (R2) | was `instituicao_pais` |
| `period` | text, 100 | `periodo` | none |
| `start_year` | integer | `ano_inicio` | none |
| `end_year` | integer | `ano_fim` (empty when "Atual") | none |
| `bond` | text, 100 | `vinculo` | none |
| `classification` | text, 255 | `enquadramento` | none |
| `work_regime` | text, 100 | `regime` | none |
| `role_function` | text, 255 | `cargo_funcao` | none |
| `activity_type` | text, 100 | `tipo` (always "Atuação profissional") | none |
| `current` | boolean | `ano_fim` is "Atual" | none |

### Rules

- **Uniqueness**: for one researcher, no two rows are equal in the 13 fields
  from `institution` to `current` (R3). Before: no two rows shared
  `institution`, `start_year` and `activity_type`.
- **Institution-only row**: a row whose seven detail fields (`period`,
  `start_year`, `end_year`, `bond`, `classification`, `work_regime`,
  `role_function`) are empty exists only when the researcher has no other row
  with the same `institution` (R4).
- **Institution fields**: `institution_name`, `institution_acronym` and
  `institution_country` are a function of `institution` alone (R2); a part of
  the text is never stored in two of them.

### Lifecycle

- **Created** when a curriculum item has no equal stored row of the
  researcher.
- **Carried** (no write) when an equal row exists.
- **Removed** when the curriculum, downloaded again, no longer carries the
  item (existing rule of spec 021, through the items carried by the
  document). A changed item is therefore a removal plus a creation.

## Curriculum activity item (parser output)

A dictionary with the 13 fields above minus `id`, `researcher_id` and
`organization_id`. `parse_professional_activities` returns the items of one
curriculum after `split_institution` and `distinct_activities`: no exact
repeats and no institution-only item beside a filled one.

## Permanent id (`horizon_ids`, entity type `professional_activity`)

| | Before | After |
|--|--------|-------|
| Form | `<person id>/activity:h:<hash12>` | same |
| Hashed fields | `institution_name`, `start_year`, `end_year`, `role_function`, `bond` | `institution`, `period`, `start_year`, `end_year`, `bond`, `classification`, `work_regime`, `role_function`, `current` |
| Rule label | `parent+institution_name+start_year+end_year+role_function+bond` | `parent+institution+period+start_year+end_year+bond+classification+work_regime+role_function+current` |
| Candidates | one per parent candidate | one per parent candidate, plus the old-rule id per parent candidate (R8) |

`horizon_meta.rule_version` goes from `3` to `4`.

## Aliases (`horizon_id_aliases`)

After the rebuild, each of the 7,855 old activity ids is either an alias of
one current id (about 5,871, reason `rebuild` or `upgraded key`) or recorded
with reason `retired` (about 1,984: 761 shared by several new rows and 1,223
of institution-only rows that are no longer stored).

## Volumes (435 curricula, measured)

| | Before | After |
|--|--------|-------|
| Curriculum items with an institution | 13,420 | 13,420 |
| Rows in `professional_activities` | 7,855 | about 9,555 |
| of which with a filled detail field | | about 9,392 |
| of which institution-only | 1,386 | about 163 |
| Rows with "IFES" as the country | 2,260 | 0 |
| Rows whose id needs a collision suffix | 114 | about 6 |
