# Feature Specification: Concurrent CNPq Group Sync with a Single Writer

**Feature Branch**: `020-cnpq-concurrent-sync`

**Created**: 2026-10-22

**Status**: Implemented

**Input**: User description: "Speed up the CNPq phase (cnpq_sync) of the weekly pipeline, now the largest remaining phase, so `make weekly-flows` keeps shrinking (2h09 after specs 015 and 016) while still running locally first and in GitHub Actions afterwards."

## Context

Specs 015 and 016 cut the weekly run from 8 h 04 min to 2 h 09 min. The CNPq
phase is now the largest remaining phase.

| Full run | CNPq phase | Groups collected |
|---|---:|---|
| 2026-10-21 | 72.4 min | — |
| 2026-10-22 (night) | 124.3 min | 349/350 |
| Spec 015 validation | 76.8 min | 265/350 (85 connection resets) |
| Spec 016 validation | 54.4 min | 350/350 |

In the spec 016 run, the CNPq phase was ~42% of the whole run.

### What the measurement showed

A breakdown of a real `cnpq_sync` (5 219 s, ~350 groups):

| Where the time goes | Share |
|---|---:|
| Waiting for the DGP portal to deliver a group page (2–60+ s per page) | **71%** |
| Opening a browser per group (done by the CNPq library) | ~5% |
| ETL work per group in short steps (~3.6 s per group) | ~24% |

- **Groups are fetched strictly one after another.** A benchmark fetched 20
  group pages with 4 in parallel: 114 s of wall time against 397 s summed
  (3.5×), 20/20 successful. The maintainer tested 4 parallel fetches in an
  earlier fork and saw a substantial reduction; 4 is the chosen default.
- **Part of the ETL work re-reads the whole researcher register for every
  group** (TD-008): about 7 600 researchers with four eagerly joined
  collections, ~350 times per run. The same pattern was fixed for the Lattes
  phases by spec 007.
- **The portal sometimes cuts connections.** In the spec 015 validation run, 85
  of 350 groups failed with connection resets within 8 minutes, right after
  another full crawl had finished. The CNPq library already retries a page up
  to 3 times, waiting 1–10 s. After that, the ETL records "no data" for the
  group and skips it for the run. The cause (reset, timeout or other) is
  currently only visible in the log message.

### Constraints that shape the solution

- **One writer.** The database is SQLite, so only one writer may run at a time.
  Only fetching group pages can happen in parallel. Everything that reads or
  writes the database stays serial.
- **The CNPq library is used as it is.** It belongs to someone else. This
  repository may change how it calls the library, and what it does with the
  results, but must not modify, replace or re-implement it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Group pages are fetched in parallel, data is written by one writer (Priority: P1)

As the maintainer, I want the CNPq phase to fetch up to 4 group pages at the
same time, while a single writer saves the results in the original group order.
The phase should take a fraction of its current time and produce exactly the
same data.

**Why this priority**: Waiting for the portal is 71% of the phase. Overlapping
those waits is the largest gain left in the weekly run.

**Independent Test**: A controlled replay feeds the same captured group pages to
the old and the new code (no portal access) and compares the results. A timed
run shows the phase is faster and never exceeds the configured number of
simultaneous fetches.

**Acceptance Scenarios**:

1. **Given** 350 groups to sync and a concurrency of 4, **When** the phase runs,
   **Then** at no moment are more than 4 group pages being fetched.
2. **Given** the fetches finish out of order, **When** results are saved,
   **Then** they are saved one at a time, in the original group order, and the
   resulting data is identical to a sequential run on the same pages.
3. **Given** a concurrency of 1, **When** the phase runs, **Then** the behaviour
   is equivalent to today's sequential phase.
4. **Given** the phase is running, **When** results are being saved, **Then** no
   "database is locked" error occurs and no database access happens outside the
   single writer.

---

### User Story 2 - Member sync stops re-reading the whole researcher register per group (Priority: P2)

As the maintainer, I want researcher lookups during member sync to use a lookup
built once per phase. That lookup is kept current as researchers are created,
and gives exactly today's answers.

**Why this priority**: It removes repeated work inside the serial writer, which
becomes the bottleneck once fetching is parallel. It is independent of Story 1.

**Independent Test**: Unit tests show the same researcher is matched or created
as today, including a researcher created by one group and found by a later
group. The controlled replay is identical.

**Acceptance Scenarios**:

1. **Given** a phase run, **When** members of all groups are synced, **Then** the
   whole researcher register is read at most once.
2. **Given** a researcher created while syncing one group, **When** a later group
   lists the same person, **Then** that researcher is found, not duplicated.
3. **Given** any member list, **When** it is synced, **Then** each member is
   matched to, or creates, the same researcher as today.

---

### User Story 3 - Portal resets do not silently cost groups (Priority: P3)

As the maintainer, I want a group whose page fails to load to be tried again
later with increasing waits. When failures cluster, the phase should slow down
instead of hammering the portal. A run then still collects all groups when the
portal recovers, and only reports groups that kept failing.

**Why this priority**: Without it, parallel fetching could make portal resets
more likely and silently lose data, as the 85 lost groups showed. It protects
the data quality of Stories 1 and 2.

**Independent Test**: With a simulated portal that fails some fetches,
temporarily or permanently, tests show retries with growing waits, reduced
concurrency during failure bursts, temporary failures recovered, and permanent
failures reported exactly as today.

**Acceptance Scenarios**:

1. **Given** a group whose first fetch fails and a later attempt succeeds,
   **When** the phase runs, **Then** the group is synced normally and counted
   as a retry, not a failure.
2. **Given** a group that fails on every attempt, **When** the phase runs,
   **Then** it is reported as a collection failure exactly as today, after a
   bounded number of attempts and a bounded total wait, and the other groups
   are not blocked.
3. **Given** several failures within a short window, **When** the phase detects
   the burst, **Then** it reduces the number of simultaneous fetches, and it may
   restore it after a period without failures.

### Edge Cases

- **Invalid group URLs:** groups whose URL lacks the 16-digit DGP identifier are
  reported as today (`cnpq_group_url_invalid`) and never fetched.
- **No groups:** the phase ends normally with an empty summary.
- **Campus filter:** a campus filter restricts the groups exactly as today.
- **Retried failures:** a fetch that returns no data is retryable, because the
  current adapter does not expose why it failed (FR-007).
- **A write failure:** today an exception while saving a group is not caught in
  the per-group sync, so it fails the CNPq flow; the phase is non-critical, so
  the pipeline continues. That behaviour is preserved, not changed, by this
  feature. Errors handled inside the sync logic, such as rollbacks per member,
  stay as they are. (Corrected during planning; the first draft said such
  failures were logged and counted.)
- **The portal is down for the whole phase:** every group ends as a reported
  failure within the bounded retry budget. The phase still finishes, and the
  pipeline continues as today, since the CNPq phase is non-critical.
- **A browser start failure in a worker:** it is treated like a fetch failure
  for that group.
- **A concurrency setting of 0, negative, or non-numeric:** fall back to the
  default (4) and log a warning.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The phase MUST fetch group pages concurrently with at most N
  fetches in flight at any time. N is configurable and defaults to 4.
- **FR-002**: Every fetch MUST go through the existing adapter and library call
  exactly as today, with each call opening its own browser. No own crawler, and
  no change to the library.
- **FR-003**: All database reads and writes of the phase MUST happen in a single
  writer, one group at a time. This covers group update, member extraction and
  sync, knowledge areas and tracking source records. No database access may
  happen in the fetch workers.
- **FR-004**: Group results MUST be saved in the original group order,
  regardless of the order in which fetches complete.
- **FR-005**: With N = 1, the phase MUST be behaviourally equivalent to today's
  sequential phase.
- **FR-006**: Member sync MUST read the whole researcher register at most once
  per phase run. Its lookup MUST be updated as researchers are created during
  the phase, and MUST give the same match-or-create decisions as today.
- **FR-007**: A fetch that returns no data MUST be retried with growing waits,
  within a bounded number of attempts and a bounded total wait per group. The
  retry wait MUST NOT block other fetches or the writer.
- **FR-008**: When fetch failures cluster within a short window, the phase MUST
  reduce its number of simultaneous fetches, never below 1. It MAY restore the
  concurrency after a period without failures.
- **FR-009**: A group that still fails after all retries MUST be reported exactly
  as today: logged, counted in the phase summary, and included in
  `cnpq_group_sync_failed`. It MUST NOT stop the other groups.
- **FR-010**: The phase summary and its report keep their current meaning and
  fields: groups synchronised, collection failures, invalid URLs, and the
  `cnpq_group_sync_failed` / `cnpq_group_url_invalid` codes.
- **FR-011**: At the end of the phase, the system MUST log one INFO line with:
  - workers configured;
  - groups fetched;
  - retries performed;
  - groups failed after retries;
  - concurrency reductions;
  - the researcher lookup counters: loaded, hits, created.

  The line MUST contain counts only, no personal data.
- **FR-012**: For the same group pages, the produced data MUST be identical to
  today's:
  - research groups updated;
  - members, roles and start dates;
  - knowledge areas and group links;
  - researchers created or matched;
  - tracking source records.
- **FR-013**: All changes MUST live in this repository's own code and tests. No
  external library (`dgp_cnpq_lib`, `eo_lib`, `research_domain`, `libbase`,
  `agent_sigpesq`, `scriptLattes`) may be modified, replaced or re-implemented.
- **FR-014**: The change MUST work identically in local runs and in the GitHub
  Actions weekly workflow (clean checkout, fresh database each run).
- **FR-015**: Automated tests MUST cover:
  - the researcher lookup built once per phase;
  - a researcher created by one group and found by a later group;
  - at most N fetches in flight;
  - all writes on one writer, in the original group order;
  - a failing fetch retried with growing waits, and reported if it never
    succeeds, while the others continue;
  - concurrency reduced when failures cluster;
  - N = 1 equivalent to sequential.

### Key Entities

- **Group to sync**: identifier, name and mirror URL, from the existing
  selection. Its position in the list defines the write order.
- **Fetched group page**: the data dictionary returned by the adapter for one
  group, or "no data". It is produced by a fetch worker and consumed by the
  writer.
- **Fetch attempt record**: per group, the number of attempts made and whether
  the group ended collected or failed. It feeds the summary line and the failure
  report.
- **Researcher lookup**: the per-phase view of the researcher register used by
  member sync, kept current as researchers are created.

## Success Criteria *(mandatory)*

Targets are guidance; the absolute gain matters most.

### Measurable Outcomes

- **SC-001**: On a full local `make weekly-flows` with a healthy portal, the CNPq
  phase takes clearly less than in the spec 016 run (54.4 min). The expectation
  is ~20–35 min, with exit 0 and 350/350 groups collected.
- **SC-002**: At no point during the phase are more simultaneous page fetches in
  flight than configured.
- **SC-003**: The phase produces no "database is locked" errors and performs no
  database access outside the single writer.
- **SC-004**: A controlled replay is identical between the old and the new code.
  It uses the same pre-CNPq database snapshot and the same captured group pages
  (saved once from a real run, so the portal's day-to-day variation is excluded).
  "Identical" means the same counts of research groups, team members, persons,
  researchers and knowledge areas and their links, plus the same name-based
  membership sets.
- **SC-005**: When the portal resets connections temporarily, the groups affected
  are recovered by the retries. In a simulated burst, every group that recovers
  within the retry budget ends collected.
- **SC-006**: The existing test suite shows no new failures (the 6 pre-existing
  ones may remain), and the tests in FR-015 pass.

## Assumptions

- The DGP portal tolerates 4 simultaneous page fetches from one machine. The
  benchmark (20 pages, 4 at a time, 0 failures) and the maintainer's earlier
  fork support this. Clustered resets are handled by FR-008.
- The adapter keeps returning "no data" for any failed fetch, and the library
  keeps its own 3-attempt retry. The ETL-level retry is a second, slower layer on
  top. This feature does not change the library's retry.
- 350 groups and ~7 600 researchers are representative of current runs.
- The replay captures group pages once from a real run, through the existing
  adapter. Captures, snapshots and comparison scripts live outside the
  repository, as in specs 015 and 016.
- Retry bounds and the failure-burst rule (window size, threshold, how far
  concurrency drops and when it recovers) are set during planning. Defaults
  should keep the worst case per failing group within a few minutes of extra
  wait.
- SigPesq stays sequential, and the Lattes phases are unchanged.
- SQLite commit latency (TD-018), phase timeouts (TD-015) and the rapidfuzz
  setting (TD-017) are out of scope.
- Validation is local first; the GitHub Actions run comes afterwards, when the
  maintainer decides.
