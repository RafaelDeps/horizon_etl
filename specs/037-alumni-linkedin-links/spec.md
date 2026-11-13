# Feature Specification: LinkedIn links from a local list

**Feature Branch**: `037-alumni-linkedin-links`

**Created**: 2026-11-13

**Status**: Draft

**Input**: User description: "Add a LinkedIn profile link to the persons listed in a local list (alumni first). A local, unversioned list (link and name per line) is read by the weekly run; the link is stored on the person with that name and appears in the exports as `linkedin_url`. No list, no failure. The dashboard is changed later by the maintainer."

## Background

The dashboard will get a LinkedIn button for alumni (former students). The
ETL has to deliver the link; the dashboard itself is changed later, by the
maintainer.

No source the ETL reads today carries a LinkedIn link: the Lattes curricula,
the SigPesq reports and the CNPq pages have none (checked on 2026-11-12).

The maintainer holds a list of alumni of two courses with their public
LinkedIn profile link: 182 names on 2026-11-13. Each entry has the name and
the link only; there is no Lattes id, no enrollment number and no e-mail, so
the only way to find the person is the name.

Compared by name, ignoring case and accents, with the persons of the local
database of 2026-11-12:

| Names of the list | Count |
|-------------------|-------|
| Match exactly one person | 148 |
| Match more than one person | 0 |
| Match no person | 34 |

The ETL already has a list of this kind: the Lattes list, one person per line,
with the id and the name. The LinkedIn list follows the same idea, with one
difference decided by the maintainer: it stays on the maintainer's machine and
is never versioned. The weekly run of GitHub Actions therefore never sees it,
and the feature is validated locally only.

## Clarifications

### Session 2026-11-13

- Q: A name of the list matches no person of the ETL. What happens? → A: Nothing is stored and no person is created; the line is reported as "not found".
- Q: The list file exists but has no usable line (empty, or only invalid lines). What happens to the stored links? → A: Nothing is removed; the summary warns that the list is empty. Links are removed only when the list has at least one usable line.
- Q: Among which persons is a name of the list searched? → A: Among all persons of the database (students, teachers, researchers), not only students.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A person of the list has a LinkedIn link in the exports (Priority: P1)

As the maintainer of the dashboard, I want each person of my list to carry
their LinkedIn link in the exported data, so that the dashboard can show a
LinkedIn button for them.

**Why this priority**: it is the feature. Without it there is nothing to show.

**Independent Test**: put a list with a few names that exist in the database
in the expected place, run the step and the exports; the persons of those
names have the link in the exports and no other person has one.

**Acceptance Scenarios**:

1. **Given** a line "https://www.linkedin.com/in/maria-silva,Maria da Silva" and one person named "Maria da Silva", **When** the run reads the list, **Then** that person has the link and it appears as `linkedin_url` in the exports.
2. **Given** the name written in the list as "MARIA DA SILVA" or "Maria  da Sílva", **When** the run reads the list, **Then** the same person gets the link: case, accents and repeated spaces do not matter.
3. **Given** a person who is not in the list, **When** the exports are written, **Then** their `linkedin_url` is empty.
4. **Given** the link written as "http://linkedin.com/in/maria-silva/?utm_source=share", **When** it is stored, **Then** it is stored as "https://www.linkedin.com/in/maria-silva".
5. **Given** the list of 182 names, **When** the local weekly run ends, **Then** about 148 persons have a link, each of them a person whose name is in the list.

---

### User Story 2 - A line that cannot be used is reported, never guessed (Priority: P1)

As the maintainer, I want every line that could not be used to be reported
with its reason, and no link to be given to a person by guess, so that a wrong
person never gets someone else's profile.

**Why this priority**: the name is the only key. A wrong match publishes a
link under the wrong person, which is worse than no link.

**Independent Test**: a list with a name that matches no person, a name shared
by two persons, a value that is not a LinkedIn profile and a repeated name;
none of them stores a link and each is in the summary with its reason.

**Acceptance Scenarios**:

1. **Given** a name that matches no person, **When** the run reads the list, **Then** no link is stored, no person is created and the line is reported as "not found".
2. **Given** a name that matches two persons, **When** the run reads the list, **Then** neither gets the link and the line is reported as "more than one person".
3. **Given** a line whose link is not a LinkedIn profile address (another site, a company page, an empty value), **When** the run reads the list, **Then** the line is reported as "invalid link" and ignored.
4. **Given** the same name on two lines with different links, **When** the run reads the list, **Then** no link is stored for that name and the lines are reported.
5. **Given** the same link on the lines of two different names, **When** the run reads the list, **Then** neither is stored and the lines are reported.
6. **Given** a run, **When** it ends, **Then** its summary gives the number of lines read, links stored, names not found, names with more than one person and invalid lines, and lists the names of the lines that were not used.

---

### User Story 3 - The list is the source of truth for the link (Priority: P2)

As the maintainer, I want the stored links to follow the list, so that fixing
or removing a line is all it takes to fix or remove a link.

**Why this priority**: the list will be corrected over time; without this the
database would keep links the list no longer has.

**Independent Test**: run with a list, change one link, remove one line, run
again; the changed link is replaced, the removed one is gone and the others
are untouched.

**Acceptance Scenarios**:

1. **Given** a person with a stored link, **When** their line carries another link in the next run, **Then** the new link replaces the old one.
2. **Given** a person with a stored link, **When** their line is removed and the run reads the list, **Then** that person has no link and no other person changed.
3. **Given** a list that did not change, **When** a second run reads it, **Then** nothing is written.
4. **Given** a name that matched no person in one run, **When** the person exists in a later run, **Then** the person gets the link without any change to the list.

---

### User Story 4 - A run without the list is harmless (Priority: P2)

As the maintainer of the weekly run, I want a run on a machine without the
list, GitHub Actions included, to end normally and to leave stored links
alone, so that the list can stay local without breaking anything.

**Why this priority**: the list is never versioned, so every run of GitHub
Actions is a run without it.

**Independent Test**: run the step with no list file; it ends successfully,
says the list is absent and changes no link.

**Acceptance Scenarios**:

1. **Given** no list file, **When** the weekly run reaches the step, **Then** the step ends successfully, reports that there is no list and writes nothing.
2. **Given** stored links and no list file, **When** the run ends, **Then** every stored link is still there.
3. **Given** a database that never saw a list, **When** the exports are written, **Then** `linkedin_url` is present and empty for every person.
4. **Given** the weekly run of GitHub Actions, **When** it runs with this feature, **Then** its result and its counts are the same as before the feature.

---

### Edge Cases

- A name of the list with a comma inside: the line is split at the first comma only (link first, then the name), so the name keeps its commas.
- A line with spaces around the link or the name: ignored.
- Empty lines and lines starting with "#": ignored, not counted as invalid.
- A line with a link and no name, or without a comma: invalid line, reported.
- The list file exists and has no usable line (empty, only comments or only invalid lines): nothing is stored and nothing is removed, and the summary warns that the list is empty. An empty file is far more often an accident than a wish to clear every link. A missing file also removes nothing.
- Two persons that are one person stored twice (a duplicate the ETL has not merged): the name matches both, so neither gets the link; the line is reported and the link appears once the duplicate is gone.
- The matched person is later merged into another person by the ETL's own consolidation: the link stays with the surviving person as long as its name is the name of the list.
- The matched person is a teacher or a researcher with the same name as the alumnus: the ETL cannot tell them apart; the person gets the link. Only names that match exactly one person are used.
- A LinkedIn address of a company, a school or a post: not a profile, invalid link.
- The same person written with a shorter name in the list than in the database ("Maria Silva" and "Maria da Silva Souza"): not the same name; not found. Approximate matching is out of scope.

## Requirements *(mandatory)*

### Functional Requirements

**The list**

- **FR-001**: The system MUST read the LinkedIn list from one fixed local place, `data/linkedin_run/linkedin.list`, one person per line: the LinkedIn profile link, a comma, the full name.
- **FR-002**: Empty lines and lines starting with "#" MUST be ignored. Spaces around the link and the name MUST be ignored. The line MUST be split at the first comma only.
- **FR-003**: The list MUST NOT be versioned or committed, and no copy of it may be written into a versioned place.
- **FR-003a**: The list file is the only place the ETL reads LinkedIn links from. The ETL MUST NOT read, copy from or write to the maintainer's alumni projects or any other folder outside this project; bringing the data into the list is done by the maintainer, outside the run.
- **FR-004**: Only a LinkedIn profile address (`linkedin.com/in/<profile>`) MUST be accepted as a link. Any other value MUST be reported as an invalid link and ignored.
- **FR-005**: An accepted link MUST be stored in one normal form: `https://www.linkedin.com/in/<profile>`, without query parameters, fragment or trailing slash.

**Finding the person**

- **FR-006**: A line MUST be matched to a person by name only, comparing the two names ignoring letter case, accents and surrounding or repeated spaces. The name MUST be searched among all persons of the database, whatever their role.
- **FR-007**: The link MUST be stored only when the name matches exactly one person.
- **FR-008**: A name that matches no person MUST store nothing and MUST NOT create a person.
- **FR-009**: A name that matches more than one person MUST store nothing on any of them.
- **FR-010**: A name that appears on more than one line with different links, and a link that appears on the lines of different names, MUST store nothing for the names involved. The same name with the same link on two lines counts once.
- **FR-011**: The step MUST NOT create, rename, merge or delete any person, and MUST NOT change any other field of a person.

**Following the list**

- **FR-012**: When the list is read, the stored links MUST end equal to the usable lines of the list: a new line adds a link, a changed link replaces the old one, and a person whose line is gone, or is no longer usable, loses the link.
- **FR-013**: Reading the same list twice MUST write nothing the second time.
- **FR-014**: When the list file does not exist, the step MUST end successfully, report that there is no list, and leave every stored link as it is.
- **FR-014a**: When the list file exists and has no usable line, the step MUST end successfully, warn that the list is empty, and leave every stored link as it is. Stored links are removed (FR-012) only by a list with at least one usable line.

**Exports**

- **FR-015**: The link MUST appear as `linkedin_url` in every canonical export that lists that person with their own fields, beside `cnpq_url` and `google_scholar_url` where those exist.
- **FR-016**: `linkedin_url` MUST be present and empty for a person without a link, so the dashboard can rely on the field.
- **FR-017**: No other export field, and no export file's existing shape, may change.

**Reporting**

- **FR-018**: The run summary MUST give the number of lines read, links stored, links added, changed and removed in this run, names not found, names matching more than one person, repeated lines that conflict, and invalid lines.
- **FR-019**: The run log MUST list the names of the lines that were not used, each with its reason, so the maintainer can correct the list. Nothing but the name and the reason is printed.

**Limits**

- **FR-020**: The link MUST NOT take part in any rule that decides who a person is or what their permanent id is. No permanent id may change, and the recorded version of the identity rules MUST NOT change.
- **FR-021**: The step MUST run as part of the weekly run, after the sources are loaded and before the exports are written, locally and in GitHub Actions.
- **FR-022**: Nothing else about the listed persons (job, company, city, income, career history) may enter the ETL.
- **FR-022a**: The list MUST NOT be tied to alumni: any person the ETL stores may be listed, and the name of the file and of the step MUST NOT say "alumni".
- **FR-023**: The change MUST be made inside this project only: no change to third-party libraries, to the dashboard or to Docker. A database created before the feature MUST work without a rebuild.

### Key Entities

- **LinkedIn list**: a local text file kept by the maintainer, one person per line, with the LinkedIn profile link and the full name. It is the only source of the link and it is not versioned. Its first content is the alumni of two courses; other people may be added later.
- **Person**: someone already stored by the ETL from its sources. The alumni of the first list are persons the ETL knows as students of advisorships and projects.
- **LinkedIn link**: the public address of a person's LinkedIn profile, at most one per person, stored in one normal form.
- **Line outcome**: what happened to a line of the list: stored, not found, more than one person, conflicting repeat, invalid.

## Success Criteria *(mandatory)*

### Measurable Outcomes

Measured on a local weekly run with the list of 182 names. The persons of the
database change a little with every download, so the counts are approximate
and the targets that are zero are exact:

- **SC-001**: About 148 persons have a LinkedIn link in the exports.
- **SC-002**: Every stored link belongs to a person whose name is a name of the list: 0 links on a person outside the list.
- **SC-003**: 0 persons are created, renamed or removed by the step; the counts of persons, advisorships and projects and every permanent id are the same as in a run without the list.
- **SC-004**: Every line that was not used (about 34 names not found) is listed in the run summary with its reason; the lines stored plus the lines reported equal the lines read.
- **SC-005**: A second run over the same list writes no change.
- **SC-006**: After one line is removed from the list, the next run removes that person's link and changes no other.
- **SC-007**: A run without the list file ends successfully and changes no link; the GitHub Actions weekly run keeps its result and its counts.
- **SC-008**: The maintainer can turn a profile link and a name into a button on the dashboard by reading one field of the exported person, with no other file.

## Assumptions

- The list is written by hand or copied by the maintainer from their own alumni data; how it is produced is not part of this feature. The alumni projects that hold that data are separate from the ETL and are never read or changed by it (maintainer's decision of 2026-11-13).
- The alumni of the list are persons the ETL already stores. The plan measured where they appear (research R1): the file that lists every person holds all 148 of them, and the student file 146, each as an entry with its own fields; `linkedin_url` is added to that person entry, which is where the dashboard reads it (FR-015, SC-008).
- Exact name comparison is enough for the first version: 148 of 182 names match one person and none matches two. The 34 names not found are persons the ETL does not have, or has under another spelling; approximate matching would risk a wrong person and stays out.
- A person is found among all persons, not only students. A teacher with the same name as an alumnus would get the link; with exactly one match required and 0 ambiguous names today, this is accepted.
- The list is the only source of the field, but a list with no usable line is treated as a mistake and changes nothing, like a missing file. To clear every link the maintainer removes the lines while at least one usable line remains, or clears the field by hand.
- The exports of GitHub Actions carry `linkedin_url` empty, because its runs never have the list. Publishing the links through that workflow would need the list, or the links, to reach it, which the maintainer decided against for now.
- Privacy: the link is a public profile address, and the course coordination chose to publish name and profile address for these alumni. The list itself stays on the maintainer's machine.
- The first list holds alumni only. Teachers, researchers and anyone else can be added to the same list later, with no change to the feature (FR-022a); there is no source for their links today.
- The dashboard is not changed by this feature.
