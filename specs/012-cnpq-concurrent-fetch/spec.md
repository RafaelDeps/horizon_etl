# Feature Specification: Concurrent CNPq group fetch, serial write

**Feature Branch**: `012-cnpq-concurrent-fetch`

**Created**: 2026-09-04

**Status**: Draft

**Input**: User description: "Parallelize the CNPq group-data fetch while keeping the database write strictly serial, using Prefect's own concurrency primitives."

## Context

The CNPq sync phase visits the CNPq portal once per research group -- 351
times in the most recent run -- to fetch each group's page before writing its
data. Fetching one page waits for the previous group's page to be fetched,
processed, and written, in strict sequence, even though nothing requires that
ordering: the pages are independent of one another.

### What measurement showed

Measured against a full weekly run on 2026-09-04, after the CNPq sync phase
was already sped up once (feature 011-cnpq-sync-index-reuse eliminated a
redundant per-group database read that had been costing ~51.5 minutes):

| What | Cost | Share of the phase |
|---|---|---|
| CNPq sync phase, total | 50.2 min | 100% |
| Fetching group pages from the portal | 40.6 min (348 fetches, ~7.0s each) | 80.9% |
| Writing group/member/knowledge-area data | 8.2 min | 16.3% |

Fetching a page is now, by a wide margin, the dominant cost, and it is
entirely sequential. A plan to run several fetches concurrently was drafted
months ago (documented in this repository's `relatorio.md`) and never
implemented; it projected cutting the fetch time roughly in proportion to the
number of concurrent fetches.

### Why this is a different feature from a straightforward parallelization

Two things changed since that original plan was written, both introduced by
feature 011:

1. **Writing is no longer safe to run concurrently for two groups**, for a
   reason beyond the database itself. The write step now updates a shared,
   in-memory list of known researchers as it goes, so that a researcher
   created while processing one group is found -- not created a second time
   -- by a later group in the same run. Two groups writing at the same
   moment could both fail to see each other's addition and create the same
   researcher twice. This constraint did not exist before feature 011.

2. **This project has already suffered a production incident from running
   browser automation concurrently within a single process**: native browser
   state from one concurrent operation corrupted memory that a later,
   unrelated database call then crashed on, taking down an entire pipeline
   run. This is documented in this project's own weekly-pipeline
   orchestration logic, and is why every weekly phase already runs in its
   own isolated operating-system process rather than sharing one. Any
   concurrency introduced here must not reintroduce that risk by running
   multiple browser sessions inside one process.

Both constraints point the same direction: fetching can run concurrently,
because each fetch is independent and touches no shared state; writing must
continue to happen one group at a time, in a single place, exactly as it
does today.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - CNPq page fetching runs concurrently (Priority: P1)

As the person responsible for the weekly run, I want the CNPq sync phase to
fetch several groups' pages from the portal at the same time, instead of
waiting for each one to finish before starting the next, so that the phase's
duration stops being dominated by network round-trips that have no reason to
happen one at a time.

**Why this priority**: this is the entire point, and it accounts for the
large majority of the phase's current duration (40.6 of 50.2 minutes).

**Independent Test**: run the CNPq sync phase and confirm that multiple group
pages are being fetched from the portal at overlapping times, not
back-to-back.

**Acceptance Scenarios**:

1. **Given** 351 groups to synchronize, **When** the phase runs, **Then**
   more than one group's page is being fetched from the portal at the same
   moment, at least part of the time.
2. **Given** a fixed number of concurrent fetch slots, **When** the phase
   runs, **Then** no more than that number of page fetches are in flight from
   the portal at once.
3. **Given** one group's fetch fails (portal error, timeout, malformed
   page), **When** the phase continues, **Then** the other groups' fetches
   and writes are unaffected, and the failure is reported the same way a
   sequential failure is reported today.

---

### User Story 2 - Writing to the database stays strictly serial (Priority: P1)

As the person responsible for data integrity, I want every group's data to
still be written to the database one group at a time, in a single place,
exactly as it happens today, so that concurrent fetching cannot produce a
duplicated researcher, a corrupted browser-driven crash, or any other
difference in what ends up written compared to the sequential behavior.

**Why this priority**: equal priority to User Story 1 -- speed without this
guarantee would trade a slow, correct phase for a fast, occasionally wrong
one, which is not an acceptable trade.

**Independent Test**: run the CNPq sync phase against a database snapshot
taken immediately before, and confirm the resulting researcher, role, team
membership, and research group counts are identical to a sequential run
against the same starting snapshot.

**Acceptance Scenarios**:

1. **Given** two groups whose data, once fetched, is ready to be written at
   nearly the same time, **When** the phase processes them, **Then** the
   database write for one completes before the write for the other begins --
   never overlapping.
2. **Given** a researcher who does not yet exist and appears as a member in
   two different groups, **When** both groups are processed in the same run,
   **Then** exactly one researcher record is created, regardless of how
   close together their fetches completed.
3. **Given** the same weekly pipeline run end to end, **When** compared
   against an equivalent run using today's sequential fetch, **Then** the
   final researcher, role, team membership, and research group counts match
   exactly.

### Edge Cases

- **A fetch fails while others are in flight**: the phase must continue
  processing the groups whose fetches succeeded, and must report the failed
  group the same way today's sequential path reports a failed fetch --
  not differently just because it happened concurrently with others.
- **The portal responds more slowly or starts rejecting requests under
  concurrent load**: the phase must have a way to reduce or disable
  concurrency (including falling back to one fetch at a time) without a code
  change, since the acceptable level of concurrent load on the portal is not
  known in advance and may need to be tuned after observing real behavior.
- **A fetch worker crashes or hangs**: it must not take down the fetches or
  writes for other groups, and must not corrupt the state the write step
  depends on (the shared researcher list, or the database connection).
- **Very few groups to process** (e.g., a campus-scoped run with only a
  handful of groups): concurrency must not break or misbehave when there are
  fewer groups than available concurrent slots.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The CNPq sync phase MUST be able to fetch more than one
  group's page from the portal at the same time.
- **FR-002**: The number of concurrent fetches MUST be configurable without a
  code change, including a setting equivalent to today's fully sequential
  behavior (one at a time).
- **FR-003**: The database write for any one group's data MUST NOT run at the
  same time as the database write for any other group's data, regardless of
  how many fetches are running concurrently.
- **FR-004**: A researcher created while processing one group MUST be
  discoverable, without duplication, by every subsequently processed group in
  the same run -- unaffected by how many fetches are in flight concurrently
  at any point.
- **FR-005**: Fetching MUST NOT run multiple browser-automation sessions
  concurrently within a single operating-system process; each concurrent
  fetch MUST be isolated in its own process.
- **FR-006**: A single group's fetch failure MUST NOT prevent other groups
  from being fetched, processed, or written, and MUST be reported using the
  same mechanism as today's sequential failures.
- **FR-007**: The set of researchers, roles, team memberships, and research
  groups produced by a full run MUST be identical to what the current
  sequential behavior produces, for the same source data -- this is a
  performance change, not a behavior change.
- **FR-008**: Documentation produced for this feature MUST be written in
  English.

### Key Entities

- **Fetch slot**: one concurrent unit of "retrieve a group's page from the
  portal," isolated from every other fetch slot and from the write step --
  carries no shared state in or out beyond the page data itself.
- **Shared researcher registry**: the same in-memory structure introduced by
  feature 011, read once per phase run and updated as researchers are
  created; this feature's core constraint is that only the single serial
  write step ever touches it.
- **Write step**: the single place where a group's fetched data is
  translated into database changes -- unchanged in behavior by this feature,
  only in how often it has to wait for a fetch to become ready.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The CNPq sync phase's total duration drops by at least 50%
  compared to the 50.2-minute baseline, measured on the same or equivalent
  data.
- **SC-002**: A full weekly pipeline run, executed after this change,
  produces the same researcher count, role count, team membership count, and
  research group count as an equivalent run before this change, on
  otherwise-identical input data -- no data loss, no duplication.
- **SC-003**: Reducing the concurrency setting to its minimum reproduces
  today's fully sequential behavior, verifiable by the phase taking
  approximately as long as it does today at that setting.
- **SC-004**: A single failed group fetch, injected deliberately, does not
  prevent the remaining groups in the same run from being processed
  successfully.
- **SC-005**: 100% of the project's existing automated tests continue to
  pass after the change, with no reduction in what they verify.

## Assumptions

- The appropriate level of concurrency against the CNPq portal is not known
  in advance and should start conservative (matching the 4 concurrent workers
  already discussed and decided in this project) rather than being maximized
  for speed; FR-002's configurability exists specifically so this can be
  tuned down if the portal shows signs of degrading under load, without a
  code change.
- This feature does not change what data is fetched or written, what the
  matching/creation rules are, or the shape of any exported artifact -- only
  how many fetches can be in flight at once and how their results reach the
  unchanged, serial write step.
- The comparison in SC-002 is made against a database snapshot taken
  immediately before the change is applied, running the same weekly pipeline
  end to end, since the CNPq source data itself can drift between runs
  independent of any code change -- the same methodology already used to
  validate feature 011.
- No change to any other weekly-pipeline phase, to the export pipeline, or to
  how failures are reported to the team, is in scope.
