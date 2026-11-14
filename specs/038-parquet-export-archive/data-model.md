# Data Model: Parquet export archive

**Feature**: 038-parquet-export-archive | **Date**: 2026-11-14

No database table, entity, key or id changes. The model below is the shape of
the files the feature reads and writes.

## JSON archive (input, unchanged)

`data/exports/exports_canonical.zip`, built by the `zip_exports` phase
(spec 029).

| Part | Used here |
|------|-----------|
| Top-level members `<name>.json` (48 on 2026-11-14) | the source of every Parquet member |
| Members under a folder (`research_group_relationship_graphs/`, `project_sigpesq_files_json/`) | not used |
| `export_manifest.json` (`official`, `key_fingerprint`) | copied as it is |

A member's text is the text after the safety net: a member with matches holds
the replaced text, a clean member holds the export file itself.

## Parquet archive (output)

`data/exports/exports_parquet.zip`.

| Rule | Value |
|------|-------|
| Members | for each top-level JSON member, the members of its layout (below); then `export_manifest.json` |
| Order | by member name, the manifest last |
| Member date | 1980-01-01 00:00 |
| Member permissions | 0644 |
| Compression | DEFLATE for every member; Parquet data inside uses zstd |
| Size | archive ≤ 100 MB (104,857,600 bytes); every member ≤ 100 MB |
| Written as | `exports_parquet.zip.tmp`, then renamed; the temporary file is removed on any failure |

### Layout of one JSON member `<name>.json`

| JSON content | Members written |
|--------------|-----------------|
| list of objects (rows), empty list included | `<name>.parquet`, `<name>.cols.json` |
| object with `graph` holding `nodes` and `edges` | `<name>.nodes.parquet`, `<name>.nodes.cols.json`, `<name>.edges.parquet`, `<name>.edges.cols.json`, `<name>.meta.json` |
| wrapped table: `horizon_ids_canonical` (`ids`), `horizon_id_aliases_canonical` (`aliases`), `source_document_states_canonical` (`documents`) | `<name>.parquet`, `<name>.cols.json`, `<name>.meta.json` |
| any other value (marts, manifests, summaries) | `<name>.json`, the member's bytes unchanged |

`<name>.meta.json`:
- graph: `{"metadata": …, "graph_stats": …, "graph": {"directed": …, "multigraph": …, "graph": …}}`;
- wrapped table: every key of the object except the rows key.

`<name>.cols.json`: `{"json_columns": [<column>, …]}`, the columns whose values
are JSON text, in column order.

### Column rule (one Parquet table)

Columns: every key found in the rows, in the order each first appears. A key
missing from a row is an empty value.

Kinds of a non-empty value: text (string), number (integer or float, not
boolean), boolean, nested (list or object).

| Kinds of the column's non-empty values | Parquet column | In `json_columns` | Value read back |
|----------------------------------------|----------------|-------------------|-----------------|
| contains nested, or more than one kind | text: each value is its JSON encoding (`ensure_ascii=False`), text values included | yes | JSON-decoded: same kind and value |
| number, all whole | 64-bit integer, nullable | no | integer |
| number, some with a fraction | 64-bit float | no | float (a whole value in such a column reads back as `3.0`, equal to `3`) |
| text | text | no | text |
| boolean | boolean | no | boolean |
| no non-empty value | empty column | no | empty |

Example, `attribute_assertions_canonical.value_json` on 2026-11-14:
177,594 text, 16,058 integer, 21,388 list, 274 object, 34,107 empty → listed in
`json_columns`; `"Divulgação"` is stored as `"\"Divulgação\""`, `42` as `"42"`,
`[1, 2]` as `"[1, 2]"`.

### Equality of a table read back (spec Clarification 3)

A table read back equals its JSON rows when, row by row in the same order, every
column has the same value, a key missing from a JSON row equals an empty
value, JSON columns are compared after decoding, and integers compare as
integers.

## Report (output)

`data/reports/parquet_archive_report.json`, written by every build:

| Field | Type | Meaning |
|-------|------|---------|
| `status` | `"built"` or `"failed"` | result of this build |
| `reason` | text or null | why it failed |
| `failed_member` | text or null | the JSON member being converted when it failed |
| `json_archive_sha256` | text or null | hash of the `exports_canonical.zip` it was built from |
| `members` | integer | members written (0 when failed) |
| `archive_bytes` | integer or null | size of the archive written |
| `largest_member` | text or null | name of the largest member |
| `largest_member_bytes` | integer or null | its size |
| `seconds` | number | time taken |

On `failed`, the previous `exports_parquet.zip` is unchanged, and the log says it
is now from an earlier run than `exports_canonical.zip`.

## Weekly phase (state)

| `zip_exports` in this run | `parquet_archive` |
|---------------------------|-------------------|
| passed | runs; a failure is a non-critical failure of the run |
| failed or skipped | skipped (recorded as a non-critical failure, not run); both archives stay as they were |
