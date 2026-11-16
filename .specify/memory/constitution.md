<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 2.0.0 (MAJOR: a governance section is redefined)
Reason: new phase of the project approved by the maintainer and their manager
  on 2026-10-26 — the database persists between runs and ingestion becomes
  incremental, driven by idempotent source hashes and permanent horizon_ids.
Modified sections:
  - "Data Integrity & Clean-State Ingestion" → "Data Integrity & Persistent
    Incremental Ingestion" (rewritten as seven rules: persistent database,
    idempotency as a fixpoint, re-creatable from sources, published identity
    history, raw inputs, provenance, sources of truth)
Unchanged: Core Principles I–V, Development Workflow & Quality Gates,
  Governance.
Added sections: none (the rewritten section keeps its position)
Removed sections: none
Templates reviewed:
  - .specify/templates/plan-template.md ✅ no change needed (generic
    Constitution Check gate; no clean-state or db-reset wording)
  - .specify/templates/spec-template.md ✅ no change needed
  - .specify/templates/tasks-template.md ✅ no change needed
  - .specify/templates/checklist-template.md ✅ no change needed
  - .specify/templates/commands/ — not present in this repository
Runtime docs reviewed:
  - README.md ✅ make db-reset usage still valid (rule 3 keeps it)
  - docs/flows-and-entrypoints.md ✅ describes today's behaviour
    (make weekly-flows still resets); update when spec B drops the
    unconditional reset
Follow-up TODOs:
  - Spec B (persistent weekly) must remove db-reset from make weekly-flows and
    update docs/flows-and-entrypoints.md accordingly.
  - Spec D (incremental downloads) must stop clean_lattes_json_output from
    wiping data/lattes_json/ (rule 5) and add the download manifest (rules 5–6).
-->

# Horizon ETL Constitution

## Core Principles

### I. Ports & Adapters Architecture (NON-NEGOTIABLE)

All external system interactions — SigPesq, Lattes, CNPq, database clients,
JSON sinks — MUST be mediated through port contracts defined in
`src/core/ports/`. Business logic in `src/core/logic/` MUST NOT import
directly from `src/adapters/`. Flows in `src/flows/` orchestrate adapters and
do not contain business rules.

**Rationale**: Prevents tight coupling between ETL logic and external systems.
Enables source substitution (e.g., switching from SQLite to Supabase) without
touching core logic. Enforces testability — core logic is always testable
without live external systems.

**Enforcement**: Any PR that imports an adapter class directly inside
`src/core/logic/` is a violation. Code review MUST reject it.

### II. Domain-First Data Modeling

Canonical domain entities come from the `research-domain` external package.
Internal ETL code MUST map raw source data into these entities — it MUST NOT
redefine domain concepts (persons, research groups, initiatives, advisorships,
fellowships, organizations) in isolation. All canonical exports MUST serialize
domain-aligned entities into JSON artifacts under `data/exports/`.

**Rationale**: A single canonical data model shared across the Horizon
ecosystem prevents drift between ETL output and dashboard/mart consumers.
Domain ownership lives in `research-domain`; Horizon ETL is a consumer.

**Enforcement**: New entity types introduced in ETL code require a
corresponding addition to `research-domain` (or explicit justification as
ETL-only transient structures). Exported JSON schemas must be derivable from
domain entities.

### III. Prefect Flow Orchestration (NON-NEGOTIABLE)

All ETL operations MUST be implemented as Prefect flows registered under
`src/flows/`. No ETL logic may run outside a Prefect flow context via
standalone scripts. Every flow MUST register state-change hooks that emit
completion reports to the configured Telegram channel (Completed, Failed,
Crashed, Cancelled states).

**Rationale**: Prefect provides execution history, retry semantics, and
observability for all pipeline runs. Bypassing flows creates blind spots in
production monitoring. Telegram hooks ensure the team is notified of any
pipeline state without polling the Prefect UI.

**Enforcement**: Scripts in `src/scripts/` are operational utilities
(auditing, diagnostics) — they may read from DB/artifacts but MUST NOT
perform ingestion or export outside a flow. Any new data ingestion MUST have
a corresponding Prefect flow.

### IV. Audit-Driven Data Quality

Every ingestion run MUST produce a verifiable audit trail. Deduplication,
entity reconciliation, and export validation are first-class architectural
concerns. `make etl-report` MUST produce a clean report before any export is
considered production-ready. Audit scripts under `src/scripts/` are part of
the architecture, not supplementary tooling.

**Rationale**: Academic data from SigPesq, Lattes, and CNPq overlaps and
conflicts. Without active audit validation, stale or duplicate records
silently corrupt downstream dashboards and reports.

**Enforcement**: New loaders or exporters MUST include or update a
corresponding audit check (e.g., deduplication count, reconciliation report).
PRs that add ingestion without audit coverage require explicit justification.

### V. LGPD Compliance by Default

Personal identifiers — CPF, telefone, e-mail — MUST be anonymized in all
exported artifacts (`data/exports/`, `data/reports/`) and in stored database
records when anonymization has been applied. No personal data MAY appear in
any output file, log, or report without explicit authorization tied to a
documented legal basis. Access to non-anonymized data MUST be logged in an
immutable audit trail recording user, timestamp, and subject.

**Rationale**: LGPD (Lei Geral de Proteção de Dados) requires that personal
data not be exposed beyond the minimum necessary for the stated processing
purpose. ETL systems are high-risk vectors for PII leakage via exported files.

**Enforcement**: All new export flows MUST pass through the anonymization
layer for CPF, telefone, and e-mail fields before writing output files. Any
code path that writes these fields in clear text to `data/exports/` or
`data/reports/` is a compliance violation and MUST NOT be merged.

## Data Integrity & Persistent Incremental Ingestion

1. **Persistent database.** `db/horizon.db` MAY persist between runs, locally
   and in GitHub Actions. A run only fetches and writes what is new or changed,
   detected by comparing source content hashes with the hashes stored in the
   database.

2. **Idempotency.** Processing the same source input again MUST NOT change the
   database: no new tracking record, no change log entry, no rewritten row.
   Idempotency is measured as a fixpoint: on a populated database, the second
   and later passes over identical inputs write nothing. Keys and hashes MUST
   be derived only from source data, never from database ids or processing
   order.

3. **Re-creatable from sources.** The database MUST still be fully
   re-creatable from scratch via `make db-reset` (or `make full-refresh`)
   followed by the ingestion flows, and a rebuild from the same source inputs
   MUST give the same entities as the incremental database. Rebuilds happen on
   demand and whenever the version of the key/hash/id rules changes; a
   database whose recorded rule version differs from the code's MUST be
   rebuilt before use.

4. **Published identity history.** The permanent entity ids (`horizon_id`) and
   their aliases are a contract with downstream consumers. The history of ids
   already published (from the previous database when it exists, otherwise
   from the versioned `exports_canonical.zip`) MAY be read as an input, but
   only to keep old ids resolvable as aliases. It MUST NOT supply or change
   any entity data. This is the only ETL artifact allowed to feed a run.

5. **Raw inputs.** Snapshot sources that are downloaded whole each run (the
   SigPesq reports in `data/raw/sigpesq/`) MUST still be cleared before their
   download. Per-item raw caches (Lattes curricula, CNPq group pages, project
   PDFs) MAY be kept between runs and refreshed on a rotation, with a manifest
   of download dates. A cached item MUST be replaced only after its new
   download succeeds, so a failed download never drops data.

6. **Provenance.** Data kept from earlier runs never expires because of age
   (old data is better than none), but every kept document MUST record when it
   was downloaded, and that date MUST be available in the exports.

7. **Sources of truth.** Apart from rule 4, no ETL artifact (export JSON,
   report) is a source of truth. Only the source inputs, flows, strategies,
   loaders and domain entities define correct behavior.

**Rationale**: The weekly run must scale to thousands of curricula and survive
source outages without re-downloading and rebuilding everything. Persistence
is safe only when every write is idempotent and a rebuild from sources stays
possible as a check. Downstream consumers need ids that do not change between
weeks or rebuilds.

## Development Workflow & Quality Gates

`make ci-check` — which runs linting (flake8), formatting checks (black,
isort), type checking (mypy), and the full test suite (pytest) — MUST pass
before any branch is merged. This is the minimum quality gate.

Makefile targets are the canonical entry points for all operations. Direct
`python` invocations are permitted for development exploration but MUST NOT
replace Makefile targets in documentation or CI. Code style follows black
(88-character line length) and isort (black profile).

Tests live in `tests/`. Integration tests in `tests/integration/` may require
a live Prefect server and local DB — they are excluded from fast CI runs but
MUST pass before release. New flows MUST have at least one corresponding test
in `tests/`.

## Governance

This constitution supersedes all other practice documents, architectural
notes, and conventions in this repository. In case of conflict, this document
takes precedence.

**Amendment procedure**: Amendments require updating this file with a
version bump, updating the Sync Impact Report comment, and propagating
changes to affected templates (plan, spec, tasks). Major changes — removal or
redefinition of a principle — require team review before merge.

**Versioning policy**:
- MAJOR: Backward-incompatible governance change (principle removal or
  fundamental redefinition).
- MINOR: New principle or section added, or materially expanded guidance.
- PATCH: Clarifications, wording improvements, non-semantic refinements.

**Compliance review**: Constitution compliance is reviewed at each
`/speckit-plan` gate (Constitution Check section) and at PR review. Automated
linting enforces code-level rules (formatting, imports). Architectural rules
are enforced via code review.

**Version**: 2.0.0 | **Ratified**: 2026-05-16 | **Last Amended**: 2026-10-27
