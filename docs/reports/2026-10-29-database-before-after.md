# The ETL Database Before and After Specs 020–023

Date: 2026-10-29. This report compares the database the weekly produced
before the four specs with the one it produces now: the same tables and
columns, plus 9 new ETL tables beside them.

- **Before**: `db/horizon.db` of the 2026-10-24 local weekly, kept in
  `data/_backup_2026-10-28_pre021/db/horizon.db` (224 MB). It was built by the
  code before spec 020 and rebuilt from scratch every week.
- **After**: the local `db/horizon.db` after five weekly runs with the spec
  021 code (2026-10-29), copied to a scratch file, with every migration of
  this branch applied (up to `0012`, spec 023), 318 MB.

The two databases come from different source downloads (2026-10-24 and
2026-10-29), so row counts differ a little for that reason too. The schema
comparison is exact.

## 1. Summary

| | Before | After |
|---|---|---|
| Tables | 42 | 51 (42 + 9 new) |
| Tables whose columns, types, keys, indexes or foreign keys changed | — | **0** |
| ETL migrations applied | 1 (`0001`) | 12 (`0001`–`0012`) |
| File size | 224 MB | 318 MB |
| How a week starts | deleted and rebuilt (`make db-reset`) | kept; only changed documents are processed |
| Permanent id per entity | none (only the numeric autoincrement id, which changed every rebuild) | `horizon_id` for 62,228 entities |
| Tracking keys (`source_records.source_record_id`) | partly built from database ids | built from source data only |

**For anyone who reads the existing tables or exports, nothing changed in
format.** Every table that existed before has the same columns, the same
types and the same indexes. Only their content changed, in the ways listed
in section 4.

## 2. Existing tables: schema unchanged

All 42 tables of the old database are still there, and none of them changed
(checked column by column with `PRAGMA table_info`, `index_list`,
`index_info` and `foreign_key_list`).

The library tables (`eo_lib`, `research_domain`) were never touched, as the
rule "third-party libraries unchanged" required:

- persons and researchers: `persons`, `researchers`, `person_emails`;
- initiatives and teams: `initiatives`, `teams`, `team_members`,
  `initiative_teams`;
- `advisorships`, `advisorship_members`, `fellowships`;
- productions: `articles`, `article_authors`, `research_productions`,
  `production_authors`;
- curriculum items: `academic_educations`, `awards`, `proficiencies`,
  `professional_activities`;
- groups and areas: `research_groups`, `group_knowledge_areas`,
  `knowledge_areas`;
- reference tables: organizations, units, types, roles, languages;
- tracking: `ingestion_runs`, `source_records`, `entity_matches`,
  `attribute_assertions`, `entity_change_logs`.

The only ETL column added before these specs, `initiatives.enrichment_json`
(migration `0001`), was already in the old database.

## 3. New tables (all owned by the ETL)

| Table | Spec | Rows now | What it holds |
|---|---|---:|---|
| `horizon_ids` | 020 | 62,228 | One permanent, readable id per entity (`person:lattes:<id>`, `group:cnpq:<id>`, `article:doi:<doi>`, `<entity>:<origin>:h:<hash>` …) |
| `horizon_id_aliases` | 020 | 7,119 | Old ids that now point to the current one (after a merge, a better source id, a rebuild, a corrected key) |
| `horizon_id_candidates` | 020 | 102,782 | Every candidate id an entity could have, used to decide merges and aliases |
| `horizon_merge_log` | 020 | 393 | Person merges done by `consolidate_duplicates`, for the aliases |
| `horizon_meta` | 020 | 2 | `rule_version` (the version of the key, hash and id rules) and the last assignment time |
| `team_member_contributions` | 020 | 37,582 | What each source document says about each team's members |
| `source_document_states` | 021 (+023) | 2,376 | One row per source document: content hash, rule version, status, dates |
| `source_document_items` | 021 | 87,673 | The items each document carries |
| `source_document_references` | 021 | 43,884 | The names each document resolved, and to which entity |

### Columns of the new tables

`horizon_ids`:

| Column | Type | |
|---|---|---|
| `entity_type` | TEXT NOT NULL | `person`, `article`, `initiative`, `advisorship`, `team`, … |
| `entity_id` | INTEGER NOT NULL | the numeric id of the row in its table |
| `horizon_id` | TEXT NOT NULL, unique | the permanent id |
| `rule` | TEXT NOT NULL | which rule built it (source id, name hash, slug …) |
| `natural_key` | TEXT | the source data the id was derived from |
| `parent_horizon_id` | TEXT | for child items (education, awards …): the owner's id |
| `collision_suffix` | TEXT | set only when two entities would share an id |
| `assigned_at` | TEXT NOT NULL | when it was first assigned |

Unique on `horizon_id` and on (`entity_type`, `entity_id`). Ids by entity
type: person 17,124, team 11,429, advisorship 8,682, professional activity
7,227, article 6,735, initiative 3,043, research production 2,807, academic
education 1,842, knowledge area 1,561, proficiency 744, organization 428,
research group 353.

`horizon_id_aliases`:

| Column | Type |
|---|---|
| `alias_horizon_id` | TEXT, primary key |
| `horizon_id` | TEXT (current id; NULL when the entity is gone, reason `retired`) |
| `reason` | TEXT NOT NULL |
| `created_at`, `updated_at` | TEXT NOT NULL |

Aliases by reason: `retired` 6,709, `rebuild` 298, `key corrected` 103,
`merge` 7, `upgraded key` 2.

The other new tables:

| Table | Columns |
|---|---|
| `horizon_id_candidates` | `horizon_id`, `candidate_id` |
| `horizon_merge_log` | `id`, `entity_type`, `loser_candidate_ids`, `winner_entity_id`, `ingestion_run_id`, `merged_at`, `consumed_at` |
| `horizon_meta` | `key`, `value` |
| `team_member_contributions` | `team_id`, `person_id`, `role_id`, `document_key`, `start_date` |
| `source_document_items` | `source_system`, `document_key`, `item_type`, `item_ref`, `is_subject` |
| `source_document_references` | `source_system`, `document_key`, `kind`, `lookup_key`, `outcome`, `score` |

Keys and indexes:

- `horizon_id_candidates`: primary key (`horizon_id`, `candidate_id`).
- `team_member_contributions`: primary key on its first four columns.
- `source_document_items`: primary key on its first four columns, and an
  index on (`item_type`, `item_ref`).
- `source_document_references`: primary key on its first four columns.

`source_document_states`, primary key (`source_system`, `document_key`):

| Column | Type | |
|---|---|---|
| `content_hash` | TEXT | canonical hash of the document's content |
| `dependency_fingerprint` | TEXT | hash of the names it resolved |
| `rule_version` | INTEGER NOT NULL | rule version it was processed under |
| `max_person_id`, `max_initiative_id` | INTEGER | the newest persons and initiatives it could see |
| `item_count` | INTEGER NOT NULL | items it carries (for the total-loss guard) |
| `last_ingestion_run_id` | INTEGER | run that last processed it |
| `processed_at` | TEXT | last successful processing |
| `last_seen_at` | TEXT NOT NULL | last time its source listed it |
| `status` | TEXT NOT NULL | `active` or `inactive` |
| `last_failure`, `last_failure_at` | TEXT | last failure (`download`, `unparsable`, `unidentified`, `total_loss`, `partial`) |
| `downloaded_at` | TEXT | spec 023: when the content it was read from was downloaded |

Documents by source today:

| Source | Documents | Inactive | With a failure record |
|---|---:|---:|---:|
| `lattes_projects` | 435 | 0 | 27 (the "Nome-nao-identificado" CVs) |
| `lattes_advisorships` | 435 | 0 | 27 |
| `cnpq_group` | 347 | 0 | 0 |
| `sigpesq_group` | 352 | 0 | 0 |
| `sigpesq_project` | 103 | 0 | 0 |
| `sigpesq_advisorship` | 704 | 0 | 0 |

## 4. What changed in the content of existing tables

| Table | Before | After | Why |
|---|---:|---:|---|
| `persons` | 17,124 | 17,124 | same sources, same people |
| `researchers` | 7,645 | 7,644 | the 27 unreadable CVs no longer create the merged "[Nome-nao-identificado]" person (spec 021) |
| `initiatives` | 11,723 | 11,725 | source changes between the two days |
| `advisorships` | 8,680 | 8,682 | source changes |
| `articles` | 6,736 | 6,735 | source changes; the DOI-less duplicate fix of spec 020 |
| `team_members` | 39,666 | 42,262 | membership is now the union of what every document says (spec 020), instead of the last document overwriting the others |
| `group_knowledge_areas` | 1,954 | 1,930 | research lines of the 2026-10-29 CNPq pages |
| `research_groups` | 354 | 353 | one group no longer in the SigPesq report |
| `entity_change_logs` | 35,978 | 33,175 | fewer false "update" logs (spec 020: a log only when a value changed) |
| `ingestion_runs` | 7 | 40 | the database now keeps the history of every weekly run |
| `source_records` | 35,547 | 35,611 | grows only when a source's content changes |

Tracking keys (`source_records.source_record_id`) changed format. Before,
some were built from database ids, which changed every rebuild. Now they are
built from source data only:

| Type | Before (example) | After (example) |
|---|---|---|
| `cnpq_group_member` | `100\|Erivania …\|Líder` (`100` = `research_groups.id`) | `cnpq:0072090883538018\|andre gustavo …\|pesquisador\|18 04 2023\|` |
| `cnpq_research_line` | `100\|Tradução e interpretação …` | `cnpq:0072090883538018\|engenharia mecanica` |
| `academic_education` | `10002\|Ensino Médio …\|2012` (`10002` = `researchers.id`) | `lattes:0059221043399777\|ciencias da religiao\|especializacao\|2008\|2010\|…` |
| `article` | `3d navier stokes … \|2003` | `lattes:0059221043399777\|10.1590/…\|journal\|…` (the CV it came from + the work's fields) |

The numeric ids (`persons.id`, `initiatives.id`, …) changed once, at the
first rebuild under spec 020. From now on they stay, because the database is
no longer rebuilt every week. The stable reference for consumers is
`horizon_id` (`horizon_ids_canonical.json`).

## 5. Exports (`exports_canonical.zip`)

| | Before | After |
|---|---|---|
| Existing export files | 35 | the same 35, **with the same fields** (checked by the spec 020 export test and file by file on the spec 021/022 CI runs) |
| New files | — | `horizon_ids_canonical.json`, `horizon_id_aliases_canonical.json` (spec 020), `source_document_states_canonical.json` (spec 021, with `downloaded_at` from spec 023) |

## 6. Files kept between runs (outside the database)

| Path | Spec | Content |
|---|---|---|
| `db/horizon.db` | 021, 022 | the database itself, restored in CI from the last successful run |
| `data/raw/` | 022 | SigPesq reports (cleared before each download) and project PDFs |
| `cache/` | 022 | Lattes curricula (HTML) |
| `data/raw/lattes/download_manifest.json` | 023 | download date of every cached curriculum |
| `data/raw/cnpq/<group id>.json` | 023 | each CNPq group page with its download date |
| `db/horizon_id_history.json` | 020 | id history saved before a `make db-reset` |
| `data/reports/source_document_states_report.json` | 021 | per phase: documents processed, skipped, failed, and downloads |
| `data/reports/restore_outcome.json` | 022 | where the CI run's database came from |

## 7. How to reproduce

```bash
# old: the backup; new: a copy of db/horizon.db with every migration applied
python db/ensure_db.py        # with DATABASE_URL pointing to the copy
# then, for every table of both files:
#   PRAGMA table_info / index_list / index_info / foreign_key_list, COUNT(*)
```

The comparison of this report was made that way on 2026-10-29. In the copy,
`downloaded_at` exists but is still empty, because the spec 023 phases had
not yet run on the local database.

## 8. The dashboard on the new data

Checked on 2026-10-29 with `horizon_dashboard` (branch at `ceaa4bea`). The
dashboard repository was not changed: everything ran on a copy in a scratch
folder.

The new export was loaded into the copy's `src/data` exactly as the
dashboard's `sync-etl-data.yml` does:

1. unpack `exports_canonical.zip` (the zip of the 2026-10-29 CI run of spec
   022, `be9a126`);
2. `node scripts/sanitize-json.mjs src/data`;
3. `node scripts/normalize-names.mjs`.

| Check | Dashboard's current data (working tree) | New export |
|---|---|---|
| Tests (`vitest run`) | 81 passed, 10 failed | 81 passed, **the same 10** failed |
| `npm run build` (the script sets an 8 GB Node heap) | **completes**, 55,951 pages | **runs out of memory** after 9,191 pages (`advisorships/index.astro`) |
| `astro build` with a 12 GB heap (command line only) | — | **completes**: 57,877 pages, 17 min, peak 15.6 GB RAM |
| Built site served (`astro preview`) | — | `/`, `/researchers/`, `/groups/`, `/projects/`, `/advisorships/`, `/publications/`, `/download/`, `/researchers/1/` all return 200 |

How to read it:

- **The data works.** With enough memory the site builds and serves every
  page, with about 1,900 more pages than today (more researchers and
  initiatives). The 10 failing tests fail with the dashboard's current data
  too, so they are not caused by the export.
- **The dashboard's 8 GB build limit is no longer enough.** The data the
  dashboard has committed (2026-09-24) holds 120 researchers with a Lattes
  CV. Its current working tree, from a later sync, holds 413, and the new
  export 399. The new files of these specs
  (`horizon_ids_canonical.json`, 18 MB, and the other two) are not read by
  any dashboard page. The files the dashboard reads grew by about 25 MB in
  total from its current data (`advisorships_tracking.json` +6 MB,
  `people_relationship_graph.json` +6 MB, …). That is enough to cross the
  8 GB heap.
- **What it needs** (dashboard side, not changed here):
  - a larger heap in its build script (`--max-old-space-size`);
  - or a build that does not load every large tracking file into pages.
  - The peak of 15.6 GB is close to the 16 GB of a standard GitHub-hosted
    runner, so its CI build may fail too.
