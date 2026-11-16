# Feature Specification: Enrichment Survives Cross-Type Title Collisions

**Feature Branch**: `022-enrich-lock-fix`

**Created**: 2026-10-24

**Status**: Implemented

**Input**: User description: "Fix the enrich_projects \"database is locked\" failure that breaks the CI weekly whenever a new project document has the same title as an existing initiative of another type."

## Context

The `enrich_projects` phase reads the SigPesq project documents (`PJ_*.json`)
and does two things: it enriches existing research projects, and it creates new
research project initiatives for documents that match no existing one. Every
write is also recorded in the tracking tables.

In the GitHub Actions weekly the phase fails with `database is locked`
(runs 39009721014 on 2026-10-17 and 40002646510 on 2026-10-23). It never fails
locally. Spec 018 reproduced it on a copy of the CI database, with and without
write-ahead logging, and found the cause (TD-020 in `docs/backlog.md`;
`docs/reports/2026-10-24-sqlite-wal-validation.md`, section 6).

### What happens

1. **A cross-type title collision.** The new project "Mapeamento dos dados do
   ENEM por município do Espírito Santo" has the same title as initiative 435,
   which is an **Advisorship**. The phase checks new titles for duplicates only
   among **Research Project** initiatives, but initiative names must be unique
   across **every** type. The insert is refused.
2. **The refused row keeps the write lock.** The phase writes each row inside a
   savepoint so that a bad row is skipped without stopping the others. Rolling
   back to that savepoint undoes the row but, in SQLite, leaves the transaction,
   and its write lock, open on the phase's connection.
3. **The tracking write is locked out.** The tracking records are written
   through other connections. The next one waits the default 5 s and fails with
   `database is locked`. The phase aborts and the weekly reports it as failed.

### What is lost

On SQLite each successful savepoint already commits its row on its own, so the
rows written before the collision are kept: the CI database holds 251 enriched
initiatives and 251 tracking source records after the failed phase. What is lost
is everything after the collision: in run 40002646510, **17 new initiatives**
that the documents would have created, with their tracking records. The code
comments describe the phase as a single unit of work that is rolled back on
error; on SQLite that is not what happens.

### Why it only shows in CI

The CI weekly processes different inputs (126 curricula instead of the 435 used
locally), and its database contains an advisorship whose title equals a
project document's title. The local inputs produce no such pair.

### Fixes already tested

On copies of the CI database:
- **(a)** checking new titles against the names of **all** initiatives: the
  colliding project is counted as a duplicate and skipped;
- **(b)** ending the open transaction after a refused row.

Each one alone completes the phase (exit 0: 251 enriched, 17 created, 0 errors),
and both produce identical databases (4 377 initiatives, 268 enriched, 268
tracking source records).

A check on the current data found no project title that matches an advisorship
only after normalization (accents, case): 0 of 38 projects created from documents
in the latest local run, 0 of 33 in the CI database.

### Constraints

- **Third-party libraries are used as they are.** `eo_lib`, `libbase` and
  `research_domain` are not modified, replaced or re-implemented.
- **The output must not change when there is no collision.**
- **Docker is out of scope.**

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A project titled like an existing initiative of another type is skipped, and the phase completes (Priority: P1)

As the maintainer, I want the enrichment phase to recognise that a new project
document has the same title as an existing initiative of any type, skip it as a
duplicate, and carry on, so that the CI weekly completes the phase and creates
every other new initiative.

**Why this priority**: This is the known cause of the CI failure. Every run with
such a title pair loses the new initiatives after it and reports the phase as
failed.

**Independent Test**: Replay the phase on a copy of the database from CI run
40002646510, with that run's project documents: the phase completes, the
colliding project is reported as a duplicate, and the expected counts are
reached.

**Acceptance Scenarios**:

1. **Given** a new project document whose title equals the title of an existing
   advisorship, **When** the phase runs, **Then** no initiative is created for
   it, it is counted as a skipped duplicate, and the phase continues.
2. **Given** the database and documents of CI run 40002646510, **When** the
   phase runs, **Then** it ends successfully with 251 enriched, 17 created and
   0 errors, and no `database is locked` appears.
3. **Given** a new project document whose title equals the title of an existing
   research project, **When** the phase runs, **Then** it is skipped as a
   duplicate, as today.

---

### User Story 2 - A refused row never locks out the tracking writes (Priority: P1)

As the maintainer, I want any row the phase fails to write, for whatever reason,
to release the database right away, so that one bad row can never block the
tracking records and abort the whole phase.

**Why this priority**: User Story 1 removes the known cause. Other row failures
(another constraint, a malformed value) would hit the same lock. The phase
already intends to skip bad rows and continue; this makes that true on SQLite.

**Independent Test**: With a real SQLite file, make one row write fail inside
the phase's per-row protection, then write a tracking record from another
connection: it succeeds immediately.

**Acceptance Scenarios**:

1. **Given** a row write that fails, **When** the next tracking record is
   written, **Then** it succeeds without waiting, and the failed row is logged
   and skipped.
2. **Given** rows written successfully before a failed row, **When** the phase
   ends, **Then** those rows are still in the database.

---

### User Story 3 - The code describes what really happens (Priority: P3)

As a maintainer reading the code, I want the comments of the enrichment phase to
say that, on SQLite, rows are committed one by one, so that nobody relies on a
rollback that does not happen.

**Why this priority**: It prevents future changes from being built on a wrong
assumption. It has no runtime effect.

**Independent Test**: Read the comments of the phase's main method and of the
per-row write helper.

**Acceptance Scenarios**:

1. **Given** the phase's main method and the per-row helper, **When** a
   maintainer reads their comments, **Then** they state that successful rows are
   committed as they are written on SQLite, and what happens to a failed row.

---

### Edge Cases

- **Normalized-only match**: a new project whose title equals another type's
  initiative only after normalization (accents, case, spacing) is treated as a
  duplicate, the same rule already applied to research projects. The current
  data has no such case (0 in the local and CI databases).
- **Two new documents with the same title in one run**: the first is created,
  the second is a duplicate, as today.
- **Dry run**: the duplicate check and its counters behave the same; nothing is
  written.
- **A failure while ending the transaction after a failed row**: it is logged;
  the phase does not crash because of it.
- **No collision at all**: the output is identical to today's (initiatives,
  enrichment payloads and tracking records).
- **Tracking disabled** (no active ingestion run): the phase still skips
  duplicates and failed rows the same way.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Before creating a new research project initiative, the phase MUST
  compare its normalized title with the normalized names of all existing
  initiatives, whatever their type, and with the titles already created in the
  same run.
- **FR-002**: A new project document whose title matches MUST NOT create an
  initiative, and MUST be counted in the existing duplicate counter
  (`skipped_duplicate`).
- **FR-003**: After any row write that fails, the phase MUST release the
  database write lock before its next write, log the failure and continue with
  the next row.
- **FR-004**: Rows written successfully before a failed row MUST remain in the
  database.
- **FR-005**: The tracking records of every row written MUST still be recorded,
  including the rows written after a failed one.
- **FR-006**: When no title collision and no row failure happen, the phase MUST
  produce the same initiatives, enrichment payloads and tracking records as the
  current code.
- **FR-007**: The comments of the phase's main method and of the per-row write
  helper MUST describe the real commit behaviour on SQLite.
- **FR-008**: Automated tests MUST reproduce, with a real SQLite file, (a) the
  cross-type title collision and (b) a failed row followed by a write from
  another connection, and MUST fail with the current code.
- **FR-009**: The fix MUST live inside horizon_etl. Third-party libraries and
  Docker files MUST NOT change.
- **FR-010**: TD-020 in `docs/backlog.md` MUST be updated with the outcome.

### Key Entities

- **Initiative**: a research project or an advisorship (or another type), with a
  name that must be unique across all types.
- **Project document (`PJ_*.json`)**: the extracted SigPesq project file the
  phase matches to initiatives or uses to create new ones.
- **Tracking record**: the source record, entity match, attribute assertions
  and change log written for every enriched or created initiative.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the database and documents of CI run 40002646510, the phase
  completes successfully: 251 enriched, 17 created, 0 errors, 0 `database is
  locked`.
- **SC-002**: On a local database where the phase already succeeds today, the
  new code produces 0 differences in initiatives, enrichment payloads and
  tracking records.
- **SC-003**: After a failed row, the next tracking write succeeds without
  waiting (well under the 5 s lock timeout).
- **SC-004**: The test suite has no new failures (6 pre-existing), and the new
  tests fail with the current code.
- **SC-005**: The next CI weekly reports `enrich_projects` as successful.

## Assumptions

- Skipping is the right outcome for a project titled like an existing
  initiative of another type, as it already is for research projects
  (maintainer's default). Linking the document to that initiative is out of
  scope.
- Normalization is the one the phase already uses for research project titles.
- The replay inputs are the artifact of CI run 40002646510 (database and
  `data/exports/project_sigpesq_files_json/`), already downloaded outside the
  repository by spec 018, and a local database taken right before
  `enrich_projects`.
- The 6 pre-existing test failures are not addressed here.
- SC-005 depends on the next CI weekly run and is checked after merge into the
  fork.
