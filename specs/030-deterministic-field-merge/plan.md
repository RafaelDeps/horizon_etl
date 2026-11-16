# Implementation Plan: Fixed Rule for Fields Written by Several Documents

**Branch**: `030-deterministic-field-merge` | **Date**: 2026-11-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/030-deterministic-field-merge/spec.md`

Branch and spec numbers differ up to branch 028. "Branch 024 (spec 021)" names
the branch first and the `specs/` folder second.

## Summary

Several documents write the status, description and dates of a shared
initiative or advisorship, and the value of a shared fellowship. Today the
last document processed wins. So an incremental run and a rebuild disagree on
about 130 initiatives, 5 fellowships and 123 advisorships (TD-028).

The plan:
1. Every document records what it says about each of those fields as a
   **claim** in a new bookkeeping table, `source_field_claims`. The claim
   carries the document's date, source rank and tie key.
2. At the end of each document, inside its transaction, a pure resolver ranks
   all the claims of the touched entities, from every source:
   - most recent date first;
   - then Lattes > SigPesq > CNPq;
   - then the fixed tie-breaks.

   It writes only the values that change.
3. The claims of documents that were not reprocessed are already stored. So
   the result depends only on the set of documents, not on their order or on
   what changed this week.

TD-029 is fixed in the initiative lookup:
- a Lattes project whose title is the stored name of an initiative of the same
  kind resolves to it;
- a name held by an advisorship is reported, the project is not stored, and
  the CV is no longer rolled back.

`HORIZON_RULE_VERSION` goes from 1 to 2, so a database kept from before this
feature is rebuilt once.

## Technical Context

- **Language/Version:** Python 3.12 in GitHub Actions; the local venv runs
  3.14. The project requires >=3.10.
- **Primary Dependencies:**
  - Prefect 3.6 (flows);
  - SQLAlchemy over SQLite, through the `eo_lib` and `research_domain`
    libraries, which stay unchanged;
  - loguru.
- **Storage:** SQLite `db/horizon.db`, persistent between runs. The schema
  gets one new table through `src/db/migrations.py`.
- **Testing:**
  - pytest;
  - the replay comparison script of branch 024 (spec 021), for SC-001.
- **Target Platform:** local Linux and the GitHub Actions weekly workflow
  (`weekly-etl.yml`).
- **Project Type:** ETL pipeline (Prefect flows plus a core library).
- **Performance Goals:** the weekly grows by at most 5% (SC-006, a
  reference). There is one indexed query per touched entity.
- **Constraints:**
  - order-free results;
  - idempotency fixpoint;
  - rollback safe per document;
  - SigPesq sequential;
  - CNPq with 4 workers;
  - no changes to third-party libraries or Docker.
- **Scale/Scope:**
  - about 4,000 Lattes initiative records and 14,700 initiative items;
  - 704 SigPesq workplans;
  - 21 fellowships;
  - about 75,000 claims.

No NEEDS CLARIFICATION is left. The research decisions are R1 to R12 in
[research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Ports & Adapters | The resolver (`src/core/logic/field_merge.py`) is pure. It reaches the database only through `IFieldClaimStore` / `IFieldWriter` in `src/core/ports/`, implemented in `src/adapters/database/`. | Pass |
| II. Domain-First | No domain entity changes. `source_field_claims` is ETL bookkeeping, like `source_document_items`, and it is not exported. | Pass (bookkeeping justified, see Complexity Tracking) |
| III. Prefect flows | No new entry point. The logic runs inside the existing phase flows. | Pass |
| IV. Audit-driven quality | The per-phase `field merge` line, the `title_collision` warnings and the replay comparison are the audit (FR-013). | Pass |
| V. LGPD | Claim values go through `scrub_pii_deep`, like `attribute_assertions` (branch 029). The table is never exported. | Pass |
| Data rule 1, persistent | Unchanged | Pass |
| Data rule 2, idempotency | The resolver writes only values that change. Claims are keyed by source data (document key, Lattes id, SigPesq Id), never by processing order. | Pass |
| Data rule 3, re-creatable | It is the goal of this feature: incremental = rebuild (SC-001). The rule version goes to 2, so old databases are rebuilt once. | Pass |
| Data rules 4–7 | Unchanged. No artifact feeds the rule. | Pass |
| Quality gate | `make ci-check` | Pass, to be run |

**Re-check after Phase 1 design:** pass, with no new violation.

## Project Structure

### Documentation (this feature)

```text
specs/030-deterministic-field-merge/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R12
├── data-model.md        # source_field_claims, resolution rule
├── quickstart.md        # tests, TD-029 reproduction, replay, fork run
├── contracts/
│   └── field-merge.md   # port, core, callers, log lines
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
src/
├── core/
│   ├── ports/
│   │   └── field_claim_store.py        # NEW: FieldClaim, IFieldClaimStore, IFieldWriter
│   └── logic/
│       ├── field_merge.py              # NEW: rank, resolve, applier, stats, Lattes date
│       ├── horizon_identity.py         # HORIZON_RULE_VERSION 1 -> 2
│       ├── project_loader.py           # claims per row; TD-029 lookup and rename guard
│       ├── initiative_handlers.py      # advisorship and fellowship claims; no "Unknown" overwrite
│       ├── project_enrichment.py       # PDF description as a claim
│       ├── document_skip.py            # replace claims + apply at document end; drops on deletion
│       └── reference_consolidator.py   # move claims on merge, resolve winner
├── adapters/database/
│   └── field_claim_store.py            # NEW: SQLite store and writer on the DocumentTransaction
├── db/migrations.py                    # NEW migration 0013_source_field_claims
└── flows/
    ├── lattes/projects.py              # pass the CV date to the loader
    ├── lattes/advisorships.py          # same
    └── sigpesq/{projects,advisorships}.py  # SigPesq Id as the tie key

specs/021-skip-unchanged-documents/research-scripts/compare_with_rebuild.py  # skip the new table

tests/
├── test_field_merge.py                 # NEW: rule, permutations, empties
├── test_field_claim_store.py           # NEW: lifecycle, rollback, merge
└── test_field_merge_loaders.py         # NEW: loaders end to end, TD-029
```

**Structure Decision:** this is the existing single-project layout. The rule
lives in `src/core/logic/field_merge.py`, its storage behind a port, and the
callers are the five writers of research R1.

## Design Notes

1. **Claims are written where the values are known.** `ProjectLoader` and
   `AdvisorshipHandler` already hold `project_data` for each row. They add one
   claim per FR-006 field and do not change how rows are matched or created.
   The handlers keep writing on create, so a new row has values at once. The
   resolver then corrects them in the same transaction.
2. **The document end is the single point of resolution.** `DocumentSkip`
   already wraps every Lattes CV and SigPesq row in one transaction. The claim
   replacement and the resolution run there, before `commit_processed`. So a
   failed document leaves claims and values untouched (branch 024 rollback).
3. **"Unknown" is not a value.** The handlers stop overwriting a stored
   status with `"Unknown"` when the document has none (research R1, R5).
4. **Fellowship value.** `_ensure_fellowship` stops writing `value` directly.
   Each SigPesq workplan claims `fellowship.value` with its Id as the tie key,
   so the newest workplan's value wins. Lattes has no value, so it makes no
   claim.
5. **TD-029** (research R7):
   - first reproduce on the artifact of run 40952053776;
   - then resolve identical names of the same kind;
   - block renames onto a name another initiative holds;
   - report names held by advisorships without failing the CV.
6. **Rule version 2** forces one rebuild of kept databases. The CI restore and
   its "same branch only" rule are untouched.

## Validation

| Check | How | Expected |
|---|---|---|
| SC-001 | quickstart §3 replay, `compare_with_rebuild.py` | 0 rows differ in initiatives, advisorships, fellowships |
| SC-002 | unit test, 3+ orders of the same documents | identical FR-006 fields |
| SC-003 | second unchanged pass | 0 changed rows, 0 change log entries |
| SC-004 | quickstart §2, artifact of run 40952053776 | CV `1703547133505721` loads, not partial |
| SC-005 | weekly log | `field merge` lines; their counts add up |
| SC-006 | weekly time against the last fork run | at most +5% (reference) |
| Suite | `make ci-check` | the same known failures only |
| Fork | quickstart §6, after the maintainer's approval | every phase exit 0, finalize True |

## Complexity Tracking

| Addition | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| New bookkeeping table `source_field_claims` | FR-008 needs the values and dates of documents that are not reprocessed, scoped to the documents that still carry the entity | `attribute_assertions` keeps every past version with no "current" mark, has no link to document states, no fellowship value and no document date (research R2) |
