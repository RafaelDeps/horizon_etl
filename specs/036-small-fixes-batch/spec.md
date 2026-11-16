# Feature Specification: Small fixes batch

**Feature Branch**: `036-small-fixes-batch`

**Created**: 2026-11-12

**Status**: Draft

**Input**: User description: "Small fixes batch: clean person names taken from Lattes advisorships, stop storing the 'JTC' fellowship twice, match project PDFs only to research projects, and ignore the order of the SigPesq student list. State how the fix reaches a persistent database."

## Background

Four small defects are left after branches 033 to 035. None is large enough
for a spec of its own, and each change to the identity rules forces a rebuild
of the database, so they are fixed together and validated once.

Measured on the local database of 2026-11-11 (branch 035, 18,429 persons). The
person counts of the table are the first estimate, by text pattern over every
person. The plan measured them exactly (research R2 and R4): among the
students of Lattes advisorships, about 155 names are cleaned, 4 texts are not
a name and 158 hold several people; 50 other persons with extra text come
from other fields and are out of scope.

**1. Person names with extra text.** The student of a Lattes advisorship comes
from the "orientando" field of the curriculum item. The field sometimes
arrives with more than the name, and the text is stored as the person's name:

| Kind | Example | Persons (about) |
|------|---------|-----------------|
| Name followed by the title of the work | "Guilherme Lopes de Oliveira. Uso do método OTA (...) (PT 10550)" | 240 |
| Several people in one field | "Eliemar Bueno/Luis Fabiano da Silva/Sérgio de Souza Godinho" | 115 |
| Not a name | "1", "Ph", "D", "-", "Acadêmicos do 6 periodo" | 50 |
| Academic title attached | "Profª Drª Teresa Cristina Janes Carneiro", "Professor Doutor ..." | 26 |
| Link attached | "Silas Gambarine Soaresjavascript:void(0)" | 1 |

These persons are shown in the dashboard lists and search. A student whose
name carries the title of the work is also a second person beside the same
student stored with the clean name.

**2. The fellowship "JTC" stored twice (TD-034).** The SigPesq row of workplan
12603 (Id 7433) has the programme "JTC", no value and the funding agency
"CNPq", but the fellowship is stored without a sponsor. The next run looks for
"JTC" of CNPq, does not find it and stores a second "JTC" (ids 15 and 21); one
advisorship moves to the new row. Seen in the local runs of branches 034 and
035 and in the fork runs of branch 035. Why the sponsor is not stored for this
fellowship was found in the plan (research R5): every new fellowship is
stored without its sponsor, and the sponsor is only set when a second row
uses the same fellowship. "JTC" and "PICTI" are used by one row each.

**3. A project PDF matched to an advisorship (TD-038).** The enrichment looks
for the research project of a PDF by title and finds an advisorship with the
same title (PJ 2449 and advisorship 140, PJ 3879 and advisorship 170). The
project's note and description are written on the advisorship (4
advisorships), and the description is written twice in every run: the
advisorship source sets "Programa: ..." and the enrichment sets the PDF text
back. The plan found why (research R6): nearly every advisorship is stored
with the type of a research project, so the enrichment takes it for one.

**4. The order of the SigPesq student list.** The portal returns the
"Estudantes" column of a project row in another order between downloads. The
row is taken for changed and written again (21 records in one local second
run), although nothing changed. The plan found the same in the "Pesquisadores"
column (8 records); both are covered.

## Clarifications

### Session 2026-11-12

- Q: The student field holds a text that is not a name ("1", "Ph", "-", "Acadêmicos do 6 periodo"). What is stored? → A: No person is created; the advisorship is stored without a student.
- Q: Where does the name cleaning apply? → A: Only to the student of a Lattes advisorship item. Names that enter by other paths (SigPesq, CNPq groups, Lattes project teams) are measured in the plan and registered in `docs/backlog.md`.
- Q: A name followed by the title of the work is cut at the full stop. What if the rule is unsure? → A: The cut is made only when what is left looks like a full name (two words or more, no digit); otherwise the text is stored as today and counted.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Students are stored under their name only (Priority: P1)

As someone reading the dashboard, I want a student to appear under their name,
without an academic title, a link or the title of their work, so that lists
and search show people, and the same student is not listed twice.

**Why this priority**: it is the only one of the four that is visible to the
dashboard user, and the largest (about 160 persons within scope).

**Independent Test**: ingest advisorship items whose student field holds each
kind of extra text; check the name of the person stored and that the
advisorship is kept.

**Acceptance Scenarios**:

1. **Given** a student field "Profª Drª Teresa Cristina Janes Carneiro", **When** the item is ingested, **Then** the person is "Teresa Cristina Janes Carneiro".
2. **Given** a student field "Dácio Guimarães de Moura ? Dr", **When** the item is ingested, **Then** the person is "Dácio Guimarães de Moura".
3. **Given** a student field "Guilherme Lopes de Oliveira. Uso do método OTA (Over-The-Air) para atualização remota (PT 10550)", **When** the item is ingested, **Then** the person is "Guilherme Lopes de Oliveira".
4. **Given** a student field "Eduarda Q. O. Senra", **When** the item is ingested, **Then** the person is "Eduarda Q. O. Senra": the full stop of an initial does not end the name.
5. **Given** a student field "Silas Gambarine Soaresjavascript:void(0)", **When** the item is ingested, **Then** the person is "Silas Gambarine Soares".
6. **Given** a student field "1", "Ph", "-" or "Acadêmicos do 6 periodo", **When** the item is ingested, **Then** no person is created and the advisorship is stored without a student, with its supervisor.
7. **Given** a student field "Rafael Scopel Paviotti/Sidarta Barroso Veloso", **When** the item is ingested, **Then** the text is stored as it is today (several people in one field are out of scope).
8. **Given** one student listed as "Maria da Silva" in one item and as "Maria da Silva. Estudo de caso sobre ..." in another, **When** both are ingested, **Then** one person "Maria da Silva" exists.
9. **Given** a run, **When** it ends, **Then** its summary says how many student names were cleaned of each kind and how many texts were not taken for a name.

---

### User Story 2 - A fellowship is stored once (Priority: P2)

As the maintainer, I want a fellowship of the SigPesq report to be recognised
in the next run, so that no copy is created and no advisorship changes
fellowship when the source did not change.

**Why this priority**: one fellowship of 21, no data lost, but it breaks the
rule that a second run over the same inputs writes nothing.

**Independent Test**: ingest the SigPesq row of the "JTC" fellowship twice;
one fellowship exists, with its sponsor, and the advisorship points to the
same fellowship after both passes.

**Acceptance Scenarios**:

1. **Given** a SigPesq row with programme "JTC", no value and funding agency "CNPq", **When** it is ingested on an empty database, **Then** one fellowship "JTC" exists and its sponsor is CNPq.
2. **Given** that database, **When** the same row is ingested again, **Then** no fellowship is created and the advisorship keeps its fellowship.
3. **Given** a fellowship row with a programme and no funding agency, **When** it is ingested twice, **Then** one fellowship exists.
4. **Given** the two programmes with the same name and different funding agencies (PIBIC of CNPq, PIBIC of Fapes), **When** they are ingested, **Then** they stay two fellowships, as today.

---

### User Story 3 - A project PDF is attached to a research project only (Priority: P2)

As the maintainer, I want the text of a project PDF to be written on the
research project it belongs to and never on an advisorship with the same
title, so that an advisorship keeps its own description and nothing is
written back and forth in every run.

**Why this priority**: 4 advisorships carry a project's note and description
today, and it is the second source of writes over unchanged inputs.

**Independent Test**: enrich a PDF whose title equals the title of an
advisorship and of no research project; the advisorship is untouched.

**Acceptance Scenarios**:

1. **Given** a project PDF whose title equals the title of an advisorship and of a research project, **When** the enrichment runs, **Then** the research project is enriched and the advisorship is not changed.
2. **Given** a project PDF whose title equals the title of an advisorship only, **When** the enrichment runs, **Then** the advisorship is not changed, and the PDF is handled as a PDF with no stored project is handled today.
3. **Given** the inputs of the 2026-11-11 run, **When** the database is rebuilt, **Then** no advisorship carries a project PDF note and advisorships 140 and 170 have the description of their own source.
4. **Given** that database, **When** a second run processes the same inputs, **Then** no description is written for an unchanged PDF or an unchanged advisorship.

---

### User Story 4 - The order of the students of a SigPesq project does not matter (Priority: P3)

As the maintainer, I want a SigPesq project row whose students arrive in
another order to be seen as unchanged, so that the run does not rewrite
records that did not change.

**Why this priority**: no data is wrong; it only causes needless writes (21
records in one run).

**Independent Test**: process the same project row twice, the second time with
the names of "Estudantes" in another order; the second pass skips it.

**Acceptance Scenarios**:

1. **Given** a stored SigPesq project row, **When** the same row arrives with the students in another order, **Then** it is skipped as unchanged.
2. **Given** a stored SigPesq project row, **When** it arrives with a student added or removed, **Then** it is processed as changed.
3. **Given** a stored SigPesq project row, **When** it arrives with the same students and a difference only in spaces around a name, **Then** it is skipped as unchanged.

---

### User Story 5 - A database filled before the fixes is repaired (Priority: P3)

As the maintainer of the persistent database, I want the fixes to reach a
database filled before them, so that the bad names, the second "JTC" and the
project notes on advisorships do not stay there.

**Why this priority**: the rules alone fix new databases; the persistent
database of the weekly run needs this story.

**Independent Test**: start a run on a database written under the old rules;
the run does not proceed incrementally on it; after the rebuild the acceptance
numbers of User Stories 1 to 3 hold.

**Acceptance Scenarios**:

1. **Given** a database written under the old rules, **When** a run starts, **Then** it is recognised as written under older rules and rebuilt before use, as the constitution requires.
2. **Given** the permanent id of a person published under a name with extra text, **When** it is looked up after the rebuild, **Then** it resolves to the person with the clean name as an alias, or is reported as retired.
3. **Given** a database rebuilt under the new rules, **When** a second run processes the same inputs, **Then** no person, fellowship or description is written for a source that did not change.

---

### Edge Cases

- A name with initials ("Eduarda Q. O. Senra", "J. R. Souza"): a full stop after an initial is part of the name, not the end of it.
- A legitimate name that starts like a title ("Doutel", "Mestre" as a surname part, "Drago"): only whole words that are academic titles are removed, never the start of a longer word.
- Only a title and nothing else ("Professora Dra", "Prof Dr", "Profª Ms"): after cleaning nothing is left, so it is not a name and no person is created.
- A one-word name ("Graciela", "ITALO"): kept as it is today; it may be all the source knows.
- A text with a full stop whose first part is one word or holds a digit ("Silva. Estudo de ..."): not cut, stored as today and counted.
- A single letter or two letters ("D", "M", "Ph"), only digits or only punctuation: not a name.
- Several people in one field, with or without titles ("A/B", "A; B; C", "X Co-orientador: Y"): left exactly as today, including any title inside the text.
- The cleaned name equals an existing person: the item is attached to that person; no second person is created.
- The cleaned name of the student equals the name of the supervisor of the same item: today's behaviour for that case is kept.
- A student field that holds the name and the work title separated by something other than a full stop: left as it is; only the measured pattern is cleaned.
- A fellowship whose funding agency is written with other letter case or spaces ("CNPQ", " CNPq "): the same sponsor.
- A fellowship row with no programme: no fellowship, as today.
- A PDF whose title equals an advisorship's title and whose project is created by the enrichment itself: the existing rule for a title already taken by another initiative applies (TD-020 in `docs/backlog.md`).
- The student list of a SigPesq project with the same name twice: the list is compared as written, apart from order.
- The researcher list of the SigPesq project row is reordered by the portal too (measured in the plan) and is covered by the same rule.

## Requirements *(mandatory)*

### Functional Requirements

**Person names (User Story 1)**

- **FR-001**: The student name of a Lattes advisorship item MUST be cleaned before the person is looked up or created.
- **FR-002**: Academic titles at the start or at the end of the name MUST be removed: the forms of professor, doctor and master, written in full or abbreviated, with or without a full stop or a gender mark ("Prof", "Profa", "Profª", "Professor", "Professora", "Dr", "Dra", "Drª", "Doutor", "Doutora", "Me", "Ms", "MSc", "Mestre", "PhD"), one or several in a row, with the punctuation that joins them to the name.
- **FR-003**: Only whole words MUST be taken for titles; a name part that only begins with the letters of a title MUST be kept.
- **FR-004**: A link or script text attached to the name MUST be removed.
- **FR-005**: When the name is followed by a full stop and the title of the work, only the name MUST be kept. A full stop that follows an initial MUST NOT end the name. The cut MUST be made only when the part kept has two words or more and no digit; otherwise the text MUST be stored as today.
- **FR-005a**: A number attached to the end of the last word of a name (a footnote mark, "Roseanne Gomes Gonçalves2") MUST be removed.
- **FR-006**: A text that, after cleaning, is not a name MUST NOT create a person: an empty text, a text without letters, a text with a digit, or a text of one or two letters. The advisorship MUST be stored with its supervisor and no student.
- **FR-007**: A one-word name of three letters or more MUST be kept, as today.
- **FR-008**: A field that holds several people MUST be stored exactly as today, including when the people are followed by the title of the work.
- **FR-008a**: Person names that enter by any other path (SigPesq, CNPq groups, Lattes project teams, article authors) MUST be stored exactly as today.
- **FR-009**: A name that needs no cleaning MUST be stored exactly as today.
- **FR-010**: The raw item of the curriculum MUST NOT be changed; the cleaning applies to what is stored as the person.
- **FR-011**: The run summary MUST report the number of names cleaned of each kind (title, link, work title) and the number of texts not taken for a name, and the number of texts with a full stop that were left uncut.
- **FR-012**: The cleaning MUST give the same result in an incremental run and in a rebuild, and MUST NOT depend on processing order.

**Fellowship (User Story 2)**

- **FR-013**: A fellowship MUST be stored with the sponsor its source row gives.
- **FR-014**: A fellowship row MUST be recognised as a stored fellowship in a later run, with or without a sponsor, so that the same row never creates a second fellowship.
- **FR-015**: Fellowships with the same programme and different sponsors MUST stay different fellowships, as today.

**Project PDF (User Story 3)**

- **FR-016**: A project PDF MUST be matched to research projects only. An advisorship, or any initiative of another type, with the same title MUST NOT receive the PDF's note, description or any other field.
- **FR-017**: A PDF whose title matches no research project MUST be handled as today, including the existing rule for a title already taken by another initiative.

**SigPesq student order (User Story 4)**

- **FR-018**: Whether a SigPesq project row changed MUST NOT depend on the order of the names in its student list or in its researcher list, nor on spaces around them.
- **FR-019**: A name added to or removed from either list MUST still count as a change.

**All fixes**

- **FR-020**: Processing the same inputs a second time on a database built under the new rules MUST write no person, fellowship, advisorship or project change.
- **FR-021**: The same inputs MUST give the same persons, fellowships and permanent ids in an incremental run and in a rebuild.
- **FR-022**: Because the name of a person without a Lattes id decides which person it is, the recorded version of the identity rules MUST change (5 to 6), and a database recorded under an earlier version MUST be rebuilt before use, as the constitution requires.
- **FR-023**: Permanent ids published before the change MUST stay resolvable as aliases or be reported as retired.
- **FR-024**: Every advisorship MUST keep its supervisor; no advisorship may be lost by these fixes.
- **FR-025**: The fixes MUST work in a local run and in the GitHub Actions weekly workflow, with no new setting.
- **FR-026**: The change MUST be made inside this project only: no change to third-party libraries, to the dashboard or to Docker.

### Key Entities

- **Person**: someone named in a source. A person without a Lattes id is known by name only, so the stored name decides who they are.
- **Student field**: the text a Lattes curriculum item gives for the student of an advisorship; it should hold a name and sometimes holds more.
- **Fellowship**: a programme ("PIBIC", "JTC") paid by a sponsor, with a value; advisorships point to it. The same programme of two sponsors is two fellowships.
- **Project PDF**: the document of a SigPesq research project, whose text gives the project its description and notes.
- **SigPesq project row**: one project of the SigPesq report, with its list of students.
- **Identity rule version**: the recorded version of the rules that decide when two records are the same entity; a database is valid only for the version it was built with.

## Success Criteria *(mandatory)*

### Measurable Outcomes

Measured on a from-scratch weekly run and on a second run over the same
inputs. The run downloads part of the curricula again, so counts are
approximate and the targets that are zero are exact:

- **SC-001**: 0 persons taken from the student field of a Lattes advisorship have a name that starts or ends with an academic title, contains a link, carries the title of a work or ends with a footnote number (about 155 before).
- **SC-002**: 0 persons are created from a text that is not a name (4 before). The advisorships of those items exist without a student (up to 4; 0 advisorships were without a student before), each with its supervisor.
- **SC-003**: The persons stored with several people in one field are the same as before (about 158 texts); none is added by the cleaning.
- **SC-004**: The number of advisorships is the same as in the run before the change (11,876), except for curricula that changed; 0 advisorships are without a supervisor.
- **SC-005**: One "JTC" fellowship exists after the second run, with its sponsor; the number of fellowships is the same in both runs (20) and none is without the sponsor its source gives (2 before).
- **SC-006**: 0 advisorships carry a project PDF note (4 before).
- **SC-007**: The second run writes no description for an unchanged PDF or advisorship, and no SigPesq project row is processed again only because its students or researchers came in another order (21 and 8 before).
- **SC-008**: The counts of projects, articles, professional activities, awards, academic educations and research groups are the same as in the run before the change, except for curricula that were downloaded again and changed.
- **SC-009**: A database built before the change is never used incrementally: it is rebuilt first, in the local run and in the weekly workflow.
- **SC-010**: The run summary shows the number of names cleaned of each kind and of texts not taken for a name.

## Assumptions

- The counts of the Background are approximate. The plan measures the exact number of each kind and where each person comes from. Persons with extra text that come from another field or source than the student field of a Lattes advisorship are counted in the plan and registered in `docs/backlog.md`; they are not cleaned by this feature.
- A field with several people is not split: an advisorship keeps one student (branch 035), so splitting changes that rule and is not a small fix. It stays in `docs/backlog.md`.
- "Not a name" is decided by the text alone (FR-006). A one-word name is kept because the source may know nothing else.
- The name ends at the first full stop that is followed by more text and does not follow an initial. The plan checks this rule against every student field of the curricula and counts the texts left uncut; those are registered in `docs/backlog.md`.
- A rebuild is the way the fixes reach an existing database: persons stored under a name with extra text cannot be renamed by an incremental run without changing their permanent id, and the constitution (Data Integrity & Persistent Incremental Ingestion, rule 3) already requires a rebuild when the identity rules change. The second "JTC" and the project notes on advisorships also disappear with the rebuild. No in-place repair is built.
- The cause of the missing sponsor is in the domain library (research R5). The library is not changed: the ETL sets the sponsor right after it creates the fellowship, and the library's behaviour is registered in `docs/backlog.md`.
- An advisorship is recognised by being an advisorship, not by its stored type. Storing advisorships under their own type is a larger change and is registered in `docs/backlog.md` (research R6).
- The weekly run of the fork and any upstream run happen only with the maintainer's approval; the rebuild they need is part of that approval.
- Validation follows the batch rule of 2026-11-11: two local runs, then two fork runs once, on this branch.
- Out of scope, kept in `docs/backlog.md`: TD-036 (two isolated identity differences), persons duplicated by citation format, TD-044 to TD-047.
- The dashboard is not changed.
