# Feature Specification: Second Try for Lattes Access Check Pages

**Feature Branch**: `028-lattes-captcha-retry`

**Created**: 2026-11-03

**Status**: Draft

**Input**: User description: "Give the Lattes curricula that came back as the portal's access check page a second try within the same run, after a pause."

## Context

Spec 023 keeps every Lattes curriculum in `cache/` with its download date,
and each run downloads the new curricula plus a rotating share of the cached
ones. Spec 024 stops asking the portal after 5 requests in a row that fail or
return the access check page.

The Lattes portal sometimes serves its access check page (a reCAPTCHA)
instead of the curriculum. Since spec 023 such a page is detected and
rejected:

- **New curriculum** (not in `cache/`): nothing is cached. The curriculum has
  no data in this run, and the next run downloads it first, as a new one.
- **Refresh**: the cached copy and its old date are kept. The next run's
  rotation takes it first, as the oldest.

Either way it is only tried again in the next weekly run, one week later.
Timeouts and connection errors already get a second attempt within the run;
access check pages get none.

The evidence says these pages fall on random requests, not on particular
people:

- **Local run from scratch (2026-11-03).**
  - 38 of 435 requests got the access check page, about 9%.
  - They came spread over 23 minutes, 1 to 5 per minute, with successes
    between them, so the spec 024 stop never triggered.
  - 35 of those 38 curricula had a real copy from an earlier run.
- **Earlier runs.**
  - Of the 27 curricula that failed this way on 2026-10-21, only 3 failed
    again on 2026-11-03, about what chance alone gives at a 9% rate.
  - CI run 41057537912 (2026-10-30) got 31 of 426.

In a run that starts from an empty cache (the first CI run after the merge,
or a local rebuild), each of these curricula loses a whole week of data.
The access check must never be answered or bypassed: asking again later is
what the next run already does, only sooner.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A curriculum rejected by the access check is asked for again in the same run (Priority: P1)

As the maintainer, I want the curricula that got the access check page to be
requested once more at the end of the Lattes download, after a pause. Most of
them should then arrive in the same run instead of a week later.

**Why this priority**: it is the whole value of the feature. In the run from
scratch of 2026-11-03, 38 curricula (9%) had no data at all because of it.

**Independent Test**: use a fake portal that serves the access check page on
the first request for some curricula and the real page on the second. Run the
Lattes download. Those curricula end with their real page and today's date:
the new ones in `cache/`, the refreshed ones replacing their old copy.

**Acceptance Scenarios**:

1. **Given** a new curriculum whose first request got the access check page,
   **When** the second try gets the real page, **Then** it is cached with
   this run's download date and processed in this run like any other new
   curriculum.
2. **Given** a refresh whose first request got the access check page,
   **When** the second try gets the real page, **Then** the cached copy is
   replaced and the download date updated.
3. **Given** a curriculum that gets the access check page on both tries,
   **When** the run goes on, **Then** it behaves exactly as today. A new one
   is not cached and is new again in the next run. A refresh keeps its cached
   copy and old date.
4. **Given** the first pass ends, **When** the second pass starts, **Then**
   it waits the configured pause first (default 5 min). It then sends at most
   one more request per rejected curriculum, with the configured number of
   workers (default 1).
5. **Given** a first pass with no access check page, **When** the download
   ends, **Then** there is no pause and no second pass, and the result is
   identical to today's.

---

### User Story 2 - The second try respects the portal stop (Priority: P1)

As the maintainer, I want the second pass to follow the spec 024 stop, so
that it never adds pressure on a portal that is blocking the run.

**Why this priority**: asking a blocking portal again and again is what makes
it block longer. The second pass must not undo spec 024.

**Independent Test**: use a fake portal that serves only the access check
page. When the stop triggers in the first pass, no second pass starts. When
the stop triggers during the second pass, its remaining requests are not
sent.

**Acceptance Scenarios**:

1. **Given** the Lattes portal was given up in the first pass, **When** the
   first pass ends, **Then** no pause and no second pass happen.
2. **Given** a second pass in progress, **When** its requests reach the
   stop's limit of access check pages or failures in a row, **Then** no
   further request is sent, and the curricula not tried behave as the ones
   not tried under spec 024.
3. **Given** the first pass ended with some failures in a row below the
   limit, **When** the second pass starts, **Then** its requests continue the
   same count. The pause does not reset it; only a success does.

---

### User Story 3 - The run says how many were retried and recovered (Priority: P2)

As the maintainer, I want the downloads line and the run summary to show how
many curricula got a second try and how many it recovered, so I can see
whether the pause works without reading the whole log.

**Why this priority**: the data is already safe without it, but without these
counts nobody can tell whether the second pass is worth its time.

**Independent Test**: run the Lattes download against the fake portal of
US1. The downloads line and the summary show the counts of curricula
retried, recovered and still rejected.

**Acceptance Scenarios**:

1. **Given** a second pass ran, **When** the download ends, **Then** the
   downloads line shows how many were retried and how many recovered. The
   existing counts (new, refreshed, reused, failed, stopped) count each
   recovered curriculum as a success.
2. **Given** no second pass ran, **When** the download ends, **Then** the
   downloads line shows nothing new beyond today's counts.

---

### User Story 4 - The second try is configurable (Priority: P3)

As the maintainer, I want to change the pause and the number of workers of
the second pass, or turn it off, locally and in a manual CI dispatch. That way
I can adjust it to how the portal behaves, as with the rotation share.

**Why this priority**: the defaults work on their own; this is an operational
lever.

**Independent Test**:
- With a pause of 0, the second pass starts right after the first.
- With 0 workers, there is no second pass, and the result is identical to
  today's.

**Acceptance Scenarios**:

1. **Given** custom settings, **When** the run starts, **Then** they are used
   instead of the defaults.
2. **Given** the second pass turned off, **When** the run starts, **Then**
   the Lattes download behaves exactly as today.
3. **Given** an invalid value, **When** the run starts, **Then** it is logged
   and the default is used, as with the rotation share.

### Edge Cases

- **A timeout or connection error on the first request**: it keeps its
  current retry and is not part of the second pass. If that retry ends in the
  access check page, the curriculum joins the second pass.
- **A failure on the second try other than the access check page**: it is a
  failed download, as today. Its existing retry for timeouts and connection
  errors still applies.
- **A full refresh** (`HORIZON_FULL_REFRESH=1`): the second pass applies to
  every rejected curriculum, with the same rules.
- **The unidentified-curriculum retry (spec 023)**: unchanged. A page that is
  a real curriculum but is later read as "Nome-nao-identificado" is not an
  access check page, and is not part of the second pass.
- **Duplicated ids in the list**: each curriculum gets at most one second
  try.
- **The phase time limit**: the second pass is bounded by the pause plus one
  request per rejected curriculum. The Lattes download keeps its current
  limit (90 min). The second pass must keep the phase inside it.
- **Excluded from the scriptLattes run**: the failed curricula are excluded
  today. A curriculum recovered in the second pass is not a failure, so it is
  included and processed in this run.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Lattes download MUST tell an access check page apart from
  the other download failures, for both new curricula and refreshes. The
  other failures keep their current retry rules unchanged.
- **FR-002**: After the first pass (new curricula, then the refresh share),
  every curriculum whose request in this run ended with the access check page
  MUST be requested once more, and only once.
- **FR-003**: Before the second pass, the download MUST wait the configured
  pause (default 5 min). The second pass MUST use the configured number of
  workers (default 1).
- **FR-004**: The second pass MUST follow the first pass's caching rules:
  - a new curriculum is cached only when the real page arrives;
  - a refresh replaces the cached copy only when the real page arrives;
  - the download date is recorded only on success.
  A curriculum rejected again MUST behave exactly as it does today.
- **FR-005**: No pause and no second pass MUST happen when the spec 024 stop
  gave the Lattes portal up in the first pass. Second-pass requests MUST
  count towards the same stop, continuing its count of failures in a row.
- **FR-006**: When the first pass had no access check page, or the second
  pass is turned off, the Lattes download MUST behave exactly as today, and
  its output MUST be identical.
- **FR-007**: The Lattes downloads line and the run summary MUST show how
  many curricula were retried and how many were recovered. A recovered
  curriculum MUST count as a success in the existing counts.
- **FR-008**: The pause, the number of second-pass workers, and turning the
  second pass off MUST be configurable through environment variables, the
  Makefile and the manual GitHub Actions dispatch, the same way as the
  rotation share.
- **FR-009**: The access check page MUST never be answered or bypassed. The
  second pass only repeats the same plain request, later.
- **FR-010**: The refresh share, the 3 first-pass workers, the spec 024
  limits, SigPesq's sequential download and the third-party libraries MUST
  stay unchanged. No table or export file changes its format.
- **FR-011**: The behavior MUST be the same locally and in GitHub Actions.
  Docker is out of scope.

### Key Entities

- **Access check page**: the portal page served instead of a curriculum,
  recognised because it lacks the curriculum title. It is the only failure
  that triggers a second try.
- **First pass**: today's Lattes download, new curricula first and then the
  refresh share, with 3 workers.
- **Second pass**: one more request, after a pause, for each curriculum the
  first pass rejected for the access check page. It is bounded by the spec
  024 stop.
- **Retried / recovered**: the count of curricula sent to the second pass,
  and of those whose real page arrived.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a run where 9% of first requests get the access check page
  at random, at least 75% of those curricula end the run with their real
  page. Today the figure is 0%.
- **SC-002**: The second pass adds at most the pause plus about 10 s per
  retried curriculum and worker, about 11 min for the 38 of the run of
  2026-11-03. The Lattes download stays inside its 90 min limit.
- **SC-003**: With the portal serving only the access check page, the run
  sends no request after the stop. When the stop triggers in the first pass,
  the second pass sends none at all.
- **SC-004**: With a healthy portal, or with the second pass turned off, the
  exports are identical to those of the same run without this feature.
- **SC-005**: Zero cached copies are lost or replaced by an access check
  page because of the second pass.
- **SC-006**: The downloads line alone tells how many curricula were retried
  and recovered in the run.

## Assumptions

- Spec 024 is in this branch: `028-lattes-captcha-retry` starts from
  `027-portal-early-stop`.
- The access check page falls on random requests, not on particular people
  (evidence in Context). If it depends on how many requests one IP sends in a
  short time, the pause and the single worker help. Either way, the second
  pass costs one request per rejected curriculum and recovers fewer of them;
  SC-001 is then a reference, not a gate.
- "A value of 0 turns the second pass off" applies to the number of
  second-pass workers. A pause of 0 starts the second pass right away, which
  is useful in tests.
- Defaults are 5 min of pause and 1 worker. The run from scratch of
  2026-11-03 asked at a steady 17 to 22 curricula per minute with 3 workers,
  with no rise in rejections towards the end. So a short pause and a slower
  pace are a reasonable first guess. They can be tuned once a real run shows
  the recovered count.
- Only one second try per curriculum and per run. More tries would add
  pressure on the portal for little gain: next week's run tries again
  anyway.
- The CNPq portal has no access check page. This spec is about Lattes only.
- Validation:
  1. tests with fake portals (rejects then serves, always rejects, healthy,
     turned off, stop in the first pass, stop in the second pass);
  2. a local run, measuring the retried and recovered counts;
  3. a dispatch on the fork.
  Nothing goes upstream before the maintainer's manager validates.
