# Feature Specification: Advisorship Canonical Data Values Fetch

**Feature Branch**: `009-advisorship-value-fetch`

**Created**: 2026-08-29

**Status**: Draft

**Input**: User description: "Refactor advisorship canonical data values fetch, because i suspect that it is placing static values instead fetch the value for the category of a people in the spefic year containing he, like viewed in data/raw/sigpesq/advisorship/YYYY/Relatorio_DD_MM_YYYY.xlsx."

## Context

Every advisorship (bolsa/orientação) exported to the canonical datasets comes from a
single SigPesq report row like `data/raw/sigpesq/advisorships/2016/Relatorio_29_08_2026.xlsx`
or `.../2025/Relatorio_29_08_2026.xlsx`. That row holds, for that advisorship and
that year: `Ano`, `Programa` (e.g. Pivic, Pibic), `Modalidade` (Voluntário/Bolsista),
`Gerenciamento`, `Edital`, `Curso`, `Campus`, `CampusOrientador`, `AvaliacaoRelatorio`,
`AceiteOrientador`/`AceiteOrientado`, `Cancelado`/`CanceladoPor`, `Ciente`,
`AgFinanciadora`, `Valor`, plus the supervisor and student names.

The current canonical advisorship export (`advisorships_canonical.json` and the
per-researcher `advisorships` lists in `researchers_canonical.json`) emits a fixed
subset of those values and drops the per-row categorical data. In the database,
every one of the 3,199 advisorship rows has `type = NULL` and `program = NULL`, and
the export labels every record with the static `initiative_type = "Advisorship"`.
On the latest canonical export, 2,693 of 3,199 advisorship entries (84%) carry no
fellowship object at all, so the program/provider category is absent rather than
placed. The user suspects the export is placing static (or absent) values where a
value specific to the person/advisorship in its year should be fetched instead.

**Clarification on "category"** (confirmed by the user): "category" is the
advisorship's program — e.g. PICTI, PIC (or PICTI-Jr, PIBIC, PIVIC, PIBITI) — and
its value depends mainly on the provider (AgFinanciadora): FAPES, IFES, CNPq,
Voluntário, etc. Both dimensions come from the advisorship's report row for its
specific year (`Programa` + `AgFinanciadora` + `Ano`), and are currently not
materialised per advisorship.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Canonical advisorship records carry their per-year category (Priority: P1)

A data consumer opens the canonical advisorship dataset and, for a given advisorship,
sees the program/type that applied to that advisorship in its own year (e.g. the
2016 Pivic advisorship shows program Pivic for 2016), mirroring the raw report row —
not a generic, static, or empty label.

**Why this priority**: This is the core suspicion: the exported value for the
advisorship category must be the per-advisorship, per-year value from the report,
which is the first place consumers notice stale/static data.

**Independent Test**: Regenerate the canonical advisorship export from a fresh
ingestion; for every advisorship whose source row defines a program/type, the
canonical record exposes exactly that value (no nulls where the report had a value,
no generic placeholders).

**Acceptance Scenarios**:

1. **Given** an advisorship sourced from `Relatorio_29_08_2026.xlsx` (2016) with `Programa = Pivic` and `AgFinanciadora = Voluntário`, **When** the canonical advisorship export is produced, **Then** that advisorship's category shows program `Pivic` and provider `Voluntário` (matching the report row), and not a null, "N/A", or fixed value.
2. **Given** an advisorship sourced from the 2025 report for the same work plan with a different program, **When** the advisorship records export, **Then** each year's advisorship keeps its own program value (no cross-year contamination).
3. **Given** an advisorship row where the report itself has an empty/absent category, **When** the export is produced, **Then** the record shows the absence explicitly and remains valid JSON.

### User Story 2 - Year-correctness of the fetched category (Priority: P2)

Because the category depends on the advisorship's year and provider, the standalone
advisorship export must show, for each advisorship, the program/provider that its
own report row carried — even when the same work plan reappears in consecutive
years with different programs/agencies, and even when `Inicio`/`Fim` span two
calendar years.

**Why this priority**: The user tied the suspicion to "the specific year"; the
report/directory year is the chosen authority, so correctness across years is the
main regression risk when fetching values.

**Independent Test**: Take advisorship work plans present in more than one report
year and independently verify each year's canonical row exposes that year's
program/provider (no first-seen value reused across years).

**Acceptance Scenarios**:

1. **Given** a work plan with advisorship rows in the 2016 and 2025 reports with different programs, **When** the advisorship export is produced, **Then** the 2016 row shows the 2016 program/provider and the 2025 row the 2025 one (no cross-year contamination).
2. **Given** an advisorship starting in one year and ending in the next (e.g. `Inicio` 2016-09-26, `Fim` 2017-07-31 under `advisorships/2016/`), **When** it is exported, **Then** its category is the 2016 (report/directory year) value.
3. **Given** the refactored fetch, **When** exports are regenerated, **Then** no advisorship row is dropped or duplicated as a side effect (count parity per year with the source reports).

> **Out of scope** (Q3 = C): the per-person advisorship lists inside `researchers_canonical.json` and the `advisorships_tracking.json` provenance export keep their current shape; this feature changes the standalone `advisorships_canonical.json` only.

### User Story 3 - Provenance of fetched category values (Priority: P3)

A consumer can verify where each advisorship category value came from (source
report file and year) through the tracking/provenance export, increasing trust in
the refactored values.

**Why this priority**: Audit-driven data quality is a core project principle; after
changing how values are fetched, the origin of the values must remain auditable.

**Independent Test**: Pick any advisorship, locate its canonical record and its
source row, and confirm the value's origin (report file and year) is traceable.

**Acceptance Scenarios**:

1. **Given** an advisorship record with a non-null category in `advisorships_canonical.json`, **When** its provenance is inspected via the existing source-record/tracking data, **Then** the source file path and year of the value are present.
2. **Given** a value fetched from the 2025 report, **When** provenance is inspected, **Then** it is attributed to `data/raw/sigpesq/advisorships/2025/...xlsx`, not an older or generic source.

### Edge Cases

- Advisorship rows where the source report category cell is empty/blank or the report version predates a new category enum.
- Advisorship records originating from Lattes (no SigPesq report row) — what value do they carry?
- The same person appearing in the same year with multiple, differently-categorized advisorship rows.
- Cancelled/voluntary advisorship rows (`Cancelado`, `Modalidade = Voluntário`) still carrying a category.
- Report filenames/`Ano` column disagreeing with the advisorship `Inicio`/`Fim` year — which year wins?
- Advisor whose campus/category differs from the advisorship execution campus.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose, for each canonical advisorship record, the advisorship **category** that applied to it in its own year, taken from its source report row — replacing any static, absent, or empty placeholder where the source supplies the value. Category here is the **program** (e.g. PIC, PICTI, PICTI-Jr, PIBIC, PIVIC) together with the **provider** that funds it (FAPES, IFES, CNPq, Voluntário, ...), matching the report's `Programa` and `AgFinanciadora` columns for that advisorship.
- **FR-002**: System MUST resolve the category for the advisorship's **specific year defined by the report/directory year** in which its row was collected (e.g. a row under `data/raw/sigpesq/advisorships/2016/` is a 2016 advisorship), regardless of any `Inicio`/`Fim` span across calendar years. No value from another year MAY be reused for it.
- **FR-003**: System MUST apply the fetched category values in the **standalone advisorship export only** (`advisorships_canonical.json`). The per-person advisorship lists inside `researchers_canonical.json` and the `advisorships_tracking.json` provenance export are out of scope and MUST keep their current shape.
- **FR-004**: System MUST keep advisorship count/id parity with the source reports after the refactor (no collapses of same-year rows, no drops, no duplication).
- **FR-005**: System MUST preserve at least the current advisorship fields and consumers' expectations (additive changes preferred); removing or renaming an existing field requires justification.
- **FR-006**: New or changed category values MUST comply with LGPD — no raw personal data (CPF, telefone, e-mail) MAY appear in exported category fields; existing anonymization on the pipeline applies.
- **FR-007**: System MUST populate the underlying advisorship category data for new ingestions — the `advisorships.program` column and the provider via the fellowship funding-agency link — so the fetched values exist in the database, not only in the export layer.
- **FR-008**: Advisorship records created from Lattes (no SigPesq report) MUST produce a defined, documented category value rather than silently relying on a fallback.
- **FR-009**: Empty/absent category in a source row MUST be represented explicitly and MUST NOT be invented or filled with a neighbouring row's value.

### Key Entities *(include if feature involves data)*

- **Advisorship**: A bolsa/orientação initiative with a student, a supervisor, start/end dates and a fellowship; per the DB it currently has `type` and `program` columns left entirely null by ingestions — the target of the per-year category value.
- **Advisorship Category (program + provider)**: The value to fetch per advisorship/year — `Programa` (PIC, PICTI, PICTI-Jr, PIBIC, PIVIC, PIBITI, ...) qualified by `AgFinanciadora` (FAPES, IFES, CNPq, Voluntário, ...). On the latest canonical export this pair is missing from 84% of advisorship records and never reached the `type`/`program` columns.
- **Person (Student/Supervisor)**: The two people in an advisorship (`advisorship_members` roles `Student` and `Supervisor`); their per-year categorical data (campus, course, role) should be exposed per advisorship.
- **Fellowship / Program**: The funding program (PIVIC, PIBIC, PIBITI…); currently materialised as a fellowship linked to the advisorship rather than a per-row advisory value.
- **SigPesq advisorship report row**: Source of truth per year — one row per advisorship/year with `Ano`, `Programa`, `Modalidade`, `Edital`, `Curso`, `Campus`, acceptance and cancellation flags.
- **Source Record**: The tracking artifact persisting the raw report row (anonymized) that backs the fetched values and provenance (FR-005, User Story 3).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of advisorship records whose source report row defines a category value, the canonical advisorship export exposes that value (0 nulls where the report supplied a value).
- **SC-002**: *(covered by SC-001 — consolidated)* 0 advisorship records show the generic static label/empty type for data that exists in the source (100% of report rows with a program/category have it surfaced).
- **SC-003**: Advisorship count per report year in the canonical export matches the source report's row count for that year (parity: no collapsed, dropped, or duplicated same-year rows).
- **SC-004**: For a verification sample of advisorship work plans that appear in multiple report years, 100% of the advisorship rows expose the program/provider of their own report/directory year (no cross-year contamination).
- **SC-005**: Nightly/new ingestion run completes with zero new raw PII introduced into exported category fields (LGPD gate remains green on the audit scan).
- **SC-006**: The full pipeline test suite (pytest/lint/format/type checks) passes — `make ci-check` green.

## Assumptions

### Clarifications (confirmed with the user)

- **Category** = the advisorship **program** (e.g. PICTI, PIC, PICTI-Jr, PIBIC, PIVIC) whose value depends mainly on the **provider** (FAPES, IFES, CNPq, Voluntário); both come from the advisorship's report row (`Programa` + `AgFinanciadora`) for its specific year.
- **Specific year** (Q2 = A): the **report/directory year** in which the advisorship row was collected (e.g. `advisorships/2016/` ⇒ 2016), irrespective of `Inicio`/`Fim` spans.
- **Artifact scope** (Q3 = C): **only the standalone advisorship export** (`advisorships_canonical.json`); researcher advisorship lists and tracking exports are unchanged.
- **Normalization**: emitted values preserve the report's spelling (e.g. `Pivic`, `Fapes`); uppercase forms like `PICTI`/`FAPES` used elsewhere in this spec are illustrative and represent the same program/provider.
- **Out of scope**: per-person categorical data (student/supervisor campus, course, role) is not surfaced by this feature; only advisorship `program`/`provider`/`year` are added.

- The raw SigPesq advisorship reports per year are the trusted source for the category values where the advisorship came from SigPesq; advisorship rows from Lattes have no such report and need their own defined sourcing (FR-008).
- Additive schema changes are preferred to preserve downstream consumers (dashboards/marts).
- The existing advisorship identity collisions (same work plan, consecutive years) already fixed in earlier features must not regress (FR-004, SC-003).
- Category values themselves are not personal data in the LGPD sense; the pipeline's existing anonymization of CPF/telefone/e-mail still applies to any row-derived data carried into exports (FR-006).
- Backfilling the historical advisorship `type`/`program` columns for already-ingested DB rows is in scope only if required to make the exports correct without full re-ingestion — to be decided in planning.