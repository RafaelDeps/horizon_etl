# Implementation Plan: Curated Export Archive

**Branch**: `013-curate-export-zip` | **Date**: 2026-09-18 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/013-curate-export-zip/spec.md`

## Summary

Reshape `exports_canonical.zip` into a single curated deliverable and cut a dead
weekly cost. Four moves, all inside existing flow code:

1. **Ship the SigPesq project documents** (`PJ_*.json`) inside the archive as
   **scrubbed copies** written at zip time — e-mails and phone numbers replaced
   with the same LGPD hash tokens the rest of the pipeline uses
   (`scrub_pii_deep`). The raw corpus on disk is never modified and never
   enters the archive unscrubbed.
2. **Exclude the noise**: any nested `*.zip` (covers `data_snapshot.zip`) and
   the report/format folders `formandos/`, `docentes/`, `mestrado/`, `parquet/`
   are pruned from the archive walk.
3. **Remove the parquet step** from `export_canonical_data_flow` entirely
   (weekly, full pipeline and manual `export_canonical` all stop emitting
   `parquet/`); the underlying script stays for manual use; ADR-003 is amended.
4. **Reuse before paying**: the Mistral extraction step (`extract_json`)
   consults the latest archive — for a project with no local JSON, an archived
   `project_sigpesq_files_json/PJ_<code>.json` is restored locally instead of
   calling the paid extraction service. Miss/malformed/absent archive falls
   back to normal extraction; `force` bypasses reuse.

## Technical Context

**Language/Version**: Python 3.12 (CI) / 3.14 (local venv) — no version-sensitive
constructs introduced; stdlib `zipfile`/`json` only.

**Primary Dependencies**: none new. Reuses `zipfile` (already imported in
`canonical_data.py`), `src/core/logic/pii_anonymizer.scrub_pii_deep` (existing,
tested), and the pinned `agent_sigpesq` `ProjectExtractor` (unchanged).

**Storage**: filesystem only — `data/exports/` (archive + corpora). No DB
schema or data changes.

**Testing**: pytest, db-less and offline. Zip behavior tested via
`zip_exports_task.fn(str(tmp_path))` (existing pattern in
`tests/test_zip_excludes_source_documents.py`); reuse behavior tested with a
fake `ProjectExtractor` and a real in-memory `zipfile` archive.

**Target Platform**: Linux (GitHub Actions runner + local), weekly pipeline.

**Project Type**: ETL pipeline; this feature touches the export flow and one
source adapter.

**Performance Goals**: zip generation stays I/O-bound; scrubbing is per-file
JSON parse/dump (corpus is hundreds of small JSONs — negligible). Reuse removes
Mistral API calls (seconds + cost per document avoided).

**Constraints**: no raw PII may reach the archive (constitution V); raw corpus
on disk immutable; archive path for project docs stays
`project_sigpesq_files_json/` (user decision); `force` semantics preserved.

**Scale/Scope**: ~hundreds of `PJ_*.json` files; one task function rewritten,
one adapter method extended, one flow call removed, two test files + one new
test file, one ADR amended.

## Constitution Check

*GATE — passed for Phase 0 (research) and re-checked after Phase 1 design.*

- **I. Ports & Adapters (non-negotiable)**: dependency direction preserved —
  `src/flows/exports/canonical_data.py` (flow layer) imports the scrubber from
  `src/core/logic/pii_anonymizer.py` (core); core still imports nothing from
  adapters. The reuse change lives in the SigPesq adapter, which is exactly the
  layer allowed to touch external artifacts. **PASS**
- **II. Domain-First Data Modeling**: no new domain entities; the PJ corpus
  remains an ETL-transient input structure (established precedent, ADR-002).
  **PASS**
- **III. Prefect Flow Orchestration (non-negotiable)**: all changed behavior
  runs inside existing Prefect tasks (`zip_exports_task`,
  `extract_project_json_task`) of existing flows; no standalone ingestion/export
  path added. **PASS**
- **IV. Audit-Driven Data Quality**: extraction stats gain a `reused` counter
  and zip generation logs excluded/scrubbed counts, so every run reports what
  was reused vs. paid for and what was excluded. **PASS**
- **V. LGPD Compliance by Default**: central to the feature — no clear-text
  e-mail/phone may enter the versioned archive; scrubbing reuses the project's
  single anonymizer (idempotency built in). Reused archived copies carry
  anonymized contact fields, which the enrichment consumer never uses.
  **PASS (strengthens compliance)**
- **Data Integrity & Clean-State Ingestion**: no DB changes; raw directories
  untouched; the archive is an output, never a source of truth — the reuse
  feature restores *input* material from the previous run's archive, which is
  the same resumable-corpus principle the download stage already follows.
  **PASS**
- **Development Workflow & Quality Gates**: new/updated tests; targeted pytest
  runs documented in quickstart.md; `make ci-check` remains the gate (known
  pre-existing failures recorded in specs/009 are out of scope). **PASS**

## Project Structure

### Documentation (this feature)

```text
specs/013-curate-export-zip/
├── spec.md                    # Feature specification (done)
├── plan.md                    # This file
├── research.md                # Phase 0: decisions & rationale
├── data-model.md              # Phase 1: archive contents, scrub mapping, reuse states
├── quickstart.md              # Phase 1: runbook (tests + manual verification)
├── contracts/
│   └── export_zip_rules.md    # R1–R15, the test-pinned contract
├── checklists/
│   └── requirements.md        # Spec quality checklist (done)
└── tasks.md                   # Phase 2 output (/speckit.tasks — NOT created here)
```

### Implementation targets (repository root)

```text
src/flows/exports/
└── canonical_data.py          # EXTENDED: SKIP_DIRS + *.zip file skip +
                               #   scrubbed-PJ writestr block;
                               #   REMOVED: export_parquet_task + its call

src/adapters/sources/sigpesq/
└── project_files.py           # EXTENDED: extract_json consults the latest
                               #   archive before calling the extractor
                               #   (reuse hit → restore; miss → Mistral)

docs/2 - implementacao/ADR/
└── 003-parquet-canonical-storage.md  # AMENDED: parquet no longer emitted by
                                      #   the flow; script remains manual

tests/
├── test_zip_excludes_source_documents.py  # REWRITTEN: scrubbed inclusion,
│                                          #   exclusions, malformed-skip
├── test_project_files_zip_reuse.py        # NEW: reuse hit/miss/force/malformed
└── test_export_canonical_data_flow.py     # UNCHANGED (never pinned parquet)
```

**Structure Decision**: single-project layout inherited as-is. No new modules,
no new directories: one flow file and one adapter file carry the whole change,
plus tests and one ADR amendment.

## Implementation Phases

### Phase 0 — Research decisions (research.md)

Resolved without agents: all unknowns were settled by reading the code
(`canonical_data.py`, `project_files.py`, `pii_anonymizer.py`) and by the two
user decisions already recorded in the spec (parquet removed from the flow
entirely; exclusion covers any nested `.zip`).

### Phase 1 — Archive curation (US1, US2)

In `zip_exports_task`:
- extend `SKIP_DIRS` to `{project_sigpesq_files_json, formandos, docentes,
  mestrado, parquet}` (the raw PJ folder stays pruned from the walk);
- skip any file whose name ends in `.zip` (covers `data_snapshot.zip`, the
  archive itself and its `.tmp`);
- after the walk, inside the same `ZipFile` context, add scrubbed copies of
  every `PJ_*.json` from the raw corpus via `zf.writestr`, using
  `scrub_pii_deep`; malformed files are skipped with a warning (FR-010).

### Phase 2 — Parquet removal (US3)

Delete `export_parquet_task` and its invocation from
`export_canonical_data_flow`; keep `src/scripts/export_parquet.py` for manual
use; amend ADR-003 (parquet no longer emitted in the weekly archive).

### Phase 3 — Archive reuse in extraction (US4)

Extend `SigPesqProjectFilesAdapter.extract_json`:
- archive path = `os.path.join(os.path.dirname(self.json_dir),
  "exports_canonical.zip")`;
- for each pending PDF stem, look up
  `project_sigpesq_files_json/<stem>.json` in the archive;
- hit + parse OK → write the parsed copy to `json_dir` (same JSON formatting
  as extraction), `stats["reused"] += 1`, no extractor call;
- miss, malformed entry, or unreadable archive → fall back to normal
  extraction; `force=True` bypasses reuse (and existing skip).

### Phase 4 — Tests and validation

Rewrite `test_zip_excludes_source_documents.py`; add
`test_project_files_zip_reuse.py`; run targeted pytest, then the full fast
suite. Verify manually per quickstart.md (zip listing + reuse smoke run).

## Milestone Ordering

1. **M1** — Archive curation (Phase 1) + rewritten zip tests — *testable alone*.
2. **M2** — Parquet removal (Phase 2) + ADR amendment — *independent of M1*.
3. **M3** — Reuse in extraction (Phase 3) + new reuse tests — *independent of
   M1/M2 code-wise, but logically builds on M1* (the archive must contain the
   corpus for reuse to have something to find).
4. **M4** — Full validation (Phase 4) — *depends on M1–M3*.

## Definition of Done

- Contract rules R1–R15 (contracts/export_zip_rules.md) are pinned by tests
  that fail when violated.
- A weekly-run archive contains: all canonical exports (unchanged), the
  scrubbed `project_sigpesq_files_json/` corpus, and nothing else new — no
  nested zip, no `formandos/`, `docentes/`, `mestrado/`, `parquet/`.
- Zero clear-text e-mails/phones in the archive (SC-002).
- `export_canonical` no longer emits `parquet/`; ADR-003 amended.
- From a clean environment with the previous archive present, extraction makes
  zero paid calls for archived projects (SC-006) and reports them as `reused`.
- Targeted and full test suites green.

## Complexity Tracking

> Filled only if Constitution Check has violations that must be justified.

No violations. The change reuses the existing anonymizer, the existing zip
task, and the existing adapter method; no new subsystem, no schema change, no
new dependency.
