# Feature Specification: Permanent Horizon Ids and Idempotent Tracking Keys

**Feature Branch**: `023-horizon-id-idempotent-hash`

**Created**: 2026-10-27

**Status**: Draft

**Input**: User description: "Give every entity a permanent, readable Horizon id derived only from source data, make the tracking keys and payload hashes idempotent on top of it, and publish the id in new export files without changing any existing table or export."

## Context

The weekly ETL rebuilds `db/horizon.db` from scratch on every run. The
maintainer and their manager decided on 2026-10-26 that the database will
persist between runs and that the ETL will only fetch and write what it does not
already have, comparing content hashes. The hashes persist with the database
and must be idempotent: the same information always yields the same key and
the same hash, in every run, and never becomes a second row.

This spec is the first of four (see `PLANO_HASH_IDEMPOTENTE.md` at the
repository root, a personal planning note). It does not skip any work and does
not make the run faster by itself. It makes identities and hashes stable, so
the later specs can safely skip unchanged documents (spec B), keep the database
in GitHub Actions (spec C) and download only what is missing (spec D).

### Who consumes the data

Another team uses this ETL's database and exports to build a new project that
combines them with other projects. It is not known whether that team reads the
database, the exports or both. The only id it receives today is the numeric
autoincrement id of each row (`researchers_canonical.json`: `"id": 1` for
Carlos Roberto Pires Campos). That number comes from the order in which the
run wrote the rows. Because the database is rebuilt every week, the same
researcher can get a different id in each export. With a persistent database
the id would still change on every `make full-refresh` and whenever
`consolidate_duplicates` merges two persons.

The core tables (`researchers`, `initiatives`, `articles`, ...) belong to the
third-party library `eo_lib` and use integer autoincrement keys. Third-party
libraries stay unchanged.

### What was measured (2026-10-26/27, on the 2026-10-24 local weekly database)

**Re-running a phase on a populated database is not idempotent.**
`ingest_lattes_projects` was run a second time on a copy of the database, with
identical inputs and no portal access. It created no duplicate initiatives,
persons or teams, but:

| Effect of the second run | Count |
|---|---:|
| Duration | 11 min (7.4 min in the original weekly) |
| `entity_change_logs` "update" rows with no real change | 3 806 (3 371 initiatives, 435 researchers) |
| `team_members` rows deleted and re-inserted with new ids | 713 |
| `team_members` rows whose `start_date` changed | 57 removed, 56 added |
| New `source_records` | 23 |

**Four tracked types build their key from internal ids.**

| Type | Key today | Where |
|---|---|---|
| `cnpq_group_payload` | `research_groups.id` | `src/flows/cnpq/groups.py:151` |
| `cnpq_group_member` | `research_groups.id` + name + role | `src/core/logic/strategies/cnpq_sync.py:278` |
| `cnpq_research_line` | `research_groups.id` + line name | `src/core/logic/strategies/cnpq_sync.py:543` |
| `academic_education` | `researchers.id` + course + degree + start year | `src/flows/lattes/projects.py:523` |

`research_groups.id` is the sequence number assigned when the SigPesq loader
creates the group, not the CNPq id, which is in the group URL
(`espelhogrupo/4439471564090237`). `researchers.id` changes when persons are
merged: the education "Política Social | Doutorado | 2020" was recorded as
`9193|...`; after the merge the person became researcher 7664, and the second
run recorded the same education again as `7664|...`. The 23 new
`source_records` were all of this kind.

**Many keys stand for more than one thing.** Within one fresh run, 1 005 keys
map to more than one payload hash:

| Type | Keys with more than one hash | Cause |
|---|---:|---|
| Lattes `article` | 573 | The same work is in each co-author's CV, with a different `authors_str` |
| Lattes `initiative` | 199 | The same project is in each participant's CV, with a different `description` and `raw_members` |
| `cnpq_group_member` | 176 | Two membership periods (`data_inicio`/`data_fim`) for the same person and role |
| Lattes `advisorship` | 27 | Two items of the same CV that differ only in `type` or `institution` |
| SigPesq `advisorship` | 26 | The same workplan in two reports, with `Valor` as the number `600` in one and the text `"600"` in the other |
| `academic_education` | 3 | Differ only in `end_year` or `description` |
| SigPesq `research_group` | 1 | The same group listed twice in the report, once with an acronym and once without |

A read-only simulation with source-native keys (CNPq group id from the URL,
`lattes_id` from the CV file name, membership dates, article type, venue,
volume and pages) and a canonical hash (empty values normalized, numbers and
strings compared as trimmed text) leaves about 22, all items recorded twice
inside the same CV, for example the same article entered twice with different
author-list formatting. The database already keeps one `articles` row for each
of them.

**Source-native ids available.**

| Entity | Has a source id | Without one |
|---|---|---|
| Researchers | `lattes_id` for 409 of 7 645 | 7 236 researchers and 9 479 other persons (students, external) |
| Research groups | CNPq id for 351 of 354 | 3 |
| Articles | DOI for 1 861 of 6 736 (3 DOIs appear twice) | 4 875 |
| SigPesq projects and workplans | code for every row | — |

No two of the 17 124 persons share a normalized name today. 237 initiatives
share a normalized name with another initiative, and 137 pairs of DOI-less
articles share a normalized title and year.

**What already works.** The payload hash is a SHA-256 of the JSON with sorted
keys (`stable_hash`, `src/tracking/recorder.py:36`) and contains no run date and
no database id. `source_records` has a unique index on source system, entity
type, record id and payload hash, so "is this exact record already here?" is
one indexed lookup. `researcher_profile` (by `lattes_id`), SigPesq projects (by
code) and enrichment records (`PJ <code>`) already use source-native keys. The
LGPD anonymizer is already idempotent (`src/core/logic/pii_anonymizer.py:102`).
Schema additions go through `src/db/migrations.py`.

## Clarifications

### Session 2026-10-27

- Q: Do aliases survive a full rebuild (make full-refresh or a rule-version change), which wipes the database? → A: Yes. Before the reset the ETL saves the previous database's ids and aliases; after the rebuild, every previously assigned id that is no longer current becomes an alias of the current id of the same entity, found through the source ids that entity had.
- Q: When the source corrects the text a computed id is derived from (a title typo fixed, a person's name changed), what happens to the old id? → A: The ETL tries to relink it. When an id disappears and a similar one appears in the same source document (same CV, same group), with an approximate match above the threshold the ETL already uses, the old id becomes an alias of the new one with reason "key corrected".
- Q: How is a collision resolved when two different entities derive the same horizon_id (e.g. two homonymous students without lattes_id)? → A: Deterministic suffix. The colliding ids get a suffix with the hash of an extra source field (the source document of origin, e.g. the SigPesq report row or the CNPq group), the same in every rebuild; if that still does not separate them, a fixed order (~2, ~3) based on the canonical content hash is applied and the case is logged. The run never fails because of a collision.
- Q: The rerun showed that fuzzy person resolution in a fresh run depends on which persons already exist (25 team rows change on the first rerun of the 2026-10-24 data). How is SC-002 measured? → A: As a fixpoint: on a populated database, the second and third passes over the same input are identical; the first pass may still move names whose best match did not exist yet when the database was built, and those changes are counted and reported. Person resolution also gets a deterministic tie-break between equal scores.
- Q: (analysis) The published-id history read from the previous export conflicts with constitution 1.0.0 ("database re-creatable only from sources"). How is it resolved? → A: The constitution was amended to 2.0.0 ("Data Integrity & Persistent Incremental Ingestion"); rule 4 allows the published identity history as an input, only to keep old ids resolvable as aliases.
- Q: (analysis) The old-vs-new replay cannot be identical, because team membership becomes the union of all documents and same-CV duplicates keep a fixed version. → A: Accept and list: SC-008 names these two differences as expected; they are counted and explained, and any other difference is a bug.
- Q: (analysis) On a full rebuild, where does the previous id history come from? → A: From the previous database when it exists (its id tables are saved to a snapshot file before the reset), otherwise from the published exports_canonical.zip.
- Q: (analysis) Should the published id file carry the extra columns rule, natural_key and parent_horizon_id? → A: Yes, six columns, so that a history read back from the zip can resolve rebuilds, rule-version changes and corrected keys.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A consumer links the same entity across weeks and rebuilds (Priority: P1)

The other team takes this week's export and last month's export, or an export
made after a full rebuild, and needs to know which records are the same
researcher, group, project or article. Today the only id it has is the numeric
row id, which can change every week. After this spec every entity also has a
`horizon_id` that is built only from source data, is readable (it shows the
source id when there is one) and stays the same for the same entity in every
run and every rebuild.

**Why this priority**: It is what the other team needs, and it is the identity
the idempotent keys of User Story 2 are built on.

**Independent Test**: Rebuild the database from scratch twice from the same
frozen inputs, export both, and compare the new id file: every entity has the
same `horizon_id` in both, even where the numeric ids differ.

**Acceptance Scenarios**:

1. **Given** a researcher with `lattes_id` 9860697624155451, **When** any run exports the data, **Then** the new id file lists that researcher as `person:lattes:9860697624155451` together with the numeric id used in the existing export files.
2. **Given** two rebuilds from scratch on the same inputs, **When** their id files are compared, **Then** the set of `horizon_id` values and the entity each one designates are identical.
3. **Given** a research group whose URL is `.../espelhogrupo/4439471564090237`, **When** it is exported, **Then** its `horizon_id` is `group:cnpq:4439471564090237`.
4. **Given** a person with no `lattes_id`, **When** it is exported, **Then** its `horizon_id` is derived from the normalized name and contains no CPF, e-mail or phone, in clear or hashed.
5. **Given** a local run and a GitHub Actions run on the same inputs, **When** their id files are compared, **Then** they are identical, although the two environments use different anonymization secrets.

---

### User Story 2 - Processing the same input twice changes nothing (Priority: P1)

The maintainer runs a phase a second time on a populated database with
identical inputs. Nothing changes: no new tracking record, no change log, no
row rewritten, no date shifted. Only new or changed information is written.
This is the property a persistent database relies on.

**Why this priority**: Without it a persistent database fills with false change
logs and duplicate tracking records every week, and the later specs cannot
tell a real change from noise.

**Independent Test**: Run each source phase three times on a populated
database with the same inputs and compare every table, ids included, after the
second and the third pass (fixpoint); report what the first extra pass changed.

**Acceptance Scenarios**:

1. **Given** a database populated by a full run and passed over once more, **When** `ingest_lattes_projects` runs again with identical inputs, **Then** no `entity_change_logs` row, no `source_records` row and no `team_members` change is produced (today every pass adds 3 806, 23 and 713).
2. **Given** the same populated database, **When** the first extra pass runs, **Then** the only changes are persons resolved differently because their best match now exists, and they are counted in the run log.
3. **Given** a CNPq group page recorded in one run, **When** the same page is processed in a later run, **Then** its tracking key is the same, because it uses the CNPq group id and not `research_groups.id`.
4. **Given** a person merged by `consolidate_duplicates`, **When** that person's CV is processed again, **Then** the academic educations are recognized as already recorded and are not written again.
5. **Given** a SigPesq workplan whose `Valor` is `600` in one report and `"600"` in another, **When** both are processed, **Then** they produce the same payload hash.
6. **Given** an item recorded twice inside the same CV with the same key, **When** the CV is processed, **Then** the item is kept once and the version kept is always the same, in every run.
7. **Given** a team whose members are unchanged in the input, **When** the team is synchronized again, **Then** no member is deleted and re-inserted and every `start_date` stays the same.

---

### User Story 3 - Merges and better ids never break an old reference (Priority: P2)

When `consolidate_duplicates` merges two persons, or when an entity gains a
better source id (a person who only had a name gains a `lattes_id`; a SigPesq
group gains a CNPq URL), the entity's `horizon_id` may change. The old one is
kept as an alias that points to the current one, and it is published, so a
consumer holding the old id can still find the entity.

**Why this priority**: Merges happen every week; without aliases the other
team's references to merged persons would dangle.

**Independent Test**: Merge two persons in a test database, one with a
`lattes_id` and one known only by name, and check the current id and the alias
list.

**Acceptance Scenarios**:

1. **Given** two persons, one with a `lattes_id` and one known only by name, **When** they are merged, **Then** the survivor's `horizon_id` is the `lattes_id`-based one and the name-based one is listed as its alias with reason "merge".
2. **Given** two merged persons of equal priority, **When** they are merged, **Then** the survivor's id is the alphabetically first, whatever the processing order.
3. **Given** a person known only by name, **When** a later run finds their `lattes_id`, **Then** the `horizon_id` becomes `person:lattes:<id>` and the previous one is listed as an alias with reason "upgraded key".
4. **Given** a DOI-less article published as `article:lattes:h:…` whose title the author corrects by one letter, **When** the CV is processed again, **Then** the new id is current and the old one is its alias with reason "key corrected".
5. **Given** any `horizon_id` that was ever published, **When** a later export is produced, **Then** it is either a current id or an alias, and it never designates a different entity.

---

### User Story 4 - Existing consumers see no format change (Priority: P2)

Whoever reads the database or the exports today keeps working without changes.
No existing table gains, loses or changes a column, type or index, and no
existing export file gains or loses a field. Everything new goes beside them,
in new tables and new export files.

**Why this priority**: The other team has already built on the current format;
redoing that work is the cost this spec must avoid.

**Independent Test**: Compare the schema of every existing table and the field
set of every existing export file before and after the change.

**Acceptance Scenarios**:

1. **Given** the schema of every table before the change, **When** the migration runs, **Then** every existing table has exactly the same columns, types and indexes, and only new tables were added.
2. **Given** the existing `*_canonical.json` files, **When** a run exports after the change, **Then** each file has exactly the same fields as before, and the numeric `id` keeps its meaning.
3. **Given** the export package, **When** it is produced, **Then** it also contains the new id file (entity type, numeric id, `horizon_id`) and the new alias file (alias, current `horizon_id`).
4. **Given** the existing Parquet conversion script, **When** it converts the new files, **Then** `horizon_id` stays text and is not turned into an integer column.

---

### User Story 5 - A change of rules triggers one clean rebuild (Priority: P3)

The rules that build keys, hashes and `horizon_id` values are versioned. When
the code's version differs from the version recorded in the database, the next
run rebuilds the database from scratch once, instead of mixing old and new
keys, and continues from there.

**Why this priority**: It protects the persistent database of the later specs
from silent duplicates after a rule change. Until those specs land, the weekly
rebuilds every week anyway.

**Independent Test**: Record an older rule version in a populated database and
start a run.

**Acceptance Scenarios**:

1. **Given** a database whose recorded rule version differs from the code's, **When** a run starts, **Then** it rebuilds from scratch and records the new version, with a log line saying why.
2. **Given** a database whose recorded version equals the code's, **When** a run starts, **Then** no rebuild is triggered by this check.

---

### Edge Cases

- **Two different entities derive the same `horizon_id`** (for example two
  future homonyms without `lattes_id`): they must never share an id or be
  merged because of it. Both ids get a suffix from their source document of
  origin, or `~2`/`~3` in canonical-hash order if that is not enough (FR-008);
  the run continues and the collision is logged. Each rule's
  collisions are measured on the current database before implementation.
- **The same DOI on two articles** (3 cases today, differing only in case or
  formatting): DOIs are normalized before the id is built, and the result
  follows the database's current outcome for those articles.
- **An article gains a DOI later**: its id moves from the title-based form to
  the DOI-based form, and the old one becomes an alias with reason "upgraded
  key".
- **A parent's id changes** (merge or upgrade) and child items (academic
  educations, professional activities, awards, proficiencies, fellowships) are
  prefixed with the parent's id: the children's ids change with it and their
  old ids also become aliases.
- **An entity is deleted** (for example when a later spec removes an item the
  author deleted from the CV): its `horizon_id` is never given to a different
  entity. If the same item reappears, it gets the same id again, because the
  id is derived from the same source data.
- **An entity has no usable natural key** (for example a placeholder such as
  "Unknown Institution"): it still gets a deterministic id from its normalized
  name and type, and the count of such entities is logged.
- **A rebuild changes the numeric ids**: the existing exports carry the new
  numeric ids as they do today; the new id file maps them to the unchanged
  `horizon_id` values.
- **A rebuild would lose an "upgraded key" alias** (a person published as
  `person:h:…` who later gained a `lattes_id` is born with the `lattes_id` in
  the rebuild): the saved history from before the reset turns the old id back
  into an alias of the current one (FR-013a).
- **The source corrects the text of a computed key** (an author fixes a typo
  in a DOI-less article title; a person without `lattes_id` changes name): the
  new computed id is relinked to the old one as an alias when the match is
  unambiguous and above the existing threshold (FR-013b); otherwise the old id
  stops appearing and the case is logged.
- **No previous database exists** (fresh checkout, GitHub Actions today): the
  history comes from the id and alias files of the published
  `exports_canonical.zip`. Only when that zip has no id files either (the very
  first run after this spec) does the history start from scratch.
- **Names with accents, punctuation or different case** ("Karin Satie Komati"
  and "KARIN SATIE KOMATI"): they normalize to the same text before hashing.

## Requirements *(mandatory)*

### Functional Requirements

**Horizon id**

- **FR-001**: Every entity the ETL stores (persons, research groups,
  initiatives of every type, advisorships, articles and other productions,
  academic educations, professional activities, awards, proficiencies,
  fellowships, and reference records such as campuses, knowledge areas,
  organizations, initiative and production types, roles and languages) MUST
  have exactly one current `horizon_id`.
- **FR-002**: A `horizon_id` MUST be derived only from source data, never from
  a database id or from the order of processing, so the same source data
  always yields the same id, in every run, in every rebuild and in every
  environment.
- **FR-003**: When the source provides an id, the `horizon_id` MUST contain it
  in readable form, as `<entity>:<origin>:<source id>`: `person:lattes:<lattes_id>`,
  `group:cnpq:<CNPq group id>`, `initiative:sigpesq-pj:<project code>`,
  `advisorship:sigpesq-pt:<workplan code>-<row id>`, `article:doi:<normalized DOI>`.
- **FR-004**: When the source provides no id, the `horizon_id` MUST be
  `<entity>:<origin>:h:<first 12 hexadecimal characters of the SHA-256 of the
  normalized natural key>`: persons without `lattes_id` by normalized name;
  Lattes projects and advisorships by their current identity keys; DOI-less
  articles by normalized title, year, type and venue.
- **FR-005**: Child items (academic educations, professional activities,
  awards, proficiencies) MUST be identified as their parent's
  `horizon_id` followed by the item kind and the hash of the fields that
  distinguish the item.
- **FR-006**: Reference records MUST use a readable slug of the normalized
  name (for example `campus:serra`, `knowledge-area:educacao`). Fellowships
  are reference records shared by many advisorships and MUST also carry their
  value, because the same programme name exists with different values
  (`fellowship:pibiti:700`, `fellowship:pibiti:900`).
- **FR-007**: A `horizon_id` MUST NOT contain a CPF, an e-mail address or a
  phone number, in clear or hashed, and MUST NOT depend on the anonymization
  secret.
- **FR-008**: Two different entities MUST NOT share a `horizon_id`. When two
  entities derive the same id, every colliding id MUST get a suffix with the
  hash of an extra source field, the source document of origin (for example
  the SigPesq report row or the CNPq group page), so the result is the same in
  every rebuild. If that still does not separate them, they MUST get `~2`,
  `~3`, … in the order of their canonical content hash, never in processing
  order. Every collision MUST be counted in the run log, and a collision MUST
  NOT fail the run.
- **FR-009**: When source ids of different priority exist for one entity, the
  highest priority wins: for persons, `lattes_id` before name; for groups, CNPq
  id before SigPesq name; for articles, DOI before title.

**Aliases**

- **FR-010**: When two entities are merged, the survivor MUST keep the
  highest-priority id (ties broken alphabetically) and the other id MUST become
  an alias of it, with reason "merge".
- **FR-011**: When an entity gains a higher-priority source id, its current
  `horizon_id` MUST switch to the new one and the previous one MUST become an
  alias, with reason "upgraded key". The same applies to the ids of its child
  items.
- **FR-012**: A `horizon_id` that was ever assigned MUST never designate a
  different entity; aliases MUST point to the current id, following chains so
  that no alias points to another alias.

**Storage and exports (compatibility)**

- **FR-013**: The ETL MUST store the current id of each entity and the aliases
  in new ETL-owned tables, created through the project's migration mechanism:
  one mapping entity type and numeric id to `horizon_id`, and one mapping alias
  to current `horizon_id` with reason and creation time.
- **FR-013a**: The id and alias history MUST survive a full rebuild (`make
  full-refresh` or a rule-version change). Before the reset, the ETL MUST save
  the previous database's id tables to a snapshot file outside the database.
  After the rebuild, the history MUST be read from the previous database's
  tables when they exist, else from that snapshot, else from the id and alias
  files of the published `exports_canonical.zip` (fresh checkout, GitHub
  Actions before spec C). Every previously
  assigned id that is no longer current MUST become an alias, with reason
  "rebuild", of the current id of the same entity, found through the source ids
  that entity had. Aliases already in the saved history MUST be carried over
  unchanged, re-pointed to the current id.
- **FR-013b**: When a computed id (FR-004, FR-005) disappears from a source
  document and a new computed id of the same entity type appears in the same
  document (same CV, same CNPq group, same SigPesq report row set), and the
  two natural keys match approximately above the similarity threshold the ETL
  already uses for name and title matching, the old id MUST become an alias of
  the new one with reason "key corrected". Below the threshold, or with more
  than one candidate above it, no alias is created and the case is counted in
  the run log.
- **FR-014**: No existing table MAY gain, lose or change a column, a type or an
  index.
- **FR-015**: No existing export file MAY gain or lose a field; the numeric
  `id` MUST keep its current meaning.
- **FR-016**: The export package MUST contain two new files: an id file with
  one row per entity (entity type, numeric id, `horizon_id`, rule, normalized
  natural key, parent `horizon_id`) and an alias file (alias, current
  `horizon_id`, reason, creation time). The natural key holds only names and
  titles that the existing exports already publish.
- **FR-017**: If the existing Parquet conversion is applied to the new files,
  `horizon_id` MUST stay text.

**Idempotent tracking**

- **FR-018**: Every tracked source record key MUST be built from `horizon_id`
  values and source-native fields, never from database ids. In particular the
  CNPq payload, member and research line keys MUST use the CNPq group id, and
  the academic education key MUST use the person's `horizon_id`.
- **FR-019**: Every key MUST include the fields that distinguish otherwise
  identical items: the CV of origin for Lattes items, membership dates for
  CNPq members, type, venue, volume and pages for articles, type and
  institution for Lattes advisorships, end year and institution for academic
  educations.
- **FR-020**: An item recorded twice inside the same source document with the
  same key MUST be kept once, always choosing the same version by a fixed rule
  that does not depend on processing order.
- **FR-021**: The payload hash MUST be computed on a canonical form: empty
  values (null, NaN, the text "nan", empty text) treated alike, numbers and
  strings compared as trimmed text, keys sorted.
- **FR-022**: The ETL MUST NOT write an update or a change log entry when no
  stored value actually changes.
- **FR-023**: Team membership synchronization MUST NOT delete and re-insert
  unchanged members, and MUST give the same `start_date` for the same input.
  A team's members MUST be the union of what every contributing document and
  initiative says, independent of processing order and of the database state
  the run starts from.
- **FR-023a**: When several persons tie for the best name-match score, person
  resolution MUST pick one by a fixed rule that does not depend on database
  order (researcher with `lattes_id` first, then exact normalized name, then
  the smallest name-based `horizon_id` candidate).
- **FR-023b**: Idempotency is measured as a fixpoint: once a database has been
  populated and passed over again, further passes over identical inputs MUST
  write nothing. Changes in the first pass caused by person resolution against
  a fuller database MUST be counted in the run log.

**Rule version**

- **FR-024**: The rules for keys, payload hashes and `horizon_id` values MUST
  carry a version recorded in the database. A run that finds a different
  recorded version MUST rebuild the database from scratch once, record the new
  version and log why.

**Constraints**

- **FR-025**: Third-party libraries (including `eo_lib`) MUST stay unchanged.
- **FR-026**: The feature MUST work locally and in GitHub Actions, and MUST NOT
  require any change to Docker.

### Key Entities

- **Horizon id**: the permanent, readable identity of one entity, derived from
  source data. Attributes: entity type, the numeric id of the row it
  designates today, the id text, the source and rule it was derived from.
- **Horizon id alias**: an id that no longer is current, pointing to the
  current id of the same entity. Attributes: alias, current id, reason (merge,
  upgraded key, rebuild, key corrected), creation time. Survives full rebuilds.
- **Tracked source record**: one record received from a source, as already
  stored in `source_records`; its key changes content (stable, source-based),
  not shape.
- **Payload hash**: the fingerprint of a source record's canonical content.
- **Rule version**: the version of the key, hash and id rules recorded with
  the database.
- **Horizon id candidate**: every id an entity could be known by (the current
  one plus lower-priority ones, such as a person's name-based id when it also
  has a `lattes_id`); used to resolve previous ids.
- **Merge record**: a merge done by `consolidate_duplicates`, with the merged
  entity's candidate ids captured before deletion and the survivor.
- **Team member contribution**: what one source document says about one team
  member (person, role, start date); a team's members are the union of the
  contributions.
- **Id history snapshot**: the previous database's id tables, saved to a file
  before a reset so the rebuild can turn old ids into aliases.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Two rebuilds from scratch on the same frozen inputs give the same
  `horizon_id` to 100% of entities, even where numeric ids differ.
- **SC-002**: On a populated database, the second and third passes of each
  source phase over identical inputs are identical: 0 change log entries, 0 new
  tracking records and 0 rewritten or changed rows in any table (today, for
  `ingest_lattes_projects` alone, every pass adds 3 806, 23 and 713). The first
  pass may only differ through person resolution against a fuller database;
  those changes are counted and reported (25 team rows on the 2026-10-24 data).
- **SC-003**: 0 `horizon_id` values are shared by two entities, and 100% of
  stored entities have one; a test with two homonymous persons without
  `lattes_id` gives them two distinct ids, identical across two rebuilds.
- **SC-004**: 0 tracking keys contain a database id, and 0 keys map to more
  than one payload hash within one run (today: 1 005).
- **SC-005**: 100% of existing tables keep their schema and 100% of existing
  export files keep their field set; the consuming team needs no change to
  keep reading them.
- **SC-006**: A local run and a GitHub Actions run on the same inputs produce
  identical id files.
- **SC-007**: After a merge, and after a full rebuild, 100% of previously
  published ids resolve, directly or through the alias file, to the current id
  of the same entity.
- **SC-008**: A replay of the old and new code on the same frozen inputs, each
  from a reset database, produces the same entities and the same existing
  export files, except for: the new tables and export files; the tracking key
  values and the false change logs that disappear; team members of teams fed
  by several documents or initiatives (now the union, with the earliest start
  date); and the attributes of same-CV duplicate items where the kept version
  differs from today's. Each of these differences is counted and explained in
  the validation report; any other difference is a defect.

## Assumptions

- Constitution 2.0.0 (amended 2026-10-27) allows a persistent, incremental
  database and the published identity history as an input for aliases only.

- The weekly still rebuilds the database every run until spec B; this spec
  must be correct both on a reset database and on a populated one.
- The first run after this spec is a full rebuild, because no existing
  tracking key is in the new format. Numeric ids change once then, as they do
  every week today.
- Names and `lattes_id` values are public and already appear in the exports;
  using a hash of the normalized name as an id is acceptable. CPF, e-mail and
  phone are not (LGPD).
- Normalization reuses the project's existing text normalization (accents,
  punctuation and case removed, whitespace collapsed).
- The consuming team's needs are not known in detail; additive change (new
  tables, new files) is the compatibility rule chosen with the maintainer on
  2026-10-27. Changing content where needed is accepted.
- The `horizon_dashboard_h` keeps reading the existing exports unchanged.
- The Parquet conversion (`src/scripts/export_parquet.py`) is no longer run by
  the weekly flow; it is only relevant if someone runs it on the new files.
- Out of scope, covered by later specs: skipping unchanged documents and the
  handling of items and documents that disappear from a source (spec B),
  keeping the database between GitHub Actions runs (spec C), downloading only
  new and rotating items (spec D).
- Validation runs locally first; GitHub Actions comes after local validation.
