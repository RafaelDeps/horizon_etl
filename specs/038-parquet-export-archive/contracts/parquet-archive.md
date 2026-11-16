# Contract: Parquet export archive

**Feature**: 038-parquet-export-archive | **Date**: 2026-11-14

## 1. Archive for consumers (the dashboard)

- Path in the ETL repository: `data/exports/exports_parquet.zip`, next to
  `data/exports/exports_canonical.zip`, committed by the weekly workflow in the
  same commit when either changed.
- Holds the top-level exports only. `research_group_relationship_graphs/` and
  `project_sigpesq_files_json/` stay in the JSON archive only.
- Members and layout: [data-model.md](../data-model.md), "Layout of one JSON
  member".
- `export_manifest.json`: the same bytes as in the JSON archive of the same
  run.

### Reading rules

1. A table `<name>.parquet` is a list of rows; read it with any Parquet reader.
2. Decode with JSON every value of the columns named in the sibling
   `<name>.cols.json` (`json_columns`); every non-empty value of such a column
   is JSON text, including values that were text in the export.
3. Integer columns are 64-bit; a reader that turns them into floating numbers
   loses precision above 2^53 (no export column reached it on 2026-11-14).
4. A graph is rebuilt as
   `{"metadata": meta.metadata, "graph_stats": meta.graph_stats, "graph": {...meta.graph, "nodes": <nodes table>, "edges": <edges table>}}`.
5. A wrapped table is rebuilt as `{...meta, <rows key>: <table>}`, with rows key
   `ids`, `aliases` or `documents`.
6. A `<name>.json` member is the export file as published in the JSON archive.

The reader of horizon_dashboard at `4d881eb` (`parquet-plugin.mjs`) follows
rules 1, 2, 4 and 6.

### Reading helpers in the ETL

`src/core/logic/parquet_layout.py` exposes, for tests and the quickstart:

- `read_member_back(archive, json_name)`: rebuilds the JSON value of one export
  (`<name>.json`) from the Parquet archive by rules 1 to 6;
- `equal_to_json(rebuilt, original)`: the equality of the data model (same
  rows in the same order, a key missing from a JSON row equals an empty value,
  integers as integers).

## 2. Build guarantees

| Guarantee | How it is checked |
|-----------|-------------------|
| Values equal the JSON archive of the same run (equality as in data-model) | `tests/test_parquet_layout.py`, `tests/test_parquet_archive.py`, quickstart step 4 |
| No value the safety net would replace | quickstart step 5; built from the scanned members |
| Same JSON archive → byte-identical Parquet archive | `tests/test_parquet_archive.py`, quickstart step 6 |
| Archive and each member ≤ 100 MB, else refused and the previous kept | `tests/test_parquet_archive.py` |
| A member that cannot be converted fails the whole archive | `tests/test_parquet_archive.py` |
| The JSON archive is never changed by this build | `tests/test_parquet_archive.py` |
| The ETL never reads the Parquet archive | `tests/test_zip_excludes_source_documents.py`, review of readers |

## 3. Commands

| Command | Does |
|---------|------|
| `make parquet-archive` | builds `$(OUTPUT_DIR)/exports_parquet.zip` from `$(OUTPUT_DIR)/exports_canonical.zip` |
| `python app.py parquet_archive [output_dir]` | the same (default `data/exports`) |
| `python -m src.scripts.export_parquet --src DIR --dst DIR` | manual conversion of a folder of JSON files to the same layout as loose files; converts every file it can, then exits 1 naming each file that failed |

## 4. Weekly phase

- Name `parquet_archive`, argv `["parquet_archive"]` plus the output folder,
  timeout 900 s, not critical, mode `app`.
- Position: right after `zip_exports`.
- Runs only when `zip_exports` ran and passed in the same run; otherwise
  recorded as skipped with the log line
  `phase 'parquet_archive' skipped: zip_exports did not build the archive`.
- A failure ends the weekly as "completed with non-critical failures".

## 5. Publishing gate

`python -m src.scripts.check_publishable_archive <archive> [--ref REF] [--warn-only]`,
unchanged, applied to each archive:

| Where | Archives | On refusal |
|-------|----------|------------|
| Weekly workflow, step "Commit the export archives if changed" | both, `--ref HEAD --warn-only` | warning; that archive is put back from the branch (removed when new); the other is still committed |
| `ci.yml`, "Check the export archive" | each one that changed since the base | the job fails |
| `.githooks/pre-commit` | each one staged | the commit is blocked |

Commit message of the weekly: `chore(exports): update the export archives from weekly run <YYYY-MM-DD>`.

## 6. Report and log

- Report: `data/reports/parquet_archive_report.json`, fields in
  [data-model.md](../data-model.md).
- Log on success: `Parquet archive built: <members> members, <bytes> bytes, largest <name> (<bytes>), <seconds> s`.
- Log on failure: an error naming the member and the reason, then the warning
  `exports_parquet.zip is now from an earlier run than exports_canonical.zip`.
- No value of any export is printed.
