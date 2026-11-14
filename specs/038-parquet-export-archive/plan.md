# Implementation Plan: Parquet export archive

**Branch**: `038-parquet-export-archive` | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/038-parquet-export-archive/spec.md`

## Summary

A new non-critical weekly phase, `parquet_archive`, runs right after
`zip_exports` and turns the top-level members of the freshly built
`exports_canonical.zip` into `data/exports/exports_parquet.zip`, in the
converter's layout. Reading the JSON archive, not `data/exports/`, makes the
Parquet values the ones that already went through the safety net. The archive
copies the JSON archive's manifest, is written atomically with fixed member
dates, is refused over 100 MB, and is committed by the weekly workflow together
with the JSON archive after the same publishing gate.

The research found that the converter's column rule looks only at the first
value of a column, so `attribute_assertions_canonical` (mixed `value_json`)
fails silently. The rule is replaced by one based on all the values of a
column; a prototype read back all 51 lists of rows and graph tables of the
2026-11-13 exports equal to
their JSON rows, byte-identical across processes, about 51 MB in all.

## Technical Context

**Language/Version**: Python 3.12 in GitHub Actions; the local `.venv` runs 3.14

**Primary Dependencies**: pandas and pyarrow (already in `requirements.txt` and `pyproject.toml`), Prefect (one flow), standard library `zipfile`, `hashlib`, `json`; `research-domain` / `eo_lib` unchanged; no new dependency

**Storage**: reads `data/exports/exports_canonical.zip`; writes `data/exports/exports_parquet.zip` (committed by the weekly workflow) and `data/reports/parquet_archive_report.json`; no database access

**Testing**: pytest: new `tests/test_parquet_layout.py` (column rule, mixed column, empty and all-empty cases, wrapped tables, graphs, JSON copies, read back equal, same bytes twice, error names the member); new `tests/test_parquet_archive.py` (archive from a small JSON archive: members, manifest copied, fixed dates, byte-identical twice, failure keeps the previous archive and leaves no temporary file, over-limit refused, report written, JSON archive untouched, no safety-net match in the values); `tests/test_export_parquet.py` (manual command over the module, exit code on a failed file); `tests/test_weekly_orchestrator.py` (phase after `zip_exports`, not critical, skipped when `zip_exports` did not pass); `tests/test_app_zip_exports.py` (dispatch `parquet_archive`; `export_canonical_data_flow(zip_exports=True)` builds both archives); `tests/test_zip_excludes_source_documents.py` (the JSON archive never holds `exports_parquet.zip`); `tests/test_weekly_etl_workflow.py` (both archives gated and committed in one step; CI checks both); the full suite; black, isort and flake8 on touched files

**Target Platform**: Linux, local runs and the GitHub Actions weekly workflow

**Project Type**: ETL pipeline (Prefect flows + domain logic)

**Performance Goals**: the phase adds about one minute (prototype: 68 s for two conversions and a read-back; one conversion is about half); peak memory about 1.4 GB

**Constraints**: archive and every member under 100 MB; no personal data beyond what the JSON archive carries; JSON archive unchanged in content, members and format; no Docker change; no change to third-party libraries or to the dashboard; no rule version or database change

**Scale/Scope**: 48 top-level members on 2026-11-14 (31 lists of rows, 10 graphs, 3 wrapped tables, 4 objects copied as JSON); about 51 MB of output; one pure module, one flow, one phase, one workflow step, three gate call sites (weekly, CI, pre-commit hook)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Ports & Adapters | PASS | The column rule and the layout are a pure module in `src/core/logic/` working on rows and bytes; the flow opens the archives and writes the files. |
| II. Domain-First Data Modeling | PASS | No entity changes; the Parquet archive is another serialization of the same canonical exports. |
| III. Prefect Flow Orchestration | PASS | The build is a Prefect flow with the Telegram state handlers, run by `app.py` and the weekly orchestrator; the script stays a manual utility over the same module. |
| IV. Audit-Driven Data Quality | PASS | Every build writes a report (status, member counts, sizes, source archive hash); tests and the quickstart check every table reads back equal to its JSON rows. |
| V. LGPD Compliance | PASS | The Parquet values come from the JSON archive after the safety net, so no value is published that the JSON archive does not carry; the same manifest and gate apply; the quickstart scans the values. |
| Data Integrity: 1. Persistent database | PASS | Untouched. |
| Data Integrity: 2. Idempotency | PASS | The same JSON archive gives a byte-identical Parquet archive; no database write. |
| Data Integrity: 3. Re-creatable | PASS | The Parquet archive is derived from the JSON archive and can be rebuilt at any time with `make parquet-archive`. No rule version change. |
| Data Integrity: 4. Published identity history | PASS | The id history keeps coming from `exports_canonical.zip` only; the Parquet archive is never read as an input (tested). |
| Data Integrity: 5. Raw inputs | PASS | No raw input involved. |
| Data Integrity: 7. Sources of truth | PASS | The Parquet archive is an output only. |
| Development Workflow | PASS | Tests before the change; full suite; formatters and linter on touched files; `make ci-check` recorded as in the earlier specs; the new Makefile target is the documented entry point. |

Re-check after Phase 1: PASS, no violation to justify.

## Project Structure

### Documentation (this feature)

```text
specs/038-parquet-export-archive/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1-R15
├── data-model.md        # Phase 1: the archive, its members, the column rule, the report
├── quickstart.md        # Phase 1: how to build and validate
├── contracts/
│   └── parquet-archive.md  # Phase 1: archive layout, reading contract, command, phase, report
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/core/logic/
└── parquet_layout.py            # NEW: column rule, layout of one member, read_member_back, equal_to_json (pure)

src/flows/exports/
├── parquet_archive.py           # NEW: task + flow: read the JSON archive, write exports_parquet.zip and the report
└── canonical_data.py            # zip_exports=True path also builds the Parquet archive; SKIP_DIRS comment

src/flows/pipelines/
└── weekly_orchestrator.py       # phase "parquet_archive" after zip_exports, non-critical, skipped unless zip_exports passed

src/scripts/
└── export_parquet.py            # manual command over parquet_layout; exit 1 when a file fails

app.py                           # dispatch "parquet_archive [output_dir]"
Makefile                         # target parquet-archive

.github/workflows/
├── weekly-etl.yml               # commit step gates and commits both archives
└── ci.yml                       # check each archive that changed

.githooks/
└── pre-commit                   # check each staged archive

tests/
├── test_parquet_layout.py           # NEW
├── test_parquet_archive.py          # NEW
├── test_export_parquet.py           # manual command, exit code
├── test_weekly_orchestrator.py      # the phase and its skip rule
├── test_app_zip_exports.py          # dispatch and the in-process path
├── test_zip_excludes_source_documents.py # JSON archive never holds the Parquet archive
└── test_weekly_etl_workflow.py      # both archives gated and committed; CI checks both

docs/
├── 2 - implementacao/ADR/003-parquet-canonical-storage.md  # amendment: the archive is back, built from the JSON archive
├── outputs-and-artifacts.md     # the Parquet archive, its layout, limits, report; stale parquet/ folder
├── flows-and-entrypoints.md     # the phase, the command, the target
└── backlog.md                   # TD-054: repository history growth
```

**Structure Decision**: the existing single-project layout. The conversion
rule is pure and shared by the flow and the manual command; the flow is the
only writer of the archive. The weekly phase sits after `zip_exports` and
before the read-only report modules.

## Complexity Tracking

No violation to justify.
