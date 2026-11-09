# Feature Specification: Paced Retry for Project PDFs Refused by the Rate Limit

**Feature Branch**: `031-mistral-rate-limit-retry`

**Created**: 2026-11-09

**Status**: Draft

**Input**: User description: "Give the SigPesq project PDFs that the Mistral API refuses with HTTP 429 a paced second try in the same run, and make the extraction log tell reused, extracted and failed documents apart."

## Context

Phase `extract_project_files` gives `enrich_projects` one structured document
per SigPesq project (`PJ_<code>.json`). It works in two stages:

1. **Download**: one PDF per project from the SigPesq portal.
2. **Extraction**: each PDF without a document becomes one. A missing
   document is first restored from the previous `exports_canonical.zip`
   (feature 013), at no cost. Only the rest are sent to the extraction
   service (Mistral), which is paid per document and limits how many calls
   it accepts per period.

The pending documents are sent one after the other, with no pause. When the
service refuses a call because of its rate limit (HTTP 429), the document
counts as an error at once and the next one is sent.

The fork runs of 2026-11-09 show the effect:

| Run | PDFs | Restored | Extracted | Errors (all HTTP 429) |
|---|---|---|---|---|
| 42616860871 (from scratch) | 321 | 296 | 0 | 25 |
| 42634852240 (restored) | 322 | 296 | 1 | 25 |

- The same 25 documents failed in both runs, for example PJ_2101, PJ_2123,
  PJ_5684 and PJ_9194.
- A document that fails never enters `exports_canonical.zip`, so the next run
  has nothing to restore and fails on it again. Without a change, these 25
  projects never get the PDF enrichment (dates, description, status) in the
  data published by CI.
- A local run has all 322 documents. Local and CI therefore differ: the field
  merge of the PDFs resolved 139 fields locally and 132 in CI.
- The opening log line says `322 PDFs | 0 already extracted (skipped) | 322
  to extract` even when 296 are then restored at no cost. It reads as if
  every document is extracted again each week, which is not the case.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A document refused by the rate limit is tried again in the same run (Priority: P1)

As the maintainer, I want a document refused because of the rate limit to be
sent again later in the same run, after a wait that grows on each try. It
should then get its structured document this week, not never.

**Why this priority**: it is the whole value of the feature. Today 25
projects (8% of 322) never get the PDF enrichment in CI.

**Independent Test**: use a fake extraction service that refuses the first
call for some documents with a rate limit error and accepts the next one.
Run the extraction. Those documents end with their structured document, and
the waits between tries grow.

**Acceptance Scenarios**:

1. **Given** a document refused once by the rate limit, **When** the next try
   is accepted, **Then** its structured document is written in this run, in
   the same format as any other, and `enrich_projects` uses it.
2. **Given** a document refused on every try, **When** the maximum number of
   tries is reached, **Then** it behaves exactly as today: no document is
   written, it counts as a failure, and the next run tries it again.
3. **Given** several pending documents, **When** they are sent, **Then** two
   consecutive calls are always spaced by at least the configured pause.
4. **Given** a document refused by the rate limit, **When** it is tried
   again, **Then** each wait is longer than the previous one, from the
   configured first wait up to the configured maximum number of tries.

---

### User Story 2 - Other failures and a long outage never hold the run (Priority: P1)

As the maintainer, I want only rate limit refusals to be retried, and the
waits to stop at a total limit. A broken PDF or a long outage of the service
must not hold the weekly run for hours.

**Why this priority**: the weekly run is bounded (the phase has 2 h, the job
5 h). Waiting without a limit would trade 25 missing projects for a failed
run.

**Independent Test**: use a fake service that refuses every call with a rate
limit error. The phase ends once the total wait limit is reached, counts the
documents not tried as left for the next run, and the weekly run goes on.
With a fake service that fails with another error, no retry happens.

**Acceptance Scenarios**:

1. **Given** a document that fails for any reason other than the rate limit
   (unreadable PDF, invalid result, another HTTP error), **When** it fails,
   **Then** it is not retried: it is logged and counted as today, and the
   batch goes on.
2. **Given** the waits of the phase reach the configured total limit,
   **When** the next wait would exceed it, **Then** no further document is
   sent. The documents not sent count as left for the next run, and the
   phase ends normally.
3. **Given** any combination of failures, **When** the phase ends, **Then**
   it never fails the weekly run and never stops the batch because of one
   document.

---

### User Story 3 - The log tells reused, extracted and failed documents apart (Priority: P2)

As the maintainer, I want the extraction log and the run summary to show
separately how many documents were restored from the archive, extracted,
retried, recovered after a retry, failed (by reason) and left for the next
run. I can then see at a glance whether money was spent and whether the
retry works.

**Why this priority**: the data is already safe with US1 and US2; without
clear counts nobody can tell what the phase did.

**Independent Test**: run the extraction with some documents restored from
the archive, some extracted, some recovered after a retry and some failed.
The log and the summary show each count, and the opening line does not
announce every PDF as "to extract".

**Acceptance Scenarios**:

1. **Given** documents restored from the archive, **When** the extraction
   starts, **Then** the opening line does not count them as to extract.
   Only the documents that will call the service are announced as such.
2. **Given** the extraction ends, **When** its summary is written, **Then**
   it shows: already present, restored from the archive, extracted (of
   which recovered after a retry), retried, failed by rate limit, failed
   for another reason, and left for the next run.
3. **Given** a run with nothing to extract, **When** the phase ends, **Then**
   the summary shows zero calls to the service.

---

### User Story 4 - The pacing and the retry are configurable (Priority: P3)

As the maintainer, I want to change the pause between calls, the first wait,
the maximum number of tries and the total wait limit, or turn the retry off,
locally and in a manual CI dispatch, as with the other run settings.

**Why this priority**: the defaults work on their own; this is an
operational lever for when the service changes its limits.

**Independent Test**: with the maximum number of tries at 0 and the pause at
0, the phase behaves exactly as today. With custom values, those values are
used.

**Acceptance Scenarios**:

1. **Given** custom settings, **When** the run starts, **Then** they are used
   instead of the defaults.
2. **Given** the retry turned off and the pause at 0, **When** the run
   starts, **Then** the extraction behaves exactly as today, apart from the
   log counts of US3.
3. **Given** an invalid value, **When** the run starts, **Then** it is logged
   and the default is used, as with the rotation share.

### Edge Cases

- **The service says how long to wait**: when a refusal says when to try
  again, that wait is used if it is within the limits; otherwise the growing
  wait applies.
- **No document to extract**: there is no pause, no call and no wait; the
  summary shows zero calls.
- **No service key, or the optional extraction dependencies missing**:
  unchanged. Today the phase builds the extractor only when there is work to
  do; the same messages and behaviour apply.
- **A document restored from the archive**: never sent to the service and
  never retried (feature 013 order kept).
- **A rate limit on a scanned PDF** (the extraction reads it with the
  service's OCR first): the whole document is tried again, with the same
  rules; the library decides internally between local text and OCR.
- **The total wait limit reached in the middle of the waits for one
  document**: that document counts as failed by rate limit; the documents
  after it count as left for the next run.
- **`force=True` (re-extract everything)**: the same pacing and retry apply
  to every document.
- **The phase time limit (2 h)**: the PDF download from scratch took 33 min
  on 2026-11-09. With the defaults, the waits of the extraction stay well
  inside the remaining time.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The extraction MUST tell a refusal because of the service's
  rate limit (HTTP 429) apart from every other failure.
- **FR-002**: A document refused because of the rate limit MUST be tried
  again in the same run, after a wait that grows on each try (default first
  wait 30 s, doubling), up to the configured maximum number of tries
  (default 3 tries after the first call).
- **FR-003**: Every other failure MUST keep today's behaviour: logged,
  counted, no retry, and the batch goes on.
- **FR-004**: Two consecutive calls to the service MUST be spaced by at least
  the configured pause (default 2 s).
- **FR-005**: The phase MUST stop sending documents when its waits would
  exceed the configured total limit (default 20 min). The documents not sent
  MUST be counted as left for the next run.
- **FR-006**: A document that still fails after its last try, or that is not
  sent, MUST behave exactly as today: no document is written, and the next
  run tries it again. One document MUST never stop the batch, and the phase
  MUST never fail the weekly run because of extraction failures.
- **FR-007**: The archive reuse (feature 013) MUST keep its order: a
  document is restored before any call, and a restored document is never
  sent to the service.
- **FR-008**: The opening log line MUST NOT count restored documents as to
  extract. The end-of-extraction summary and the run summary MUST report
  separately: already present, restored from the archive, extracted,
  recovered after a retry, retried, failed by rate limit, failed for another
  reason, and left for the next run.
- **FR-009**: The pause, the first wait, the maximum number of tries and the
  total wait limit MUST be configurable through environment variables, the
  Makefile and the manual GitHub Actions dispatch, the same way as the
  rotation share. An invalid value MUST be logged and replaced by the
  default.
- **FR-010**: With the maximum number of tries at 0 and the pause at 0, the
  extraction MUST behave exactly as today, and the structured documents it
  writes MUST be identical.
- **FR-011**: The format of the structured documents, `enrich_projects`, the
  PDF download stage, SigPesq's sequential download and the third-party
  libraries (agent_sigpesq, mistralai) MUST stay unchanged. The retry lives
  in horizon_etl, around the library call.
- **FR-012**: The behaviour MUST be the same locally and in GitHub Actions.
  Docker is out of scope.

### Key Entities

- **Pending document**: a project PDF with no structured document, neither
  present locally nor restored from the archive. Only these call the
  service.
- **Rate limit refusal**: the service's answer that too many calls were
  made (HTTP 429). It is the only failure that is retried.
- **Try**: one call to the service for one document. The first try plus at
  most the configured number of retries.
- **Wait budget**: the total time the phase may spend waiting for the rate
  limit; once spent, the remaining documents are left for the next run.
- **Extraction counts**: already present, restored, extracted, recovered,
  retried, failed by rate limit, failed for another reason, left for the
  next run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a fork run with the 25 documents refused on 2026-11-09 still
  pending, at least 23 of them (90%) end the run with their structured
  document. Today the figure is 0.
- **SC-002**: After that run and the next one, the PDF field merge in CI
  resolves at least as many fields as the local run (139 on 2026-11-09),
  give or take changes in the sources.
- **SC-003**: With the service refusing every call, the extraction stage
  ends within the total wait limit plus 5 minutes, and the weekly run goes
  on.
- **SC-004**: With nothing to extract, the phase makes zero calls and adds no
  wait.
- **SC-005**: With the retry off and the pause at 0, the structured documents
  are identical to those of the same run without this feature.
- **SC-006**: The end-of-extraction summary alone tells how many documents
  were restored, extracted, recovered, failed by reason and left for the
  next run.

## Assumptions

- Branch `031-mistral-rate-limit-retry` starts from `fix-stale-tests`, which
  holds branch 030 and the TD-031 test fixes.
- The 25 failures come from sending calls back to back, not from those PDFs
  themselves: locally the same 25 PDFs were extracted. A paced retry is
  therefore expected to recover them.
- The extraction library raises an error that carries the HTTP status of the
  refusal, so a rate limit can be told apart without changing the library.
- Defaults (pause 2 s, first wait 30 s doubling, 3 retries, total wait limit
  20 min) are starting values; the maintainer may tune them per run.
- A recovered document enters `exports_canonical.zip` through the existing
  commit step of the weekly workflow, so later runs restore it at no cost.
- Keeping the structured documents in the weekly state bundle, refreshing
  PDFs already downloaded and the service's batch API
  (agent_sigpesq `BatchProjectExtractor`) are out of scope and may be later
  specs.
