# Feature Specification: Parquet export archive

**Feature Branch**: `038-parquet-export-archive`

**Created**: 2026-11-14

**Status**: Draft

**Input**: User description: "Publish the canonical exports as Parquet again, in a second archive next to exports_canonical.zip, so the dashboard can be built in GitHub Actions."

## Background

The dashboard keeps a copy of the exports in its own repository and builds the
site from it in GitHub Actions. With the data of the 2026-11-13 local run, two
export files are over GitHub's limit of 100 MB per file:

| Export file | Size |
|-------------|------|
| advisorships_tracking.json | 164 MB |
| attribute_assertions_canonical.json | 133 MB |
| people_relationship_graph.json | 88 MB |
| source_records_canonical.json | 63 MB |
| initiatives_tracking.json | 61 MB |

The dashboard can therefore no longer be pushed or built in CI. It once read a
compact columnar copy of the exports (Parquet) and that reader will be brought
back in the dashboard repository. The ETL has to deliver that copy again.

The ETL still has the converter that produces it (`src/scripts/export_parquet.py`,
kept up to date by specs 020 and 021). Spec 013 removed it from the export
flow and left it for manual use only. Its layout:

- a table becomes `<name>.parquet` plus `<name>.cols.json`, the list of columns
  that hold nested values written as text;
- a graph becomes `<name>.nodes.parquet` and `<name>.edges.parquet`, each with
  its `.cols.json`, plus `<name>.meta.json`;
- small objects (summaries, marts, `_meta`) are copied as `<name>.json`.

Measured on the 2026-11-13 exports:

| Measure | Value |
|---------|-------|
| Top-level export files (JSON) | 855 MB |
| The same files inside exports_canonical.zip | 54.9 MB |
| The same files converted to Parquet, all but attribute_assertions_canonical | 43 MB |
| attribute_assertions_canonical converted with its mixed column written as text | 7.5 MB |
| Expected Parquet archive | about 51 MB |
| Largest Parquet file | 7.8 MB |
| Conversion time / peak memory (without attribute_assertions_canonical) | 36 s / 1.2 GB |
| research_group_relationship_graphs/ (stays JSON) | 361 files, 111 MB, largest 4.7 MB |

Why a second archive instead of adding Parquet to exports_canonical.zip:

- exports_canonical.zip must stay JSON: the ETL reads it back (published id
  history, previous SigPesq project documents).
- It is 58 MB and its build refuses an archive over 100 MB (spec 029); JSON
  and Parquet together would be about 101 MB.
- Every member of exports_canonical.zip is text and goes through the personal
  data safety net (spec 029) before it is written. A binary Parquet file cannot
  be scanned the same way, so the Parquet content has to come from text that
  already went through the safety net.

The converter takes new fields with no change: it builds the columns from each
export file, so `linkedin_url` (spec 037) is already in the converted
researchers table, with the same 148 links as the JSON. It does not convert
every export, though. It decides how to write a column from the first non-empty
value only, and the column `value_json` of `attribute_assertions_canonical`
(249,421 rows, the 133 MB file) mixes text (177,594), integers (16,058), lists
(21,388) and objects (274). The first value is text, so the lists are not
written as text and the file fails. The converter logs a warning and goes on,
so the converted folder silently lacks that table. On 2026-11-14 it is the only
top-level export with a column that mixes kinds of values.

A folder `data/exports/parquet/` (17 MB, 2026-09-17) is left on the
maintainer's machine from before spec 013. Nothing produces or reads it today.

## Clarifications

### Session 2026-11-14

- Q: When the Parquet archive fails, what happens to the JSON archive? → A: The JSON archive is built and published as usual; the previous Parquet archive is kept, and the run log and the export report say the failure and that the two archives now come from different runs.
- Q: How is the Parquet archive published? → A: Committed to the ETL repository by the weekly workflow, like the JSON archive, in every run where the data changed; the growth of the repository history is registered in docs/backlog.md to be handled later.
- Q: What counts as "the same rows" when reading Parquet back? → A: Same values in the same row order, with nested values revived; a key missing from a JSON row equals null; id columns compare as integers.
- Q: Does the converter take the new export data? → A: New fields yes (linkedin_url included); but a column mixing kinds of values (value_json of attribute_assertions_canonical) makes the file fail silently. The converter must handle mixed columns, and a file that cannot be converted fails the whole Parquet archive (FR-016, FR-017, FR-018).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The weekly run publishes a Parquet archive (Priority: P1)

After every weekly run, locally and in GitHub Actions, the maintainer finds
`data/exports/exports_parquet.zip` next to `exports_canonical.zip`. It holds
the Parquet layout of every top-level export, in the layout the converter
already produces, with the same values as the JSON archive of the same run.
The weekly workflow commits it together with the JSON archive, so the
dashboard can take it from the ETL repository.

**Why this priority**: it is what unblocks the dashboard build in CI.

**Independent Test**: run the export step on a populated database; open the
Parquet archive, read every table back, and compare it with the JSON of the
same run.

**Acceptance Scenarios**:

1. **Given** a finished weekly run, **When** the export step ends, **Then**
   `exports_parquet.zip` exists, is under 100 MB, and every file in it is
   under 100 MB.
2. **Given** the Parquet archive and the JSON archive of the same run, **When**
   every Parquet table is read back (reviving the columns named in its
   `.cols.json`), **Then** it gives the same rows as the JSON export of the same
   name, for every top-level export: the same values in the same row order,
   nested values equal after revival, a key missing from a JSON row read back
   as null, and id columns compared as integers.
3. **Given** the weekly workflow in GitHub Actions, **When** the run ends and
   either archive changed, **Then** both archives are committed in the same
   commit.
4. **Given** the change, **When** exports_canonical.zip is built, **Then** it
   has the same member list and format as before the change.

---

### User Story 2 - The Parquet archive is as safe as the JSON archive (Priority: P1)

Everything the safety net replaced in the JSON archive is replaced the same way
in the Parquet archive: the Parquet values are built from the text that went
into the JSON archive, after the safety net. The Parquet archive carries the
same manifest (key fingerprint, official flag) and passes the same publishing
gate (size, manifest, official build, same key as the committed archive) in
the pre-commit hook, in CI and in the weekly workflow's commit step.

**Why this priority**: the archive is public; the dashboard is not worth a leak
of personal data.

**Independent Test**: build both archives from exports that contain a planted
e-mail and phone number; the JSON archive has them replaced, and no Parquet
value holds the plain values. Run the publishing gate on a Parquet archive
without a manifest, from a local build, over the limit, and with another key.

**Acceptance Scenarios**:

1. **Given** an export value replaced by the safety net in the JSON archive,
   **When** the Parquet archive is built, **Then** the same value in the
   Parquet archive holds the same replacement and never the plain value.
2. **Given** a Parquet archive with no manifest, built locally, over 100 MB, or
   made with another key than the committed one, **When** the publishing gate
   runs, **Then** it refuses it exactly as it refuses such a JSON archive
   (a failure in CI and in the pre-commit hook, a warning that puts the
   committed archive back in the weekly workflow).
3. **Given** the text of every Parquet value, **When** it is run through the
   safety net scan, **Then** it finds no match.

---

### User Story 3 - A failed or repeated build changes nothing (Priority: P2)

A build that fails (conversion error, archive over the limit, missing key)
keeps the previous Parquet archive and does not touch the JSON archive. Two
builds from the same export content give byte-identical Parquet archives, so
the weekly workflow does not commit a new Parquet archive when the published
data did not change.

**Why this priority**: the archive is committed to git every run; noise or a
broken archive would reach the dashboard.

**Independent Test**: build the Parquet archive twice from the same export
folder and compare the bytes; force a failure in the middle of a build and
check the previous archive is unchanged.

**Acceptance Scenarios**:

1. **Given** the same export content, **When** the Parquet archive is built
   twice, **Then** both archives are byte-identical.
2. **Given** a failure while the Parquet archive is built, **When** the step
   ends, **Then** the previous Parquet archive is unchanged and no partial file
   is left.
3. **Given** a failure of the Parquet archive, **When** the export step ends,
   **Then** exports_canonical.zip is built and published as it is today, and
   the run log and the export report warn that the Parquet archive is from an
   earlier run.

### Edge Cases

- A column mixes kinds of values (text, numbers, lists, objects), like
  `value_json` of attribute_assertions_canonical: it is converted, and every
  value reads back with its original kind (text stays text, a number stays a
  number, a list stays a list).
- One export file cannot be converted: the whole Parquet archive fails and the
  previous one is kept (FR-006); an archive missing a table is never published.
- An export file is an empty list: the Parquet archive still carries the table
  (with no rows) so the dashboard finds every expected file.
- An export file is neither a list, a graph nor a known wrapped table (a
  summary or a mart): it is copied as JSON, after the safety net, like today's
  converter does.
- A new export file appears in a later spec: it is converted with no change to
  this feature.
- One Parquet file would be over 100 MB: the archive is refused and the
  previous one is kept, with a log line naming the file.
- The key used by the safety net is missing: neither archive is built, as today
  for the JSON archive.
- The stale `data/exports/parquet/` folder exists: it is not read, not changed
  and not put into either archive.
- research_group_relationship_graphs/: not converted and not in the Parquet
  archive; the dashboard keeps reading it as JSON from the JSON archive.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The export step MUST write `data/exports/exports_parquet.zip`,
  holding the Parquet layout of every top-level export file, in the layout the
  converter produces today (`.parquet` + `.cols.json` for tables;
  `.nodes.parquet`, `.edges.parquet`, their `.cols.json` and `.meta.json` for
  graphs; `.json` for small objects).
- **FR-002**: The Parquet content MUST be built from the export text after the
  safety net, the same text that goes into exports_canonical.zip, so a value
  replaced in the JSON archive is replaced the same way in the Parquet archive.
- **FR-003**: The Parquet archive MUST carry the same manifest as the JSON
  archive (key fingerprint and official flag).
- **FR-004**: The Parquet archive MUST be built in a temporary file and replace
  the previous one only on success; any failure MUST keep the previous Parquet
  archive and leave no partial file.
- **FR-005**: The build MUST refuse a Parquet archive over 100 MB, or one
  holding a file over 100 MB, keeping the previous archive.
- **FR-006**: A failure of the Parquet archive MUST NOT stop, fail or change the
  JSON archive, which is built and published as usual. The failure MUST be
  reported in the run log and the export report, together with a warning that
  the Parquet archive is now from an earlier run than the JSON archive.
- **FR-007**: The same export content MUST give a byte-identical Parquet
  archive (fixed member dates, sorted members, deterministic writing).
- **FR-008**: exports_canonical.zip MUST keep its current member list, content
  and format; it MUST NOT carry the Parquet archive or any Parquet file.
- **FR-009**: The publishing gate MUST apply to the Parquet archive the same
  checks it applies to the JSON archive, in the pre-commit hook, in CI (when the
  Parquet archive changed) and in the weekly workflow's commit step.
- **FR-010**: The weekly workflow MUST commit the Parquet archive together with
  the JSON archive, in one commit, and only when one of them changed; a refused
  Parquet archive MUST be put back from the branch like a refused JSON archive,
  without failing the run. The archive is published only this way (no
  release asset, no separate workflow artifact).
- **FR-011**: The ETL MUST NOT read the Parquet archive as an input; the
  published id history and the previous SigPesq documents keep coming from
  exports_canonical.zip.
- **FR-012**: The stale `data/exports/parquet/` folder MUST NOT be produced,
  read or archived; the ETL leaves an existing one untouched, and the docs say
  it is obsolete and can be removed by hand.
- **FR-013**: The manual converter MUST keep working, with the fixes of FR-016
  and FR-017.
- **FR-014**: ADR-003, `docs/outputs-and-artifacts.md` and
  `docs/flows-and-entrypoints.md` MUST describe the Parquet archive: what it
  holds, how it is built, its limits, and that the dashboard consumes it.
- **FR-015**: `docs/backlog.md` MUST register the growth of the repository
  history caused by committing the Parquet archive (about 40 MB per run in
  which the data changed), as an item to handle later.
- **FR-016**: A column that mixes kinds of values MUST be converted, and each
  value MUST read back with its original kind; the column sidecar MUST tell the
  reader exactly which columns to revive, as it does today for nested columns.
- **FR-017**: Every top-level export file MUST be in the Parquet archive. If one
  file cannot be converted, the whole Parquet archive MUST fail (handled as in
  FR-006) and the log MUST name the file and the reason; the archive MUST NOT be
  published without it.
- **FR-018**: New fields and new export files MUST be converted with no change
  to the converter, as long as they are lists of rows, graphs, known wrapped
  tables or small objects.

### Key Entities

- **JSON archive** (`exports_canonical.zip`): the published export, text only,
  after the safety net; read back by the ETL. Unchanged by this feature.
- **Parquet archive** (`exports_parquet.zip`): the compact copy of the
  top-level exports for the dashboard; same values, same manifest, same
  publishing gate; never read by the ETL.
- **Column sidecar** (`<name>.cols.json`): the list of columns holding nested
  values written as text, so a reader revives exactly those columns.
- **Manifest** (`export_manifest.json`): key fingerprint and official flag of
  an archive.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a local weekly run, the Parquet archive exists, is under
  100 MB (about 51 MB expected), and its largest file is under 100 MB (about
  8 MB expected).
- **SC-002**: For 100% of the top-level exports, the rows read back from the
  Parquet archive equal the rows of the JSON export of the same run (same
  values and order; a missing key equals null; ids as integers).
- **SC-003**: 0 values of the Parquet archive match the personal data patterns
  of the safety net, and every value replaced in the JSON archive is replaced in
  the Parquet archive.
- **SC-004**: Two builds from the same export content give byte-identical
  Parquet archives.
- **SC-005**: exports_canonical.zip has the same member list as the archive of
  the run before the change.
- **SC-006**: The export step takes at most about 1 more minute than before the
  change (reference value: the conversion took 36 s).
- **SC-007**: The publishing gate refuses 100% of the bad Parquet archives in
  the tests (no manifest, local build, over the limit, another key).
- **SC-008**: 100% of the top-level export files are in the Parquet archive,
  attribute_assertions_canonical included, and the 249,421 values of its
  `value_json` column read back with their original kind.

## Assumptions

- The weekly exports keep changing between runs (run records, dates), so the
  JSON archive is not byte-identical across runs today; byte identity is
  required of the Parquet archive for the same export content only.
- The Parquet archive is committed to git every run in which the data changed.
  Parquet compresses the whole table, so each such run adds up to about 40 MB
  to the repository history, on top of the JSON archive (the JSON archive was
  committed 6 times between 2026-11-11 and 2026-11-13). This is accepted for
  now and registered in the backlog (FR-015).
- The dashboard's reader expects the converter's current layout; the dashboard
  changes (reader, sync workflow) are made in the dashboard repository.
- Peak memory of the conversion (about 1.2 GB) fits the GitHub Actions runner.
- research_group_relationship_graphs/ stays JSON and only in the JSON archive.
- No change to third-party libraries and no Docker change; the Parquet library
  is already a dependency of the ETL.
- Must work locally and in GitHub Actions.
