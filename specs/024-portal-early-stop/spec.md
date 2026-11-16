# Feature Specification: Stop Downloading When a Portal Blocks

**Feature Branch**: `027-portal-early-stop`

**Created**: 2026-10-30

**Status**: Draft

**Input**: User description: "Stop downloading from the CNPq and Lattes portals as soon as they block or stop answering, and finish the run from the copies kept between runs."

## Context

Spec 023 keeps a raw copy of every CNPq group page (`data/raw/cnpq/`) and
every Lattes curriculum (`cache/`), with its download date, and spec 022
carries them between GitHub Actions runs. Each run downloads only new items
plus a rotating share of the stored ones. A failed download already falls back
to the stored copy, and the failure is recorded.

That fallback only helps when the download gives up in time. Two CI runs show
it does not:

- **CNPq, run 40966298828 (2026-10-29).** The DGP portal was down. Every page
  failed 9 times: 3 attempts by the ETL, each with the 3 attempts of the CNPq
  library. The adaptive concurrency limit went from 4 to 2. A failed page
  falls back to its stored copy only once its download returns, and with 87
  pages due the phase hit its 3 h limit first. The phase was killed before it
  wrote anything, and the run took 3 h 40 min. The CNPq data in the database
  stayed intact, but the stored pages were never used.
- **CNPq, run 40002646510 (2026-10-23).** The same outage: 697 of 697 page
  navigations timed out from the first request, the phase used its whole 3 h,
  and the exports shipped with no CNPq group. (That was before spec 023, so
  there were no stored pages either.)
- **Lattes, run 40966298828.** The portal sometimes serves its access check
  page (a reCAPTCHA) instead of the curriculum. Since spec 023 such a page is
  rejected and the cached copy kept. Out of 109 refreshes, 23 were rejected;
  the run kept asking the portal after it had started blocking.

Older data is better than none (constitution, provenance rule), and the
access check must never be answered or bypassed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - CNPq stops downloading when the portal is down or hangs (Priority: P1)

As the maintainer, I want the CNPq phase to stop calling the portal as soon as
it is clearly not answering, and to process every remaining group from its
stored page, so that an outage costs minutes instead of the phase's whole 3 h
limit, and the groups keep their data in the exports.

**Why this priority**: two of the recent CI runs lost 3 h to an outage; in one
of them the exports shipped with no CNPq group.

**Independent Test**: with stored pages for every group and a fake portal that
fails (or never answers) every request, run the CNPq phase: it stops after the
configured number of failures in a row, processes every group from its stored
page, and ends in minutes with the database unchanged.

**Acceptance Scenarios**:

1. **Given** the configured number of downloads in a row fail with no success
   between them (default 8), **When** the next download would start, **Then**
   no further request is sent to the portal in this run, and every group not
   yet downloaded is processed from its stored page with that page's original
   download date.
2. **Given** downloads that keep running past the configured time budget
   (default 45 min) because the portal is slow or hangs, **When** the budget
   runs out, **Then** downloading stops in the same way, even if the failures
   were not in a row.
3. **Given** a group with no stored page when downloading stops, **When** the
   phase ends, **Then** that group is a failed download, as today, and nothing
   about it changes in the database.
4. **Given** a portal that fails a few times and then answers again, **When**
   a download succeeds before the limit is reached, **Then** the count of
   failures in a row starts again from zero, and the phase goes on as today.
5. **Given** a portal that answers normally, **When** the phase runs with the
   default settings, **Then** downloading never stops early and the result is
   identical to today's.

---

### User Story 2 - Lattes stops refreshing when the portal blocks (Priority: P1)

As the maintainer, I want the Lattes download to stop asking the portal after
it returns the access check page (or fails) several times in a row, so that
the run does not keep hitting a portal that is blocking it, and the curricula
left keep their cached copy for the next run.

**Why this priority**: it is the same failure as US1 on the other portal, and
asking a blocking portal again and again is what makes it block longer.

**Independent Test**: with cached curricula and a fake portal that returns the
access check page, run the Lattes download: it stops after the configured
number of rejections in a row, keeps every cached copy, and the curricula not
refreshed are the first ones picked by the rotation of the next run.

**Acceptance Scenarios**:

1. **Given** the configured number of refreshes in a row return the access
   check page or fail (default 5), **When** the next refresh would start,
   **Then** no further curriculum is requested from the portal in this run.
2. **Given** downloading stopped, **When** the run goes on, **Then** every
   curriculum not refreshed is processed from its cached copy, keeps its old
   download date, and is taken first by the next run's rotation.
3. **Given** a new curriculum (not in the cache) that was not downloaded
   because downloading stopped, **When** the next run starts, **Then** it is
   still new and is downloaded first.
4. **Given** a portal that answers normally, **When** the download runs with
   the default settings, **Then** it never stops early and the result is
   identical to today's.

---

### User Story 3 - The run says when a portal was given up (Priority: P2)

As the maintainer, I want the run summary and the logs to say when a portal
was given up, why (failures in a row or time budget), and how many items came
from stored copies, so I can tell an outage from a bug without reading the
whole log.

**Why this priority**: the early stop changes what the run downloads; it must
be visible, but the data is already safe without it.

**Independent Test**: run the CNPq phase and the Lattes download against a
fake portal that is down: the summary shows, for each source, that it was
given up, the reason, the moment, and the counts of downloaded, stored-copy
and failed items; the weekly ends with success.

**Acceptance Scenarios**:

1. **Given** a source given up during the run, **When** the run ends, **Then**
   the summary names the source, the reason and the number of items processed
   from stored copies, and the weekly does not fail because of it.
2. **Given** a source not given up, **When** the run ends, **Then** the
   summary shows nothing new for it beyond today's counts.

---

### User Story 4 - The limits are configurable (Priority: P3)

As the maintainer, I want to change the failures-in-a-row limits and the CNPq
time budget, or turn the early stop off, locally and in a manual CI dispatch,
so I can adjust them to how the portals behave.

**Why this priority**: the defaults work on their own; this is an operational
lever, like the rotation share.

**Independent Test**: set a limit of 2 and run against a fake portal that
fails: downloading stops after 2 failures; turn the early stop off: every due
item is tried, as today.

**Acceptance Scenarios**:

1. **Given** custom limits, **When** the run starts, **Then** they are used
   instead of the defaults, for each source separately.
2. **Given** the early stop turned off, **When** the run starts, **Then** the
   downloads behave as they do today.

### Edge Cases

- **Downloads in progress when the limit is reached**: no new request is
  started and no failed download is retried after the stop. A download
  already in progress may finish; a success is used, but the phase does not
  wait for it beyond a bounded time.
- **Failures spread out between successes**: they do not stop downloading,
  since the count is of failures in a row. The time budget still bounds the
  phase.
- **A full refresh on a healthy but slow portal**: the time budget applies to
  a full refresh too; the groups not reached use their stored page, and are
  the oldest in the next rotation.
- **No stored copy at all** (first run, or an empty cache): the early stop
  still stops the requests; those items are failed downloads, as today.
- **A campus filter on the CNPq phase**: the limits apply to the filtered
  groups only.
- **The access check page on a new curriculum**: it counts towards the Lattes
  limit like a rejected refresh.
- **The unidentified-curriculum retry** (spec 023): unchanged; a curriculum
  that was not refreshed keeps its retry mark.
- **A run where CNPq is given up but Lattes is not** (or the reverse): each
  source decides on its own.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The CNPq phase MUST stop sending requests to the portal when the
  configured number of downloads in a row (default 8) has failed with no
  success between them.
- **FR-002**: The CNPq phase MUST also stop sending requests when its
  downloads have run longer than the configured time budget (default 45 min).
- **FR-003**: After the CNPq stop, downloads not yet started MUST be
  cancelled, failed downloads MUST NOT be retried, and every remaining group
  MUST be processed from its stored page with its original download date. The
  phase MUST NOT wait without bound for downloads still in progress.
- **FR-004**: A CNPq group with no stored page when downloading stops MUST be
  a failed download, as today: nothing about it changes in the database, and
  the failure is recorded.
- **FR-005**: The Lattes download MUST stop requesting curricula (refreshes
  and new ones) when the configured number of requests in a row (default 5)
  has returned the access check page or failed.
- **FR-006**: After the Lattes stop, every cached curriculum MUST be processed
  from its cached copy with its old download date, so the next run's rotation
  takes the ones not refreshed first; a new curriculum not downloaded stays
  new for the next run.
- **FR-007**: A success MUST reset the count of failures in a row, for each
  source separately.
- **FR-008**: With a portal that answers normally, the default limits MUST
  never trigger, and the output MUST be identical to today's.
- **FR-009**: The run summary and the logs MUST state, for each source given
  up, the reason, when it happened, and the counts of items downloaded, taken
  from stored copies, and failed. A source given up MUST NOT make the weekly
  fail.
- **FR-010**: The limits, the time budget and turning the early stop off MUST
  be configurable, locally and in a manual GitHub Actions dispatch, the same
  way as the rotation share.
- **FR-011**: The access check page MUST never be answered or bypassed.
- **FR-012**: The existing retry and concurrency rules for a healthy portal
  stay as they are: CNPq keeps 4 workers and a single database writer; SigPesq
  stays sequential; third-party libraries are unchanged; no table or export
  file changes its format.

### Key Entities

- **Early stop**: the decision, per source and per run, to stop sending
  requests to a portal; it has a reason (failures in a row, or time budget)
  and a moment.
- **Failures in a row**: for each source, the count of consecutive failed
  requests with no success between them; a success resets it.
- **Time budget**: the longest time the CNPq downloads may run in one phase.
- **Stored copy**: the raw item kept by spec 023 (CNPq page or cached
  curriculum) with its download date, used for every item not downloaded.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the CNPq portal down for the whole run (every request fails
  or hangs), the CNPq phase ends in at most 15 min, against 3 h today.
- **SC-002**: In that run, 100% of the groups with a stored page keep their
  data in the database and in the exports.
- **SC-003**: With the Lattes portal serving only its access check page, the
  run sends at most the configured limit of requests (5 by default), plus the
  ones already in progress, before it stops.
- **SC-004**: With both portals answering normally, the exports are identical
  to those of the same run without this feature.
- **SC-005**: Zero cached copies or stored pages are lost or replaced because
  of an early stop.
- **SC-006**: In a run with an early stop, the summary alone tells which
  source was given up, why, and how many items came from stored copies.

## Assumptions

- Spec 023 is merged into this branch (branch `027-portal-early-stop` starts
  from `026-rotating-raw-downloads`).
- "A failure" for CNPq is one failed download attempt of the ETL, which
  already includes the CNPq library's own 3 tries (about 95 s when the portal
  hangs). Counting whole pages, after all their retries, would stop only after
  about 27 min in run 40966298828, against SC-001 (plan, research R1). For
  Lattes a failure is a request that failed or returned the access check
  page. A curriculum that downloads but cannot be identified later (spec 023)
  is not a portal failure.
- The defaults (8 failures, 45 min, 5 rejections) come from the recent runs.
  In the seven healthy CI runs of 2026-10-28 and 2026-10-29 there was at most
  one failed CNPq attempt and one failed Lattes download per run. A CNPq
  rotation took about 4 min and a full download 15 to 25 min, so 45 min only
  triggers on a portal that is slow or hanging (plan, research R2 and R3).
- Turning the early stop off restores today's behaviour, for diagnosis.
- Telling "portal down" from "portal blocking 4 connections from a data
  centre IP" is out of scope; this spec only bounds the cost of either.
- The phase time limits of the weekly orchestrator stay as they are; this spec
  keeps the phases well inside them.
- Validation: tests with fake portals (healthy, down, hanging, access check),
  then a local replay, then a dispatch on the fork; nothing goes upstream
  before the maintainer's manager validates.
