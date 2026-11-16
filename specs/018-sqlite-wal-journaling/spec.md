# Feature Specification: SQLite WAL Journaling for the ETL Database

**Feature Branch**: `021-sqlite-wal-journaling`

**Created**: 2026-10-23

**Status**: Implemented

**Input**: User description: "Enable SQLite WAL journaling for every SQLite connection opened by horizon_etl, to cut the per-commit disk cost that dominates the Lattes phases."

## Context

Specs 015, 016 and 017 cut the local weekly run from 8 h 04 min to 1 h 37 min.
The two Lattes ingestion phases are still among the largest, and they grow
linearly with the number of curricula. The institute plans to grow from 435
curricula to several thousand.

### What the measurement showed

A profile of `lattes_projects` and `lattes_advisorships` (2026-10-23, 435
curricula, database on an NVMe disk):

| Where the time goes | `lattes_projects` | `lattes_advisorships` |
|---|---:|---:|
| Committing to the database, waiting for the disk | **63%** (~184 000 commits, ~420 per curriculum, ~3.6 ms each) | **34%** (~161 000 commits) |
| Loading an initiative to link it to a team (third-party library) | — | 24% |
| Other SQL | 7% | ~6% |
| Name matching (pure Python) | 5% | 5% |

- **The commits come from a third-party library.** `libbase`'s repository
  commits after every single record it adds: entities, ~88 700 attribute
  assertions and every source record. The ETL cannot change how often the
  library commits.
- **What the ETL can change is what a commit costs.** In its default mode the
  database forces every commit to physical disk before returning. In
  write-ahead-log mode with normal synchronisation, a commit only appends to a
  log file, and the disk is forced at checkpoints.
- **This was already suspected** as TD-018: the same curricula ran ~2.1× slower
  with the database on disk than on a memory filesystem.

### Benchmark (no code changed)

A wrapper enabled write-ahead logging with normal synchronisation on every new
database connection, then ran the two phases from the same pre-Lattes snapshot,
on the same machine and disk, against a baseline run without it:

| Phase | Baseline | With WAL | Speed-up |
|---|---:|---:|---:|
| `lattes_projects` | 1 298 s (21.6 min) | 521 s (8.7 min) | 2.5× |
| `lattes_advisorships` | 1 476 s (24.6 min) | 875 s (14.6 min) | 1.7× |
| **Both phases** | **46.2 min** | **23.3 min** | **−22.9 min** |

Both databases came out identical: the same counts of teams (11 785), team
members (39 665), initiatives (11 685), initiative↔team links (11 755),
advisorships (8 680), persons (17 516) and researchers (7 645), and the same
initiative↔team links, team memberships and person names compared by name. The
baseline matched the spec 017 full run (21.1 and 24.7 min), so the measurement
is representative.

### A failure that may be related

The `enrich_projects` phase fails in the GitHub Actions weekly with
`database is locked` (runs 39009721014 on 2026-10-17 and 40002646510 on
2026-10-23). The phase is non-critical, so the run continues, but project
enrichment is not applied to the CI exports. Write-ahead logging lets readers
and a writer work at the same time, so it may remove this failure. This is a
hypothesis to verify, not a known fact.

### Constraints that shape the solution

- **Third-party libraries are used as they are.** `libbase`, `eo_lib` and
  `research_domain` must not be modified, replaced or re-implemented. The
  setting must live inside horizon_etl and reach the connections the libraries
  open.
- **The database is rebuilt from scratch on every weekly run** (`db-reset`), and
  the CI has no persistent database. Losing the last few commits after a power
  loss is acceptable, because an interrupted run is redone from the start.
  Database corruption is not acceptable.
- **Every weekly phase runs in its own process.** The weekly orchestrator starts
  each phase as a separate `python app.py <phase>` or `python -m <module>`
  process, so the setting must apply in every one of them, not only in the
  process that starts the weekly.
- **Some ETL code opens the database file directly**, outside the libraries'
  connection layer: the duplicate consolidation, reference consolidation,
  duplicate audit, anonymisation backfill and ETL reporting code, among others.
  They must keep working with a database in write-ahead-log mode.
- **The CI uploads `db/horizon.db` as an artifact** at the end of the weekly.
  The uploaded file must hold all the data on its own.
- **Docker is out of scope.**

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Commits stop waiting for the disk, with identical data (Priority: P1)

As the maintainer, I want every database connection the ETL opens, including
the ones opened by third-party libraries, to use write-ahead logging with
normal synchronisation, so that the Lattes phases spend far less time waiting
for the disk and produce exactly the same data.

**Why this priority**: Commit cost is the largest share of both Lattes phases,
and those phases grow linearly with the number of curricula. Halving them is the
largest measured gain left, and it compounds as the institute adds curricula.

**Independent Test**: A controlled replay runs `lattes_projects` and
`lattes_advisorships` with the old and the new code from the same pre-Lattes
snapshot, on disk, and compares the resulting databases and the phase
durations. No portal is contacted.

**Acceptance Scenarios**:

1. **Given** a database on disk and the new code, **When** any weekly phase
   opens a connection through the libraries or through the ETL, **Then** that
   connection uses write-ahead logging with normal synchronisation.
2. **Given** the same pre-Lattes snapshot and the same 435 curricula, **When**
   both Lattes phases run with the old code and with the new code, **Then** the
   two databases are identical in the counts and by-name comparisons used by
   specs 015–017.
3. **Given** the same machine and disk, **When** both Lattes phases run with the
   new code, **Then** together they take substantially less time than the
   baseline (reference: 46.2 → 23.3 min).
4. **Given** a database URL that points to PostgreSQL, **When** any phase runs,
   **Then** nothing changes for that database and no error is raised.

---

### User Story 2 - The final database file is complete and self-contained (Priority: P1)

As the maintainer, I want `db/horizon.db` to hold all the data on its own at the
end of a weekly run, so that the artifact uploaded by the CI, and any copy of
the file, is complete and opens like any other database file.

**Why this priority**: In write-ahead-log mode, recent changes live in a
companion log file until they are moved into the main file. An artifact that
uploads only the main file could silently miss data. This must hold for the
feature to be safe in the CI.

**Independent Test**: Run the weekly (or the last phase that writes to the
database), copy only `db/horizon.db` to another directory, open it there, and
compare its contents with the original.

**Acceptance Scenarios**:

1. **Given** a weekly run that finished, **When** `db/horizon.db` is copied
   alone, without any companion files, **Then** the copy contains every row
   written during the run.
2. **Given** that copy, **When** it is opened by a standard SQLite tool or
   library, read-only or read-write, **Then** it opens without errors and
   without needing companion files.
3. **Given** the CI weekly workflow, **When** the artifact is uploaded, **Then**
   the database in the artifact is complete.

---

### User Story 3 - Database reset and direct readers keep working (Priority: P2)

As the maintainer, I want the database reset, and every piece of ETL code that
opens the database file directly, to behave as before with a database in
write-ahead-log mode.

**Why this priority**: The weekly starts with a reset, and several phases
(duplicate consolidation, anonymisation backfill, reports) read and write the
file directly. A stale companion log file left by a previous run must never mix
with a freshly created database.

**Independent Test**: Run the reset twice in a row after a run that left
companion files, then run the phases that open the file directly, and check that
the new database starts empty and that those phases succeed.

**Acceptance Scenarios**:

1. **Given** a previous run that left companion log files next to the database,
   **When** the reset runs, **Then** the companion files are removed together
   with the database, and the new database starts empty.
2. **Given** a database in write-ahead-log mode, **When** the duplicate
   consolidation, the anonymisation backfill and the ETL reports run, **Then**
   they produce the same results as with the old code.

---

### User Story 4 - Know whether this fixes the `database is locked` failure (Priority: P3)

As the maintainer, I want to know whether write-ahead logging removes the
`database is locked` failure of the `enrich_projects` phase seen in the CI
weekly runs, so that I can decide whether that failure needs separate work.

**Why this priority**: The failure means project enrichment is missing from the
CI exports. Fixing it is desirable, but this feature is justified by the speed
gain alone.

**Independent Test**: Reproduce the failure (or the conditions of the CI runs)
with the old code, then run the same conditions with the new code, and record
the outcome in the validation report.

**Acceptance Scenarios**:

1. **Given** the conditions of the failing CI runs, **When** `enrich_projects`
   runs with the new code, **Then** the validation report states whether the
   failure still occurs and, if it does, what holds the lock.

---

### Edge Cases

- **Stale companion files**: a run that crashed or was cancelled leaves
  `horizon.db-wal` and `horizon.db-shm` behind. Deleting only the main file and
  creating a new one next to an old log file can corrupt the new database. The
  reset must remove all of them.
- **A phase killed mid-run** (timeout, signal 11): the next phase opens the same
  database. Write-ahead-log recovery must leave it consistent, with the killed
  phase's committed work intact.
- **Several connections in one process**: the libraries create their own engines
  and sessions (for example a connection-client singleton). Every one of them
  must get the setting, including connections opened after the first one.
- **Connections opened before the setting is registered**: any connection that
  exists before the setting is in place would keep the old behaviour. The
  setting must be in place before the first database connection of each
  process.
- **Read-only consumers of the artifact**: a database left in write-ahead-log
  mode can fail to open from a read-only location without its companion files.
  The final file must not depend on them.
- **Non-SQLite databases**: when the database URL points to PostgreSQL, the
  setting must not be applied and must not fail.
- **Tests**: the test suite creates in-memory and temporary databases. The
  setting must not break them (in-memory databases cannot use
  write-ahead logging and silently stay in memory mode).
- **Local disk vs memory filesystem**: on a memory filesystem the gain is small,
  because commits are already cheap there. Benchmarks must run on disk.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every new SQLite connection opened in an ETL process, by the ETL or
  by a third-party library, MUST use write-ahead-log journaling and normal
  synchronisation.
- **FR-002**: The setting MUST be in place before the first database connection
  of every process that runs a weekly phase, whether the phase is started as
  `python app.py <phase>` or as `python -m <module>`, locally and in the GitHub
  Actions weekly workflow.
- **FR-003**: The setting MUST be implemented inside horizon_etl. `libbase`,
  `eo_lib`, `research_domain` and every other third-party library MUST NOT be
  modified, replaced or re-implemented.
- **FR-004**: When the database is not SQLite, the setting MUST do nothing and
  MUST NOT raise errors.
- **FR-005**: The data written by every phase MUST be identical to the data
  written by the current code, proven by a controlled replay of
  `lattes_projects` and `lattes_advisorships` from the same pre-Lattes snapshot,
  using the counts and by-name comparisons of specs 015–017.
- **FR-006**: At the end of a weekly run, `db/horizon.db` MUST contain all the
  data on its own and MUST open without companion files, read-only or
  read-write, so that the CI artifact and any copy of the file are complete.
- **FR-007**: The database reset MUST remove the database's companion log files
  together with the database file.
- **FR-008**: ETL code that opens the database file directly MUST keep producing
  the same results with a database in write-ahead-log mode. This covers at
  least duplicate consolidation, reference consolidation, the duplicate audit,
  the anonymisation backfill and the ETL reports.
- **FR-009**: A phase that is killed (timeout or signal) MUST NOT leave the
  database corrupted for the phases that follow it.
- **FR-010**: The existing test suite MUST keep its current results (no new
  failures), including tests that use in-memory or temporary databases.
- **FR-011**: The validation report MUST state whether the `enrich_projects`
  `database is locked` failure still happens with the new code, and, if it
  does, what holds the lock.
- **FR-012**: The setting MUST be documented in `docs/flows-and-entrypoints.md`,
  and TD-018 in `docs/backlog.md` MUST be updated with its outcome.
- **FR-013**: Docker files and images MUST NOT be changed by this feature.

### Key Entities

- **ETL database (`db/horizon.db`)**: the SQLite file rebuilt from scratch on
  every weekly run. It is uploaded as a CI artifact at the end of the run.
- **Companion log files (`horizon.db-wal`, `horizon.db-shm`)**: files that exist
  next to the database while it is in write-ahead-log mode. They hold recent
  changes until a checkpoint moves them into the main file.
- **Pre-Lattes snapshot**: a database built offline (schema creation, SigPesq
  persistence from the local Excel reports, CNPq sync fed with the 350 stored
  group payloads) used as the common starting point of the replay.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the database on disk, `lattes_projects` and
  `lattes_advisorships` together take at most 60% of the baseline time on the
  same machine (reference measurement: 23.3 min against 46.2 min, 50%).
- **SC-002**: The controlled replay shows identical databases for the old and
  the new code: 0 differences in the counts and by-name comparisons.
- **SC-003**: A copy of `db/horizon.db` taken alone at the end of a weekly run
  contains 100% of the rows of the original and opens with no companion files.
- **SC-004**: A full local weekly run completes with the same critical-phase
  results as before, and the Lattes phases are faster than in the spec 017
  validation run (21.1 and 24.7 min).
- **SC-005**: The test suite has no new failures compared with the current
  baseline (6 pre-existing failures).
- **SC-006**: The validation report answers, with evidence, whether the
  `enrich_projects` `database is locked` failure is fixed.

## Assumptions

- The target environments are the local machine and the GitHub Actions
  `ubuntu-latest` runner, both with the database on a local disk. Network
  filesystems are out of scope.
- The SQLite version bundled with Python (3.46.1 locally) supports write-ahead
  logging; no extra dependency is needed.
- Time targets are references, not blockers. The absolute gain matters more
  than a specific number.
- The current weekly behaviour is kept: the database is reset at the start of
  every run, and nothing is carried between CI runs.
- The 6 pre-existing test failures (Lattes download, loader mapping, SigPesq
  adapter, weekly workflow) are not addressed by this feature.
- The replay uses the same frozen inputs available locally: the SigPesq Excel
  reports in `data/raw/sigpesq/`, the 435 Lattes JSONs in `data/lattes_json/`
  and the 350 CNPq group payloads stored as source records.
- Other remaining costs found by the profile (the initiative loading inside
  `research_domain`, the per-curriculum garbage collection) are out of scope.
