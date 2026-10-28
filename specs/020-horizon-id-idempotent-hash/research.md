# Research: Permanent Horizon Ids and Idempotent Tracking Keys

**Feature**: [spec.md](spec.md) | **Date**: 2026-10-27

All measurements were taken on `db/horizon.db` from the 2026-10-24 local
weekly (`logs/weekly_018_validation.log`), read-only, with the scripts in
[`research-scripts/`](research-scripts/). The rerun experiment used a copy of
that database in the session scratchpad; `db/horizon.db` was never written.

---

## R1. Where the `horizon_id` is computed: a post-pass, not at every insert

**Decision**: A new weekly phase, `assign_horizon_ids`, runs after
`consolidate_duplicates` and before `export_canonical`. It reads the finished
database and derives every entity's id with pure functions, then reconciles
the result with the id history (R5) and writes the two new tables.

**Rationale**:
- Entities are created in more than a dozen places (SigPesq loaders, Lattes
  tasks, CNPq sync, enrichment, the `eo_lib` controllers). Hooking id creation
  into each one would touch every loader and still miss the merges done later
  by `consolidate_duplicates`.
- After consolidation, the database holds exactly the entities that will be
  exported, so the ids are computed on the final state, once.
- Everything the rules need is already in the database (R2): `cnpq_url` on
  researchers and groups, DOI and title on articles, and the source keys of
  initiatives and advisorships through `entity_matches` → `source_records`.
- The functions are pure (input: the entity's source data; output: the id),
  so the same functions also build the tracking keys at ingestion time (R6),
  and two rebuilds give the same result by construction.

**Alternatives considered**:
- *Assign at insert time*: rejected for the reasons above; a merge would still
  need a fix-up pass.
- *A column on every core table*: forbidden by FR-014, and those tables belong
  to `eo_lib`.

## R2. Rules per entity type, measured on the current database

`research-scripts/sim_horizon_ids.py` derives a candidate id for every row of
every entity table and counts ids shared by two rows.

| Entity (table) | Rows | Rule (priority order) | Rows per rule | Shared ids |
|---|---:|---|---|---:|
| Person (`persons`, `researchers`) | 17 124 | `lattes_id` from `researchers.cnpq_url` or the `researcher_profile` source record; else hash of normalized name | 409 lattes, 16 715 name | 0 |
| Research group (`research_groups` + `teams.name`) | 354 | CNPq id from `cnpq_url`; else hash of SigPesq name | 350 CNPq, 4 name | 2 |
| Initiative (`initiatives` without `advisorships`) | 3 043 | SigPesq project code (`sigpesq project\|<code>`), then `PJ <code>`, then Lattes identity key, then type + name | 86 / 189 / 2 756 / 12 | 0 |
| Advisorship (`advisorships`) | 8 680 | SigPesq workplan (`sigpesq workplan\|<code>\|<row>`), then `PJ <code>`, then Lattes identity key | 590 / 2 / 8 088 | 0 |
| Article (`articles`) | 6 736 | Normalized DOI; else hash of title + year + type + venue | 1 861 DOI, 4 875 hash | 73 |
| Other production (`research_productions`) | 2 807 | Hash of title + year + type | 2 807 | 8 |
| Academic education | 1 843 | Parent person id + hash of type + course + start year | — | 2 |
| Professional activity | 7 227 | Parent + hash of institution + years + role + bond | — | 53 |
| Award | 167 | Parent + hash of title + year | — | 0 |
| Proficiency | 744 | Parent + language slug | — | 0 |
| Team not a research group | 11 431 | Child of the initiative it staffs (`<initiative id>/team`) | — | 0 |
| Fellowship | 19 | Slug of name + value (`fellowship:pibiti:700`) | — | 4 |
| Knowledge area | 1 561 | Slug of normalized name | — | 7 |
| Organization, campus, types, roles, languages, education types | 494 | Slug of normalized name | — | 0 |
| **Total** | **~63 000** | | | **149** |

**What the 149 shared ids are.** They are not homonyms. They are rows the
database already holds twice for the same thing, differing only in case,
accents or punctuation, which the loaders' exact-match deduplication does not
catch:

- articles: "Coconut shell gasification numerical mod…" and "COCONUT SHELL
  GASIFICATION NUMERICAL MOD…", same year, same congress (ids 15 and 3163);
  3 of the 73 are the same DOI on two rows;
- knowledge areas: "Probabilidade e Estatística" / "Probabilidade e
  Estatistica", "Física" / "Fisica", "Redes Neurais Convolucionais." /
  "Redes Neurais Convolucionais";
- research groups: two SigPesq groups pointing to the same CNPq group
  ("Educação e Sociedade" and "Grupo de Pesquisa Educação e Sociedade");
- fellowships: four "PIBITI" rows, two of them with the same value 700.

**Decision**: Keep the rules as in the table. Shared ids are resolved by the
FR-008 suffix (R4), so every row keeps a distinct, stable id and nothing is
merged or changed in the data. The phase reports them per type (R10): they are
a deduplication backlog for a later spec, not something this spec fixes.

**Rationale**: Merging them would change the data, which is out of scope and
would break the replay equivalence (SC-008). Giving them distinct ids is the
behaviour the spec asks for, and the audit report makes them visible.

**Alternatives considered**: tightening the rules until 0 rows share an id
(for example, adding the numeric id) was rejected: it would bring back the
dependency on database ids that the spec forbids.

**Refinements adopted from the measurement**:
- DOIs are lowercased and stripped of `https://doi.org/` and
  `http://dx.doi.org/` before use.
- Fellowships include the value: the same programme name with different values
  (PIBITI 700, 900, 0) are different rows today.
- A person's `lattes_id` comes from `cnpq_url` first and from the
  `researcher_profile` source record second (both measured: 409 persons).

## R3. Id format and hash length

**Decision**: `<entity>:<origin>:<source id>` or `<entity>:<origin>:h:<12 hex>`,
children as `<parent id>/<kind>:h:<12 hex>`, reference records as
`<entity>:<slug>`. The hash is SHA-256 of the `|`-joined normalized parts,
truncated to 12 hexadecimal characters (48 bits).

**Rationale**: 48 bits gives a collision probability of about 7×10⁻⁶ for 63 000
ids of one type (birthday bound n²/2⁴⁹), and any real collision is still caught
and suffixed (R4). The longest id measured is 254 characters (a long DOI); ids
are text in new tables, so length is not a constraint. Normalization reuses
`normalize_text` from `src/core/logic/initiative_identity.py` (accents,
punctuation, case, whitespace), so the ids agree with the identity keys the
loaders already use.

**Alternatives considered**: UUIDv5 (not readable, does not show the source id);
full 64-character hashes (no gain, harder to read).

## R4. Collision suffix (FR-008)

**Decision**: After deriving all ids of a type, group the rows that share an
id. For each group:
1. Append `~` plus the first 6 hex characters of the hash of the row's source
   document of origin. This is the first `entity_matches` → `source_records`
   row of the entity, ordered by a document name. A Lattes CV is named
   `lattes:<lattes_id>`; any other file is named by its file name
   (`basename`), for example the SigPesq report.
   - Only the name, because `source_file` is stored as an absolute path,
     which differs between checkouts. The 2026-10-27 rebuild check found
     this: two rebuilds in different directories gave 150 articles different
     suffixes.
   - Not the CV file name, because it starts with the CV's position in
     `data/lattes_run/lattes.list` (`229_<name>_<lattes_id>.json`), which
     moves when a curriculum is added or removed. Found by the 2026-10-28
     GitHub Actions comparison.
2. If rows still share an id (same document, or no source record at all),
   order them by the canonical hash of their own row content (all columns
   except the numeric id) and append `~2`, `~3`, …; the first keeps the
   step-1 id.
3. Count every group in the phase report.

**Rationale**: Both steps depend only on source data and content, never on
insertion order, so two rebuilds give the same suffixes (SC-003). Step 1
separates the common case (two CVs that typed the same work differently).
Step 2 is the last resort and is still deterministic.

**Alternatives considered**: failing the run (rejected in clarification Q3);
first-come numbering (order-dependent).

## R5. Id history and aliases (FR-010 to FR-013b)

**Decision** (updated after the 2026-10-27 analysis): The id history is read,
at the start of `assign_horizon_ids`, from the first source that exists:
1. the id tables in the current database (persistent database, spec B
   onwards);
2. `db/horizon_id_history.json`, a snapshot of those tables that
   `make db-reset` (and the rule-version reset of R11) writes **before**
   deleting the database, through `src/scripts/save_horizon_id_history.py`. It
   survives local resets; the file is git-ignored;
3. the two new files inside the previously published
   `data/exports/exports_canonical.zip`. That zip is versioned in git and is
   therefore present in every checkout, including a fresh GitHub Actions run
   before spec C keeps the database.

Sources 2 and 3 are also merged when both exist, so an id published in the zip
but absent from a stale local snapshot is not lost.

Every previously published id is then resolved against the new state:
- **Still current** → nothing to do.
- **One of the current entity's candidate ids** → alias, reason "upgraded key"
  (or "rebuild" when the history came from the zip after a reset). Each entity
  carries all its candidate ids, not just the winner: a person with a
  `lattes_id` also has the name-based candidate, so `person:h:<hash of name>`
  resolves to `person:lattes:<id>`. Children carry the candidates built from
  each of their parent's candidates.
- **A merge recorded in this run** → alias, reason "merge" (R7).
- **Its natural key matches one new computed id approximately, in the same
  document** → alias, reason "key corrected" (R8).
- **Still unresolved** → stays in the alias table pointing to nothing current
  and is counted ("retired"); it is never reused (FR-012), because a new
  entity that derives the same text would by definition be the same source
  data.

**Implementation note (2026-10-27)**: the merge log is checked before the
candidate lookup, so an id that stops being current because of a merge gets the
reason "merge" even when it is also a candidate of the survivor. After the
candidate lookup, an old id whose `natural_key` equals the `natural_key` of
exactly one current id of the same type resolves to it with reason "rebuild"
(the rule-version change of FR-024), and a child whose parent resolved
follows it (`<new parent>/<same tail>`, the parent's reason).

To make the history self-sufficient, each row of the published id file carries
`rule` (which rule produced it) and `natural_key` (the normalized text the hash
was taken from; empty for source ids). Names, titles and `lattes_id` values
are already public in the existing exports, so this adds no personal data. It
also lets a rule-version change (FR-024) recompute old ids under the new rules.

**Rationale**:
- The weekly resets the database today and will keep doing so until spec B;
  the only state that survives a reset, both locally and in GitHub Actions, is
  what is versioned in git. The published zip is exactly the set of ids the
  consuming team has seen, which is the set that must keep resolving (SC-007).
- Candidate ids make "upgraded key" and "rebuild" a pure lookup, so no merge
  log is needed for those cases.

**Alternatives considered**:
- *A separate history file committed by the workflow*: a second versioned
  artifact for the same information the zip already carries.
- *Only the zip*: simpler, but loses ids that existed locally and were never
  published (no impact on consumers, but it hides local merges when testing).
- *Only the pre-reset snapshot*: lost on every fresh CI checkout until spec C.

**Constitution**: allowed by rule 4 of "Data Integrity & Persistent Incremental
Ingestion" (constitution 2.0.0, amended 2026-10-27): the published identity
history may feed a run only to keep old ids resolvable as aliases. It never
supplies entity data.

## R6. Tracking keys at ingestion time (FR-018 to FR-020)

**Decision**: The 9 call sites of `tracking_recorder.record_source_record` build
`source_record_id` with helpers from the same pure module as R2, using
source-native values that are known at ingestion time (no database id):

| Type | New key | Call site |
|---|---|---|
| `cnpq_group_payload` | CNPq group id (from `group_info["url"]`) | `src/flows/cnpq/groups.py:148` |
| `cnpq_group_member` | CNPq id + name + role + `data_inicio` + `data_fim` | `src/core/logic/strategies/cnpq_sync.py:275` |
| `cnpq_research_line` | CNPq id + normalized line name | `src/core/logic/strategies/cnpq_sync.py:540` |
| `academic_education` | `lattes:<CV lattes_id>` + course + degree + start + end + institution | `src/flows/lattes/projects.py:521` |
| `article` | `lattes:<CV>` + DOI or title + year + type + venue + volume + pages | `src/flows/lattes/projects.py:391` |
| `researcher_profile` | `lattes_id` (unchanged) | `src/flows/lattes/projects.py:203` |
| Lattes `initiative` / `advisorship` | `lattes:<CV>` + current identity key (+ type + institution for advisorships) | `src/core/logic/project_loader.py:372` |
| SigPesq rows, groups, PJ files | unchanged (already source codes) | `project_loader.py:372`, `research_group_loader.py:167`, `project_enrichment.py:887` |

`research-scripts/sim_tracking_keys.py` measures keys with more than one
canonical payload hash within one run: **1 005 today → 22** with these keys.
The 22 are items recorded twice inside the same CV.

**Same-document duplicates (FR-020)**: before processing a CV's list of items
of one kind, the task groups them by key and keeps only the item with the
smallest canonical payload hash. The database already keeps one entity for
each (verified: one `articles` row for each sampled case), so the effect on
entities is limited to which of the two near-identical versions supplies the
attributes; the replay records any such difference (quickstart step 4).

**Rationale**: The CV `lattes_id` is in the file name
(`219_Karin-Satie-Komati_9860697624155451.json`) and is the owner's
`person:lattes:` id, so the tracking key and the `horizon_id` agree without
waiting for the post-pass.

## R7. Merges (FR-010)

**Decision**: `PersonConsolidator.consolidate_pair`
(`src/core/logic/person_consolidator.py:218`) and the merges in
`src/core/logic/reference_consolidator.py` record each merge
(entity type, loser's candidate ids, winner's numeric id) in an ETL-owned table
`horizon_merge_log` before deleting the loser. `assign_horizon_ids` turns each
entry into aliases of the winner's current id, reason "merge". The winner's id
is the highest-priority candidate of the merged entity, ties broken
alphabetically, independent of which row survived.

**Rationale**: After the merge the loser's name is gone from the database, so
its candidate ids cannot be derived later; they must be captured at merge
time. The consolidators already hold the connection and both rows there.

## R8. "Key corrected" relinking (FR-013b)

**Decision**: For each unresolved previous id with a computed rule, look for new
computed ids of the same entity type that (a) did not exist in the history,
(b) share the same parent or source document (same owner CV for Lattes items,
same author set for articles, same CNPq group for members), and (c) whose
natural key is similar to the old one by `rapidfuzz.fuzz.token_sort_ratio`
≥ 90, the scorer and threshold `PersonMatcher` already uses for fuzzy name
matches (`src/core/logic/person_matcher.py:294` and `:304`). Exactly
one candidate → alias, reason "key corrected". Zero or several → counted, no
alias.

**Rationale**: Reuses the matcher's threshold, so "similar" means the same as
elsewhere in the ETL. Restricting to the same document keeps false links rare.
The `natural_key` column of the history (R5) is what makes the comparison
possible.

The implementation should import or share that value, not copy the number.

**Implementation note (2026-10-27)**: the shared value is
`horizon_identity.FUZZY_MATCH_THRESHOLD`, used by `PersonMatcher` too. The id
history keeps no source document per id (the snapshot and the published files
carry `rule`, `natural_key` and `parent_horizon_id` only), so "same document"
is applied as: same entity type, same rule and same parent (the old parent
resolved to its current id); a root (an article, a DOI-less project) is
compared only with the new ids of its type and rule. The exactly-one-candidate
condition still applies, and the zero / several cases are counted in the
report (`key_corrected_without_match`, `key_corrected_ambiguous`).

## R9. Idempotent writes (FR-022, FR-023)

### R9.1 False change logs

**Cause** (read in code): `record_change` is called with `operation="update"`
and `changed_fields` = every non-empty attribute, without comparing to what is
stored:
- researchers: `src/flows/lattes/projects.py:186–240` sets `needs_update = True`
  whenever `citation_names`, `cnpq_url` or `resume` is present, calls
  `researcher_ctrl.update` and logs all three fields (435 rows in the rerun);
- initiatives: `src/core/logic/project_loader.py:553` logs every non-empty
  tracked attribute of an existing initiative (3 371 rows in the rerun).

**Decision**: Before updating, snapshot the stored values of the tracked
attributes; compare canonical forms (same canonicalization as the payload
hash); update and log only when at least one differs, with `changed_fields`
listing only those and `before`/`after` holding their old and new values.

### R9.2 Team members rewritten

**Probable cause** (read in code; confirmation in progress, see R9.3):
`TeamSynchronizer.sync_members` (`src/core/logic/team_synchronizer.py:177`) has
replace semantics per call: it adds the roster it receives and removes every
member of the same roles that is not in that roster. A Lattes project appears
in each participant's CV, and each CV's roster can differ (other members, other
start dates). The team ends up with whatever the last CV processed left, and
that depends on the state the run starts from: on a reset database and on a
populated one, the same CVs in the same order give different results. That is
the 713 rewritten rows and the 57 changed `start_date` values.

**Decision**: Make membership a function of all contributions, not of the last
call. A new ETL-owned table `team_member_contributions`
(team id, person id, role id, source document key, start date) records what
each document says. After each document, the team's members of the managed
roles are recomputed as the union over documents, with `start_date` = the
earliest contributed date; the synchronizer then writes only the difference
(adds missing, removes members no document contributes any more, updates a
date only when the earliest date changed).

**Consequence**: on a reset database the final team is the union of all CVs'
rosters, where today it is order-dependent. The replay (quickstart step 4)
measures how many `team_members` rows differ from today's output; these are
the only expected differences in existing tables' content besides tracking.

### R9.3 Rerun confirmation (2026-10-27)

A fresh copy of the 2026-10-24 database was re-run with
`ingest_lattes_projects`. It reproduced the same numbers: 713 rows rewritten
with new ids, 57 membership rows lost, 56 added. The changes were then traced
team by team.

| Teams affected | Count | Fed by more than one source document | Shared by more than one initiative | Neither |
|---|---:|---:|---:|---:|
| Rows rewritten (same content, new id) | 244 teams | 207 | 26 | 28 |
| Content changed | 55 teams | 20 | 23 | 25 |

For comparison, only 327 of the 2 907 Lattes-fed teams have more than one CV,
and 251 of 11 446 teams are linked to more than one initiative. So there are
three causes:

1. **Several CVs sync the same team** (replace semantics per call, R9.2): most
   of the rewrites.
2. **One team shared by two initiatives.** The team lookup is by normalized
   name, so two Lattes projects with the same title but different years share
   a team, and each overwrites the other's roster. Example: "Resposta do
   pinhão-manso…", initiatives 1076 and 4090, team 1425, same CV.
3. **Person resolution depends on the database state** (the 25 rows in neither
   group, all `Coordinator`/`Researcher`). Example: in the original run, Fabrício
   Albani Oliveira's CV resolved "Ciro Alexandre Torres Alves" to person 7710,
   because person 11030 "Ciro Alexandre Alves Torres" (a researcher) did not
   exist yet at that point of the run. In the rerun both exist, the token-sort
   score of the two names is the same, and the matcher picks 11030. The
   resulting team rows differ.

**Decisions**:
- Causes 1 and 2: the contribution table of R9.2 solves both, because the
  team's members become the union over documents and over initiatives. The
  document key carries the initiative as well
  (`lattes:<cv>#<initiative identity key>`).
- Cause 3 is not a write bug. A fresh run resolves names against a database
  that is still being filled, while a rerun resolves them against the complete
  one. Two measures:
  - a deterministic tie-break in `PersonMatcher` when several candidates have
    the same best score: prefer a researcher with `lattes_id`, then the
    exact normalized name, then the smallest name-based `horizon_id`
    candidate, never the database order;
  - the idempotency check (SC-002) is measured as a **fixpoint**: on a
    populated database, the second and third passes over the same input must
    be identical. The first pass may still move the few names whose best
    match did not exist yet when the database was built. The validation
    report counts them (25 rows today).
- **Accepted by the maintainer on 2026-10-27**: SC-002 is measured as a
  fixpoint (spec FR-023a, FR-023b, SC-002 updated). The stronger alternative,
  a two-pass person resolution in fresh runs, was rejected because it would
  change today's matching results.

## R10. Audit report (constitution IV)

**Decision**: `assign_horizon_ids` writes
`data/reports/horizon_ids_report.json` and logs its summary: ids per entity type
and rule, collision groups per type with examples (R2: 149 today), aliases
created per reason, retired ids, "key corrected" attempts that found zero or
several candidates, and the rule version. Nothing in it is personal data
beyond names and titles already exported.

## R11. Rule version (FR-024)

**Decision**: `HORIZON_RULE_VERSION` (an integer constant in the pure module)
is stored in a one-row ETL-owned table `horizon_meta` and in the header of the
id file. At the start of the weekly, the orchestrator compares it with the
database's: if the database exists and the versions differ, it runs the reset
target before the phases and logs why. Today `make weekly-flows` always resets,
so the check only becomes visible when spec B removes the unconditional reset;
it is implemented and tested now so spec B only has to drop `db-reset`.

## R12. Export files

**Decision**: `export_canonical` writes `horizon_ids_canonical.json` and
`horizon_id_aliases_canonical.json` into the output directory; the existing
`zip_exports_task` walk (`src/flows/exports/canonical_data.py:284`) already
includes every file in that directory, so no zip change is needed. No existing
export file is touched. Shapes in
[contracts/export-files.md](contracts/export-files.md).

`src/scripts/export_parquet.py` pins "id-like" columns to a nullable integer
type; the plan checks its detection so that `horizon_id`, `alias_horizon_id`
and `natural_key` stay text (FR-017).

## R13. Constraints confirmed

- No change to `eo_lib` or any third-party library: new tables only, created by
  `src/db/migrations.py` (`CREATE TABLE IF NOT EXISTS`, recorded in
  `schema_migrations`).
- `rapidfuzz` is already a dependency (`RAPIDFUZZ_IMPLEMENTATION=fallback` in
  the workflow).
- The ids do not use `HORIZON_PII_HMAC_KEY`, so local and CI runs produce the
  same ids (SC-006).
- No Docker change.
