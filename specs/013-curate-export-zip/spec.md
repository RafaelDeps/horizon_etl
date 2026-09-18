# Feature Specification: Curated Export Archive

**Feature Branch**: `013-curate-export-zip`

**Created**: 2026-09-18

**Status**: Draft

**Input**: User description: "Change the content of exports_canonical.zip: include the SigPesq project documents (PJ_*.json) with personal data scrubbed, and exclude the dataset snapshot file, any other nested archive files, and the formandos/, docentes/, mestrado/, and parquet/ folders; also stop the weekly run from producing the parquet mirror of the canonical exports. Additionally, in the project-document extraction step (the Mistral step), before extracting a project, check whether the project-documents folder inside the latest export archive already has a document for the same project; if it does, do not run extraction for that project and reuse the archived document instead."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Download archive with project documents included (Priority: P1)

As a downstream consumer of the export archive, I download the weekly artifact and find the research project documents (the PJ_*.json corpus) inside it under the folder they know, so I can inspect the raw material the enrichment phase was built from — without any coordinator/project contact information in clear text.

**Why this priority**: The project documents are the missing piece consumers currently have to obtain out-of-band; including them (scrubbed) closes that gap. This is the primary reason for the feature.

**Independent Test**: After a weekly run, unzip the archive and verify every project document that exists in the export folder is present under `project_sigpesq_files_json/`, and that no real e-mail address or phone number appears anywhere in the archive.

**Acceptance Scenarios**:

1. **Given** a completed weekly run that produced N project documents, **When** the export archive is inspected, **Then** all N documents are present in the archive with the same file names and relative folder.
2. **Given** project documents that contain coordinator and team e-mail addresses, **When** the archive contents are scanned for contact data, **Then** no raw e-mail address or phone number is found (each is replaced by an anonymized token).
3. **Given** a run with no project documents, **When** the archive is produced, **Then** the run still succeeds, the archive has no project-document entries, and no error is surfaced.

---

### User Story 2 - Archive stays a curated dataset deliverable (Priority: P1)

As a maintainer, I want the weekly export archive to ship only the curated dataset deliverable — canonical exports plus the scrubbed project documents — and never its inputs, a snapshot of the export folder, formatted report views, or an alternate format, so consumers never receive intermediate or redundant material.

**Why this priority**: Excluding these artifacts is the second explicit goal and is required to keep the archive a single, honest dataset deliverable.

**Independent Test**: After a weekly run, verify the archive contains none of: the dataset snapshot file, any nested archive file, and the formandos/, docentes/, mestrado/, and parquet/ folders.

**Acceptance Scenarios**:

1. **Given** a dataset snapshot file and/or other zip archives present in the export folder, **When** the export archive is produced, **Then** no nested archive file appears in it.
2. **Given** previous runs left formatted report folders (formandos/, docentes/, mestrado/) or a parquet folder in the export folder, **When** the export archive is produced, **Then** none of those folders are included.
3. **Given** any of those excluded items are absent, **When** the archive is produced, **Then** nothing breaks and the archive is unaffected.

---

### User Story 3 - Weekly run no longer produces the parquet mirror (Priority: P1)

As a maintainer, I want the weekly run to stop emitting the parquet mirror of the canonical exports, so run duration and artifact volume shrink while every other canonical output is preserved.

**Why this priority**: Removing the parquet step is the third explicit goal; it removes dead weight from each weekly run.

**Independent Test**: After a weekly run, confirm no parquet mirror is regenerated and that every canonical export file that was previously in the archive is still present.

**Acceptance Scenarios**:

1. **Given** the weekly pipeline runs to completion, **When** the run finishes, **Then** the parquet mirror of the canonical exports is not generated as part of the canonical export step.
2. **Given** the weekly run completed without the parquet step, **When** the archive and export folder are inspected, **Then** every canonical export produced in earlier runs is still present (no data loss).
3. **Given** a maintainer needs the parquet format later, **When** they invoke the dedicated on-demand export command, **Then** it is still available for manual use.

---

### User Story 4 - Extraction step reuses documents from the latest archive (Priority: P2)

As a maintainer, I want the project-document extraction step (which sends projects to the paid OCR/LLM service) to reuse an already-extracted document from the latest export archive instead of paying for a new extraction, so re-runs and fresh environments without a local document corpus do not re-spend on the same projects.

**Why this priority**: This is a cost/performance optimization on top of the curated archive (US1). The extraction step is already non-critical to the weekly run, and existing documents already skip extraction — this extends that same principle to the archived copies.

**Independent Test**: In an environment that has the latest export archive but no local documents, run the full extraction step: projects that have a document inside the archive's project-documents folder are not sent to the extraction service and end up with a usable local document that carries the archived content.

**Acceptance Scenarios**:

1. **Given** the latest export archive contains a document for a given project and there is no local document for it, **When** the extraction step processes that project, **Then** no extraction service call is made and that project's document is created locally from the archived copy.
2. **Given** a project with no document anywhere (neither locally nor in the archive), **When** the extraction step processes it, **Then** a normal extraction service call is made as before.
3. **Given** a forced full re-extraction is requested, **When** the extraction step runs, **Then** reuse from the archive is bypassed and every project is sent to the extraction service.
4. **Given** the archive has a document for a project but that archived document is unusable (malformed), **When** the extraction step processes the project, **Then** it falls back to a normal extraction service call instead of failing.

---

### Edge Cases

- **Run with no project documents**: the archive is still produced successfully and simply has no project-document entries.
- **Malformed or unreadable project document**: that single document is skipped with a recorded warning; the rest of the archive is still produced and the run does not fail.
- **Absent excluded categories**: excluding data that is not present must be a no-op.
- **Campus-filtered run**: the inclusion/exclusion rules behave identically; only the scope of the dataset varies.
- **Re-run on already-anonymized values**: applying the anonymization twice must not further change the value (idempotent).
- **Stale files from previous runs**: the exclusion rules apply regardless of whether the excluded folders/files are fresh or leftover from an earlier run.
- **Archive absent or without the project folder**: the extraction step proceeds exactly as today (no reuse available, normal extraction).
- **Archived document present but malformed**: the step falls back to a normal extraction for that single project; it never crashes the run.
- **Forced full re-extraction**: reuse from the archive and skip-if-exists are both bypassed; every project is extracted anew.
- **Local document already exists**: the existing skip behavior applies first; the archive is only consulted for projects without a local document.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST include every project document (`PJ_*.json`) present in the project-documents folder inside the export archive.
- **FR-002**: Included project documents MUST have every e-mail address and phone number replaced by an anonymized token before being archived, and the archive MUST NOT contain any raw e-mail address or phone number.
- **FR-003**: Project documents MUST be archived under a stable, deterministic relative path so consumers can rely on it between runs.
- **FR-004**: The raw (unmodified) project documents MUST NOT be included in the archive; only their anonymized copies may be archived.
- **FR-005**: The archive MUST NOT contain the dataset snapshot file or any other nested archive file present in the export folder.
- **FR-006**: The archive MUST NOT contain the `formandos/`, `docentes/`, `mestrado/`, or `parquet/` folders even when they exist in the export folder.
- **FR-007**: The weekly run MUST NOT generate the parquet mirror of the canonical exports as part of the canonical export step.
- **FR-008**: All canonical export files delivered before this change MUST continue to be present in the archive.
- **FR-009**: Re-anonymizing an already anonymized value MUST be a no-op (idempotent), so repeated runs cannot further transform the data.
- **FR-010**: A malformed project document MUST be skipped individually with a recorded warning without aborting the archive generation.
- **FR-011**: Before extracting (sending to the extraction service) a project for which no local document exists, the system MUST check whether the project-documents folder inside the latest export archive contains a document for the same project.
- **FR-012**: When such an archived document exists and is usable, the system MUST NOT call the extraction service for that project; instead it MUST create the local document from the archived copy.
- **FR-013**: Reuse from the archive MUST be matched per project (by the project code that both the document file name and the archive path carry) and MUST NOT overwrite a local document that already exists.
- **FR-014**: A forced full re-extraction MUST bypass both the existing skip-if-exists behavior and the archive reuse, sending every project to the extraction service.
- **FR-015**: When the archive is absent, does not contain the project's document, or the archived copy is unusable, the system MUST proceed with a normal extraction for that project rather than erroring.

### Key Entities

- **Export archive**: the single, versioned artifact (`exports_canonical.zip`) delivered after each weekly run.
- **SigPesq project documents**: the `PJ_*.json` corpus that feeds enrichment; now part of the archive in anonymized form.
- **Canonical exports**: the curated dataset files (organizations, researchers, initiatives, graphs, tracking) that must keep being delivered unchanged.
- **Excluded artifacts**: the dataset snapshot file, any other nested archive files, the formatted report folders (`formandos/`, `docentes/`, `mestrado/`), and the parquet mirror folder.
- **Parquet mirror**: the alternate-format copy of the canonical exports; no longer generated by the weekly run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the project documents present in the export folder appear in the archive with the same file name and relative path.
- **SC-002**: A full-text scan of the archive contents finds zero raw e-mail addresses and zero raw phone numbers.
- **SC-003**: The archive contains no nested archive file and no entries under `formandos/`, `docentes/`, `mestrado/`, or `parquet/`.
- **SC-004**: Weekly runs complete without generating a parquet mirror, and weekly run duration does not increase as a result.
- **SC-005**: Every canonical export file previously delivered in the archive is still present after the change.
- **SC-006**: From a clean environment that has only the latest export archive and the project downloads, a full extraction run makes zero extraction-service calls for projects that already have an archived document, and 100% of those projects end up with a usable local document.

## Assumptions

- Names and project content (titles, descriptions, objectives, schedule) are not personal contact data under this project's policy and therefore remain unchanged; only e-mail addresses and phone numbers are anonymized, consistent with how the rest of the pipeline handles them.
- The on-disk project documents are never modified in place; only the copies placed inside the archive are anonymized.
- The dedicated on-demand command that mirrors the canonical exports into the parquet format may remain available for manual use; only the weekly run stops producing it.
- The archive continues to be generated once per weekly run, at the same point in the pipeline as today.
- Existing consumers depend on the canonical export file names and paths; those are preserved exactly.
- Documentation that describes the archive contents and the parquet emission (including ADR-003) will be updated as a follow-up; this is tracked, not a blocking acceptance criterion.
- Reused archived documents are the anonymized copies that the feature ships in the archive: on re-runs, e-mail and phone fields in the local corpus may therefore carry anonymized tokens for reused projects and raw values for freshly extracted ones, which is acceptable because the consumers of these documents do not use contact fields.
- "Latest export archive" means the export archive currently present in the export folder (rewritten by the latest run); no other archive source is consulted.

## Dependencies

- Requires the existing LGPD anonymization capability (the same one used elsewhere in the pipeline) to be reused so the archiving behavior stays consistent with the project's privacy treatment.
- Requires the list of always-excluded export categories (snapshot, nested archives, report folders, parquet) to be maintained by the pipeline.