# Feature Specification: Reuse the researcher index in CNPq member sync

**Feature Branch**: `011-cnpq-sync-index-reuse`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Eliminate two redundant full-table reads inside the CNPq group-sync loop: the researcher lookup repeated once per group, and the role lookup repeated once per member."

## Context

The weekly pipeline synchronizes CNPq research group membership across 351
groups. For every group, the sync logic asks the researcher registry the same
question — "who exists?" — expecting the same answer every time within a
single run. It asks it again for every group, expecting it to somehow be
different.

### What measurement showed

Measured against the current database (6,853 researchers, 351 CNPq groups,
19,677 team members), on 2026-09-01:

| What | Cost | Called |
|---|---|---|
| Full researcher lookup | 8.81 s | once per group (351×) |
| Lightweight researcher index (existing) | 0.03 s | — |
| Full role lookup | milliseconds | once per member (~19,677×) |

The full researcher lookup is expensive because the researcher record eagerly
loads four unrelated collections (knowledge areas, articles, productions,
emails) for every row, producing far more data than the sync logic ever reads.
351 groups × 8.81 s ≈ **51.5 minutes per weekly run**, spent re-answering an
unchanging question.

This is not new: the same pattern was found and fixed in the Lattes ingestion
phases in an earlier feature (007-researcher-lookup-index), which introduced a
lightweight index precisely for this purpose. It measures at 0.03 s for the
same 6,853 researchers — a 343× difference — and the function that consumes
the researcher list already accepts either the lightweight index or the full
records, unchanged, because that compatibility was built for exactly this
kind of reuse.

The role lookup is the same shape of problem at a smaller scale: an
11-row table, asked about once per member instead of once per group. The
absolute cost is small (seconds, not minutes), but it is the same repeated
question, and fixing it costs nothing once the surrounding loop is already
being touched.

### Why this matters beyond the time saved

The cost of the researcher lookup grows with the size of the researcher
table, not with the number of groups. In August, the same call cost 8.5 s
against 1,060 researchers; today it costs 8.81 s against 6,853 — the
institute's researcher registry more than sextupled since. Every week the
registry grows, this specific waste grows with it, silently, until the CNPq
phase eventually challenges its own timeout again — the same failure mode
this project has already hit once for a different phase (documented in the
project backlog as TD-007).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - CNPq sync stops re-reading the researcher registry per group (Priority: P1)

As the person responsible for the weekly run, I want the CNPq group-member
sync to ask "who exists?" once per run instead of once per group, so that the
phase's duration stops being dominated by an answer that never changes
mid-run, and so it stops growing every time the researcher registry grows.

**Why this priority**: this is the change itself, and it accounts for the
overwhelming majority of the measured waste (51.5 of roughly 51.6 minutes).

**Independent Test**: run the CNPq sync phase against the current database and
confirm the researcher registry is read once, not once per group, while the
set of researchers matched or created for each member is unchanged.

**Acceptance Scenarios**:

1. **Given** 351 groups to synchronize, **When** the sync runs, **Then** the
   full researcher registry is read at most once for the entire run.
2. **Given** a member whose name already exists in the registry, **When**
   that member is synchronized, **Then** the same existing researcher is
   matched as before the change.
3. **Given** a member whose name does not yet exist, **When** that member is
   synchronized, **Then** a new researcher is created, and a later member in
   the same run with the same name finds that newly created researcher
   instead of creating a duplicate.

---

### User Story 2 - Role lookup stops repeating per member (Priority: P2)

As the person responsible for the weekly run, I want the role registry to be
read once per group instead of once per member, so the same unnecessary
repetition does not linger in the same function after the larger waste is
fixed.

**Why this priority**: correct and cheap to fix alongside User Story 1, but
its cost is a few seconds total — it does not change wall-clock duration in
any way a person would notice.

**Independent Test**: run the CNPq sync phase and confirm the role registry is
read once per group, while every member still ends up with the same role
assignment as before the change.

**Acceptance Scenarios**:

1. **Given** a group with multiple members, **When** the group is
   synchronized, **Then** the role registry is read once for that group, not
   once per member.
2. **Given** a member whose role name matches an existing role
   case-insensitively, **When** that member is synchronized, **Then** the
   same existing role is assigned as before the change.

### Edge Cases

- **Researcher created mid-run by a different group**: the newly created
  researcher must be discoverable by subsequent groups in the same run,
  without re-reading the full registry.
- **Two members with the same name in different groups, neither pre-existing**:
  the first must create a researcher; the second must find and reuse it, not
  create a duplicate — the exact failure mode a prior related fix
  (008-guard-participant-merge) protects against for a different loader.
- **Role name differing only by case** (e.g., "pesquisador" vs "Pesquisador"):
  must continue to match the same existing role.
- **Empty or newly created database** (no researchers, no roles yet): the sync
  must still complete, creating researchers and roles as needed, without
  assuming a non-empty starting registry.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The CNPq group-member sync MUST read the full researcher
  registry at most once per phase execution, regardless of the number of
  groups processed.
- **FR-002**: The CNPq group-member sync MUST read the full role registry at
  most once per group processed, regardless of the number of members in that
  group.
- **FR-003**: A researcher created while processing one group MUST be
  discoverable, without duplication, by subsequently processed groups within
  the same run.
- **FR-004**: The set of researchers matched or created, and the set of roles
  assigned, MUST be identical to the current behavior for the same input data
  — this is a performance change, not a behavior change.
- **FR-005**: The change MUST NOT alter the researcher or role matching rules
  themselves (name comparison, case sensitivity, tie-breaking) — only how
  often the underlying registries are read.
- **FR-006**: Documentation produced for this feature MUST be written in
  English.

### Key Entities

- **Researcher registry snapshot**: the set of known researchers, read once
  per phase run instead of once per group, and kept current within the run as
  new researchers are created.
- **Role registry snapshot**: the set of known roles, read once per group
  instead of once per group member.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The CNPq group-member sync phase completes with the researcher
  registry read **1 time** per run, verified by direct observation of the
  running phase (not inferred from duration alone).
- **SC-002**: The time spent reading the researcher registry across a full run
  drops from approximately 51.5 minutes to under 1 minute, measured against
  the same database used for the original measurement.
- **SC-003**: A full weekly pipeline run, executed after the change, produces
  the same researcher count, the same role count, and the same team
  membership count as a run executed immediately before the change, on
  otherwise-identical input data — no data loss, no duplication.
- **SC-004**: 100% of the project's existing automated tests continue to pass
  after the change, with no reduction in what they verify.

## Assumptions

- The lightweight researcher index and its integration contract already exist
  and are proven in production (feature 007); this feature applies that
  existing mechanism to a new call site rather than designing a new one.
- No new database schema, migration, or external dependency is required.
- The comparison in SC-003 is made against a database snapshot taken
  immediately before the change is applied, running the same weekly pipeline
  end to end, since the CNPq source data itself can drift between runs
  independent of any code change.
