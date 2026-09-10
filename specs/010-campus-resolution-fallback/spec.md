# Feature Specification: Campus Resolution — SigPesq Execution Campus + Advisorship Fallback

**Feature Branch**: `010-campus-resolution-fallback`

**Created**: 2026-09-03

**Status**: Draft

**Input**: User description: "Widen campus resolution in the canonical export to reduce the 31.4% of exported researchers with `campus: null`, through two complementary changes: (A) persist the SigPesq execution campus so it survives even when the project has no research group, and (B) add an advisorship-supervisor fallback tier to the export campus resolver."

## Context

A person has no campus column of their own. Campus is attributed at export time by
the campus resolver, which today derives a person's campus from a single signal:
membership in a research group that has a campus. Everyone outside a research
group — scholarship students, project coordinators, Lattes-only profiles — is
exported with `campus: null`.

Measured on the current database (`db/horizon.db`) and the current canonical
export:

- 9,626 researchers exported, **3,018 with `campus: null` (31.4%)**.
- 6,608 people are covered by the research-group signal.
- 6,338 advisorship membership rows exist, with clean roles (`Supervisor` and
  `Student`, 3,169 each). **1,936 people** who have no campus today take part in
  an advisorship whose `Supervisor` does have a resolved campus.
- Of 3,169 advisorships, **587 come from SigPesq** and 2,742 from Lattes.
- The SigPesq source reports carry the campus on every row: the research-project
  report has `CampusExecucao` filled on 102/102 rows; the advisorship reports have
  `CampusExecucao` on 115/115 and `CampusOrientador` on 115/115. A separate
  student `Campus` column is filled on 94/115 rows and arrives dirty
  (`"Serra"`, `"Campus Serra"`, `"serra"`, `"Serra "`).

That campus value is already read by the SigPesq mapping strategies under the
`campus_name` key, but it is consumed only to attribute a campus to a research
group. When a SigPesq project or advisorship has no research group, the campus
that the source stated explicitly is **discarded**.

This feature makes that source-stated campus survive ingestion, and adds a
last-resort inference for people whose only institutional link is an advisorship.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Scholarship student gets a campus from their supervisor (Priority: P1)

A person appears in the canonical export only because they are the student in an
advisorship. They belong to no research group, so today they are exported with no
campus and disappear from every campus-filtered view in the dashboard. Their
supervisor, however, is a known researcher with a resolved campus. The export
should attribute the supervisor's campus to the student, because the advisorship
is institutionally anchored where the supervisor works.

**Why this priority**: It is the single largest measured gain (~1,936 people) and
depends on data already present in the database, so it delivers value on its own
without any ingestion or schema change.

**Independent Test**: Run the canonical export against the current database and
compare the count of researchers with `campus: null` before and after. The count
must drop by roughly 1,900 without any re-ingestion of sources.

**Acceptance Scenarios**:

1. **Given** a person with no research-group membership who is the `Student` in an
   advisorship whose `Supervisor` resolves to campus "Serra", **When** the
   canonical export runs, **Then** that person is exported with campus "Serra".
2. **Given** a person who already resolves to campus "Vitória" through a research
   group and who is the `Student` in an advisorship supervised by someone from
   "Serra", **When** the canonical export runs, **Then** that person is still
   exported with campus "Vitória", because direct evidence outranks the
   supervisor inference.
3. **Given** a person whose only advisorship has no `Supervisor` member, or whose
   supervisor has no resolved campus, **When** the canonical export runs,
   **Then** that person is exported with `campus: null` — the feature never
   invents a campus.

---

### User Story 2 - Project and advisorship keep the campus the source stated (Priority: P1)

A SigPesq research project is registered with an execution campus but has no
registered research group. Today that project, its coordinator, and its
participants are all exported with no campus even though the source report states
the campus explicitly on every row. The execution campus should be persisted at
ingestion time and used directly by the export, independently of research groups.

**Why this priority**: It is the only change that produces *authoritative* campus
data rather than inference, and it is what allows the participants of
group-less projects to inherit a campus at all.

**Independent Test**: Re-ingest the SigPesq project and advisorship reports and
verify that every initiative created from a row with `CampusExecucao` carries a
campus, including initiatives whose row has no `GrupoPesquisa`; then confirm those
initiatives and their participants export with that campus.

**Acceptance Scenarios**:

1. **Given** a SigPesq project row with `CampusExecucao` = "Presidente Kennedy"
   and an empty `GrupoPesquisa`, **When** the project is ingested, **Then** the
   resulting initiative is linked to the "Presidente Kennedy" campus, and **When**
   the canonical export runs, **Then** the initiative and the people on its team
   are exported with that campus.
2. **Given** a SigPesq advisorship row with `CampusExecucao` = "Alegre", **When**
   the advisorship is ingested and exported, **Then** the advisorship carries
   campus "Alegre" instead of depending on the parent project's research group.
3. **Given** two rows naming the same campus with different spellings
   (`"Serra"`, `"Campus Serra"`, `"serra"`, `"Serra "`), **When** they are
   ingested, **Then** both resolve to the same single campus record, with no
   duplicate campus created.
4. **Given** a row whose campus name does not match any known campus and cannot be
   created, **When** it is ingested, **Then** ingestion completes normally and the
   record is simply left without a campus.

---

### User Story 3 - A person active in more than one campus resolves predictably (Priority: P2)

A researcher leads a group at one campus, coordinates a project executed at
another, and supervises students at a third. The export must pick one campus
deterministically and by a stated rule, rather than by whichever query ran last.

**Why this priority**: It does not add newly-covered people, but it protects the
correctness of people who already have a campus once new evidence sources start
competing with the existing one.

**Independent Test**: Construct a person with conflicting evidence and confirm the
exported campus matches the documented precedence and weighting, and that
re-running the export yields the same answer.

**Acceptance Scenarios**:

1. **Given** a person with direct evidence (research group and/or source-stated
   execution campus) pointing at campus A and supervisor-inferred evidence
   pointing at campus B, **When** the export runs, **Then** campus A is chosen.
2. **Given** a person whose direct evidence points at campus A twice and campus B
   once, **When** the export runs, **Then** campus A is chosen by weight.
3. **Given** the same database exported twice with no changes in between,
   **When** both exports are compared, **Then** every person's campus is
   identical.

---

### Edge Cases

- An advisorship lists more than one `Supervisor`, each at a different campus:
  each supervisor contributes evidence, and the weighted count decides; a tie is
  broken deterministically rather than randomly.
- A chain of inference must not form: a person who only got their campus *from* a
  supervisor must not then act as a supervisor-source for someone else. Inference
  is computed from directly-evidenced campuses only, in a single pass.
- A supervisor who has no campus contributes nothing; the student stays `null`
  rather than falling through to a default campus.
- Campus names arrive with surrounding whitespace, differing case, accents, or a
  redundant "Campus " prefix, and must not create duplicate campus records.
- A cancelled advisorship still carries a legitimate institutional link; it is
  treated like any other for campus purposes.
- An initiative whose research group campus disagrees with the source-stated
  execution campus: both are direct evidence and compete by weight; neither is
  silently dropped.
- People with genuinely no institutional evidence remain `null` — the export must
  never substitute a placeholder or a real unit such as "Reitoria" for
  "unknown".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The ingestion of SigPesq research projects MUST persist the row's
  stated execution campus as an attribute of the resulting initiative, regardless
  of whether the row names a research group.
- **FR-002**: The ingestion of SigPesq advisorships MUST persist the row's stated
  execution campus as an attribute of the resulting advisorship, regardless of
  whether a parent project or research group is present.
- **FR-003**: Campus names taken from source rows MUST be normalized before
  lookup so that variations in case, surrounding whitespace, accents, and a
  leading "Campus " prefix resolve to the same campus record, reusing the campus
  resolution behaviour already used when attributing campuses to research groups.
- **FR-004**: A source row whose campus cannot be resolved MUST NOT fail the
  ingestion of that row; the record is persisted without a campus and the
  condition is logged.
- **FR-005**: The export campus resolver MUST treat the persisted execution
  campus of an initiative or advisorship as direct evidence for that initiative
  or advisorship, and for the people linked to it, at the same level of authority
  as research-group membership.
- **FR-006**: The export campus resolver MUST add a final fallback tier in which
  a person with no directly-evidenced campus inherits the campus of the
  `Supervisor` members of the advisorships they take part in.
- **FR-007**: The supervisor fallback MUST be applied only to people who have no
  direct evidence of their own; direct evidence MUST always win over inference.
- **FR-008**: The supervisor fallback MUST be computed from directly-evidenced
  campuses only, so that an inferred campus can never be the source of another
  inference.
- **FR-009**: When several campuses compete within the same level of authority,
  the resolver MUST continue to select the campus by weighted count, as it does
  today, and MUST break ties deterministically.
- **FR-010**: A person, initiative, or advisorship with no usable evidence MUST
  continue to be exported with a null campus; no placeholder, default, or real
  organizational unit may be substituted for an unknown campus.
- **FR-011**: The export MUST remain runnable against an existing database with no
  re-ingestion: the supervisor fallback depends only on data already stored.
- **FR-012**: The change MUST NOT alter the exported campus of any person who
  already resolves to a campus today, except where new direct evidence
  legitimately outweighs the existing evidence.
- **FR-013**: The campus-scoped export path, which filters exports to a single
  campus, MUST keep working and MUST see the newly attributed campuses.

### Key Entities *(include if feature involves data)*

- **Campus**: An organizational unit of the institution (23 exist today, e.g.
  Serra, Vitória, Alegre, Vila Velha). Identified by name; the same campus may be
  named inconsistently across source rows.
- **Initiative**: A research project or advisorship. Currently has no campus of
  its own; this feature gives it one, sourced from the report row.
- **Advisorship**: An initiative linking a supervisor and a student, with member
  roles `Supervisor` and `Student`.
- **Person**: The exported researcher. Has no campus column; the campus is
  attributed at export time from the evidence available.
- **Campus evidence**: A (person, campus) observation with an authority level
  (direct or inferred) and a weight, aggregated to select one primary campus.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The share of exported researchers with no campus falls from 31.4%
  to at most 12%, on the same database, with no source re-ingestion required for
  the supervisor-fallback portion of the gain.
- **SC-002**: At least 1,900 people who are exported with no campus today are
  exported with a campus after the change.
- **SC-003**: Every SigPesq project and advisorship row that states an execution
  campus produces a record carrying that campus — 100% of rows that state one,
  including rows with no research group.
- **SC-004**: No person who has a campus today is exported with no campus after
  the change.
- **SC-005**: Exporting the same unchanged database twice produces identical
  campus attributions.
- **SC-006**: No campus record is duplicated as a result of spelling variations in
  the source reports; the campus count stays at its current value unless a
  genuinely new campus appears in the sources.
- **SC-007**: The weekly pipeline completes within its existing time budget, with
  no phase newly exceeding its timeout.

## Out of Scope

These were evaluated against the current data and deliberately excluded:

- **Co-authorship network fallback**: measured gain is 4 additional people, with a
  high risk of attributing an external co-author's campus to a researcher.
- **SUAP/SIAPE personnel integration**: `persons.identification_id` is 100% empty
  (0 of 9,806) and all 738 stored e-mails are anonymized to the `anon.lgpd`
  domain by the LGPD step, so neither join key exists; the dataset also does not
  exist inside the repository.
- **Forcing deduplication before export**: already in place in the weekly
  orchestrator, and the measured residual gain is zero (3 duplicate groups, 6
  people, 0 additional campuses).
- **"Reitoria" or "Multicampi" as an ambiguity label**: Reitoria is a real
  organizational unit, so using it for "unknown" would fabricate data. Ambiguity
  is resolved by weight; genuine absence of evidence stays null.
- **Adding a campus column to persons/researchers**: campus stays a derived,
  export-time attribution.

## Assumptions

- Campus continues to be modelled as an organizational unit, and the existing
  campus resolution behaviour used for research groups is the correct place to
  resolve a campus name to a campus record.
- In an advisorship, the supervisor's campus is the better proxy for the
  student's campus than the student's own self-declared campus text, which is
  present on only 94 of 115 sampled rows and arrives unnormalized.
- The `Supervisor` / `Student` role names in advisorship membership remain the
  stable role vocabulary.
- The dashboard consuming the export treats a null campus as "unknown" and does
  not require a sentinel value.
- The SigPesq report column names (`CampusExecucao`, `CampusOrientador`,
  `Campus`) remain stable; they are already read today, so this feature does not
  introduce a new dependency on them.
- The measured figures in this document reflect a database whose most recent
  ingestion was scoped to the Serra campus; absolute counts will grow as other
  campuses are ingested, while the relative behaviour stays the same.
