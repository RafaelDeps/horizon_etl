# Feature Specification: Reliable Participant Deduplication

**Feature Branch**: `008-guard-participant-merge`

**Created**: 2026-08-28

**Status**: Draft

**Input**: User description: "The dashboard built from the latest weekly pipeline
run shows duplicated participants (e.g. the student 'Israel Magalhães do Carmo'
appears twice). Only one of the duplicate records carries initiative data, and
that data looks incomplete. Redesign participant deduplication to use a
reliable identity criterion in which the participant's name is an important
matching signal, merging complementary initiative data across duplicates
instead of arbitrarily keeping one record."

## Context

The weekly pipeline ingests participants into a single catalog from many
independent sources: SigPesq project and advisorship spreadsheets, Lattes
curricula, research-group spreadsheets, and CNPq groups. Each source rebuilds
identity on its own, through its own matching path, so the same physical person
can become more than one participant record.

That is not hypothetical. In the 2026-08-28 weekly export consumed by the
dashboard, the student **Israel Magalhães do Carmo** appears twice. One record
carries five initiatives — advisorships and research projects where the person
acts as Student — while the other carries **no initiative at all**, holding only
a membership in the research group "Núcleo de Estudos em Robótica e Automação".
A full scan of `researchers_canonical.json` (9,738 records) found **176 name
groups holding two or more participant records**, and in every detected pair one
member is data-rich while the other holds none.

### Why the current deduplication is inadequate

Two failure modes combine:

1. **The identity criterion is not reliable.** Participant identity is
   reconstructed source-by-source with a variety of heuristics (exact-name and
   canonical-name matching, fuzzy matching, Lattes-scoring), and the only
   holistic deduplication pass detects duplicates by normalized full name but
   never aggregates the initiative data from the losing record into the winner.
   Nothing guarantees that all records of one person are recognized as one
   person, or that merging preserves both records' data.

2. **Deduplication is a manual, post-hoc step.** It is not part of the weekly
   pipeline, so the exported data the dashboard reads is never deduplicated.
   The duplicated person is simply exported as-is.

### What stays from the previous version of this feature

This feature was originally specified to protect participants from a different
kind of damage: name-based similarity applied to **initiatives** (advisorships),
whose name is the *title of a thesis* that legitimately repeats across the
curricula of advisor and co-advisor with different participants. Matching those
records by normalized title merged 100 advisorships and destroyed 200
participant links. The guard that advisorships never match by normalized title
**remains in force** and is exercised by regression tests — the same rule that
reduced 57 duplicate projects to zero keeps applying to projects only.

This feature deliberately takes name-based identity to the **participant** level
where it belongs: a participant *is* identified by name, unlike an advisorship.
But it must be done safely. The name is an **important signal, never a
sufficient one**: identical normalized names are the starting point of identity,
and the merge only happens when no evidence says the two records are actually
distinct homonyms. When records do belong to one person, their complementary
initiative data is merged, never thrown away.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One participant, many spellings, one record (Priority: P1)

As the data quality owner, I want a participant found in two sources to be
recognized as the same person even when the name is written differently — a
different case, accent, whitespace or particle (`do`/`De`/`DOS`) — so that a
second source does not create a brand-new participant record.

**Why this priority**: This is the identity core of the feature. Without it,
every unreliable comparison path keeps minting duplicates for the same person.

**Independent Test**: Feed two source rows that name the same participant in
different spellings ("Israel Magalhães do Carmo" and "ISRAEL MAGALHAES DE
CARMO") and assert that exactly one participant record exists afterwards.

**Acceptance Scenarios**:

1. **Given** a participant already stored as "Israel Magalhães do Carmo",
   **When** a source row arrives as "ISRAEL MAGALHÃES DO CARMO", **Then** the
   row resolves to the stored participant and no new record is created.
2. **Given** the same participant stored under particle variants ("Gustavo Maia
   De Almeida" vs "Gustavo Maia de Almeida"), **When** the normalized identity
   keys are compared, **Then** they are equal.
3. **Given** a name with punctuation ("Maria-Aparecida Santos!" vs "Maria
   Aparecida Santos"), **When** the normalized identity keys are compared,
   **Then** they are equal.

---

### User Story 2 - Complementary data of a duplicate is merged, never discarded (Priority: P1)

As a dashboard consumer, I want the initiative data spread across two duplicate
records of the same participant to end up in a single record, so that the UI
shows the full history instead of the snapshot that happened to be saved last.

**Why this priority**: This is the observed user-visible defect. The Israel
Magalhães do Carmo pair is exactly this case: one record owns five initiatives,
the other owns none but holds a research-group membership. Keeping only one
record discards the other's data.

**Independent Test**: Consolidate a fixture where record A holds advisorship X
and record B holds project Y plus a research-group membership, then assert the
surviving participant holds X, Y and the research-group membership.

**Acceptance Scenarios**:

1. **Given** two records of the same participant where record A links to
   initiative X and record B links to initiative Y, **When** the group is
   consolidated, **Then** the surviving record links to both X and Y.
2. **Given** the Israel Magalhães do Carmo pair (record with advisorship and
   research-project teams; record with only a research-group membership),
   **When** the export is produced after deduplication, **Then** the dashboard
   shows exactly one participant whose initiative list is the union of both
   records.
3. **Given** two duplicate records that share one identical link (same
   initiative, same role), **When** consolidated, **Then** the shared link
   appears exactly once.

---

### User Story 3 - Simultaneous and same-researcher initiatives are preserved (Priority: P1)

As a data quality owner, I want the deduplication to preserve every initiative a
person is part of, including initiatives that overlap in time and initiatives
that share the same researcher, so that the merge never narrows a person's
history down to a single initiative by mistake.

**Why this priority**: A person legitimately holds several initiatives at once
and across sources. Distinct initiative sets are **not** evidence that two name
records are different people, and identical researchers are **not** evidence
that records are duplicates of each other — either interpretation destroys data.

**Independent Test**: Consolidate a fixture where one person is simultaneously
Student on two advisorships and Researcher on one project, all sharing the same
advisor, and assert that all three initiatives survive the merge.

**Acceptance Scenarios**:

1. **Given** a participant with two simultaneous advisorships under the same
   advisor, **When** two duplicate records that each mention one of the
   advisorships are consolidated, **Then** both advisorships survive.
2. **Given** two records of the same participant that each reference the same
   researcher on different initiatives, **When** consolidated, **Then** all
   initiatives of that researcher's shared work survive.
3. **Given** a participant appearing in a research group and in an advisorship
   at the same time, **When** the records are merged, **Then** both the group
   membership and the advisorship are present in the result.

---

### User Story 4 - Homonyms and conflicting identifiers are never merged (Priority: P1)

As the data quality owner, I want two distinct people who share a normalized
name to remain separate records, explicitly flagged for review, so that a merge
never fuses two separate careers into one.

**Why this priority**: The name is an important signal but not enough. The whole
value of the feature depends on the guard: without it, deduplication is the same
damage the initiative-level guard was created to prevent, just moved to people.

**Independent Test**: Seed two "José da Silva" records with distinct Lattes URLs
and assert that the consolidator keeps both and reports the group as a homonym
candidate that it refused to merge.

**Acceptance Scenarios**:

1. **Given** two records with the same normalized name but distinct Lattes/CNPq
   URLs, **When** deduplication scans them, **Then** they are **not** merged and
   the group is flagged for manual review.
2. **Given** two records with the same normalized name but distinct
   identification IDs, **When** deduplication scans them, **Then** they are
   **not** merged and the group is flagged for manual review.
3. **Given** a participant whose name is only an honorific or junk ("Dr",
   "PROF"), **When** deduplication scans it, **Then** it is flagged and never
   merged with anything.

---

### User Story 5 - The deduplicated catalog is what the dashboard reads (Priority: P2)

As the pipeline operator, I want deduplication to run as part of the weekly
pipeline, before the exports the dashboard consumes, so that a duplicate only
ever shows up in one weekly window, not every week.

**Why this priority**: Fixing the criterion alone leaves the pipeline exporting
pre-consolidation data. The observed defect reappears every run until dedup is
in the pipeline path that produces the dashboard source data.

**Independent Test**: Run the weekly pipeline end-to-end on a fixture with one
known duplicate pair and assert that the exported `researchers_canonical.json`
contains one record for the pair.

**Acceptance Scenarios**:

1. **Given** a database containing the Israel Magalhães do Carmo pair,
   **When** the weekly pipeline runs, **Then** the exported researcher data
   contains exactly one Israel Magalhães do Carmo record with the union of both
   records' links.
2. **Given** the pipeline run above, **When** the exclusion report is read,
   **Then** it lists every refused homonym group with its reason.

### Edge Cases

- **Name present in no index**: a participant name found in no other record is
  unmatched — it stays a separate record. Missing or empty names produce no key,
  no match and no error.
- **No identifiers on either record**: identical normalized name with no Lattes
  URL, no identification ID and no email on either side still means "same
  person" — this is the exact state of the observed pairs. Absence of evidence
  to the contrary is enough; it is blocking identifiers that separate people.
- **Missing/invalid name**: empty, single-token or honorific-only names must not
  match anything and must be flagged instead of merged.
- **Particles and connectors**: particles such as `de`, `da`, `do`, `dos`,
  `das`, `di`, `du`, `del`, `dela`, `e` and `y` must normalize to a single form
  so `De`, `de`, `DO`, `do` compare equal.
- **Punctuation and hyphens**: hyphens, alphanumeric punctuation and stray
  marks become spaces, so `Santos-Junior` and `Santos Júnior` collapse to the
  same key.
- **Honorifics and degree suffixes**: tokens such as `Dr`, `Prof`, `M.Sc.` are
  not part of the person's name. Where the data carries them, their treatment
  must be deterministic and identical across every comparison path.
- **Name changed between records (spouse/adoption/insertions)**: a record that
  legitimately uses a different surname does **not** share a normalized name and
  is therefore not merged automatically; it is only reported as a *candidate*,
  never merged. Keeping the criterion exact-normalized-name avoids inventing
  identity that the data does not support.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST recognize two participant records as the same
  person when their **normalized names are equal** and no strong identifier
  conflicts (distinct Lattes/CNPq URL or distinct identification ID) exist
  between them.
- **FR-002**: The normalized full name MUST be the **primary participant
  identity criterion**; initiative titles, research-group names and fuzzy name
  similarity MUST NOT be used as participant identity evidence.
- **FR-003**: Name normalization MUST be a single, shared function used by every
  participant comparison path, and MUST produce equal keys regardless of letter
  case, accents (diacritics), whitespace, punctuation, hyphens and surname
  particle capitalization.
- **FR-004**: Normalized name equality MUST be exact-key equality, not a fuzzy
  similarity threshold. Fuzzy matching MUST NOT merge participants; it may at
  most suggest candidate groups for review.
- **FR-005**: When two records represent the same person, the system MUST merge
  their initiative data as a **union** — every initiative, advisorship member,
  team membership, research-group membership and researcher-side association
  from the losing record is transferred to the winner unless an identical
  (entity, role) link already exists there. Arbitrary discarding of one
  record's data is forbidden.
- **FR-006**: The system MUST preserve **simultaneous initiatives**: initiatives
  that overlap in time for the same participant remain distinct initiatives
  before and after the merge.
- **FR-007**: The system MUST preserve **initiatives associated with the same
  researcher**: two records that share a researcher carry corroborating
  evidence, and all of that researcher's shared initiatives survive the merge.
- **FR-008**: The system MUST NOT merge a group whose members carry **conflicting
  strong identifiers** (two different Lattes/CNPq URLs or two different
  identification IDs); such groups MUST be flagged for manual review instead.
- **FR-009**: Winner selection MUST prefer the record with strong identifiers
  and more linked data, and MUST be deterministic. Given a tie, the resolution
  MUST pick the record that preserves the most data (or an explicit documented
  tiebreak).
- **FR-010**: Field-level conflicts between duplicates MUST be resolved
  deterministically — the winner's value is preserved, the loser's value is kept
  only when the winner has none — and every conflict MUST be logged or reported.
- **FR-011**: The deduplication step MUST run before the canonical exports are
  produced in the weekly pipeline, and MUST emit an actionable report of what
  was merged and what was refused.
- **FR-012**: The prior initiative guard MUST remain in force and MUST be
  covered by regression tests: advisorships NEVER match another advisorship by
  normalized title, while projects still do.
- **FR-013**: Deduplication MUST be idempotent — running it twice over the same
  catalog changes nothing on the second run.
- **FR-014**: The regression tests MUST run without a database, external service
  or pipeline execution, and conclude in seconds.
- **FR-015**: All exported artifacts continue to comply with the LGPD rollout:
  no real personal data beyond the minimum necessary, and anonymized emails in
  every comparison key and report.

### Key Entities

- **Participant record**: a person linked to initiatives and groups. Two
  participant records may represent the same physical person, which is the
  condition this feature must detect. Persisted as a `Person` (with an optional
  `Researcher` side).
- **Normalized name key**: the product of the shared normalization function on a
  participant's full name — the primary identity key. Case, accents, whitespace,
  punctuation and particles are stripped or canonicalized so that spelling
  variations yield the same key.
- **Strong identifier**: a value that uniquely identifies a person across
  sources and therefore vetoes a merge when it conflicts — Lattes/CNPq URL and
  identification ID (email hashes are treated as corroborating only, because
  they are anonymized at write time).
- **Initiative link**: an association between a participant and an initiative
  (advisorship membership, team membership, project participation) or a research
  group membership. Links are the data that must be unioned, never discarded,
  when records are merged.
- **Deduplication report**: the scan result the pipeline must emit — merged
  groups, refused homonym groups and the reason for each refusal.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After deduplication and export, the dashboard source data contains
  **zero** duplicate participant groups where one record holds initiative data
  and the other holds none. Baseline measured at 176 such groups on
  2026-08-28; the "Israel Magalhães do Carmo" pair is the named exemplar.
- **SC-002**: The initiative counts of every merged participant equal the union
  of the pre-merge records — **no participant loses an initiative or group
  membership during deduplication** (verifiable on the whole export by comparing
  aggregate link counts before and after; for `initiative_persons`,
  `advisorship_members`, `team_members` and research-group memberships).
- **SC-003**: No homonym group is merged: distinct Lattes URLs or identification
  IDs on records sharing a normalized name remain separate and appear in the
  refusal report.
- **SC-004**: Deduplication is reproducible — the same catalog in any order of
  input yields the same winner selection and the same merged result.
- **SC-005**: The new regression tests run in **less than 5 seconds**, with no
  database and no network, and removing or weakening any guard in production
  makes **at least one test fail** (the experiment of the previous version of
  this feature remains mandatory).
- **SC-006**: The prior initiative guard is still enforced: with the code as-is,
  **100% of the new tests pass** and **no existing test changes its result**.

## Assumptions

- The observed duplicate pairs are created during ingestion by independent
  matching paths and re-appear in every weekly run; deduplication must therefore
  run inside the weekly pipeline rather than once by hand.
- The normalized full name, compared by strict equality, is the strongest signal
  common to every source: strong identifiers are either absent or anonymized in
  the majority of records, and the observed duplicates carry none of them.
- Name equality without conflicting identifiers is sufficient to merge: the
  evidence collected (176 pairs, each with a data-rich and a data-empty record)
  shows the false-positive risk of an unguarded merge is lower than the
  continuing damage of duplicated participants.
- The initiative-level guard (advisorships never match by normalized title) is
  prior art that stays; this feature changes participant-level matching only and
  must not weaken that guard.
- A participant with a genuinely different name (e.g. surname change) is out of
  scope for automatic merging — the exact-normalized-name criterion intentionally
  leaves those records separate, matching what the data can actually support.