# Implementation Plan: Reliable Participant Deduplication

**Branch**: `008-guard-participant-merge` | **Date**: 2026-08-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/008-guard-participant-merge/spec.md`

**Note**: This revision rewrites the feature artifacts in English. The original
(2026-08-28) version specified a guard protecting participants from
name-based matching at the *initiative* level. This revision keeps that
initiative-level guard (spec FR-012, contract R1–R5) and adds the
participant-level deduplication redesign the user requested: normalized name as
the **primary identity criterion**, strong-identifier **vetoes** against
homonyms, and **union** merging of complementary initiative data.

## Summary

House the participant duplicates observed in the weekly export (176 name groups,
exemplar "Israel Magalhães do Carmo": one record with five initiatives, one with
only a research-group membership) by consolidating participant records with
**equal normalized full names** subject to the rule *no conflicting strong
identifier*; transfer every link the loser owns into the winner (union of
initiatives, memberships, education and researcher-side data); refuse and flag
homonym and junk-name groups; and run the dedup step **inside the weekly
pipeline before the canonical exports**. The name is an important signal, never
a sufficient one — an unguarded name match is exactly the false-merge class the
initiative-level guard protects against, and the participant-level guards
(R8, R13) are what keep this feature honest.

## Technical Context

**Language/Version**: Python 3.11 (Prefect flows, SQLAlchemy-ish sqlite usage,
`thefuzz` already present for the existing fuzzy matcher).

**Primary Dependencies**: stdlib (`unicodedata`, `sqlite3`/SQLAlchemy as the
codebase uses), `prefect`, existing `src.core.logic` modules (`person_matcher`,
`person_consolidator`, `researcher_resolution`, `initiative_identity`).
**No new external dependencies** are required for the redesign.

**Storage**: `db/horizon.db` (SQLite) — participant records in `persons`
(+ `researchers`, links, emails, education, knowledge areas); the dedup pass
reads/writes the catalog and produces a JSON report artifact under
`data/reports/`.

**Testing**: pytest. The feature's regression tests run **db-less and offline**
(in-memory SQLite replicating the real schema), fast (<5s total), mirroring
`tests/test_person_consolidator.py`, `tests/test_person_matcher.py`,
`tests/test_project_loader_matching.py`. The **mandatory experiment** (spec
SC-005): weaken a guard in production, suite must fail; restore, suite passes.

**Target Platform**: Linux, scheduled weekly pipeline.

**Project Type**: ETL pipeline (research-data catalog); this feature is data
quality/identity logic.

**Performance Goals**: dedup of the full catalog (9.7k+ persons, ~15k+
participant links) in seconds, once per weekly run, with bounded report size.

**Constraints**: no new schema migrations; no network at test time; anonymity
(algorithms operate on anonymized email hashes; reports must not leak personal
data — LGPD rollout); the prior initiative guard must keep passing unchanged
(SC-006).

**Scale/Scope**: ~9.7k persons, 176 known duplicate groups; feature spans one
shared normalization function, one consolidation operation, one pipeline phase.

## Constitution Check

*GATE — passed for Phase 0 (research) and Phase 1 (design).*

- **Minimum viable complexity.** The redesign reuses the existing
  `PersonConsolidator` instead of introducing a new subsystem.
- **No scope creep.** The pipeline, ingestion and exports are touched only by a
  single added phase; no source loader behavior is redesigned.
- **Guard against false positives.** The strong-identifier veto and junk-name
  refusal are the constitution's safety rails for a matching feature.
- **Evidence-based.** Acceptance rests on the measured baseline (176 groups,
  2026-08-28 export) and the named exemplar, not on intuition.

## Project Structure

### Documentation (this feature)

```text
specs/008-guard-participant-merge/
├── spec.md              # Feature specification (rewritten, English)
├── research.md          # Identity-criterion analysis & decisions (English)
├── data-model.md        # Dedup scenarios A–G (English)
├── plan.md              # This file (English)
├── quickstart.md        # Runbook (English)
├── contracts/
│   └── dedup_rules.md   # R1–R14, the test-fixed contract (renamed from regras_correspondencia.md)
├── checklists/
│   └── requirements.md  # English requirements checklist
└── tasks.md             # Phase 2 execution order (/speckit.tasks)
```

### Implementation targets (repository root)

```text
src/
├── core/
│   ├── logic/
│   │   ├── person_identity.py      # NEW: single shared key function (R7)
│   │   ├── person_consolidator.py  # EXTENDED: union merge, vetoes, report, idempotency
│   │   ├── person_matcher.py       # ADAPTED: normalize_name delegates to the shared key
│   │   ├── researcher_resolution.py# ADAPTED: casefold/normalize via shared key
│   │   └── initiative_identity.py  # UNCHANGED: initiative/title guard stays
│   └── ...
└── flows/
    └── pipelines/
        └── weekly.py               # EXTENDED: dedup phase before export_canonical

src/scripts/
└── consolidate_duplicates.py       # EXTENDED: rasterizes the report, keeps manual use

tests/
├── test_person_identity.py         # NEW contract tests for the key function
├── test_person_consolidator.py     # EXTENDED: vetoes, union, junk, idempotency, report
├── test_weekly_orchestrator.py     # EXTENDED: dedup before export; report emitted
└── test_project_loader_matching.py # UNCHANGED: R1–R5 initiative guard regression
```

**Structure Decision**: single-project layout inherited as-is; the feature adds
one module (`person_identity.py`), extends the existing consolidator and the
weekly pipeline, and leaves the initiative guard untouched. No new directories,
no new app layers.

## Implementation Phases

### Phase 0 — Normal-form contract (`person_identity.py`)

Build the single shared key function (R7): NFD + drop combining marks, uppercase
(or single case), punctuation/hyphen → space, whitespace collapse, particle
canonicalization (`DE..Y` → lowercase canonical). Tests pin the examples from
data-model.md (spelling table, Scenario B). `PersonMatcher.normalize_name` and
the resolution path's casefold call are delegated to it so every comparison path
agrees.

### Phase 1 — Consolidation semantics (US2, US3, US4)

Extend `PersonConsolidator`:
- group memberships by the shared key;
- **veto** on conflicting strong identifiers (different Lattes/CNPq URL or
  identification ID) → refusal with reason;
- **junk-name refusal** (R13);
- **union merge**: transfer every link the loser owns unless an identical
  (entity, role) link already exists on the winner (R10);
- **deterministic winner** quality rule + fixed tiebreak (R12); field conflicts
  "winner wins", logged;
- **idempotency** (R14): second run is a no-op;
- emit the **deduplication report**.

Simultaneous and same-researcher initiatives survive by construction of the
union (Scenario E), covered by tests.

### Phase 2 — Identity-path unification (US1)

Point the participant-facing comparison paths at the shared key so one
participant in two spellings resolves to one record across sources. The
initiative guard (R1–R5) is untouched and its regression tests must still pass.

### Phase 3 — Pipeline integration (US5)

Insert the dedup phase into `weekly.py` **before** `export_canonical`; the
report joins the pipeline's `data/reports/`. `make weekly` and the dashboard
source export then consume an already-deduplicated catalog.

### Phase 4 — Validation and regression experiment

Run the full suite; run the baseline metrics comparison (176 → 0 initiativeless
duplicate groups, aggregate link-count equality, SC-002). Run the **mandated
experiment**: remove the veto → suite fails; restore → passes. Record results in
`tasks.md`'s final log step.

## Milestone Ordering

Milestones must close in this order because each depends on the previous:

1. **M1** – Shared key function + contract tests (Phase 0) — *testable alone*.
2. **M2** – Vetoes + union merge + report in the consolidator (Phase 1) —
   *depends on M1*.
3. **M3** – Comparison-path unification (Phase 2) — *depends on M1*.
4. **M4** – Pipeline dedup phase (Phase 3) — *depends on M2*.
5. **M5** – Full validation, metrics and the regression experiment (Phase 4) —
   *depends on M2/M4*.

## Definition of Done

- All contract rules R1–R14 are pinned by tests that fail when violated.
- The Israel Magalhães do Carmo pair (and, on the real catalog, every one of the
  176 groups) resolves to one record whose initiative set equals the union.
- Weekly-pipeline exports contain no initiativeless duplicate pairs — the
  dashboard shows one participant with the complete history.
- Full suite fast and green, <5s, db-less and offline; no existing test changes
  result (SC-006).
- All artifacts in this directory are written in English and internally
  consistent (spec ↔ research ↔ contract ↔ plan ↔ tasks ↔ checklist).

## Complexity Tracking

> Filled only if Constitution Check has violations that must be justified.

No violations. The design reuses the existing consolidator and adds one shared
key module; no new subsystem, no new project, no schema change.