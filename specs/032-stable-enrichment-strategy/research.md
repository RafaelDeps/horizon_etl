# Research: Stable enrichment strategy for document-created projects

All findings come from reading `src/core/logic/project_enrichment.py` on
branch `032-stable-enrichment-strategy` (based on `fix-stale-tests`, which
holds spec 030 and TD-031) and from the local `db/horizon.db` of 2026-11-09.

## R1. Where the strategy changes

**Finding.** `ProjectEnrichmentLoader.run` matches every document
(`match_pj`), keeps one winner per initiative (`resolve_claims`), then:

- `_create_initiative` writes the note of an unmatched document with
  `strategy=NEW_FROM_DOCUMENT`;
- `_enrich_winners` writes the note of a matched document through
  `build_enrichment(..., strategy=cand.match.strategy, prior=current)`.

`build_enrichment` already carries `origin`, `reviewed_at` and `reviewed_by`
from `prior` (`origin_from_prior`), but sets `match_strategy=strategy`. On the
run after a creation the creating document matches its initiative by exact
title (the initiative's name is the document's `titulo`), so the note's
`match_strategy` moves from `new_from_document` to `title_exact`.

**Decision.** Decide the stored strategy inside `build_enrichment`, from the
resolved origin, the prior note and the current document. One pure function,
`strategy_from_prior`, next to `origin_from_prior`.

**Alternatives considered.**
- *Leave `match_strategy` out of the replay comparison*: hides the difference
  but the second run still rewrites 37 notes and logs 37 changes.
- *Drop `match_strategy` from the note*: the exports and the review tooling
  read it; a schema change for one value is out of proportion.

## R2. How to recognise the creating document

**Finding.** Every note the phase writes holds `project_code` (the document's
normalized code, or `None`) and `source_file` (the PDF name from
`_meta.arquivo`). In the local database all 37 notes with origin
`new_from_document` have both.

**Decision.** The current document is the creating document when the resolved
origin is `new_from_document` and:
- the document has a code and it equals the note's `project_code`; or
- the document has no code, and its `source_file` is set and equals the
  note's `source_file`.

**Alternatives considered.**
- *Compare titles*: a title can be edited in SigPesq; the code is the stable
  key the rest of the pipeline uses.
- *Only check `prior.match_strategy == new_from_document`*: does not repair
  notes that already drifted to `title_exact` (R4).

## R3. Which current strategies keep `new_from_document`

**Finding.** A rebuild never matches the creating document by code: if the
SigPesq report listed the project, a rebuild would match it by code and not
create it, so origin would be `matched_existing` and the two databases differ
for another reason. When the creating document later matches by code, that is
new information (the project entered the SigPesq report), not the false
change of TD-033.

**Decision.** Keep `new_from_document` only when the current match is by title
(`title_exact` or `title_fuzzy`). A code match records `sigpesq_project_code`.
The spec's FR-001 is narrowed to title matches accordingly.

**Alternatives considered.** *Any strategy*: would hide a real code match
behind "created from this document".

## R4. Notes that already drifted

**Finding.** The persistent database of the fork CI went through more than one
run, so its document-created notes say `title_exact`. Their `origin` is still
`new_from_document` (carried forward), and `project_code`/`source_file` still
name the creating document.

**Decision.** Base the rule on the resolved origin, not on the prior strategy.
The first run after the change writes `new_from_document` back (one change per
drifted note); the next run writes nothing. A legacy note without `origin`
whose strategy already drifted is inferred `matched_existing` by
`origin_from_prior` and is not repaired; none exists in the local database.

**Alternatives considered.** *A one-off migration script*: would be ETL logic
outside a flow (constitution III) for a repair the normal run does anyway.

## R5. "Writes nothing": the UPDATE of an unchanged note

**Finding.** `_enrich_winners` calls `_apply` for every winner, which runs
`UPDATE initiatives SET enrichment_json = ...` even when the payload equals
the stored one. The change log already skips it (`changed=` compares
`canonical(enrichment)` with the prior), but the row is still rewritten for
every enriched initiative on every run.

**Decision.** In `_enrich_winners`, when the canonical payload equals the
stored one and no description is to be written, skip `_apply` and count the
row as written, so the description merge and the tracking run as today. This
makes FR-006 and SC-001 hold for the row itself, not only for the change log,
and applies to every enriched initiative, not only the 37.

**Alternatives considered.** *Keep the UPDATE*: the content is the same, but
the constitution's idempotency rule says no rewritten row.

## R6. What stays as it is

- `record_entity_match` keeps receiving `cand.match.strategy`: the per-run
  tracking records the real match (FR-005).
- The phase counters `by_code`, `by_title_exact`, `by_title_fuzzy` keep using
  `cand.match.strategy` (FR-008).
- `origin_from_prior`, `derive_needs_review`, `mark_reviewed` and the review
  fields are unchanged (FR-004).
- No new setting, Makefile target or workflow input (FR-009).
