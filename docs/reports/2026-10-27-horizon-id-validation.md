# Horizon Ids and Idempotent Hashes — Validation Report (spec 020)

Date: 2026-10-27 · Spec: `specs/020-horizon-id-idempotent-hash/` · Branch:
`023-horizon-id-idempotent-hash` · Machine: the maintainer's local machine.

## 1. Summary

- **Every entity has a permanent, readable id** (`horizon_id`), derived only
  from source data: 62,227 entities, 0 shared ids. Two rebuilds from scratch in
  different directories give identical id files (SC-001).
- **Re-running a phase on the same inputs no longer changes the database**
  (SC-002). The old code added 3,806 change logs and rewrote 354 team member
  rows on every pass. Now passes 2 and 3 of `ingest_lattes_projects`,
  `lattes_advisorships` and `cnpq_sync` leave every table identical, except 27
  change logs of the one "[Nome-nao-identificado]" person (TD-022, a known data
  defect kept out of this spec).
- **No existing table or export changes format** (SC-005). The migrations only
  add 6 ETL-owned tables, and the export only adds 2 files.
- **Old ids never break**: a merge, a better source id, a rebuild or a
  corrected key turns the old id into an alias in
  `horizon_id_aliases_canonical.json`. `make db-reset` saves the id history
  first.
- **Defects found and fixed during the validation**, all in the ETL:
  - advisorship members deleted and re-inserted on every run;
  - CNPq member end dates oscillating between name spellings;
  - false "create" change logs;
  - collision suffixes that depended on the checkout path;
  - 8 articles that lost their DOI with the new CV order.
- **Pending**: the GitHub Actions comparison (SC-006, T061). It needs a
  manual dispatch on the fork, after the maintainer's go-ahead.

## 2. Success criteria

| Criterion | Target | Result | Status |
|---|---|---|---|
| SC-001 two rebuilds | same `horizon_id` for 100% of entities | Two replays of the new code in different directories: 62,227 vs 62,227 ids, identical on (`entity_type`, `horizon_id`, `natural_key`); 157 vs 157 aliases, identical | Met |
| SC-002 fixpoint | passes 2 and 3 identical | All tables identical except 27 `entity_change_logs` rows, all on the "[Nome-nao-identificado]" person (TD-022) | Met, with the TD-022 exception |
| SC-003 unique ids | 0 shared, 100% assigned, homonyms distinct and stable | 0 shared ids; every row of every entity table has one; homonym test passes across two rebuilds; 149 collision groups get stable suffixes | Met |
| SC-004 tracking keys | 0 database ids in keys; 0 keys with more than one hash | 0 keys built from database ids (every CNPq/Lattes key starts with `cnpq:` or `lattes:`); keys with more than one hash 1,005 → 1 (one SigPesq research group listed twice in the report) | Met for database ids; 1 source duplicate left |
| SC-005 compatibility | schemas and export fields unchanged | Schema test: every pre-existing table identical, 6 new tables. Export test and real exports: the 26 existing files keep their record fields; 2 new files | Met |
| SC-006 local vs CI | identical id files | Not run (needs the maintainer's go-ahead for a fork dispatch) | Pending |
| SC-007 old ids resolve | 100% after merge and rebuild | Unit scenarios (merge, equal-priority merge, upgraded key, rebuild from zip, snapshot, key corrected, rule change, chains, reappearing id) pass. Real rebuild: every id of the previous new-code run is current or an alias | Met |
| SC-008 old vs new replay | only the listed differences | All differences classified in section 6; one defect (DOI) found and fixed | Met after the fix |

## 3. Replays

Inputs: a frozen copy of the 2026-10-24 local weekly inputs (SigPesq reports,
347 CNPq group payloads, 435 Lattes CVs, project documents). The portals are
replaced by those files, so the old and the new code read exactly the same
data. The weekly phase order is kept, minus the two download phases.

- **Old code**: a copy of the tree at `4985384`, before any change.
- **New code**: copies of the working tree, taken before each run, so the
  repository could keep changing during long runs.
- Databases and exports are kept outside the repository, never in
  `db/horizon.db`. Telegram variables are empty.

## 4. Before the change (old code)

Three reruns of `ingest_lattes_projects` on the old code's database:

| Pass | Change logs added | Team member rows | Content changes |
|---|---:|---:|---|
| 1 vs fresh | 3,806 | 394 removed / 393 added | 43 removed / 42 added, +33 source records |
| 2 vs 1 | 3,806 | 354 rewritten | none |
| 3 vs 2 | 3,806 | 354 rewritten | none |

Within one fresh run, 1,005 tracking keys mapped to more than one payload hash.

## 5. Ids on the real data

Measured on the 2026-10-24 database, then on the replay databases.

| Entity | Rows | Collision groups | Rules |
|---|---:|---:|---|
| person | 17,124 | 0 | lattes_id 409, name 16,715 |
| research_group | 354 | 2 | cnpq_id 350, sigpesq_name 4 |
| initiative | 3,043 | 0 | sigpesq code 86, PJ code 189, Lattes identity 2,756, name 12 |
| advisorship | 8,680 | 0 | SigPesq workplan 590, Lattes identity 8,088, PJ code 2 |
| article | 6,736 | 73 | DOI 1,861, title+year+type+venue 4,875 |
| research_production | 2,807 | 8 | title+year+type |
| academic_education | 1,843 | 2 | parent + type + course + start |
| professional_activity | 7,227 | 53 | parent + institution + years + role + bond |
| award / proficiency | 167 / 744 | 0 | parent + title + year / parent + language |
| team | 11,431 | 0 | initiative it staffs |
| reference tables | 2,055 | 7 (knowledge areas) | slug |
| fellowship | 19 | 4 | slug + value |

- **Collisions**: 149 groups in total. Each is the same item stored twice in
  the database, differing only by case or accent. Recorded as TD-023 for a
  future deduplication spec.
- **Personal data**: no CPF, e-mail or phone in any id or `natural_key`. The 3
  phone-like matches are DOIs.
- **Longest id**: 254 characters.
- **Timing**: `assign_horizon_ids` takes about 17–20 s on the full database,
  including the history read and the alias reconciliation.

## 6. Old vs new replay (SC-008)

Compared through the ids: `assign_horizon_ids` was run on a copy of the old
code's database, and relations were translated to `horizon_id` values.
Initiatives, advisorships and their teams are compared by their type+name
candidate, because their winning id comes from the tracking key, whose format
changed.

**Identical**: initiatives (3,043), research groups, fellowships, knowledge
areas, organizational units, roles, languages, types, and the knowledge-area
links.

| Difference | Old → new | Explanation |
|---|---|---|
| (a) team members | 39,384 → 42,341 | +3,266 rows in 1,074 teams (Student 1,522, Researcher 1,294, Coordinator 449): a team is now the union of what every CV says, where the last CV used to replace the others. 309 removed and 18 date changes follow person resolution (TD-024) |
| (b) advisorships | 8,580 → 8,565 | 28 same-CV duplicates dropped; the "\| Orientacao …" disambiguation suffix goes to another occurrence of a repeated title |
| (b) articles | 85 pairs | Same title and year, another venue spelling (76) or DOI (9), from the CV that is read first |
| (b) persons | 45 / 47 | 17 the same person with another spelling kept; the rest are particle variants that resolve in another order (TD-024) and TD-022 |
| (c) tracking keys | 35,547 → 35,634 source records | New source-native key format |
| (d) change logs | 35,978 → 33,104 | False updates no longer written |
| (e) new tables | — | `horizon_ids`, `horizon_id_candidates`, `horizon_id_aliases`, `horizon_merge_log`, `horizon_meta`, `team_member_contributions` |

**Defect found**: 8 articles lost their DOI. The article appears in two CVs,
only one with the DOI. With the CVs read in a fixed order, the CV without the
DOI sometimes came first and created the article, and the later title match
never filled it in. Fixed: empty `doi`, `journal_conference`, `volume` and
`pages` of a stored article now take a later CV's value, and are never
overwritten (`_fill_missing_article_fields` in `src/flows/lattes/projects.py`).
Confirmed in the final replay (section 8).

`null_researchers_canonical.json` goes from 695 to 714 records. These are the
same people with another spelling kept, the same cause as TD-024.

## 7. Defects found by the fixpoint and rebuild checks

| Run | What changed between passes 2 and 3 | Cause | Fix |
|---|---|---|---|
| 1 | 16,476 advisorship members re-inserted; 542 false advisorship "create" logs; 2 CNPq end dates | Members replaced on every update; the handler found the advisorship by its disambiguated title after the loader had not, so its state was never read; two spellings of one person each wrote their own end date | Keep an unchanged member; read the state of the advisorship the handler will update; one end date per resolved person, written after the loop and compared with the stored value |
| 2 | 695 advisorship members (512 advisorships) re-inserted | The same work listed twice in one CV, or in two CVs, lands on one advisorship row, and each row rewrote the members | Members of an existing advisorship are written once per phase, with the last value |
| 3 | only TD-022 | — | — |
| Rebuild | 150 articles and 4 groups with other ids in another directory | The collision suffix hashed the absolute path of the source file | Hash the file name only |

## 8. Final runs with the final code

| Check | Result |
|---|---|
| Replay from a reset database, history from the previous run's zip | Every phase exit 0. 62,227 ids, 149 collision groups. The history came from the zip of an earlier new-code replay, taken before the file-name fix and the article fill: 167 aliases (3 merge, 9 rebuild, 155 retired). The 9 rebuild aliases are DOI-less ids of articles that now have their DOI (`article:h:…` → `article:doi:…`). Of the 155 retired ids, 154 are the old path-dependent collision suffixes (150 articles, 4 groups), which no code after the fix can produce. The last one is an article whose empty venue was filled from a later CV, which changed its natural key too much for a key-corrected match. These ids come from code versions that were never published, so no consumer holds them |
| Fixpoint, 3 passes on that database | `ingest_lattes_projects`, `lattes_advisorships` and `cnpq_sync`, each pass exit 0. Passes 2 and 3 leave every table identical, except the same 27 `entity_change_logs` rows of TD-022 |
| The 8 DOIs of section 6 | Present, for example `10.1590/0103-8478cr20170579`, `10.4067/s0718-58392019000300366`, `10.5965/2764747102032013075` |
| Local weekly with downloads (T060), in an isolated copy of the project | All 21 phases exit 0, in about 1 h 10 min, on an ephemeral Prefect server and without Telegram. `assign_horizon_ids` runs between `consolidate_duplicates` and `export_canonical`. `exports_canonical.zip` holds `horizon_ids_canonical.json` (62,228 ids, all distinct) and `horizon_id_aliases_canonical.json`. The report has the same rules and counts as section 5, with 149 collision groups and 3 ids kept from merges. The alias file is empty, as expected: the copy's database and zip came from before this spec, so there was no id history to read |

## 9. Quality gate

| Check | Old tree (`4985384`) | New tree |
|---|---|---|
| `black --check src tests` | 47 files would be reformatted | the same 47 files |
| `isort --check src tests` | 37 errors | the same 37 |
| `flake8 src tests` | 574 | 574 (−2 W291 in `cnpq_sync.py`, +2 E402 for new imports in the existing late-import block of `projects.py`) |
| `pytest` | 6 failed (pre-existing) | 579 passed, the same 6 failed |

The constitution's quality gate also lists mypy, which `make ci-check` does not
run; it was not run here.

## 10. Known exceptions and follow-ups

- **TD-022**: 27 Lattes CVs without a readable name collapse into one person,
  whose `cnpq_url` and resume change on every pass. Future spec.
- **TD-019**: CNPq members without a start date get the run's timestamp, so a
  rebuild compared with an older run differs on about 900 links. This does not
  affect the fixpoint.
- **TD-023**: the 149 duplicate groups (section 5).
- **TD-024**: person resolution in a fresh run depends on creation order.
- **SC-006 / T061**: compare the id file of a fork CI run with the local one.
