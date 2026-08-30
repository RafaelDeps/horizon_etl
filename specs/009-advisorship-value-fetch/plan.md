# Implementation Plan: Advisorship Canonical Data Values Fetch

**Branch**: `009-advisorship-value-fetch` | **Date**: 2026-08-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-advisorship-value-fetch/spec.md`

## Summary

`advisorships_canonical.json` currently omits the advisorship program (category) and
provider, and never states the report year — the DB has all `program`/`type` NULL and
only 506/3,199 rows linked to a fellowship, so 84% of canonical advisorship objects
carry no category. This feature resolves `program`, `provider`, and `year` per
advisorship from its stored (LGPD-masked) SigPesq payload (`Programa`,
`AgFinanciadora`, report/directory year from `source_path`, `Ano` as tie-break),
publishes them additively in `advisorships_canonical.json` only (Q3=C), and populates
`advisorships.program` for new SigPesq ingestions (FR-007, column already exists in
research_domain — no schema change). Lattes-sourced rows export explicit `null`
(no program/provider in CVs, FR-008). Full decisions in `research.md`.

## Technical Context

**Language/Version**: Python 3.14 (`.venv/bin/python`)

**Primary Dependencies**: Prefect, SQLAlchemy 2.x, pandas/openpyxl (SigPesq xlsx),
`research_domain` (Advisorship/Fellowship/AdvisorshipType), `eo_lib`

**Storage**: SQLite `db/horizon.db` (research_domain schema). Reads:
`advisorships`, `initiatives`, `fellowships`, `organizations`,
`source_records` (`raw_payload_json`, `source_path`), `entity_matches`.

**Testing**: pytest (unit in `tests/`; integration in `tests/integration/`),
`make ci-check` (flake8, black, isort, mypy, pytest) as the quality gate.

**Target Platform**: Linux server (local Prefect + SQLite)

**Project Type**: Prefect ETL pipeline (flows / strategies / loaders / logic /
adapters) producing canonical JSON artifacts under `data/exports/`. The changed
surface is business logic (`src/core/logic/`) + tests; flows unchanged in shape.

**Performance Goals**: Export step stays single-pass over 3,808 advisorship source
records via one grouped SQL join + Python resolution; no per-row DB queries, no
network calls.

**Constraints**:
- LGPD (FR-006): only non-PII payload keys (`Programa`, `AgFinanciadora`, `Ano`,
  year fields) may be read/emitted; payloads already masked on write.
- Constitution I: `src/core/logic/` must not import adapters; source-record access
  stays on the existing session/repository pattern already used by the exporter.
- Additive fields only (FR-005); artifact scope is `advisorships_canonical.json` only
  (Q3=C); researchers/list files and `advisorships_tracking.json` untouched.

**Scale/Scope**: 3,199 advisorship entities; 3,808 advisorship source records
(701 sigpesq + 3,107 lattes); 19 fellowships; single export artifact.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Justification |
|-----------|--------|---------------|
| I. Ports & Adapters | ✅ PASS | New logic lives in `src/core/logic/`; source payload read through the exporter's existing session, no adapter import into core. |
| II. Domain-First Data Modeling | ✅ PASS | Reuses research_domain `Advisorship.program`; no new entity types; exported fields derivable from domain + stored source records. |
| III. Prefect Flow Orchestration | ✅ PASS | No new ingestion/export script; existing flows (SigPesq advisorship flow, canonical export flow) carry the change. FR-007 affects only new ingestions routed through the flow. |
| IV. Audit-Driven Data Quality | ✅ PASS | Parity + correctness validated by tests and `quickstart.md` (§3); no new loader/export without audit coverage. |
| V. LGPD Compliance by Default | ✅ PASS | Only `Programa`/`AgFinanciadora`/`Ano` from already-masked payloads; no PII field read or written (FR-006). |
| Dev Workflow & Quality Gates | ✅ PASS | `make ci-check` required; tests added under `tests/`. |

Result: no violations; `Complexity Tracking` stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/009-advisorship-value-fetch/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── advisorships-canonical.md
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/core/logic/
├── canonical_exporter.py                       # export: add year/program/provider (export_advisorships + fetch SQL)
├── advisorship_canonical_values.py             # NEW: load source values (SQL) + pure resolution rules
├── initiative_handlers.py                      # persist advisorship.program (create+update paths)
├── strategies/
│   ├── sigpesq_advisorships.py                 # add "program" to map_row return
│   └── lattes_advisorships.py                  # no change to program/provider (null by design)

src/scripts/
└── audit_advisorship_category_provenance.py    # NEW: read-only provenance/parity audit (SC-004; constitution III permits diagnostics)

tests/
├── test_canonical_exporter.py                  # extend: export emits new fields, parity sample
├── test_initiative_handlers.py                 # extend: program persisted on create/update
├── test_mappers.py                             # extend: strategy return carries "program"
└── test_advisorship_canonical_values.py        # NEW: resolution rules (dir year vs Ano, ties, lattes null)
```

**Structure Decision**: Single ETL project (Option 1). The feature is logic + tests
only; the exporter's private SQL is moved into a dedicated small module
(`advisorship_canonical_values.py`) so resolution rules are pure and unit-testable
without a session, mirroring how the rest of `src/core/logic/` is organized. No new
folders, no flow files, no adapter changes.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *(none)* | — | — |

## Plan Notes

- Phase 2 (`/speckit.tasks`) will produce `tasks.md`; task categories will follow
  logic/tests layout above.
- Backfill of the DB `program` column for historical rows is intentionally out of scope
  (spec assumption): the export resolves history from `source_records`; FR-007 covers
  new ingestions only.
- Performance goal (single-pass grouped SQL, no per-row DB queries) is enforced by
  task T002.