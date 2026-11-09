# Research: Fixed Rule for Fields Written by Several Documents

**Branch**: `030-deterministic-field-merge` | **Date**: 2026-11-05

Every finding below was checked in the code of branch `029-pii-safe-exports`
(commit `19ae6b6`) or in the local `db/horizon.db` (read only).

Branch and spec numbers differ up to branch 028. "Branch 024 (spec 021)" names
the branch first and the `specs/` folder second.

## R1. Who writes the shared fields today

**Finding.** Four phases write the fields of FR-006. Each one overwrites them
with its own values:

| Phase | Source system (tracking) | Writes | Where |
|---|---|---|---|
| `sigpesq` (projects report) | `sigpesq_research_projects` | initiative name, status, description, start/end date | `StandardProjectHandler.create_or_update` |
| `sigpesq` (advisorships reports) | `sigpesq_advisorships` | advisorship status, description, dates, cancellation; fellowship value | `AdvisorshipHandler.create_or_update`, `_ensure_fellowship` |
| `lattes_projects` | `lattes_projects` | initiative status, description, start/end date | `StandardProjectHandler.create_or_update` |
| `lattes_advisorships` | `lattes_advisorships` | advisorship status, description, dates | `AdvisorshipHandler.create_or_update` |
| `enrich_projects` | `sigpesq_project_files` | `enrichment_json`; description only when empty | `ProjectEnrichmentLoader._enrich_winners` / `_apply` |

All of these are in `src/core/logic/initiative_handlers.py` and
`src/core/logic/project_enrichment.py`.

Details that matter for the rule:
- `update_initiative` is called with `status=project_data.get("status",
  "Unknown")`. So a document with no status writes `"Unknown"` over a real
  status. This breaks FR-005 today.
- `_ensure_fellowship` keeps one `Fellowship` row per program and sponsor (21
  rows locally: PIBIC, PIBITI, PIVIC…). It overwrites `value` with the value
  of the last workplan that has a non-zero value. This explains the 5
  fellowships of the replay. The 123 advisorships point at them, and so they
  differ too.
- `enrich_projects` writes the PDF description only when the initiative has
  none (`write_desc = bool(new_desc) and (self.overwrite or not current)`). The
  result depends on whether a Lattes or SigPesq description was already there.

**Decision.** The rule is applied to these five writers. The handlers keep
creating rows as today, and a resolver writes the winning values after them.

**Alternatives considered.**
- *Changing each handler to compare with the stored value*: rejected. The
  stored value alone does not tell which document wrote it, so the rule cannot
  be applied.

## R2. Claims of documents that are not reprocessed (FR-008)

**Finding.** Branch 023 (spec 020) records an `attribute_assertions` row for
every field a source record gives to an entity, with `value_json`:
- 246,298 rows locally;
- for initiatives: status, description, start/end date, name, and
  `enrichment` for the PDFs;
- for advisorships: status, description, dates, name.

They cannot be used as the claims directly:
1. `source_records` is unique on `(system, type, record_id, payload_hash)`. A
   changed document adds a new source record and keeps the old one. The
   assertions hold every past version, with no flag for the current one.
2. Nothing links an assertion to the document state of branch 024 (spec 021).
   So a document that stopped mentioning the entity, or that became inactive,
   cannot be left out (FR-009).
3. The fellowship value has no assertion.
4. The document date (the Lattes CV update date) is stored nowhere.
   `source_document_states.downloaded_at` is the download date, not the CV
   date.

**Decision.** Add a new ETL bookkeeping table, `source_field_claims`. It
holds one row per document × entity × field, with the value and the ranking
data. The document transaction writes it, in the same way it writes
`source_document_items`:
- the claims of a document are replaced each time the document is processed;
- they are dropped when the document is deleted or no longer carries the
  entity.

See data-model.md.

**Alternatives considered.**
- *Read the current claims from `attribute_assertions` plus the latest
  `source_records`*: rejected because of points 1 to 4 above. It would also
  need the CV date added somewhere else anyway.
- *Re-read the raw files of every document of the entity*: rejected. It goes
  against FR-008, and old raw files may be gone (rotation of branch 026, spec
  023).

## R3. When the resolver runs

**Finding.**
- The Lattes phases process one CV per transaction (`document_phase`,
  `DocumentSkip`).
- The SigPesq phase processes one report row per document, inside
  `document_phases`.
- `ProjectLoader` collects `before` states in `_pending` and writes the net
  change log in `flush_change_log`.
- `enrich_projects` is not a document phase. It runs over every PDF on each
  run (`297 reused` in run 41931785261).

**Decision.**
- In the document phases, the resolver runs at the end of each document,
  inside its transaction, for the entities whose claims the document changed.
  It runs before `flush_change_log`, so the change log gets the final value
  once.
- In `enrich_projects`, it runs for each initiative the phase writes.
- A rollback (branch 024, spec 021) discards the claims and the resolved
  values together.

Every resolution reads all the claims of the entity, from every source. So the
value only depends on the set of claims, never on which phase or document came
last (FR-007).

**Alternatives considered.**
- *One resolution pass at the end of the weekly*: rejected. Between the phase
  and that pass, the marts and the exports would see the last-writer values.
  The change log would also get two entries per field.

## R4. Rank of a claim

**Decision.** Each claim gets a sort key. The smallest key wins among the
non-empty values (FR-001 to FR-005):

```
(has_date ? 0 : 1, -date_ordinal, source_rank, tie_key)
```

| Source | date | source_rank | tie_key |
|---|---|---|---|
| Lattes (`lattes_projects`, `lattes_advisorships`) | `informacoes_pessoais.atualizacao_cv`, dd/mm/yyyy | 0 | Lattes id, as a 16-digit string (lowest wins) |
| SigPesq report row (`sigpesq_research_projects`, `sigpesq_advisorships`) | none | 1 | `0`, then the SigPesq Id negated, zero-padded (highest Id wins) |
| SigPesq PDF (`sigpesq_project_files`) | none | 1 | `1`, then the code (the row beats the PDF, FR-004) |
| CNPq | `data_do_ultimo_envio` | 2 | group id |

Other cases:
- An unreadable or missing CV date counts as no date (edge case of the spec).
- Two claims from the same document cannot share a row. When a CV lists the
  same project twice, which the loader already logs as "Dropped N duplicate
  projects", the first one after the loader's own deduplication is the claim.

**Rationale.** Every part of the key comes from source data, never from
database ids or processing order (constitution rule 2).

## R5. Empty and equal values

**Decision.**
- Empty means `None`, `""`, whitespace only, or the placeholder status
  `"Unknown"`.
- Values are compared after the same `canonical()` that `flush_change_log`
  already uses, plus trimming and case folding for text. Values that differ
  only in spaces or case are the same value (edge case), and the winner's
  exact text is stored.
- When every claim is empty, the stored value is left as it is: no write, and
  no change from `None` to `"Unknown"`.

## R6. Enrichment (`enrichment_json`, 38 differences)

**Finding.** `build_enrichment` carries `origin`, `reviewed_at` and
`reviewed_by` from the stored payload (`prior`). The rest comes from the PDF
and from the match: `match_strategy`, and `needs_review`, which derives from
the match. The match uses the initiative's current name and description, and
those are the values TD-028 makes order-dependent. The payload has one writer,
the PDF that wins the match, so the rule has nothing to rank there. Its input
is what varies.

**Decision.**
- The description the PDF offers becomes a claim with rank "SigPesq PDF". So
  it fills a description only when no Lattes or report claim has one, as
  agreed in the spec.
- The enrichment payload is not ranked. It is rebuilt from the resolved
  fields.
- A validation task measures again, after US1, how many `enrichment_json` rows
  differ. If any remain, it records which keys differ, and the cause is fixed
  or written down as a known exception. The review state carried in `prior` is
  human data and is kept.

**Alternatives considered.**
- *Ranking the enrichment payload as one field*: it has a single source per
  initiative, so ranking changes nothing.

## R7. TD-029: why an identical name does not resolve

**Finding.** `_lookup_existing_initiative` tries, in this order:
1. the identity key;
2. the `existing_by_name` cache;
3. `_lookup_existing_by_exact_name`, which runs `SELECT id FROM initiatives
   WHERE name = :name` on the table that holds both initiatives and
   advisorships;
4. the normalized name.

Step 3 returns `None` when the row with that name is an advisorship. The
create that follows then breaks `UNIQUE(initiatives.name)`.

A second path is a rename. A project that resolved by identity to initiative
A gets the title that initiative B already has, and the guard at
`project_loader.py:670` only covers names that are equal after normalization.

On the local database every project title of CV `1703547133505721` matches a
stored Research Project, so the failure needs the database state of the
incremental run of 2026-10-29.

The artifact of that run, CI run 40952053776 (`weekly-etl-artifacts`, 371 MB),
is available until 2027-01-27.

**Reproduction (T026).** On the database of the artifact of CI run 40952053776,
6 project titles of CV `1703547133505721` are the names of advisorships of the
same researcher. It is path 1. The record is in the scratchpad
`e/E_TD029.txt`. In a local rebuild the same names belong to Research
Projects, because `lattes_projects` runs before `lattes_advisorships` and the
advisorships get a disambiguated title (`_build_disambiguated_advisorship_title`:
"<title> | Orientacao <first student> | <start year> | sigpesq <id>").

**Decision (maintainer, option B).**
- **Identical name, same kind:** the project resolves to that initiative.
- **Identical name held by an advisorship:** the project keeps the plain name,
  and the advisorship is renamed to the title it would get in a rebuild. That
  title comes from the values the advisorship's own loader used, read from its
  latest tracking assertions (`student_names`, `start_date`) and, for SigPesq
  workplans, the workplan Id. When its document is processed again,
  `AdvisorshipHandler.find_existing` computes the same title and finds it, so
  no duplicate is created. The rename is logged (`title collision ... renamed`)
  and counted in `collisions_resolved`.
- **Rename onto a name another initiative holds:** the persisted name is kept,
  as the guard already does for spelling.

## R8. Rule version and rebuild (FR-014)

**Finding.**
- `HORIZON_RULE_VERSION = 1` in `src/core/logic/horizon_identity.py`.
- `run_weekly._reset_if_rule_version_changed` rebuilds a populated database
  whose `horizon_meta.rule_version` differs.
- `DocumentSkip` also stores the rule version per document. So a new version
  reprocesses every document, even without a reset.

**Decision.** Raise `HORIZON_RULE_VERSION` to 2. The first weekly on a kept
database is rebuilt once, as the constitution requires.

The CI restore is unchanged. It reads only runs of the same branch, so the
first run of a new branch starts from scratch anyway (FR-015, maintainer's
rule).

## R9. Merges of duplicates

**Finding (corrected during implementation).** `ReferenceConsolidator` merges
articles, teams and knowledge areas, never initiatives, advisorships or
fellowships. Nothing in the pipeline merges two initiatives. When a document
stops carrying an initiative, `DocumentItemStore` deletes the initiative only
if no other document carries it. The document's claims are replaced first, so
no claim is left on a deleted row.

**Decision.** No merge step is needed. `move_claims` stays in the port for a
future initiative merge. Task T019 is not applicable.

## R10. Counts in the log (FR-013)

**Decision.** The resolver counts each field it resolves that had more than
one non-empty, different value. It puts the field under one of three counts:
- `by_date`: the winner had a date and a later date than every other claim;
- `by_source`: the winner beat the others by source rank;
- `by_tiebreak`: the tie key decided.

It also counts `collisions_resolved` and `collisions_reported` (R7).

Each phase logs one line, for example:

```
field merge lattes_projects: fields=312 by_date=201 by_source=96 by_tiebreak=15 collisions_resolved=1 collisions_reported=0
```

A run with no conflicts logs zeros (US4-2).

## R11. Cost (SC-006, reference only)

**Finding.** Locally, an incremental `lattes_projects` takes 13 s and a
rebuild 679 to 911 s (validation report of branch 024).

**Decision.**
- The resolver runs one indexed query per touched entity, on
  `(entity_type, entity_id)`.
- About 14,700 initiative items in a rebuild come to well under a minute.
- The extra table holds about 5 claims per initiative item, around 75,000
  rows, so the database grows by a few MB.

## R12. Validation tools

**Decision.**
- The SC-001 replay reuses
  `specs/021-skip-unchanged-documents/research-scripts/compare_with_rebuild.py`
  of branch 024. It leaves out the tracking and bookkeeping tables. The new
  `source_field_claims` is added to its `SKIP_TABLES`, like
  `source_document_items`.
- The replay order: rebuild; two unchanged passes; one pass after changing
  two CVs and one SigPesq row; then a comparison with a rebuild of the final
  inputs.
- SC-002: a unit test loads the same fixture documents in three orders and
  compares every FR-006 field.
