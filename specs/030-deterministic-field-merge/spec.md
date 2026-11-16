# Feature Specification: Fixed Rule for Fields Written by Several Documents

**Feature Branch**: `030-deterministic-field-merge`

**Created**: 2026-11-05

**Status**: Draft

**Input**: User description: "Merge the fields of initiatives and fellowships that several source documents write by a fixed rule, so an incremental run gives the same result as a rebuild (TD-028), and let a Lattes project whose title equals a stored initiative name join that initiative instead of failing its CV (TD-029)."

## Context

The database persists between runs (constitution 2.0.0). Each run reprocesses
only the source documents that changed (branch 024, spec 021), and rule 3 of the
constitution requires that a rebuild from the same inputs gives the same
entities as the incremental database.

Two problems in the backlog break that rule.

**TD-028: the last document to write a field wins.** One initiative can be
listed in several documents:
- in the CV of each participant on Lattes;
- in one or more SigPesq project rows and its project PDF.

One fellowship can be listed in several SigPesq workplans and in Lattes CVs.
Today each document that mentions the record overwrites its description,
status, start date and end date (and, for a fellowship, its value) with its
own. The record keeps the values of whichever document was processed last.

- A rebuild processes every document in a fixed order, so its result is
  always the same.
- An incremental run processes only the changed documents. The last writer is
  then a different document, and the record gets different values.

The local replay of branch 024 (spec 021, 2026-10-29) measured this, on a database kept
between passes. After a rebuild and two passes
with unchanged inputs:
- about 130 initiatives differed from the rebuild: description 50, status 27,
  start date 26, end date 18, enrichment 38;
- 5 fellowships differed (their value), and so did the 123 advisorships that
  point at them;
- every other table was identical, and the passes after that wrote nothing.

Branch 023 (spec 020) already solved the same problem for article fields, with a merge
that does not depend on order.

**TD-029: a project whose title equals a stored name fails its CV.** On CI
run 40952053776 (2026-10-29, incremental), the CV `1703547133505721` failed as
partial. One of its projects matched no existing initiative, but its title
was the stored name of another one, and names are unique, so the write
failed. Since branch 024 (spec 021) the whole CV is rolled back, keeps its previous data
and is tried again every run.

The loader already joins a project to an initiative whose name differs only
in spelling (case, accents). An identical name does not always resolve. The
failure did not appear in the rebuilds of 2026-11-03 (local) or in CI run
41931785261, so, like TD-028, it depends on the order of an incremental run.

**Dates available in each source** (measured on 2026-11-05):

| Source | Date of the document | What it measures |
|---|---|---|
| Lattes | every CV (435 of 435) has its last update date | when the person last edited the CV, as a whole |
| SigPesq | none per row; project rows have only start and end, workplans have start, end and acceptance dates | the period of the project or workplan, not an edit |
| CNPq | every group (347 of 347) has its last submission date | the group page; CNPq writes research groups, not initiatives or fellowships |

## Clarifications

### Session 2026-11-05

Decided by the maintainer before this spec:
- When documents disagree, the most recent document wins.
- The source order Lattes > SigPesq > CNPq settles equal dates and missing
  dates.
- SigPesq documents count as having no date.
- Between Lattes CVs with the same date, the lowest Lattes id wins.
- Between SigPesq rows, the highest SigPesq Id wins.

Accepted by the maintainer after the first draft:
- Q: Which fellowship fields follow the rule? → A: value, status, start date
  and end date. They are written by several workplans the same way as the
  value.
- Q: A SigPesq report row and the PDF of the same project have the same Id and
  no date. Which one wins? → A: the report row wins. The PDF only fills a
  field the row leaves empty, as the enrichment does today.
- Q: What about a project whose title is the name of an advisorship? → A
  (first draft): it is not merged and is reported. **Replaced during
  implementation:** the reproduction on the database of CI run 40952053776
  showed that the known case, CV `1703547133505721`, is exactly this. Six of its
  project titles were held by advisorships of the same researcher. A rebuild
  stores projects before advisorships, so there the projects get the plain name
  and the advisorships a disambiguated one ("<title> | Orientacao <student> |
  <year>"). Not storing the project would keep the incremental database
  different from a rebuild.
- Q: So who keeps the name? → A (maintainer, 2026-11-05, option B): the project
  always keeps the plain name. An advisorship that holds it is renamed to the
  disambiguated title the loader already gives advisorships, which is what a
  rebuild stores. No project and no advisorship is lost.
- Q: Does the rule change force a rebuild? → A: yes, once, for a database
  built before this feature. Separately, every new branch keeps starting from
  scratch in GitHub Actions, because the restore only reads runs of the same
  branch. This feature must not change that.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A shared initiative gets the same values in any run (Priority: P1)

As the maintainer, I want an initiative listed in several documents to get its
description, status and dates from a fixed rule. Then an incremental run and a
rebuild give it the same values, whatever documents changed this week.

**Why this priority**: it is the bulk of TD-028, about 130 initiatives that
change depending on the run. It breaks rule 3 of the constitution, and the
exports change without any change in the sources.

**Independent Test**: load an initiative from two Lattes CVs with different
update dates and from a SigPesq row, in every order, and also with only one of
the documents reprocessed. The stored values are the same every time.

**Acceptance Scenarios**:

1. **Given** an initiative in two Lattes CVs, updated on 2026-03-10 and
   2026-09-02, with different descriptions, **When** the documents are
   loaded in either order, **Then** the description is the one of the CV
   updated on 2026-09-02.
2. **Given** the same initiative is stored, **When** an incremental run
   reprocesses only the CV updated on 2026-03-10, **Then** the description
   stays the one of the CV updated on 2026-09-02, and nothing is written.
3. **Given** an initiative in a Lattes CV and in a SigPesq row with different
   statuses, **When** they are loaded in either order, **Then** the status is
   the one of the Lattes CV.
4. **Given** an initiative whose Lattes CVs all leave the end date empty and
   whose SigPesq row has one, **When** they are loaded, **Then** the end date
   is the one of the SigPesq row.
5. **Given** two Lattes CVs with the same update date and different start
   dates, **When** they are loaded in either order, **Then** the start date is
   the one of the CV with the lowest Lattes id.
6. **Given** two SigPesq rows of the same initiative with different
   descriptions, **When** they are loaded in either order, **Then** the
   description is the one of the row with the highest SigPesq Id.

---

### User Story 2 - A shared fellowship gets the same values in any run (Priority: P2)

As the maintainer, I want a fellowship listed in several workplans or CVs to
get its value, status and dates from the same rule.

**Why this priority**: same problem as User Story 1, on fewer records (5
fellowships and the 123 advisorships that point at them, in the replay). The fellowship value feeds the analytics marts.

**Independent Test**: load a fellowship from two SigPesq workplans with
different values, in both orders. The stored value is the one of the workplan
with the highest SigPesq Id.

**Acceptance Scenarios**:

1. **Given** a fellowship in two workplans with different values, **When**
   they are loaded in either order, **Then** the value is the one of the
   workplan with the highest SigPesq Id.
2. **Given** a fellowship also listed in a Lattes CV, with a different end
   date, **When** they are loaded, **Then** the end date is the one of the
   Lattes CV. The value, which the CV does not have, stays the SigPesq one.

---

### User Story 3 - A project with an identical stored name no longer fails its CV (Priority: P3)

As the maintainer, I want a Lattes project whose title is exactly the stored
name of an initiative of the same kind to join that initiative. Its CV then
loads fully instead of being rolled back every run.

**Why this priority**: it affects one known CV, but the whole CV is lost from
the incremental database and is retried every week. It also depends on order,
like TD-028.

**Independent Test**: store an initiative, then load a CV with a project of
the same title that the identity lookup does not find. The CV loads with no
partial status, and the project's fields are merged by the rule of User
Story 1.

**Acceptance Scenarios**:

1. **Given** a stored initiative named "X" and a CV with a project titled "X"
   that resolves to no initiative by identity, **When** the CV is loaded,
   **Then** the project joins the initiative "X" and the CV is not partial.
2. **Given** the name "X" belongs to an advisorship, **When** a CV with a
   project titled "X" is loaded, **Then** the project is stored as "X", the
   advisorship is renamed to "X | Orientacao <student> | <year>", the run logs
   the rename, and reprocessing the advisorship's document finds it under that
   name (no duplicate).

---

### User Story 4 - The reviewer can see the rule working (Priority: P4)

As the maintainer, I want each run to report how many fields the rule decided
and how, so a reviewer can check it without reading the database.

**Why this priority**: it does not change the data, but without it a wrong
rule would go unnoticed.

**Independent Test**: run a load with conflicting documents and read the run
log.

**Acceptance Scenarios**:

1. **Given** a run where documents disagree, **When** the load ends, **Then**
   the log shows how many fields were decided by date, by source order and by
   a tie-break, and how many title collisions were resolved or reported.
2. **Given** a run where no documents disagree, **When** the load ends,
   **Then** the counts are zero and no other output changes.

### Edge Cases

- **A CV with no update date, or an unreadable one**: it counts as having no
  date, like a SigPesq row. Between undated documents, the source order and
  the tie-breaks decide.
- **All documents of a field are empty**: the field stays empty. An empty
  value never replaces a filled one.
- **A document stops mentioning the record** (a project removed from a CV, a
  CV no longer downloaded): its values no longer take part. The field gets the
  winner among the documents that still mention the record, as a rebuild
  would give.
- **The winning document changes its value**: the new value is stored, and
  the change goes to the change log.
- **A document with a newer date but an empty field**: it does not win that
  field. The best non-empty value wins.
- **Project PDFs**: they belong to SigPesq and have no date. The fields they
  fill (the enrichment and descriptions taken from them) follow the same rule.
  Against the report row of the same project, which has the same Id, the row
  wins and the PDF only fills what the row leaves empty.
- **Values that differ only in spaces or case**: they count as the same value,
  and nothing is written.
- **Parent projects** whose status and dates are computed from their child
  projects: they keep being computed after the children are merged.
- **The rule version**: if the rule changes the stored values, a database
  built with the old rule is rebuilt, as the constitution requires for a
  change in the key, hash or id rules.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When the documents that mention an initiative or fellowship
  disagree on a field, the system MUST store the value of the most recent
  document. The date of a Lattes document is its CV's last update date.
  SigPesq documents, including project PDFs, MUST count as having no date.
- **FR-002**: A document with a date MUST win over a document with no date.
- **FR-003**: Between documents with the same date, or with no date, the
  source order Lattes > SigPesq > CNPq MUST decide.
- **FR-004**: Within one source, the system MUST use fixed tie-breaks: between
  Lattes CVs with the same date, the lowest Lattes id wins; between SigPesq
  rows, the highest SigPesq Id wins; between a SigPesq report row and the PDF
  of the same project, the row wins.
- **FR-005**: An empty value MUST never replace a filled one. A lower-ranked
  document MUST still fill a field that every higher-ranked document leaves
  empty.
- **FR-006**: The rule MUST apply to these initiative fields: description,
  status, start date, end date, and the enrichment fields derived from the
  project files. For fellowships it MUST apply to value, status, start date and
  end date.
- **FR-007**: The stored values MUST depend only on the set of documents that
  mention the record, never on the order they are processed in, nor on which
  of them were reprocessed in this run.
- **FR-008**: In an incremental run, the system MUST decide each field with
  the values and dates of every document that mentions the record, including
  documents that were not reprocessed in this run, without reading them again.
- **FR-009**: When a document no longer mentions a record, its values MUST no
  longer take part in the rule for that record.
- **FR-010**: A Lattes project whose title is identical to the stored name of
  an initiative of the same kind MUST resolve to that initiative, and its
  fields MUST be merged by FR-001 to FR-005. Its CV MUST NOT fail because of
  that name.
- **FR-011**: When the identical name belongs to an advisorship, the project
  MUST keep the name and the advisorship MUST be renamed to its disambiguated
  title, the one the loader gives an advisorship whose title is in use, so the
  result equals a rebuild. The rename MUST be logged with the CV, the title and
  both records. No project or advisorship may be dropped.
- **FR-012**: Every change in a stored value MUST go through the existing
  change log. A field whose winning value does not change MUST write nothing
  (idempotency fixpoint, constitution rule 2).
- **FR-013**: Each run MUST log how many fields were decided by date, by
  source order and by tie-break, and how many title collisions were resolved
  and reported.
- **FR-014**: If the rule changes values already stored, the rule version
  MUST change, so a database built with the old rule is rebuilt before use.
- **FR-015**: The system MUST keep unchanged:
  - the matching of initiatives and people;
  - the article merge of branch 023 (spec 020);
  - the per-document skip and rollback of branch 024 (spec 021);
  - the PII rules of spec 029;
  - SigPesq sequential and CNPq with 4 workers;
  - the restore of GitHub Actions, which reads only runs of the same branch,
    so the first run of every new branch starts from scratch;
  - the third-party libraries (eo_lib, research_domain, scriptLattes,
    dgp_cnpq_lib, agent_sigpesq).
- **FR-016**: The feature MUST work locally and in the GitHub Actions weekly
  workflow, with no change to Docker.

### Key Entities

- **Initiative**: a research, extension or development project. Its
  description, status, start date, end date and enrichment can come from
  several documents.
- **Fellowship (advisorship)**: a student's fellowship or advisorship. Its
  value, status and dates can come from several workplans and CVs.
- **Source document**: one Lattes CV, one SigPesq row or workplan, one
  project PDF or one CNPq group page. It has a source, an id within that
  source and, for Lattes and CNPq, a date.
- **Field claim**: the value one source document gives to one field of one
  record, with that document's source, date and id. The rule picks the
  winning claim among all the claims of a field.
- **Title collision**: a project whose title equals the stored name of a
  record it did not resolve to by identity.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the replay of branch 024 (spec 021), after a rebuild, two passes with
  unchanged inputs and one incremental pass with only some documents changed,
  0 initiatives, 0 fellowships and 0 advisorships differ from a rebuild of the
  same inputs (today about 130 initiatives, 5 fellowships and 123
  advisorships).
- **SC-002**: Loading the same documents in at least three different orders
  gives identical values in every field of FR-006.
- **SC-003**: A second pass with unchanged inputs writes nothing: 0 changed
  rows and 0 change log entries.
- **SC-004**: CV `1703547133505721`, or a test that reproduces its collision,
  loads with no partial status, and no project is lost.
- **SC-005**: In a run with conflicting documents, the log shows the counts of
  FR-013, and they add up to the number of fields that had more than one
  non-empty value.
- **SC-006**: The weekly run time grows by at most 5% over a run with the same
  inputs before this feature. This is a reference, not a gate.

## Assumptions

- The source tracking of branch 023 (spec 020) already stores the values each source
  document gave to each record. It can provide the claims of documents that
  were not reprocessed in this run.
- The Lattes update date is read from the CV itself and kept with the
  document. For a CV kept from an earlier run, the date of that copy is used.
- A SigPesq Id is a number, and a larger Id means a row created later.
- CNPq does not write initiatives or fellowships. It is kept last in the
  source order only to complete the rule.
- The status values of Lattes and SigPesq are already mapped to the same set,
  so they can be compared.
- Once the rule is in place, the first run rebuilds the database because of
  FR-014. That rebuild is expected and takes about as long as a run from
  scratch.
- The work starts from branch `029-pii-safe-exports`, which includes branches 026 to 028 (specs 023
  to 025), the SQLite finalize fix and spec 029.
