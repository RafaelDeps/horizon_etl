# Feature Specification: Team Lookup Index for the Lattes Ingestion Phases

**Feature Branch**: `018-team-lookup-index`

**Created**: 2026-10-22

**Status**: Draft

**Input**: User description: "Eliminate the per-record full-table team lookup that makes the Lattes phases of the weekly pipeline grow quadratically, so `make weekly-flows` fits comfortably inside the GitHub Actions 6-hour job limit and still runs locally."

## Context

The weekly pipeline (`make weekly-flows`) now ingests about 435 Lattes CVs. The
last full local run (2026-10-21 23:28 → 2026-10-22 07:32) took **8 h 04 min**.
The run before it never finished `lattes_advisorships`: the phase was killed by
its 3-hour ceiling around CV 360 of 435. Measurements are recorded in
`docs/reports/2026-10-22-weekly-runtime-and-language-study.md`.

| Phase | Records processed | Duration | Share of run |
|---|---:|---:|---:|
| `lattes_advisorships` | 9 706 | 252 min | 52% |
| `lattes_projects` | 3 371 | 81 min | 17% |
| **Both** | **13 077** | **333 min** | **69%** |

### What the measurement showed

Profiling the real phase code against copies of the database showed:

- **One step dominates.** "Find the team for this initiative, or create it" is
  76% of `lattes_projects` and 84% of `lattes_advisorships`.
- **It re-reads every team for every record.** To answer that question for a
  single record, the step reads the whole team register with every team's
  members, each member's person and each member's role. At ~10 600 teams that
  materialises ~3.7 million in-memory objects and takes 1.5–1.9 s. The same team
  identifiers and names alone can be read in ~0.18 s.
- **It re-normalises every name.** After the read, each existing team name is
  normalised again and compared with the requested one.
- **The cost grows with records × teams.** The phases create teams as they run,
  so each CV costs more than the one before: 0.22 → 0.45 min per CV within one
  run. Full-scale figures match: 1.44 s per record in `lattes_projects` and
  1.56 s per record in `lattes_advisorships`.
- **A one-time lookup gives identical answers.** Built from identifiers and
  normalised names, it answered all 361 lookups of a benchmark sample in 0.47 s
  in total, with exactly the same matches (357/361) as the current step.

A second, smaller hotspot is in `lattes_advisorships`. It builds a fresh project
loader for every CV, and each new loader re-reads all initiatives and all persons
(~5.8 s per CV under the profiler). `lattes_projects` already reuses a single
loader for the whole phase.

This is the same failure pattern that `specs/007-researcher-lookup-index` fixed
for researchers: a whole register is re-read for each record, to answer a
question whose answer barely changes between records.

### Operational consequence

GitHub-hosted runners stop any job after 6 hours, and the weekly workflow sets
300 minutes. At 8 h 04 min the weekly run cannot finish in CI at all, and it
gets slower as the institute's data grows.

## Clarifications

### Session 2026-10-22

- Q: What reference proves the entities produced are unchanged (SC-004 / FR-009)? → A: Controlled replay. Start from one database snapshot taken before the Lattes phases, use the same Lattes JSON files, run `lattes_projects` + `lattes_advisorships` with the old and the new code, and compare the results.
- Q: Should the team lookup apply to every use of team matching, or only to the Lattes phases? → A: Every use. Team matching always goes through the lookup, including the `sigpesq` phase (its project and advisorship loaders). The controlled replay covers that phase too.
- Q: What should the team lookup log? → A: A per-phase summary. At the end of each phase that uses the lookup, one INFO line with teams loaded, hits, creations, incremental refreshes and teams found by those refreshes. In the Lattes phases, each CV's processing duration at DEBUG level.
- Q: The weekly log never shows DEBUG (`dgp_cnpq_lib` resets loguru to INFO at import), so at which level is the per-CV duration logged? → A: INFO. This supersedes "DEBUG" in the previous answer: one INFO line per CV (~870 per run), still no per-lookup lines.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Team matching stops re-reading the whole team register per record (Priority: P1)

As the maintainer who runs the weekly pipeline, I want team matching to consult
a lookup built once per phase in every phase that uses it (`sigpesq`,
`lattes_projects`, `lattes_advisorships`). The Lattes phases should then take
minutes instead of hours, and their per-CV cost should stop growing as the run
creates teams.

**Why this priority**: This single step accounts for most of the 333 minutes
spent in the two Lattes phases. Without it, the weekly run cannot fit in a CI
job, whatever else is optimised.

**Independent Test**: Run `lattes_projects` and `lattes_advisorships` against
the same inputs before and after the change. Phase durations must drop below the
targets in Success Criteria, and the resulting teams, memberships and
initiative–team links must be identical.

**Acceptance Scenarios**:

1. **Given** a database with existing teams, **When** a record asks for a team
   whose name exactly equals an existing team's name, **Then** that existing team
   is returned and no team is created.
2. **Given** an existing team named "Conecta FAPES", **When** a record asks for
   "Conecta Fapes", **Then** that team is returned (match after normalisation)
   and no team is created.
3. **Given** two existing teams whose names normalise to the same value,
   **When** a record asks for that name, **Then** the team with the lowest
   database identifier is returned, as today.
4. **Given** no existing team matches, **When** a record asks for a team,
   **Then** a team is created with the same name and description as today. A
   later record in the same phase asking for the same (or an equivalent) name
   receives that new team instead of creating a second one.
5. **Given** a team was created during the phase by code other than the team
   matching step, **When** a record asks for a matching name, **Then** that team
   is found and no duplicate is created.
6. **Given** team creation fails for a record, **When** a later record asks for
   the same name, **Then** the failure did not leave a phantom entry, and creation
   is attempted again rather than returning a team that does not exist.

---

### User Story 2 - Advisorships phase reuses one project loader for all CVs (Priority: P2)

As the maintainer, I want `lattes_advisorships` to prepare its initiative and
person lookups once per phase, as `lattes_projects` already does, rather than
once per CV.

**Why this priority**: After Story 1 this is the largest repeated cost left in
the advisorships phase (~435 rebuilds per run). It is secondary because Story 1
alone removes most of the phase's time.

**Independent Test**: Run the advisorships phase over several CVs and confirm
the project loader is built once. Each CV must still be ingested with its own
supervisor-specific advisorship mapping, and the advisorships, teams and
memberships produced must be identical to the current behaviour.

**Acceptance Scenarios**:

1. **Given** N CV files, **When** the advisorships phase runs, **Then** the
   project loader is built once and each CV's advisorships still use that CV's
   own supervisor-specific mapping.
2. **Given** an advisorship created while processing one CV, **When** a later CV
   in the same phase references the same advisorship or person, **Then** the
   existing record is matched instead of duplicated.

---

### User Story 3 - The weekly run fits in CI (Priority: P3)

As the maintainer, I want a full `make weekly-flows` to finish well within the
CI job limit, so the GitHub Actions workflow can complete again. It must still
run unchanged on my machine.

**Why this priority**: This is the end goal, and it follows from Stories 1 and 2.
It is verified by a full run rather than built separately.

**Independent Test**: Run `make weekly-flows` locally on the current inputs and
compare the phase durations and entity counts with the 2026-10-22 baseline.

**Acceptance Scenarios**:

1. **Given** the current ~435 CVs, **When** `make weekly-flows` runs locally,
   **Then** every phase exits 0 and both Lattes phases meet their time targets.
2. **Given** the GitHub Actions weekly workflow (clean checkout, fresh database),
   **When** it runs with this change, **Then** the Lattes phases behave exactly
   as they do locally, with no dependency on state left by a previous run.

### Edge Cases

- **Empty database:** the first run against a freshly created database has no
  teams. The lookup starts empty, and every team is created and then found by
  later records.
- **No database session:** tests and isolated callers may use a team controller
  without a database session. Team matching must still work, falling back to a
  single full read to build the lookup.
- **Equivalent names in one phase:** two CVs may produce names that differ only
  in case, accents or punctuation (for example "PROJETO X" and "Projeto X").
  They must resolve to one team, as they do today.
- **Missing or empty name:** team matching keeps today's behaviour: nothing new
  is matched or created that the current step would not match or create.
- **Teams created outside the matching step:** other ingestion code in the same
  process (for example, project loaders built for other purposes) may create
  teams. The lookup must notice them before creating a new team on a miss.
- **Failed creation:** a failure or rollback must not leave an entry that points
  to a team that does not exist.
- **Large registers:** the approach must keep working as teams grow well beyond
  today's ~11 000. Per-record cost must not grow with the register size.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Team matching MUST NOT read the full team register (teams with
  their members, persons and roles) once per record, in any phase that uses it.
  Those phases are `sigpesq` (project and advisorship loaders),
  `lattes_projects` and `lattes_advisorships`. Only one implementation of team
  matching may exist; no phase may switch the lookup off. Any full read of team
  identifiers and names MUST happen at most once per team synchroniser lifetime.
- **FR-002**: The lookup MUST contain only what matching needs: each team's
  identifier and name. It MUST be keyed by the same name normalisation used
  today, so exactly the same names match.
- **FR-003**: When several existing teams share a normalised name, the lookup
  MUST resolve to the team with the lowest database identifier, which is what
  the current step returns.
- **FR-004**: On a miss, the system MUST check for teams created since the
  lookup was last refreshed (by any code in the same process) before creating a
  team. That check MUST read only the newer teams, not the whole register.
- **FR-005**: When a team is created, it MUST be added to the lookup so later
  records in the same phase find it. If creation fails, the lookup MUST stay
  unchanged.
- **FR-006**: The value returned to callers MUST keep working for both current
  callers (creating an initiative's team and adding members to an initiative's
  team) and for member synchronisation, with no change to those callers'
  behaviour. A lightweight reference carrying the team identifier and name is
  acceptable.
- **FR-007**: Without a database session, the system MUST build the lookup from
  a single full read through the team controller. Existing tests that use a
  mocked team controller MUST keep passing unchanged.
- **FR-008**: `lattes_advisorships` MUST build one project loader per phase run
  and reuse it across all CVs. Each CV MUST still be ingested with its own
  supervisor-specific advisorship mapping.
- **FR-009**: For the same inputs, the set of initiatives, teams, team
  memberships, initiative–team links, advisorships and persons produced MUST be
  the same as before the change. The lookup MUST NOT introduce duplicate teams,
  within one CV or across CVs of the same phase.
- **FR-010**: All changes MUST live in this repository's own code and tests. No
  external library (`eo_lib`, `research_domain`, `libbase` or others) may be
  modified.
- **FR-011**: The change MUST work identically in the GitHub Actions weekly
  workflow (clean checkout, fresh database each run) and in local runs. It MUST
  NOT depend on state persisted between runs.
- **FR-012**: Automated tests MUST cover:
  - a hit by exact name;
  - a hit by normalised name;
  - lowest-identifier tie-breaking;
  - creation on a miss, with the new team found by a later lookup;
  - a team created outside the synchronizer being found instead of duplicated;
  - a failed creation leaving the lookup unchanged;
  - the advisorships phase building only one project loader per run.
- **FR-013**: At the end of each phase that uses team matching (`sigpesq`,
  `lattes_projects`, `lattes_advisorships`), the system MUST log one INFO-level
  summary line with:
  - teams loaded into the lookup;
  - lookups answered from it (hits);
  - teams created;
  - incremental refreshes performed (FR-004);
  - teams those refreshes found.

  No per-lookup log lines may be added.
- **FR-014**: In `lattes_projects` and `lattes_advisorships`, the system MUST log
  each CV's processing duration at INFO level, identified by its position in
  the phase and its Lattes ID (not by the file name, which embeds the person's
  name). INFO is required because the process-wide log threshold is INFO in
  every run, so DEBUG lines never reach the weekly log. This lets SC-003 be
  checked from the default run log alone.

### Key Entities

- **Team**: a named group attached to an initiative (project or advisorship).
  Identified by a database identifier, matched by name. Has memberships, but
  matching does not need them.
- **Team lookup**: a per-phase, in-memory view of the team register that maps
  each normalised team name to the earliest team carrying it. It also records
  the highest team identifier already seen, so newer teams can be picked up.
- **Team reference**: what team matching returns. At minimum the team's
  identifier and name, which is everything current callers use.
- **Project loader**: the component that ingests a batch of project or
  advisorship records. It holds lookups of existing initiatives and persons that
  should be prepared once per phase.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a full local `make weekly-flows` with the current ~435 CVs,
  `lattes_projects` finishes in under 20 minutes (baseline: 81 min) and exits 0.
- **SC-002**: On the same run, `lattes_advisorships` finishes in under 20
  minutes (baseline: 252 min) and exits 0.
- **SC-003**: In `lattes_advisorships`, the average processing time of the last
  50 CVs is no more than 1.5× that of the first 50 CVs, measured from the
  per-CV durations logged under FR-014. Baseline: about 2× within
  one run, and still rising.
- **SC-004**: In a controlled replay, the old and new code produce identical
  results. The replay starts from the same database snapshot and the same source
  files, then runs the affected phases once with each version:
  - `sigpesq`: from an empty, freshly initialised database, using the same
    SigPesq raw files;
  - `lattes_projects` followed by `lattes_advisorships`: from a snapshot taken
    just before `lattes_projects`, using the same Lattes JSON files.

  Identical means:
  - the same counts of teams, team memberships, initiatives, initiative–team
    links, advisorships and persons;
  - the same set of (initiative name, team name) links and (team name, person
    name, role) memberships.

  Every difference must be explained and documented. A full `make weekly-flows`
  is not used for this check, because a full run re-downloads its sources and
  changes the inputs.
- **SC-005**: The full weekly run on the same machine completes in under half of
  the 2026-10-22 baseline (8 h 04 min). This leaves room for the remaining work
  (outside this feature) to bring it under the 6-hour CI limit with margin.
- **SC-006**: The whole existing automated test suite passes, plus the new tests
  listed in FR-012.

## Assumptions

- The CNPq phase (124 min in the baseline) is out of scope. Its concurrency or
  crawler replacement is separate work, so this feature alone is not expected to
  bring the total run under 6 hours. SC-005 reflects that.
- The phase ceilings were temporarily multiplied by 10 in
  `src/flows/pipelines/weekly_orchestrator.py`. They are not changed by this
  feature; revisiting them is a follow-up once new durations are measured.
- SigPesq collection (downloads from the portal) stays sequential and unchanged.
  Only the persistence step of the `sigpesq` phase is affected, because its
  project and advisorship loaders use the same team matching.
- No migration to another language is part of this work.
- During a phase, teams are only created by code running in the same process, so
  checking for newer team identifiers is enough to see them. No other process
  writes teams to the same database concurrently.
- The name normalisation used today (case, accents and punctuation folded,
  whitespace collapsed) is the correct equivalence and is kept unchanged.
- The 2026-10-22 run (`logs/weekly_run2_20261021.log`) is the baseline for
  durations (SC-001, SC-002, SC-003, SC-005). Equivalence of the produced
  entities (SC-004) is proven by the controlled replay, not by comparing runs
  made on different days.
