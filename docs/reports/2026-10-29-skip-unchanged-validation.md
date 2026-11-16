# Skip Unchanged Documents — Validation Report (spec 021)

Date: 2026-10-29 · Spec: `specs/021-skip-unchanged-documents/` · Branch:
`024-skip-unchanged-documents` · Machine: the maintainer's local machine.

## 1. Summary

- **Unchanged documents are skipped and write nothing** (SC-001). On a
  database already processed by the new code, a pass over the same inputs
  skips every document (the one SigPesq group listed twice in its report is
  the only one processed, by design) and changes no row of any table except
  the `ingestion_runs` rows and the documents' `last_seen_at`.
- **The Lattes phases go from 20 min to under a minute on unchanged inputs**
  (SC-002): `lattes_projects` 12–28 s and `lattes_advisorships` 12–19 s on the
  replay, against 471–695 s and 700–1313 s with the spec 020 code.
- **A changed CV is processed alone** (SC-003): one edited CV is the only Lattes
  document processed; the article only it carried is deleted, the link to the
  article another CV shares is removed and the article kept, and every table
  equals a rebuild on the same inputs, apart from the known exceptions of
  section 8.
- **A failure never deletes data** (SC-004): an unreadable CV, a CV that lost
  every item, a listed CV without its JSON and a CNPq page that did not
  download are recorded as failed (`unidentified`, `total_loss`, `download`,
  `download`) and change no data row.
- **Documents gone from their source are kept as inactive** (SC-005): one
  group removed from the SigPesq report and one id removed from `lattes.list`
  become inactive in exactly their sources (`sigpesq_group`, `cnpq_group`,
  `lattes_projects`, `lattes_advisorships`) and keep their data.
- **No existing table or export changes format** (SC-007): the schema check of
  the 102 existing tables and indexes is identical; the only new export file is
  `source_document_states_canonical.json`.
- **`make weekly-flows` keeps the database** (US5): it now depends on
  `make db-ensure`, which creates a missing database and otherwise only runs
  the migrations; `make full-refresh` still rebuilds.
- **Defects found by the validation and fixed** (section 7): the reference
  check reprocessed most documents after a rebuild, and was slow on skipped
  documents; an old failure record stayed after a successful read.
- **Not met yet** (section 8): rows shared by several documents (about 130
  initiatives, 5 fellowships and the 123 advisorships that point at those
  fellowships) keep the values of the last document that wrote them, so they can differ from a rebuild after documents are reprocessed out
  of the rebuild order (TD-028).
- **GitHub Actions** (SC-008): the weekly on the fork succeeds on an empty
  runner with the same export files and fields, plus the new file (section 11).

## 2. Success criteria

| Criterion | Target | Result | Status |
|---|---|---|---|
| SC-001 unchanged inputs | 100% skipped; only `ingestion_runs` and `last_seen_at` change | Pass 3 after a rebuild: lattes 0 processed of 408 (+27 unidentified), CNPq 0 of 350, SigPesq 2 of 1,659 (the duplicated group row); pass 2 vs pass 3: only `source_document_states` differs, in `last_seen_at` | Met (after the one-time convergence of section 4) |
| SC-002 Lattes time | ≤ about 2 min together | 12.5 + 12.4 s (T028), 28.0 + 18.8 s (round 1), 24.3 + 15.0 s (round 3) | Met |
| SC-003 one changed CV | 1 CV processed; equal to a rebuild | 1 CV processed by `lattes_projects`; `deleted_items=1`; every table identical to the rebuild except the TD-028 rows and the R9.3 membership rows | Met except TD-028 |
| SC-004 failures | 0 deleted rows; state unchanged | Round 1: 4 failures with the right reasons; v2 vs round 1: no data table changed | Met |
| SC-005 listings | failed listing: 0 inactive; complete: exactly the absent | Round 3: 1 inactive per affected source; tests: empty report, missing `lattes.list` and a campus filter change no status | Met |
| SC-006 three rounds | equal to a rebuild on the last inputs | Rounds 1–3: every table identical except TD-028 rows, R9.3 membership rows and 2 orphan knowledge areas | Met except TD-028 |
| SC-007 schema | no existing table or export changes | Schema check identical (102 tables/indexes); export tests pass | Met |
| SC-008 CI | same results as before plus the new file | Fork run 40856179199: all 21 phases exit 0; same 37 export files and fields plus the new file; count differences only in Lattes items, from different CV downloads (section 11) | Met |

## 3. Replays

Inputs: the frozen copy of the 2026-10-24 local weekly inputs used by spec 020
(SigPesq reports, 347 CNPq group payloads, 435 Lattes CVs, project
documents), in the scratchpad, never in the repository. The portals are
replaced by those files. Databases and exports are kept outside the
repository; Telegram variables are empty. Each run is the weekly phase order
minus the downloads: `sigpesq`, `cnpq`, `lattes_projects`,
`lattes_advisorships`, `enrich_projects`, `recalculate_parent_projects`,
`consolidate_duplicates`, `assign_horizon_ids`, `export_canonical`.

Equivalence with a rebuild is measured with
`specs/021-skip-unchanged-documents/research-scripts/compare_with_rebuild.py`
(rows compared through `horizon_id`, tracking and state tables left out,
items of inactive and failed documents left out on both sides, R9.3 membership
rows and orphan reference rows listed but not failing).

## 4. Base: rebuild, then unchanged passes

| Run | sigpesq | cnpq | lattes_projects | lattes_advisorships | consolidate | export |
|---|---|---|---|---|---|---|
| Rebuild, spec 020 code (`base_a`) | 97 s | 244 s | 528 s | 700 s | 168 s | 242 s |
| Rebuild, new code (`v2_fresh`) | 87 s | 281 s | 679 s | 911 s | 209 s | 296 s |
| Pass 2, unchanged | 604 s | 132 s | 333 s | 277 s | 188 s | 291 s |
| Pass 3, unchanged | 614 s | 127 s | 110 s | 52 s | 191 s | 290 s |
| Round 1 (final code) | 35 s | 15 s | 28 s | 19 s | 192 s | 291 s |

The rebuild with the new code is slower than with the spec 020 code (one
transaction and the item links per document). Passes 2 and 3 ran before the
cache fix of section 7; round 1 shows the final code on unchanged documents.

Documents processed after the rebuild:

| Source | Pass 2 | Pass 3 |
|---|---|---|
| lattes_projects (408 readable) | 78 | 0 |
| lattes_advisorships | 31 | 0 |
| cnpq_group (350) | 3 | 0 |
| sigpesq_group (354) | 2 | 2 (the duplicated row) |
| sigpesq_project (103) | 2 | 0 |
| sigpesq_advisorship (1,202) | 47 | 0 |

Pass 2 reprocesses, once, the documents whose names were resolved by fuzzy
matching while persons created later in the rebuild could now match them
(research R3, conservative by design), and those that resolved to a person
merged away by `consolidate_duplicates`. From pass 3 on, nothing is processed.

## 5. Round 1 — failures (US3, T034)

Inputs: one CV replaced by an unidentified file, one CV with every first-level
section emptied, one listed CV without its JSON, one CNPq URL failing.

```text
documents lattes_projects: processed=0 skipped=405 failed=30 (download=1 total_loss=1 unidentified=28)
documents lattes_advisorships: processed=1 skipped=405 failed=29 (download=1 unidentified=28)
documents cnpq_group: processed=0 skipped=349 failed=1 (download=1)
```

The emptied CV kept its advisorships (they sit one level deeper in the JSON,
under `orientacoes`), so `lattes_advisorships` processed it normally. Compared
with the database before the round: no data table changed; only
`source_document_states` (failure records, `last_seen_at`) and one reference
row of that advisorships document.

## 6. Rounds 2 and 3 — a changed CV and removed documents (US2, US4)

Round 2 restores the round 1 files and edits one CV
(`9639592687692535`): one article only it carries removed, one article shared
with another CV removed, one new article added.

```text
documents lattes_projects: processed=1 skipped=407 failed=27 (unidentified=27) deleted_items=1
documents lattes_advisorships: processed=2 skipped=406 failed=27 (unidentified=27)
```

Round 3 removes one group from the SigPesq groups report ("Agro Data Science e
Tecnologias", CNPq `2279789551670727`) and one id from `lattes.list`
(`6705768287504290`).

```text
documents sigpesq_group: processed=2 skipped=351 inactive=1
documents cnpq_group: processed=0 skipped=349 inactive=1
documents lattes_projects: processed=0 skipped=408 failed=27 (unidentified=27) inactive=1
documents lattes_advisorships: processed=0 skipped=408 failed=27 (unidentified=27) inactive=1
```

Comparison with a rebuild on the same inputs (rounds 2 and 3 rerun with the
final code, `compare_with_rebuild.py`):

| Table group | Round 2 | Round 3 |
|---|---|---|
| Schema of the 102 existing tables and indexes | identical | identical |
| Items left out (inactive or failed documents) | 0 | 91 (the removed group and CV) |
| `persons`, `researchers`, `articles`, `article_authors`, `academic_educations`, `awards`, `professional_activities`, `proficiencies`, `research_productions`, `production_authors`, `teams`, `initiative_teams`, `research_groups`, `group_knowledge_areas`, `initiative_knowledge_areas`, `researcher_knowledge_areas`, every reference table | identical | identical |
| `initiatives` | 133 rows differ | 132 rows differ |
| `advisorships` | 123 rows differ | 123 rows differ |
| `fellowships` | 5 / 4 rows | 5 / 4 rows |
| `knowledge_areas` | identical | 2 orphan rows kept (not failing) |
| membership rows (R9.3, not failing) | `team_members` 934/931, `advisorship_members` 74/74, `team_member_contributions` 32/32 | similar |

The `initiatives`, `advisorships` and `fellowships` rows are the TD-028
exception (section 8), and they are the same rows as in the base comparison
(section 4): the edits of the rounds add no difference of their own. The 123
advisorships differ only in their `fellowship_id`, because the fellowships
they point at differ. Almost all `team_members` rows listed are the leaders of
SigPesq groups, whose `start_date` is the day the loader created the group
(`ResearchGroupLoader`, unchanged behaviour): the rebuild ran a day later.

## 7. Defects found by the validation and fixed

- **Reference check after a rebuild** (`src/core/logic/document_skip.py`): a
  name resolved to a person or initiative of that very name was still checked
  against every person created after the document, so after a rebuild 193 of
  408 CVs, 149 CNPq pages and 177 SigPesq workplans were processed again. An
  exact resolution cannot be changed by a person created later (the exact match
  comes first and the earlier person wins a tie); such lookups are now left
  out of the fuzzy check. Pass 2 went to 78 / 3 / 47.
- **Slow checks on skipped documents**: the check normalized the names of every
  person and initiative created after each document, for every document (the
  SigPesq phase took 600 s with everything skipped). Name normalizations are
  cached and the delta rows are read once per phase; the decisions are the
  same on all 2,377 documents and the SigPesq phase takes 35 s.
- **Stale failure record**: a CV that failed to download once and came back
  unchanged was skipped with its old `last_failure` still set, so it counted as
  failed. A skipped document now clears its failure record.
- **CNPq pages that shuffle a table**: the mirror returns
  `equipamentos_e_softwares_relevantes` in a different order on each download,
  so 3 to 6 unchanged pages were processed again on every real weekly. The
  CNPq document hash now sorts lists before hashing (`order_free`).
- **`last_seen_at` in the idempotency tests**: the listing date is written by
  every run that sees a document (by design); the tests now leave it out.

## 8. Known exceptions and follow-ups

- **TD-028 — rows shared by several documents keep the last writer's values**:
  initiatives listed in several CVs or SigPesq rows, and fellowships shared by
  several workplans, keep the description, status, dates or value of the last
  document that wrote them. A rebuild writes in a fixed order; an incremental
  run reprocesses some documents, so after the one-time convergence of section
  4 about 130 initiatives (description 50, status 27, start date 26, end date
  18, `enrichment_json` 38) and 5 fellowships differ from a rebuild, and so do
  the 123 advisorships that point at those fellowships. They stay stable afterwards. Fixing it means an order-independent
  merge rule in the loaders (as spec 020 did for articles); recorded in
  `docs/backlog.md`.
- **Group-level links of CNPq pages**: members and research lines that
  disappear from a CNPq page are not deleted (today's behaviour): the same rows
  can come from the SigPesq report, which does not record them as items.
- **Unidentified CVs**: the 27 `Nome-nao-identificado` CVs fail as
  `unidentified` every run and no longer create the merged
  "[Nome-nao-identificado]" person (TD-022), as the spec states.
- **Merged teams** (`ReferenceConsolidator`): contribution links keep the old
  team id; a CV that later drops such a project leaves its members on the
  winning team until a rebuild.

## 9. Local weekly on the real database (T059)

`make weekly-flows` on `db/horizon.db` (the 2026-10-24 database, restored
from `data/_backup_2026-10-28_pre021/`, checksum verified before the first
run), with the real downloads and Telegram variables empty. The Prefect
server was already running, so no container was started or changed.

| Run | Start | Total | Reset? | sigpesq | cnpq | lattes_projects | lattes_advisorships |
|---|---|---|---|---|---|---|---|
| 1 | 03:11 | 69 min | yes, once (no recorded rule version) | 1.8 min | 19.1 min | 9.2 min | 15.9 min |
| 2 | 04:20 | 45 min | no | 1.1 min | 13.1 min | 4.0 min | 4.2 min |
| 3 | 05:13 | 34 min | no | 0.7 min | 13.1 min | 13 s | 7 s |
| 2026-10-24 (old code) | | | yes (`db-reset`) | | | 7.4 min | 12.4 min |

Documents processed:

| Source | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| lattes_projects | 408 (+27 unidentified) | 78 | 0 |
| lattes_advisorships | 408 (+27 unidentified) | 31 | 0 |
| cnpq_group (350) | 347 | 6 | 3 |
| sigpesq_group (353) | 353 | 2 | 2 |
| sigpesq_project (103) | 103 | 2 | 0 |
| sigpesq_advisorship (1,202) | 704 (+498 repeated rows) | 47 | 0 |

Run 2 is the one-time convergence after a rebuild (section 4). From run 3 on,
the Lattes phases take 20 s together (SC-002: target about 2 min). The CNPq
phase still downloads every page to compare it (13 min, spec C's subject); the
3 to 6 pages processed again per run came from the mirror returning one table
(`equipamentos_e_softwares_relevantes`) in a different order on each
download. The CNPq content hash now ignores list order (section 7).

After the CNPq fix, two more runs:

| Run | Start | Total | cnpq processed | lattes_projects | lattes_advisorships | SigPesq processed |
|---|---|---|---|---|---|---|
| 4 | 05:51 | 38 min | 322 of 350 (the new hash, once) | 0 (13 s) | 0 (7 s) | 2 (the duplicated row) |
| 5 | 06:29 | 32 min | 0 of 350 | 0 (13 s) | 0 (5 s) | 2 (the duplicated row) |

Run 5 is the steady state on the real database: no document processed apart
from the duplicated SigPesq group row, every phase exit 0.

## 10. Quality gate

- **Tests**: `pytest`: 632 passed, 6 failed. The 6 failures are the ones
  present before this spec (`test_download_lattes_flow` ×3,
  `test_loader_mapping`, `test_sigpesq_adapter` 429,
  `test_weekly_etl_workflow::test_weekly_etl_workflow_runs_weekly_flows_with_notifications`).
  New tests: `test_document_transaction.py`, `test_document_skip.py`,
  `test_document_state_store.py`, `test_cv_document.py`, `test_ensure_db.py`,
  `test_incremental_lattes.py`, `test_incremental_cnpq_sigpesq.py`, and a
  states-file test in `test_export_canonical_data_flow.py`.
- **`make ci-check`** (format-check, lint, test) fails before and after this
  spec on the same pre-existing issues: `black --check` would reformat 47
  files at `HEAD` and 46 now (every file this spec created or touched is
  formatted); `flake8` reports 574 warnings at `HEAD` and 578 now, the 4 new
  ones being E402 for imports added below the existing `faulthandler.enable()`
  line of `src/flows/lattes/projects.py`, like the 20 imports already there.
- **No third-party library changed**; the libraries the session rebinding
  relies on are pinned by a test (`eo_lib` 0.2.2, `research_domain` 0.14.4,
  `libbase` 0.1.0).

## 11. GitHub Actions (T061, SC-008)

Run [40856179199](https://github.com/RafaelDeps/horizon_etl/actions/runs/40856179199)
on the fork, branch `024-skip-unchanged-documents`, dispatched on 2026-10-29
after the maintainer's go-ahead. The runner starts with no database, so the
run is a rebuild: `make weekly-flows` created it through `make db-ensure`.
All 21 phases exited 0 in 1 h 38 min; the workflow committed the new
`exports_canonical.zip` (`bffecb9`).

```text
documents sigpesq_group: processed=353 skipped=0 failed=0
documents sigpesq_project: processed=103 skipped=0 failed=0
documents sigpesq_advisorship: processed=704 skipped=498 failed=0
documents cnpq_group: processed=347 skipped=3 failed=0
documents lattes_projects: processed=409 skipped=0 failed=26 (unidentified=26)
documents lattes_advisorships: processed=409 skipped=0 failed=26 (unidentified=26)
```

Against the previous CI export (`0b55907`, weekly of 2026-10-28, spec 020
code): the same 37 files with the same record fields, plus
`source_document_states_canonical.json` (2,376 documents, fields
`source_system`, `document_key`, `status`, `last_seen_at`, `processed_at`).
Record counts differ, all in items that come from Lattes CVs: of the
horizon ids, 4,958 are only in the old export and 6,554 only in the new one,
mostly `person:h` (1,124 / 940), Lattes teams (1,077 / 1,549), Lattes
advisorships (771 / 1,166), DOI-less articles (426 / 713) and professional
activities (518 / 588); `person:lattes` ids differ both ways (21 / 27). The
runner downloads the CVs live, so the two runs read different sets of CVs,
as in spec 020 (section 11 of its report). No difference outside Lattes items
was found, and no field changed.
