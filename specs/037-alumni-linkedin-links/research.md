# Research: LinkedIn links from a local list

**Feature**: `037-alumni-linkedin-links` | **Date**: 2026-11-13

Measurements are read-only, on the local database after the second run of
branch 036 (`db/horizon.db`, 18,329 persons, rule version 6) and on the
exports of that run (`data/exports/`). The 182 names used for the counts were
read once from the maintainer's alumni data, only to measure; the ETL does not
read that place (R9). Only counts are quoted.

## R1. Where the persons of the list appear in the exports

- **Finding**: `researchers_canonical.json` lists every person of the
  database (18,329 entries), not only teachers. All 148 matched persons are
  entries of it, each with `id`, `name`, `cnpq_url`, `google_scholar_url`.
- **Finding**: the same person entry is written to the classification files:
  `students_canonical.json` (146 of the 148), `researchers_only_canonical.json`
  (1), `outside_ifes_canonical.json` (1) and `null_researchers_canonical.json`.
  All of them are built from one function,
  `CanonicalDataExporter._build_researcher_base_export_dict`, which already
  sets `cnpq_url` and `google_scholar_url` to `None` when absent.
- **Finding**: of the 148 persons, 147 are the Student of an advisorship and
  all 148 are members of a project team; 29 also have a row in the library's
  `researchers` table.
- **Decision**: `linkedin_url` is added in that one function, from a map
  `person id -> link` loaded once per export. Every person file gets the field
  with no other change. The spec's open point (which export lists the alumni)
  is closed: the dashboard reads `linkedin_url` of the person entry.
- **Alternatives considered**: adding the link to the student fields inside
  advisorships and project teams (many places, and the person entry already
  exists); a separate `linkedin_links.json` file (the dashboard would need a
  second file, against SC-008).

## R2. Where the link is stored

- **Finding**: `persons` and `researchers` belong to the domain library. The
  ETL has its own migrations (`src/db/migrations.py`, 14 so far): one adds a
  column to a library table (`initiatives.enrichment_json`), the others create
  ETL-owned tables beside the library's ("they never alter them").
- **Decision**: a new ETL-owned table, migration `0015_person_linkedin_links`:
  `person_id INTEGER PRIMARY KEY`, `linkedin_url TEXT NOT NULL UNIQUE`,
  `listed_name TEXT NOT NULL`, `updated_at TEXT NOT NULL`. One link per
  person and one person per link are enforced by the table.
- **Rationale**: no library table is altered; a person without a link has no
  row; the library's `Person` entity and its `to_dict` are untouched, so
  nothing else that reads persons changes.
- **Finding**: migrations run at the start of every weekly
  (`weekly_orchestrator`), in `db-ensure` and in `db-reset`, so a database
  created before the feature gets the table without a rebuild. The exporter
  still treats a missing table as "no links" (an export run alone on an older
  database).
- **Alternatives considered**: `ALTER TABLE persons ADD COLUMN linkedin_url`
  (the library's entity would not know the column, and its `to_dict` would
  not carry it, so the exporter would need the extra query anyway).

## R3. Where the step runs

- **Finding**: the weekly's phases are a list in
  `src/flows/pipelines/weekly_orchestrator.py`; each runs `app.py <name>` in
  its own process, in order. After the sources come
  `recalculate_parent_projects`, `consolidate_duplicates` (merges duplicate
  persons), `assign_horizon_ids` and `export_canonical`.
- **Decision**: a new phase `linkedin_links`, right after
  `consolidate_duplicates` and before `assign_horizon_ids`, not critical
  (its failure does not stop the run), 300 s. `app.py linkedin_links` calls a
  small Prefect flow, `src/flows/maintenance/linkedin_links.py`, as the other
  maintenance phases do. Running after the consolidation means the names are
  compared with the final persons.
- **Decision**: a Makefile target is not added; `app.py linkedin_links` can
  be run alone, as every other phase.

## R4. Persons merged by the consolidation

- **Finding**: `PersonConsolidator` merges a duplicate person into another
  and deletes the loser. It accepts merge hooks; one exists for the ETL's
  document links (`repoint_person_links`).
- **Decision**: a second hook, `repoint_linkedin_link`: when the loser has a
  link and the winner has none, the row moves to the winner; when both have
  one, the winner's stays and the loser's row is deleted. So a link survives a
  merge even in a run without the list.
- **Finding**: when the list is read, the step also removes rows whose person
  no longer exists, as part of making the stored links equal to the list.

## R5. The rule (pure)

- **Decision**: one pure module, `src/core/logic/linkedin_links.py`, with no
  database and no file access:
  - `normalize_profile_link(text)`: accepts `linkedin.com/in/<profile>` with
    or without scheme, `www.` or a country subdomain (`br.linkedin.com`), any
    letter case in the host, an optional trailing slash, query or fragment;
    returns `https://www.linkedin.com/in/<profile>` with the profile part as
    written (it may hold percent-encoded letters), or `None`. Company, school,
    post and other paths are not profiles.
  - `parse_list(lines)`: one `ListLine(number, link, name, problem)` per
    non-empty, non-comment line; split at the first comma.
  - `plan(lines, persons, stored)`: the names are compared with
    `normalize_text` (the ETL's existing normalisation: case, accents,
    spaces). Returns the links to add, change and remove, and the outcome of
    every line (`stored`, `not_found`, `several_persons`, `conflict`,
    `invalid`).
- **Decision**: the conflicts of FR-010 are found before matching: a
  normalized name with two different links, and a link under two different
  normalized names, make every line involved a `conflict`.
- **Decision**: when the list has no usable line, `plan` returns no change
  at all (clarification of 2026-11-13).

## R6. Idempotency and tracking

- **Decision**: the step compares the planned links with the stored rows and
  writes only the difference; `updated_at` changes only when the row changes.
  A second run over the same list writes nothing (FR-013).
- **Decision**: the step is not a "source document" of spec 021 and writes
  no tracking record or change log: the list is local configuration, not a
  collected source, and the constitution's idempotency rule is met by the
  comparison above. The run summary is the audit trail.

## R7. The run summary

- **Decision**: the flow logs one line,
  `linkedin links: lines N, stored N (added N, changed N, removed N), not
  found N, several persons N, conflicts N, invalid N`, then one line per
  unused line with the name and the reason, and writes the same as
  `data/reports/linkedin_links_report.json` (ignored by git, like the other
  reports). Without the file: `linkedin links: no list at
  data/linkedin_run/linkedin.list, nothing changed`. With a file that has no
  usable line: a warning that the list is empty and nothing changed.

## R8. Privacy

- **Finding**: the anonymizer (`pii_anonymizer`) handles CPF, e-mail and
  phone fields; it does not touch URL fields such as `cnpq_url`. A LinkedIn
  profile address is a public address of the same kind.
- **Finding**: the list lives under `data/`, which `.gitignore` already
  excludes (`data/*`); the report is under `data/reports/`, also ignored.
- **Decision**: no anonymizer change. The log prints the names of unused
  lines (needed to fix the list, FR-019) and never a link of an unmatched
  line together with other data.
- **Finding**: `exports_canonical.zip` built locally carries the links; the
  maintainer never commits the local zip. The zip committed by the workflow
  comes from GitHub Actions, which has no list.

## R9. The maintainer's alumni projects

- **Decision** (maintainer, 2026-11-13): the ETL never reads or writes the
  alumni projects. No path outside this repository appears in the code. The
  list is produced outside the run; the quickstart shows a one-off command
  the maintainer may run by hand, which only reads the alumni file and writes
  `data/linkedin_run/linkedin.list`.

## R10. Expected numbers

| What | Expected |
|------|----------|
| Lines read | 182 |
| Links stored | about 148 |
| Not found | about 34 |
| Several persons, conflicts, invalid | 0 |
| Persons, advisorships, projects, permanent ids | unchanged |
| Exports that gain the field | 5 person files, in every entry |

## R11. Limits kept

- Exact name only: a person stored under another spelling is not found.
- A person and a homonym: both exist, so the name matches two and nobody
  gets the link.
- The exports of GitHub Actions carry the field empty.
