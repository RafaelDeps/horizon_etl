# Feature Specification: Stable enrichment strategy for document-created projects

**Feature Branch**: `032-stable-enrichment-strategy`

**Created**: 2026-11-09

**Status**: Draft

**Input**: User description: "Make the second weekly run over unchanged project PDFs write nothing (TD-033). When the PDF that created an initiative matches it again (same project code, or same file when it has no code), keep match_strategy = new_from_document, so the second run writes nothing and matches a rebuild. Another PDF matching that initiative still records its own strategy. origin, needs_review, the review fields and the per-run entity_matches tracking stay as they are."

## Context

The project enrichment phase reads one document per SigPesq project PDF and
writes a note on the research project it matches. The note records, among
other things:

- **how the project came to exist** (`origin`): permanent, carried from one
  run to the next;
- **how the document matched in this run** (`match_strategy`): by project
  code, by exact title, by similar title, or "created from this document" when
  no project matched and the phase created one.

When a document matches no project, the phase creates the project and writes
"created from this document". On the next run the same document finds that
project by its exact title, so the note changes to "exact title". Nothing in
the sources changed, yet:

- the second run rewrites the note of each such project and logs a change for
  it (37 projects in the spec 030 replay of 2026-11-06);
- a database rebuilt from the same inputs keeps "created from this document",
  so the incremental database and the rebuild differ (backlog item TD-033).

The constitution requires that a second pass over identical inputs writes
nothing, and that a rebuild from the same inputs gives the same entities as
the incremental database.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A second run over unchanged documents writes nothing (Priority: P1)

As the maintainer, when I run the weekly twice over the same project PDFs, the
second run must not rewrite the notes of the projects those PDFs created, nor
log changes for them.

**Why this priority**: it is the idempotency rule of the constitution, and the
37 rewrites and change entries per run hide real changes in the change log.

**Independent Test**: on a database where a document created a project, run
the enrichment twice with the same documents; the second run leaves the note
unchanged and logs no change for that project.

**Acceptance Scenarios**:

1. **Given** a project created by document PJ_X in an earlier run, **When** the
   enrichment runs again with the same PJ_X and PJ_X matches that project by
   exact title, **Then** the note still says "created from this document" and
   no change is logged for that project.
2. **Given** a project created by a document without a project code, **When**
   the same document file matches it again, **Then** the note still says
   "created from this document".
3. **Given** the same inputs, **When** the database is rebuilt from scratch and
   also run incrementally twice, **Then** the notes of the document-created
   projects are identical in both databases.

---

### User Story 2 - Other documents still record how they matched (Priority: P2)

As the maintainer, when a different PDF matches a project that another
document created, I still want the note to say how that PDF matched.

**Why this priority**: the strategy is useful audit information; only the
false change caused by the creating document must go.

**Independent Test**: a project created by PJ_X is matched in a later run by
PJ_Y (another code); the note records PJ_Y's strategy.

**Acceptance Scenarios**:

1. **Given** a project created by PJ_X, **When** PJ_Y matches it by exact
   title, **Then** the note records "exact title" and the project keeps its
   origin "created from document" and its review flag.

---

### User Story 3 - Databases that already drifted are repaired (Priority: P3)

As the maintainer, the persistent database used by the weekly (locally and in
GitHub Actions) already holds notes that changed to "exact title" for projects
their own document created. I want them back to "created from this document",
so the incremental database matches a rebuild without a reset.

**Why this priority**: without it, the fix only helps databases built after
it, and the persistent CI database keeps differing from a rebuild.

**Independent Test**: on a database where a document-created project's note
says "exact title" for its own document, one enrichment run writes "created
from this document" once; the run after it writes nothing.

**Acceptance Scenarios**:

1. **Given** a project whose origin is "created from document" and whose note
   says "exact title" for the same document, **When** the enrichment runs,
   **Then** the note is rewritten once to "created from this document" and the
   next run writes nothing.

### Edge Cases

- A document-created project that a person has already reviewed: the review
  date, reviewer and cleared review flag are kept; only the strategy rule
  applies.
- The creating document's project code changes between runs (the PDF was
  re-extracted with another code): it counts as another document and records
  its own strategy.
- Two documents claim the same project in one run: the existing winner rule
  (code beats title, ties by file name) still picks one; the rule above then
  applies to the winner.
- A note written before the origin field existed: its origin is inferred as
  today, and the rule applies to it the same way.
- A project the phase did not create (origin "matched existing"): its strategy
  is recorded as today, with no change.
- The creating document later matches its project by project code (the project
  entered the SigPesq report): the code match is recorded.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When the document that created a project matches that project
  again by title (exact or similar), the enrichment MUST record the strategy
  "created from this document". A match by project code is recorded as such,
  since it means the project now exists in the SigPesq report (research R3).
- **FR-002**: A document is "the document that created the project" when the
  project's origin is "created from document" and the document has the same
  project code as the one recorded in the note; when the document has no
  project code, when it has the same source file as the one recorded.
- **FR-003**: Any other document matching a project MUST record the strategy
  that matched it in the current run, as today.
- **FR-004**: The origin, the review flag and the review date and reviewer
  MUST be decided exactly as today.
- **FR-005**: The per-run match tracking (the record of how each document
  matched in each run) MUST keep recording the real strategy of the run.
- **FR-006**: A second enrichment run over unchanged documents MUST write no
  note and log no change for the projects created by those documents.
- **FR-007**: Notes already stored with another strategy for the project's own
  creating document MUST be corrected on the next run, once, with no reset.
- **FR-008**: The counts the phase logs (matched by code, by exact title, by
  similar title) MUST keep counting how documents matched in the current run.
- **FR-009**: Behaviour MUST be the same locally and in GitHub Actions; no new
  setting is needed.

### Key Entities

- **Enrichment note**: the per-project record written from a project PDF; holds
  the project code, the source file, the origin, the match strategy, the review
  state and the extracted content.
- **Creating document**: the project PDF whose run created the project; known
  by the project code (or source file) stored in the note.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A second weekly run over unchanged project PDFs rewrites 0 notes
  and logs 0 changes for document-created projects (37 before).
- **SC-002**: A rebuild and an incremental database built from the same inputs
  have 0 differences in the notes of document-created projects (37 before).
- **SC-003**: On a database that already drifted, the first run after the
  change corrects every drifted note and the following run writes 0 notes.
- **SC-004**: Projects created or matched by other documents keep the same
  notes as before the change (no difference outside the document-created
  projects).

## Assumptions

- The project code and the source file recorded in a note identify the
  document that wrote it; both are already stored in every note the phase
  writes.
- The 37 projects of the replay are all document-created projects matched
  again by their own document; no other cause of note changes is in scope.
- Out of scope: the other replay differences (TD-034 to TD-037), the project
  PDF extraction (spec 031), and the field merge of spec 030.
- No Docker change and no change to third-party libraries.
