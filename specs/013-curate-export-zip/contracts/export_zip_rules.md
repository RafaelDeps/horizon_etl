# Contract: Export Archive Rules (R1–R15)

**Branch**: `013-curate-export-zip` | **Date**: 2026-09-18

The test-pinned contract for `zip_exports_task`
(`src/flows/exports/canonical_data.py`) and
`SigPesqProjectFilesAdapter.extract_json`
(`src/adapters/sources/sigpesq/project_files.py`). Every rule is falsifiable
by a named test; the suite must fail when a rule is violated.

## A. Archive contents (zip side)

- **R1 — Scrubbed corpus ships.** Every `PJ_*.json` in
  `<output_dir>/project_sigpesq_files_json/` appears in the archive at
  `project_sigpesq_files_json/<same name>`.
- **R2 — No raw contact data.** The concatenated archive bytes contain no
  clear-text e-mail (RFC-style `local@domain.tld`) and no phone pattern the
  project's scrubber recognizes. Anonymized tokens (`@anon.lgpd`,
  `LGPD-PHONE-`) MAY appear.
- **R3 — Scrub idempotency.** Re-archiving content that already carries
  anonymized tokens leaves those tokens byte-identical.
- **R4 — Raw corpus never walked in.** `project_sigpesq_files_json` stays in
  `SKIP_DIRS`; no archive member originates from the raw walk of that folder.
- **R5 — No nested archives.** No member path ends in `.zip` — this covers
  `data_snapshot.zip`, the archive itself, and its `.tmp`.
- **R6 — Report/format folders pruned.** No member path starts with
  `formandos/`, `docentes/`, `mestrado/`, or `parquet/`, even when those
  folders exist in the export folder.
- **R7 — Surgical pruning.** Members in other subfolders (e.g.
  `docentes`-like names are pruned, but `marts/anything.json`) still ship;
  pruning never over-matches beyond the five names in `SKIP_DIRS`.
- **R8 — Absent categories are a no-op.** With none of the excluded items and
  no PJ corpus present, generation succeeds and the archive holds exactly the
  walked files.
- **R9 — One malformed document never sinks the archive.** A `PJ_*.json` that
  fails to parse is skipped with a recorded warning; all other members ship.

## B. Parquet removal (flow side)

- **R10 — No parquet emission.** `export_canonical_data_flow` does not call
  the parquet task; the task is removed from the flow module. The manual
  script `src/scripts/export_parquet.py` remains importable/usable.

## C. Archive reuse (adapter side)

- **R11 — Local wins.** A PDF whose JSON already exists locally is skipped
  without consulting the archive (existing behavior preserved).
- **R12 — Hit reuses, zero paid calls.** For a pending PDF whose
  `project_sigpesq_files_json/<stem>.json` exists in the archive and parses:
  the extractor is NOT called; the parsed copy is written to `json_dir` with
  the standard JSON formatting; `stats["reused"]` counts it.
- **R13 — Stem matching.** Matching is exactly
  `project_sigpesq_files_json/<stem>.json` — no fuzzy or content-based
  matching, no other archive locations.
- **R14 — Force bypasses reuse.** With `force=True`, every PDF goes to the
  extractor regardless of archive contents (and regardless of local JSONs).
- **R15 — Graceful fallback.** Missing archive, unreadable/corrupt archive,
  missing entry, or malformed entry → the project is extracted normally; the
  run neither fails nor degrades other projects.

## Traceability

| Rule | Spec | Test home |
|---|---|---|
| R1–R9 | US1, US2 (FR-001..006, FR-009, FR-010) | `tests/test_zip_excludes_source_documents.py` |
| R10 | US3 (FR-007) | `tests/test_zip_excludes_source_documents.py` (import-level) + quickstart smoke |
| R11–R15 | US4 (FR-011..FR-015) | `tests/test_project_files_zip_reuse.py` |
