# Feature Specification: Download Only What Is New Plus a Rotating Share

**Feature Branch**: `026-rotating-raw-downloads`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "Download only new items plus a rotating share of existing ones for Lattes and CNPq, reusing the raw copies kept between runs, and publish when each document was downloaded."

## Context

Spec 021 made the database persistent and incremental: a document whose
content did not change is skipped, and a failed download keeps the stored
data. Spec 022 carries the raw downloads (`data/raw`) and the Lattes cache
(`cache/`) between GitHub Actions runs. What is still downloaded every run is
decided by each source:

- **Lattes**: only the curricula missing from `cache/` are downloaded; a
  curriculum already there is never downloaded again. Before spec 022 the CI
  cache started empty every run, so every curriculum was fresh. Now that the
  cache is kept, a curriculum downloaded once in CI never updates. Locally
  that has always been so. File times do not survive the CI artifact, so the
  age of a cached curriculum cannot be read from the file. About 6% of
  curricula change per week and 17% per month (estimate from the 2026-10
  plan).
- **CNPq**: every run downloads all ~350 group pages (4 workers) only to
  compare them. In the steady state of the 2026-10-29 CI run 40914744437 the
  CNPq phase took 15.6 of the run's 39 min, and 0 to 3 pages had changed. The
  pages (about 6 KB each) are not stored, so a group whose page fails to
  download can only fall back to what the database already holds.
- **Project PDFs**: already downloaded only when missing, and kept between CI
  runs by spec 022. They are out of scope.
- **SigPesq reports**: downloaded whole every run (constitution, raw inputs
  rule). They are out of scope, apart from recording their download date.

The constitution (Data Integrity rules 5 and 6) already allows per-item raw
caches refreshed on a rotation with a manifest of download dates, requires
that a cached item be replaced only after its new download succeeds, and
requires every kept document to record when it was downloaded, available in
the exports.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Lattes curricula are refreshed on a rotation (Priority: P1)

As the maintainer, I want each weekly run to download the curricula that are
new plus the share of existing ones that were downloaded longest ago, so that
every curriculum is checked again about every four weeks and Lattes data keeps
updating in CI, without downloading all of them every week.

**Why this priority**: since spec 022, Lattes data in CI stops updating after
the first download; this is a correctness problem, not only a speed one.

**Independent Test**: on a copy of the inputs with a manifest of download
dates, run the Lattes download: it fetches the missing curricula plus the
oldest quarter, records their new dates, and leaves the others untouched;
after four runs every curriculum has a date from those runs.

**Acceptance Scenarios**:

1. **Given** a list of curricula of which some are not cached, **When** the
   run starts, **Then** every missing curriculum is downloaded and gets a
   download date.
2. **Given** cached curricula with known download dates, **When** the run
   starts, **Then** the quarter with the oldest dates is downloaded again (the
   share rounded up), and the rest is reused from the cache.
3. **Given** a curriculum being refreshed, **When** its new download fails,
   **Then** its previous cached copy stays, its download date is unchanged, and
   the failure is recorded.
4. **Given** cached curricula without a recorded date (the first run after this
   feature), **When** the run starts, **Then** they count as the oldest and are
   refreshed a share at a time, never all at once.

---

### User Story 2 - CNPq pages are stored and refreshed on a rotation (Priority: P1)

As the maintainer, I want each group page to be stored with its download date,
and each run to download only new groups plus the oldest share, reusing the
stored page for the rest, so that the CNPq phase stops costing about 15 min
per run, and a group whose page fails to download still has its last page.

**Why this priority**: the CNPq phase is the largest remaining cost of the
weekly (40% of the steady-state CI run), and an unavailable portal used to
leave groups without data.

**Independent Test**: with stored pages for most groups, run the CNPq phase:
it downloads the new groups plus the oldest quarter, processes the stored
pages of the others (skipped when unchanged), and takes a fraction of today's
time.

**Acceptance Scenarios**:

1. **Given** a group with no stored page, **When** the run starts, **Then** its
   page is downloaded and stored with its download date.
2. **Given** stored pages, **When** the run starts, **Then** the oldest quarter
   is downloaded again and the others are read from storage.
3. **Given** a page that fails to download, **When** a stored copy exists,
   **Then** the stored copy is used, the failure is recorded, and the group's
   data stays as before; **When** no stored copy exists, **Then** the document
   is a failed download as today (spec 021).
4. **Given** a group gone from the SigPesq groups report, **When** the run
   starts, **Then** its page is not downloaded (spec 021 rule) and its stored
   page is kept.

---

### User Story 3 - Every document says when it was downloaded (Priority: P2)

As a consumer of the exports, I want to know, for every source document, when
its content was downloaded, so I can tell how recent each piece of data is
(older data is better than none, but it must be labelled).

**Why this priority**: the rotation keeps data that may be up to a few weeks
old; the date makes that visible without changing any existing export.

**Independent Test**: after a run, every document in the states export has a
download date; a curriculum reused from the cache keeps its earlier date; a
SigPesq row has the date of the report it came from.

**Acceptance Scenarios**:

1. **Given** a document downloaded in this run, **When** the run ends, **Then**
   its download date is this run's.
2. **Given** a document reused from storage, **When** the run ends, **Then**
   its download date is the date of the stored copy.
3. **Given** the states export, **When** it is read, **Then** each document
   shows its download date next to its status, and every other export file
   keeps its fields.

---

### User Story 4 - The share is configurable and a full refresh stays possible (Priority: P3)

As the maintainer, I want to change the share refreshed per run and to force a
full refresh of every item on demand, so I can trade freshness for time, and
recover quickly after a portal problem or a parser fix.

**Why this priority**: the default works on its own; this is an operational
lever.

**Independent Test**: set a share of one half and run: half of the cached
items are refreshed; request a full refresh: every item is downloaded again.

**Acceptance Scenarios**:

1. **Given** a share setting, **When** the run starts, **Then** that share of
   the cached items (rounded up) is refreshed.
2. **Given** a full refresh request, **When** the run starts, **Then** every
   Lattes curriculum and every CNPq page is downloaded again, and items whose
   download fails keep their previous copy.

### Edge Cases

- **Ties in the download date** (many items downloaded in the same run): the
  order among them is fixed (by item id), so the same items are picked in the
  same situation.
- **The list of curricula changes** (an id added or removed): an added id is
  missing from the cache and downloaded; a removed one is not downloaded, and
  its cached copy and date stay (spec 021 marks its documents inactive).
- **The manifest is missing or unreadable**: every cached item counts as
  undated (oldest); the run refreshes one share and rebuilds the manifest; it
  never falls back to downloading everything.
- **A stored CNPq page with an invalid or empty content**: treated as missing;
  the group is downloaded.
- **The portal is down for the whole run**: every refresh fails, every stored
  copy is used, and the run completes with the failures recorded.
- **A refreshed item that did not change**: its date advances; its document is
  skipped as unchanged (spec 021); nothing else is written.
- **A rule-version rebuild** (spec 021): the database is rebuilt from the
  stored raw copies; the rotation is not reset.
- **CNPq run with a campus filter**: only the filtered groups are considered
  for download and rotation.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Lattes download MUST keep a manifest of the download date of
  every cached curriculum, stored with the raw data so that it travels between
  CI runs.
- **FR-002**: Each run MUST download every listed curriculum that is not
  cached, plus the configured share (default one quarter, rounded up) of the
  cached listed curricula with the oldest download dates; undated ones count
  as the oldest; ties are broken by id.
- **FR-003**: A refreshed curriculum MUST replace its cached copy only after
  its new download succeeds; on failure the previous copy and date stay and
  the failure is recorded.
- **FR-004**: The CNPq phase MUST store each downloaded group page, with its
  download date, under `data/raw/cnpq/`, keyed by the CNPq group id.
- **FR-005**: Each CNPq run MUST download the groups with no stored page, plus
  the configured share of the stored ones with the oldest download dates, and
  read the stored page for every other group to process.
- **FR-006**: When a CNPq download fails and a stored page exists, the stored
  page MUST be used for that group and the failure recorded; a stored page is
  replaced only by a successful download.
- **FR-007**: Every source document's processing state MUST record the
  download date of the content it was built from (Lattes curriculum, CNPq
  page, SigPesq report), and the states export MUST publish it.
- **FR-008**: No existing table may change its schema and no existing export
  file may change its fields; the download date goes into the ETL's own state
  table and states export only.
- **FR-009**: The share refreshed per run MUST be configurable, and a full
  refresh of every item MUST be possible on demand, locally and in CI.
- **FR-010**: The rotation MUST be deterministic: the same manifest, list and
  share give the same items to download.
- **FR-011**: Each run MUST log, per source, how many items were new,
  refreshed, reused, and failed (and reused because of the failure).
- **FR-012**: The behaviour MUST be the same locally and in GitHub Actions;
  third-party libraries are unchanged; CNPq keeps 4 workers; SigPesq stays
  sequential.

### Key Entities

- **Raw item**: a downloaded source unit kept between runs: a Lattes
  curriculum in `cache/`, a CNPq group page in `data/raw/cnpq/`.
- **Download manifest**: for each raw item, its id and the date of its last
  successful download.
- **Download date (provenance)**: the date of the content a document was built
  from, kept in the document's processing state and published in the states
  export.
- **Rotation share**: the fraction of existing items downloaded again in a run
  (default one quarter).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the default share, every listed curriculum and every CNPq
  page is downloaded again at least once in any four consecutive runs.
- **SC-002**: In the steady state, the CNPq phase takes at most 40% of its
  current time (reference: 15.6 min in the 2026-10-29 CI run, so about 6 min;
  a reference target, not a blocker).
- **SC-003**: Zero items lose their previous copy because of a failed
  download.
- **SC-004**: 100% of the documents in the states export have a download date,
  and a document reused from storage keeps the date of its stored copy.
- **SC-005**: With the portal unavailable for a whole run, every group with a
  stored page keeps its data and the run completes.
- **SC-006**: The existing export files keep their names and fields; their
  content equals that of a run that downloads everything, apart from the
  changes the sources made since the reused copies were downloaded.

## Assumptions

- Specs 021 and 022 are merged into this branch.
- The weekly runs about once a week, so "every four runs" means about every
  four weeks; the share is the lever if that is too slow or too fast.
- A Lattes curriculum's freshness is measured by its download date, not by the
  "last update" date the curriculum itself shows; reading that date would need
  a request per curriculum, which is what this spec avoids.
- The share applies separately to Lattes and CNPq, with the same default; one
  setting may cover both unless the plan finds a reason to split them.
- The SigPesq reports keep being downloaded whole every run; their download
  date is the run's.
- The stored CNPq pages hold only what the database already holds from them
  (public group data; e-mails of public CNPq pages may stay in clear, as they
  already do); no new personal data is stored.
- Validation: locally on frozen inputs first, then on the fork with
  consecutive dispatches; nothing goes upstream before the maintainer's
  manager validates.
