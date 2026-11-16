# Feature Specification: Persistent Database Between GitHub Actions Weekly Runs

**Feature Branch**: `025-ci-persistent-database`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "Keep the SQLite database and the raw downloads between GitHub Actions weekly runs by restoring them from the previous successful run's artifact."

## Context

Spec 021 made the database persistent and incremental: a weekly run on a kept
database only processes the source documents that changed. Locally that
already works: on a kept database the whole weekly took 32 min on 2026-10-29,
with `lattes_projects` at 13 s and `lattes_advisorships` at 7 s.

In GitHub Actions every weekly still starts on an empty runner, so it always
rebuilds the database from scratch: the 2026-10-29 fork run 40856179199 (spec
021 code) took 1 h 38 min. The workflow already uploads the database and the
`data/` folder as the `weekly-etl-artifacts` artifact (366 MB compressed,
30-day retention, uploaded even when the run fails), but no run ever restores
it. The Lattes raw HTML cache (`cache/`, 66 MB locally) is not uploaded.

Measured facts the requirements rely on:

- The workflow's "Compress large export files" step runs before the upload and
  replaces every file over 10 MB under `data/` by a `.zip` of it, so the
  artifact does not hold those files in the form the phases read.
- The end of every weekly makes `db/horizon.db` self-contained (spec 018), so
  the file alone is a complete database. Sizes today: database 318 MB (68 MB
  gzipped), `data/raw` 223 MB, `cache/` 66 MB.
- `make weekly-flows` runs `make db-ensure` (spec 021): it creates the
  database only when the file is missing, otherwise it applies the pending
  migrations. A database recorded with another `HORIZON_RULE_VERSION` is
  rebuilt once by the weekly, keeping the horizon id history.
- The SigPesq reports under `data/raw/sigpesq/` are cleared before their
  download on every run (constitution, raw inputs rule).
- GitHub's dependency cache is evicted after 7 days without access, which is
  exactly the weekly interval; a file over 100 MB cannot be committed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A weekly CI run continues from the previous run's database (Priority: P1)

As the maintainer, I want each weekly GitHub Actions run to start from the
database, raw downloads and Lattes cache that the last successful weekly run
of the same branch left, so that the run only processes what changed and
finishes in a fraction of today's 1 h 38 min.

**Why this priority**: it is the whole point of the feature: without the
restore, the persistent database of spec 021 never reaches CI.

**Independent Test**: on the fork, dispatch the weekly twice on the same
branch. The second run restores the first run's database, its phases report
most documents as skipped, and it is clearly shorter.

**Acceptance Scenarios**:

1. **Given** a successful weekly run on the branch whose artifact is still
   available, **When** the next weekly run starts, **Then** it restores
   `db/horizon.db`, `data/raw` and `cache/` from that artifact before any phase
   runs, and the database is the one that run left, unchanged.
2. **Given** a restored database, **When** the phases run on unchanged
   sources, **Then** the documents are skipped as on a local kept database
   (spec 021) and the run's exports keep the same files and fields.
3. **Given** a restored database recorded with another rule version, **When**
   the weekly starts, **Then** it is rebuilt once, exactly as a local kept
   database would be.

---

### User Story 2 - A run without a usable artifact rebuilds as today (Priority: P1)

As the maintainer, I want a run that finds nothing to restore (first run of a
branch, every artifact expired, a download error, a damaged file) to rebuild
from scratch as today and never fail because of it, so the restore can only
make a run faster, never break it.

**Why this priority**: the weekly feeds another team; a missing or broken
artifact must not cost a week of data.

**Independent Test**: dispatch the weekly on a branch with no successful run,
and once with the restore forced to fail; both complete as a rebuild and the
log says why nothing was restored.

**Acceptance Scenarios**:

1. **Given** no successful weekly run on the branch, **When** the run starts,
   **Then** it logs that there is nothing to restore and rebuilds the database
   from scratch.
2. **Given** a successful run whose artifact expired, or a download that fails,
   **When** the run starts, **Then** it logs the reason and rebuilds.
3. **Given** a restored database that fails an integrity check, **When** the
   run starts, **Then** the file is discarded, the reason is logged, and the
   run rebuilds.
4. **Given** the last runs failed, **When** the next run starts, **Then** it
   restores from the most recent successful run, never from a failed one.

---

### User Story 3 - The restored files are exactly what the phases read (Priority: P2)

As the maintainer, I want the files a run restores to be the same files the
phases of the previous run left, never the compressed copies the upload makes,
and the Lattes cache to travel with them, so a restored run reads its inputs
exactly as a local kept run does.

**Why this priority**: a restored file in another form would look missing to
the phases, which would silently download or rebuild it.

**Independent Test**: compare checksums of the database, `data/raw` and
`cache/` at the end of one run with the files restored at the start of the
next.

**Acceptance Scenarios**:

1. **Given** a file over 10 MB under the restored folders, **When** the next
   run restores the artifact, **Then** the file is present under its own name
   with its original content.
2. **Given** a run that ends, **When** its artifact is uploaded, **Then**
   `cache/` is part of it.
3. **Given** the restored SigPesq reports, **When** the SigPesq phase runs,
   **Then** they are still cleared before the new download.

---

### User Story 4 - The run says where its database came from (Priority: P3)

As the maintainer, I want each run to state whether its database was restored
(and from which run) or rebuilt, and why, so I can tell a fast incremental run
from a rebuild without reading the whole log.

**Why this priority**: it is what makes a slow run explainable; it changes no
data.

**Independent Test**: read the job summary of a restored run and of a rebuilt
run.

**Acceptance Scenarios**:

1. **Given** a restored run, **When** it ends, **Then** its summary names the
   run the database came from and that run's date.
2. **Given** a rebuilt run, **When** it ends, **Then** its summary says it was
   rebuilt and why (no successful run, expired, download error, damaged file,
   rule version change).

### Edge Cases

- **First run of a new branch**: there is no successful run on that branch;
  the run rebuilds. It never borrows another branch's database.
- **The most recent successful run's artifact expired but an older one did
  not**: the run restores from the newest successful run whose artifact is
  still available.
- **A partially uploaded or truncated artifact**: the download or the
  integrity check fails; the run rebuilds.
- **A run fails after the restore**: its artifact is never used by later
  runs; the next run restores from the last successful one.
- **Two runs of the same branch at once**: the workflow's concurrency group
  already queues them; each restores from the last run that finished
  successfully before it started.
- **The restored database comes from older ETL code**: the pending migrations
  apply on start; a rule version change triggers the one rebuild.
- **A restored database written with another PII key**: cannot happen in CI,
  because only the CI key writes CI databases, and no local database is ever
  uploaded as a CI artifact.
- **The artifact grows** (the database and the raw files grow every week): the
  upload and download must stay within the job's time budget; the size of what
  is restored is logged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Before any phase runs, the weekly workflow MUST look for the most
  recent successful weekly run of the same branch whose artifact is still
  available, and restore from it `db/horizon.db`, `data/raw` and `cache/`.
- **FR-002**: Only runs that completed successfully MAY be restored from; the
  artifact of a failed, cancelled or still-running run MUST NOT be used.
- **FR-003**: When nothing can be restored (no successful run, every artifact
  expired, a download error, a damaged or incomplete file), the run MUST
  continue as a rebuild from scratch, log one line with the reason, and MUST
  NOT fail because of the missing restore.
- **FR-004**: A restored database MUST pass an integrity check before the
  phases use it; a database that fails it is discarded and the run rebuilds.
- **FR-005**: The restored files MUST be identical to the files the phases of
  the restored run left (same names, same content). The compression of large
  files before the upload MUST NOT change what is restored, or the restore
  MUST undo it.
- **FR-006**: `cache/` MUST be added to the uploaded artifact.
- **FR-007**: The artifact's retention MUST be raised from 30 to 90 days.
- **FR-008**: A restored database MUST go through the same start of the weekly
  as a local kept database: pending migrations applied, and one rebuild when
  its recorded rule version differs from the code's (spec 021).
- **FR-009**: The SigPesq reports MUST still be cleared before their download,
  whether or not they were restored.
- **FR-010**: CI databases MUST only be written with the CI
  `HORIZON_PII_HMAC_KEY`: a run never restores a database that was not produced
  by a CI run of this workflow, and no local database is uploaded as its
  artifact.
- **FR-011**: The job summary of every run MUST state whether the database was
  restored, from which run (id and date), and the size of what was restored,
  or that it was rebuilt and why.
- **FR-012**: A local check MUST simulate the restore from a downloaded
  artifact (find, download or copy, undo compression, verify, place the files)
  so the logic is validated before any CI run.
- **FR-013**: The restore MUST use only what the runner and the workflow
  already have (the workflow's own token and the GitHub CLI on the runner); no
  external database service, no new secret, no Docker change.
- **FR-014**: The existing exports, their files and their fields MUST NOT
  change; the restore only changes where the database comes from.

### Key Entities

- **Weekly run**: one execution of the weekly workflow on a branch, with an
  id, a date, a conclusion (success, failure, cancelled) and its artifact.
- **Run artifact**: what a run uploads at its end: the database, `data/` and,
  after this spec, `cache/`; it expires after its retention period.
- **Restore outcome**: what the start of a run decided: restored (from which
  run, what size) or rebuilt (and why).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A weekly run that restores the previous run's database finishes
  in at most 60% of the time of a rebuild run on the same branch (reference:
  1 h 38 min for the 2026-10-29 rebuild, so about 1 h at most; a reference
  target, not a blocker).
- **SC-002**: In a restored run on unchanged sources, the Lattes phases skip
  at least 95% of the CVs, as on a local kept database.
- **SC-003**: 100% of the runs without a usable artifact complete as a rebuild,
  with zero failures caused by the restore.
- **SC-004**: The restored database and raw files have the same checksums as
  the files the restored run left at its end.
- **SC-005**: 100% of the runs state in their summary whether the database was
  restored (with the source run) or rebuilt (with the reason).
- **SC-006**: A restored run's exports keep every existing file and field, and
  differ from a rebuild run on the same day only where the sources differ.
- **SC-007**: An artifact stays restorable for 90 days.

## Assumptions

- Spec 021 is merged into this branch: the database is persistent,
  `make db-ensure` creates it only when missing, unchanged documents are
  skipped, and the rule version guard rebuilds when needed.
- "Same branch" means the branch the run executes on (the default branch for
  scheduled runs, the dispatched branch for manual runs). A branch never
  restores another branch's database, so a new branch starts with a rebuild.
- The workflow already has `actions: write`, which covers reading and
  downloading the artifacts of its own repository's runs.
- The SigPesq raw reports are restored with the rest of `data/raw`; restoring
  them is harmless because the SigPesq phase clears them before downloading.
- `data/lattes_json/` keeps its current behaviour (rebuilt from `cache/` each
  run); keeping it between runs and downloading only what is missing is spec D.
- The artifact keeps holding the whole `data/` folder as today; only
  `db/horizon.db`, `data/raw` and `cache/` are restored from it.
- Validation: locally first (FR-012), then two manual dispatches on the fork:
  the first rebuilds or restores the 2026-10-29 run, the second restores and
  is clearly shorter. Nothing goes upstream before the maintainer's manager
  validates it.
