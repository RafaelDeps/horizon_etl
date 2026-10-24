# Specification Quality Checklist: SQLite WAL Journaling for the ETL Database

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-23
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Validation pass 1 (2026-10-23): all items pass.
- The technical names (SQLite, write-ahead logging, synchronisation level,
  `libbase`, `eo_lib`, `research_domain`, `db/horizon.db`, the companion
  `-wal`/`-shm` files, `python app.py <phase>`) are **constraints the user
  supplied**, following the convention of specs 015–017. The feature *is* a
  database setting, so the spec cannot describe it without naming it. The spec
  says *what* must hold: every connection uses the setting, identical data, a
  self-contained final file, a clean reset, direct readers unaffected. It leaves
  *how* to `/speckit-plan`: where the listener is registered so every phase
  process gets it, how the final file is made self-contained (checkpoint,
  switching the journal mode back, or another way), and how the reset removes
  the companion files.
- Code reading during specification found facts that shaped the requirements:
  - horizon_etl creates no database engine of its own; every engine comes from
    the libraries (`eo_lib`'s connection-client singleton among them), so the
    setting must reach connections the ETL does not create (FR-001, FR-003).
  - Many modules open `db/horizon.db` directly with `sqlite3.connect`
    (person and reference consolidators, duplicate auditor, anonymisation
    backfill, ETL reporter, several scripts), which shaped FR-008.
  - `make db-clean` removes only `db/horizon.db`; a stale `-wal` file next to a
    new database is a known corruption hazard, which shaped FR-007.
  - `.gitignore` already ignores `db/*.db-*`, so the companion files never reach
    the repository.
- SC-001 sets 60% of the baseline as the bar, with the measured 50% as the
  reference, because time targets are references, not blockers.
