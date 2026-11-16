# Feature Specification: One advisorship per student when titles repeat

**Feature Branch**: `035-one-advisorship-per-student`

**Created**: 2026-11-11

**Status**: Draft

**Input**: User description: "Keep one advisorship per student when several advisorships share the same title. An advisorship item whose title equals an existing advisorship's title is taken for that advisorship whatever the student, and the student is replaced. Accept the title match only when the student is the same; otherwise create a new advisorship under the existing distinct name (title + '| Orientacao' + student, year, SigPesq id). Keep advisor and co-advisor records of one work together. State how the fix reaches a persistent database."

## Background

Advisorships come from two sources: the SigPesq advisorship report and the
Lattes curricula. When an advisorship item arrives, it is recognised as an
already stored advisorship in two ways: by its own source identity, or, failing
that, by a stored advisorship with exactly the same title. The second rule does
not look at the student. The item is written over the stored advisorship and
its single student is replaced, so the earlier student loses the advisorship.

Generic titles are common: "Estágio Supervisionado Obrigatório", "Iniciação
Científica", "Trabalho de Conclusão de Curso".

Measured on the local database after the second run of 2026-11-11
(10,260 advisorships):

| What | Count |
|------|-------|
| Lattes (title, student) pairs with no advisorship of their own | 1,537 |
| ... of which in titles with more than one student | 1,458, in 447 titles |
| SigPesq advisorship rows whose student has no advisorship | 89 rows, 82 students (51 cancelled, 38 not cancelled) |
| Advisorships fed by more than one Lattes curriculum item | 647 |
| Advisorships already stored under a distinct name | 652 |

Example: the advisorship "Estágio Supervisionado Obrigatório" is fed by 49
Lattes curriculum items of different students and is one row with one student.

The same happens in SigPesq when a student is replaced in a workplan: the new
student takes the advisorship of the cancelled one (TD-037 in
`docs/backlog.md`).

Two advisorships cannot have the same name in the database; that rule belongs
to the domain library and does not change. The system already has a way around
it: an advisorship whose title is taken is stored under a distinct name,
`<title> | Orientacao <student> | <year> | sigpesq <Id>`. It is applied only
when no stored advisorship was matched, which the title rule above prevents.
652 advisorships carry such a name today and the exports show it.

Not every advisorship fed by more than one curriculum item is wrong: the same
work is legitimately listed in the advisor's curriculum and in the
co-advisor's, with the same student. Those must stay one advisorship.

## Clarifications

### Session 2026-11-11

- Q: The same student has two advisorship items with the same title and different years. One advisorship or two? → A: Two, when both items carry a year and the years differ; when one of them has no year they stay one advisorship.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every student keeps their advisorship when the title repeats (Priority: P1)

As a consumer of the exported data, I want every advisorship listed in a
curriculum to exist with its own student, so that students are not missing
from the data and an advisor's advisorships are not undercounted.

**Why this priority**: this is data loss. About 1,500 advisorships are missing
from the exports today.

**Independent Test**: ingest two curriculum items with the same title and
different students; two advisorships exist afterwards, each with its own
student.

**Acceptance Scenarios**:

1. **Given** a stored advisorship "Estágio Supervisionado Obrigatório" of student A, **When** a curriculum item with the same title and student B is ingested, **Then** two advisorships exist, one with student A and one with student B, and student A's advisorship is unchanged.
2. **Given** the scenario above, **When** the names are read, **Then** the first advisorship keeps its title and the second is stored as the title followed by `| Orientacao`, the student's name and the year when present.
3. **Given** 49 curriculum items with the same title and 49 different students, **When** all are ingested, **Then** 49 advisorships exist, one per student.
4. **Given** the inputs of the 2026-11-11 run, **When** the database is rebuilt from scratch, **Then** no Lattes (title, student) pair is without an advisorship of its own (1,537 today).

---

### User Story 2 - A replaced SigPesq student and the cancelled one each have an advisorship (Priority: P1)

As a consumer of the exported data, I want a student who replaced another in a
SigPesq workplan to have an advisorship of their own, and the cancelled
student to keep theirs marked as cancelled, so that both appear in the data
(TD-037).

**Why this priority**: same data loss as User Story 1, in the other source: 82
students have no advisorship today.

**Independent Test**: ingest a SigPesq report with two rows of the same title,
one cancelled with student A and one not cancelled with student B; two
advisorships exist, A's cancelled and B's not.

**Acceptance Scenarios**:

1. **Given** two SigPesq rows with the same title, one cancelled with student A and one active with student B, **When** the report is ingested, **Then** two advisorships exist: A's marked as cancelled, B's not.
2. **Given** the scenario above, **When** the report is ingested in the opposite row order, **Then** the same two advisorships exist with the same students and the same cancellation state.
3. **Given** the inputs of the 2026-11-11 run, **When** the database is rebuilt from scratch, **Then** no SigPesq advisorship row has a student without an advisorship (89 rows today).

---

### User Story 3 - The same work recorded twice stays one advisorship (Priority: P2)

As the maintainer, I want the fix to split only advisorships of different
students, so that one work listed by the advisor and by the co-advisor, or
present in SigPesq and in Lattes, does not become two advisorships.

**Why this priority**: a rule that also split correct matches would create
duplicates, which is wrong data of another kind.

**Independent Test**: ingest two curriculum items with the same title and the
same student from two different curricula; one advisorship exists.

**Acceptance Scenarios**:

1. **Given** the same title and the same student in the advisor's curriculum and in the co-advisor's, **When** both are ingested, **Then** one advisorship exists.
2. **Given** a SigPesq row and a Lattes item with the same title and the same student, **When** both are ingested, **Then** one advisorship exists.
3. **Given** the same title and a student name that differs only in letter case or accents, **When** both are ingested, **Then** one advisorship exists.
4. **Given** the same title, the same student and the years 2019 and 2020, **When** both items are ingested, **Then** two advisorships exist, one per year.
5. **Given** the same title and the same student, one item with a year and one without, **When** both are ingested, **Then** one advisorship exists.
6. **Given** an item with a title that matches a stored advisorship and no student name, **When** it is ingested, **Then** it is attached to the stored advisorship, as today.
7. **Given** the inputs of the 2026-11-11 run, **When** the database is rebuilt from scratch, **Then** no advisorship has more than one student, no two initiatives share a name, and projects, articles, professional activities, awards, academic educations and technical productions keep their counts.

---

### User Story 4 - A database that already holds the merged advisorships is repaired (Priority: P3)

As the maintainer of the persistent database, I want the fix to reach a
database filled before it, so that the weekly run does not keep the missing
advisorships hidden forever.

**Why this priority**: the rule alone fixes new databases; without this story
the persistent database of the weekly run would keep the old merges.

**Independent Test**: start a run on a database written under the old rule;
the run does not proceed incrementally on it; after the rebuild the acceptance
numbers of User Stories 1 and 2 hold; the next run over the same inputs writes
no advisorship change.

**Acceptance Scenarios**:

1. **Given** a database written under the old rule, **When** a run starts, **Then** the database is recognised as written under older rules and is rebuilt before use, as the constitution requires.
2. **Given** a database rebuilt under the new rule, **When** a second run processes the same inputs, **Then** no advisorship is written or renamed.
3. **Given** a permanent id published before the change, **When** it is looked up after the rebuild, **Then** it resolves to an advisorship as an alias or is reported as retired.

---

### Edge Cases

- The same student has two items with the same title and different years (a renewal): they are two advisorships. If one of the items has no year, they are one.
- The advisor's and the co-advisor's curricula record the same work of the same student with different years: two advisorships exist. This is the accepted cost of keeping renewals apart.
- The same student is written differently in two curricula (abbreviated or with a missing surname): the names do not compare equal, so two advisorships exist. Matching name variants is out of scope.
- Two different students with exactly the same name and the same title: they are one advisorship; nothing in the sources tells them apart.
- The stored advisorship with that title has no student: the incoming item is attached to it and supplies the student.
- The incoming item has no student name: today's behaviour (title match accepted).
- Several stored advisorships share the title (one bare, the others under distinct names): the item goes to the one with its student; if none has it, a new one is created.
- The distinct name built for a new advisorship is already taken: this can only be the same title with the same student and the same year, which is a match, not a new row.
- A project has the same title as an advisorship: the existing rule stays (the project keeps the title and the advisorship is renamed).
- A project PDF matched to an advisorship with the same title (TD-038): unchanged, out of scope.
- An advisorship split by the rebuild that already had a published permanent id: the old id stays resolvable; which resulting advisorship keeps it follows the existing permanent-id rules.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: An advisorship item MUST be recognised as a stored advisorship by title only when the stored advisorship has the same student and their years do not differ.
- **FR-001a**: The years of an item or of an advisorship are the range from its start year to its end year (one year when it carries only one). Years differ only when both sides carry years and the two ranges share no year. Missing years on either side never prevent the match.
- **FR-002**: Student names MUST be compared ignoring letter case, accents and surrounding or repeated spaces.
- **FR-003**: Recognition by the item's own source identity MUST stay as it is today and take precedence over the title.
- **FR-004**: An item whose title matches only advisorships of other students, or of the same student in another year, MUST become a new advisorship, with its own student and supervisor.
- **FR-005**: The new advisorship MUST be stored under the existing distinct name: the title, `| Orientacao`, then the student's name, the start year and the SigPesq id, each when present. The format of the name MUST NOT change.
- **FR-006**: Ingesting an item MUST NOT replace the student of an advisorship that belongs to another student.
- **FR-007**: Items with the same title and the same student whose years do not differ (FR-001a) MUST be one advisorship, whichever curriculum or source they come from.
- **FR-008**: An item without a student name, and a stored advisorship without a student, MUST be matched by title as today.
- **FR-009**: Each advisorship MUST keep at most one student and one supervisor, as today.
- **FR-010**: A cancelled SigPesq row and the row of the student who replaced it MUST give two advisorships, each with the cancellation state of its own row.
- **FR-011**: Projects, research groups and every other initiative type MUST keep their current matching and their names.
- **FR-012**: The same inputs MUST give the same advisorships, students and permanent ids in an incremental run and in a rebuild. The permanent id of an advisorship MUST NOT depend on processing order or on a database id.
- **FR-013**: Processing the same inputs a second time on a database built under the new rule MUST write no advisorship change.
- **FR-014**: Because this changes when two records are the same advisorship, the recorded version of the identity rules MUST change (4 to 5), and a database recorded under an earlier version MUST be rebuilt before use, as the constitution requires.
- **FR-015**: Permanent ids published before the change MUST stay resolvable as aliases or be reported as retired.
- **FR-016**: The feature MUST work in a local run and in the GitHub Actions weekly workflow, with no new setting.
- **FR-017**: The change MUST be made inside this project only: no change to third-party libraries, to the dashboard or to Docker.

### Key Entities

- **Advisorship**: the supervision of one student's work by one supervisor, with a title, dates, a type and a cancellation state. One advisorship may be fed by a SigPesq row and by items from several curricula.
- **Advisorship item**: one advisorship as listed in one source: a row of the SigPesq report or an entry of one researcher's Lattes curriculum, with the title, the student and the supervisor as written there.
- **Student / Supervisor**: the two people linked to an advisorship, one of each.
- **Distinct name**: the name an advisorship receives when its title is already taken: title, `| Orientacao`, student, year, SigPesq id.
- **Identity rule version**: the recorded version of the rules that decide when two records are the same entity; a database is valid only for the version it was built with.

## Success Criteria *(mandatory)*

### Measurable Outcomes

Measured on a from-scratch weekly run over the inputs of 2026-11-11. The run
downloads part of the curricula again, so the targets that are counts are
approximate and the targets that are zero are exact:

- **SC-001**: 0 Lattes (title, student) pairs are without an advisorship of their own (1,537 before); the number of advisorships grows from 10,260 to about 11,890.
- **SC-002**: 0 SigPesq advisorship rows have a student without an advisorship (89 before); every replaced student and every cancelled one has their own advisorship with the right cancellation state.
- **SC-003**: "Estágio Supervisionado Obrigatório" exists as one advisorship per student (49 items in one row before).
- **SC-004**: Advisorships with the same title, the same student and no differing year in two curricula are still one advisorship each; the same title and student in two different years are two advisorships.
- **SC-005**: 0 advisorships have more than one student and 0 initiatives share a name.
- **SC-006**: The counts of projects, articles, professional activities, awards, academic educations and technical productions are the same as in the run before the change, except for items of curricula that were downloaded again and changed.
- **SC-007**: A second run over the same inputs writes no advisorship change for a source that did not change.
- **SC-008**: A database built before the change is never used incrementally: it is rebuilt first, in the local run and in the weekly workflow.

## Assumptions

- The names keep the `| Orientacao ...` suffix (maintainer's decision of 2026-11-11). Removing it needs the unique-name rule of the domain library to change and stays in `docs/backlog.md`.
- The first advisorship stored with a title keeps the bare title; the later ones receive the distinct name. Which one is first may differ between runs; only the permanent ids, the students and the number of advisorships must be the same.
- The student and the year are the fields compared on a title match. The supervisor is not compared, because the same work appears with another supervisor in the co-advisor's curriculum. The years are compared as ranges (FR-001a) because a SigPesq row spans two calendar years and the curriculum often records the year the work ended: comparing single years would store the same advisorship twice for 99 of the 171 (title, student) pairs present in both sources (plan, research R4).
- 97 Lattes (title, student) pairs hold more than one year (measured in the plan, research R5); with them the expected total is about 11,890 advisorships.
- A rebuild is the way the fix reaches an existing database. Advisorships already merged cannot be split by an incremental run, and the constitution (Data Integrity & Persistent Incremental Ingestion, rule 3) already requires a rebuild when the identity rules change. No in-place repair is built.
- The weekly run of the fork and any upstream run happen only with the maintainer's approval; the rebuild they need is part of that approval.
- Out of scope, kept in `docs/backlog.md`: TD-038 (a project PDF matched to an advisorship with the same title), person names stored with an academic title, and project status changes between runs (TD-028 rule, working as designed).
- The dashboard is not changed; it already shows the names with the suffix.
