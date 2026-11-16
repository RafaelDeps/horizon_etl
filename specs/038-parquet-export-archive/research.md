# Research: Parquet export archive

**Feature**: 038-parquet-export-archive | **Date**: 2026-11-14

All measures below were taken on 2026-11-14, read-only, on the local
`data/exports/exports_canonical.zip` of 2026-11-13 (second local run of spec
037), with pandas 3.0.5 and pyarrow 25.0.1 from the local `.venv`. The
prototype ran in a scratch folder outside the repository.

## R1 — Where the Parquet content comes from

**Decision**: the Parquet archive is built from the members of the
`exports_canonical.zip` that the same run has just written, never from the
files in `data/exports/`.

**Rationale**: the JSON archive holds the exact text that went through the
safety net (`zip_exports_task` writes a scanned member as replaced text, a
clean member as the file itself). Reading the members back gives FR-002 by
construction: every value replaced in the JSON archive is replaced in the
Parquet archive, and nothing else is published. The safety net is idempotent
(`scan_text` docstring: "tokens are never matched again"), so a scan of the
Parquet values finds nothing (SC-003).

**Alternatives considered**:
- Convert inside the `zip_exports_task` walk, while each member's text is in
  hand: one read less, but the two archives would share one task, so a Parquet
  failure could break the JSON archive (against FR-006), and the task would
  hold the conversion's memory on top of its own.
- Convert the files of `data/exports/` and then scan the Parquet: a binary
  file cannot be scanned the way the text members are (spec 029, FR-003).

## R2 — When it is built

**Decision**: a new weekly phase, `parquet_archive`, right after
`zip_exports`, non-critical, with a 900 s timeout. It runs only when
`zip_exports` ran and passed in the same run; otherwise it is recorded as
skipped, with the log line "phase 'parquet_archive' skipped: zip_exports did
not build the archive". `app.py parquet_archive [output_dir]` runs it alone,
and a Makefile target `parquet-archive` calls it. Outside the weekly,
`export_canonical_data_flow(zip_exports=True)` (manual `app.py
export_canonical` without the weekly, and the unified pipeline) builds the
Parquet archive right after the JSON archive, never raising.

**Rationale**: a phase of its own runs in its own process (memory freed after
it) and a failure is a non-critical failure of the weekly ("completed with
non-critical failures"), so the run and the JSON archive are untouched
(FR-006). Skipping it when the JSON archive was not rebuilt keeps the two
archives from the same run: an older JSON archive and its own Parquet archive
stay as they were.

**Alternatives considered**: call it at the end of `zip_exports_flow`
(`tests/test_app_zip_exports.py::test_zip_exports_flow_calls_only_the_zip_task`
pins that flow to the zip task alone, and a failure would need to be swallowed
inside the critical phase); make it critical (against FR-006).

## R3 — How a column is written (fixes the mixed column)

**Decision**: each column is classified by the kinds of its non-empty values:
text, number, boolean, nested (list or object).

| Kinds found | Written as | Read back as |
|-------------|------------|--------------|
| nested, alone or with others; or more than one kind | every non-empty value encoded as JSON text (text values too); column listed in `.cols.json` | each value decoded from JSON: the original kind |
| numbers, all whole | nullable 64-bit integer | integer |
| numbers, some with a fraction | 64-bit float | float |
| text only | text | text |
| booleans only | boolean | boolean |
| none (all empty) | empty column | empty |

Columns are taken in the order they first appear in the rows; a key missing
from a row is written empty.

**Rationale**: today the converter looks only at the first non-empty value.
`value_json` of `attribute_assertions_canonical` (249,421 rows: 177,594 text,
16,058 integers, 21,388 lists, 274 objects) starts with text, so the lists are
not encoded and the file fails ("Expected bytes, got a 'list' object"). It is
the only mixed column on 2026-11-14. Encoding every value of a JSON column,
text included, makes the decoding exact: today a text value left raw inside a
nested column would come back changed when decoded ("123" becomes 123). The
whole-number rule replaces the id-column pin (`_is_id_column` +
`pd.to_numeric`), which also turned numeric text ids into integers.

Prototype result over the 48 top-level members (31 lists of rows and 10 graphs,
that is 51 tables with the graph node and edge lists apart; the 3 wrapped tables
were not part of the prototype): every table read back equals its JSON rows (same
values and order, missing key = null, integers as integers); 49.1 MB of
Parquet for the lists and graphs, plus the three wrapped tables and the JSON
copies, about 51 MB in all; `attribute_assertions_canonical` 7.5 MB, the
largest file 7.8 MB (`source_records_canonical`). Conversion of all tables
twice plus reading back: 68 s, peak memory 1.4 GB.

**Alternatives considered**: encode only the non-text values of a mixed column
(the decoder could not tell a text that looks like JSON from an encoded
value); store each mixed value in typed side columns (a new layout the
dashboard reader does not know).

## R4 — The layout stays the converter's

**Decision**: the members keep today's layout:

- list of rows → `<name>.parquet` + `<name>.cols.json`;
- wrapped table (`horizon_ids_canonical`, `horizon_id_aliases_canonical`,
  `source_document_states_canonical`) → `<name>.parquet` + `<name>.cols.json` +
  `<name>.meta.json` (the other keys);
- graph (`metadata`, `graph_stats`, `graph` with `nodes` and `edges`) →
  `<name>.nodes.parquet`, `<name>.edges.parquet`, their `.cols.json`, and
  `<name>.meta.json` (`metadata`, `graph_stats`, `graph` without the lists);
- any other object (marts, manifests, `data_provenance_canonical`, `_meta`) →
  `<name>.json`, the member's bytes as they are in the JSON archive.

Two changes: an empty list of rows becomes an empty table (today it is copied
as JSON), and a wrapped table with an empty list becomes an empty table plus
its meta (today it is copied as JSON), so a reader always finds the same
files.

**Rationale**: the dashboard's last reader (`parquet-plugin.mjs` at
horizon_dashboard `4d881eb`) reads `<name>.parquet`, revives with
`JSON.parse` exactly the columns named in `<name>.cols.json`, and rebuilds a
graph from the nodes, edges and meta files. Encoding every value of a listed
column (R3) is what that reader expects. The 10 graph files of 2026-11-14 hold
only `metadata`, `graph_stats` and `graph` (with `directed`, `multigraph`,
`graph`, `nodes`, `edges`), so the meta file loses nothing.

**Alternatives considered**: a new layout (one file per export with nested
types): the dashboard reader would have to be rewritten.

## R5 — Byte-identical archive for the same content

**Decision**: members in name order, each with the fixed date
1980-01-01 00:00, permissions 0644 and DEFLATE compression; the Parquet bytes
written in memory with zstd and no index; the JSON text written with sorted
keys where the converter makes it (sidecars, meta files).

**Rationale**: two separate processes converting the same members gave the
same Parquet bytes (same sha256). A fixed member date removes the only other
source of change. The JSON archive itself changes every run (its member dates
are file times and the exports carry run records such as
`ingestion_runs_canonical` and `generated_at`), so in practice the Parquet
archive changes whenever the JSON archive does; it never changes on its own.

**Caveat**: GitHub Actions installs pandas and pyarrow from `requirements.txt`
(`>=` pins). A new version may write different bytes once, for the same data.
Accepted: it is one extra commit when the library changes.

## R6 — Manifest

**Decision**: the Parquet archive carries the JSON archive's
`export_manifest.json` byte for byte, as its last member.

**Rationale**: the same key fingerprint and official flag (FR-003), and the
gate's key comparison works on the Parquet archive with no change. A JSON
archive without a manifest stops the build (nothing to copy), which the gate
would refuse anyway.

## R7 — Limits and atomic write

**Decision**: the archive is written to `exports_parquet.zip.tmp`; each member
is checked against 100 MB before it is written and the finished file against
100 MB (the same `MAX_ARCHIVE_BYTES` of spec 029); only then
`os.replace` puts it in place. Any error removes the temporary file and keeps
the previous archive.

**Rationale**: FR-004 and FR-005, and the same pattern as `zip_exports_task`.

## R8 — Reporting

**Decision**: every build writes `data/reports/parquet_archive_report.json`:
status (`built`, `failed`), the reason and the member that failed, the sha256
of the JSON archive it was built from, the number of members, the archive
size, the largest member and its size, and the seconds taken. A failure logs
an error with the member and reason, and a warning: "exports_parquet.zip is
now from an earlier run than exports_canonical.zip".

**Rationale**: FR-006 asks for the failure in the log and in "the export
report". The export report of spec 029 (`export_scan_report.json`) belongs to
the JSON archive and is written by another phase; a sibling report for the
Parquet archive keeps each phase writing only its own file. The sha256 of the
JSON archive lets anyone check that both archives come from the same run.

## R9 — Publishing gate

**Decision**: `src/scripts/check_publishable_archive.py` needs no change: it
takes the archive path, and checks size, manifest, official flag and key
against the same path at a ref. It is called for both archives:

- weekly workflow commit step: one call per archive with `--warn-only`; a
  refused archive is put back from the branch (or removed when new), the other
  one can still be committed;
- `ci.yml` "Check the export archive": one check per archive that changed;
- `.githooks/pre-commit`: one check per staged archive.

**Note**: the pre-commit hook also blocks any staged `data/exports/*` file over
50,000,000 bytes. The JSON archive (58 MB) is already over it and the Parquet
archive (about 51 MB) will be too: the archives are committed by the weekly
workflow, where the hook does not run. Left as it is.

## R10 — Weekly commit step

**Decision**: the step "Commit exports_canonical.zip if changed" becomes
"Commit the export archives if changed": it gates each archive that exists,
stages both, and makes one commit when either changed, with the message
`chore(exports): update the export archives from weekly run <date>`, then
pushes as today.

**Rationale**: FR-010 (one commit, only when one changed, a refused archive
put back without failing the run).

## R11 — The ETL never reads the Parquet archive

**Decision**: no change is needed; a test pins it. The readers name the JSON
archive explicitly (`horizon_id_store.DEFAULT_ZIP_PATH`,
`project_files` → `exports_canonical.zip`). `zip_exports_task` skips every
nested `.zip`, so `exports_parquet.zip` never enters the JSON archive, whose
member list stays the same (FR-008, FR-011, SC-005).

## R12 — Where the code lives

**Decision**: the conversion moves to a pure module,
`src/core/logic/parquet_layout.py` (column rule, layout of one member, reading
a table back). The flow, `src/flows/exports/parquet_archive.py`, opens the
JSON archive, writes the Parquet archive and the report.
`src/scripts/export_parquet.py` stays as the manual command over the same
module, with the same options; it now exits 1 and names the file when one
cannot be converted, after converting the others (FR-013, FR-017).

**Rationale**: Principle III (export logic runs in a Prefect flow, scripts are
utilities) and Principle I (the rule is testable without files). pandas is
already used in `src/core/logic/`.

## R13 — The stale `data/exports/parquet/` folder

**Decision**: nothing produces or reads it; `parquet` stays in `SKIP_DIRS`
(comment updated), so it never enters the JSON archive, and the Parquet
archive is built from the JSON archive, so it never enters that one either. The
ETL does not delete it; the docs say it is obsolete and can be removed by hand
(FR-012). On GitHub Actions it does not exist.

## R14 — No rule, database or Docker change

No key, hash, id or rule version changes (`HORIZON_RULE_VERSION` stays 6); no
migration; no table read or written. pandas and pyarrow are already
dependencies. No Docker change. The dashboard is not touched.

## R15 — Backlog

**Decision**: add TD-054 "The Parquet archive grows the repository history":
about 40 to 50 MB per run in which the data changed, on top of the JSON
archive; options to study later (release asset, history rewrite, a separate
data repository).
