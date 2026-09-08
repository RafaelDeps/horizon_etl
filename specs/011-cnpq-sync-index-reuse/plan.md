# Implementation Plan: Reuse the researcher index in CNPq member sync

**Branch**: `011-cnpq-sync-index-reuse` | **Date**: 2026-09-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/011-cnpq-sync-index-reuse/spec.md`

## Summary

The CNPq group-member sync asks the researcher registry "who exists?" once per
group — 351 times per weekly run — even though the answer cannot change
mid-run except by the sync's own writes. Each ask costs 8.81 s against the
current database because the query eagerly loads four unrelated collections
per researcher; the total is ~51.5 minutes wasted per run, and it grows with
the researcher table, not with the group count.

A lightweight replacement already exists and is proven in production
(`load_researcher_index` / `ResearcherRef`, feature 007), measured at 0.03 s
for the same data. This feature moves the researcher lookup from inside the
per-group sync call up to the flow, building the index once and threading it
through the task boundary — the same shape of fix already applied to the
Lattes ingestion flows. A second, smaller instance of the same pattern (the
role lookup, currently read once per *member* instead of once per *group*) is
fixed alongside it, in place, with no cross-call state needed.

## Technical Context

**Language/Version**: Python 3.14.4 (`.venv`)

**Primary Dependencies**: SQLAlchemy 2.0.x, Prefect 3.6.23, research-domain

**Storage**: SQLite (`db/horizon.db`), tables `persons`, `researchers`, `roles`

**Testing**: pytest — `tests/test_cnpq_sync.py` (existing), plus new cases in
the same file or a sibling, following the `ProjectLoader.__new__` + `MagicMock`
pattern from `tests/test_project_loader_matching.py`

**Target Platform**: Linux

**Project Type**: Single-project ETL pipeline

**Performance Goals**: researcher registry read 1 time per CNPq sync run
(down from 351); registry-reading cost drops from ~51.5 minutes to under a
minute for the same data

**Constraints**: `CnpqSyncLogic()` is constructed fresh once per group inside
the `sync_single_group` Prefect task, so no `self`-level cache persists across
groups — the index must be built in the flow and passed down as an explicit
parameter, requiring `cache_policy=NO_CACHE` on the task per the existing
Lattes precedent; the self-healing joined-table-insert block in `sync_members`
must remain untouched

**Scale/Scope**: 351 CNPq groups, 6,853 researchers, ~19,677 members per run

## Constitution Check

| Principle | Status | Justification |
|---|---|---|
| **I. Ports & Adapters** | ✅ Compliant | Change confined to `src/core/logic/strategies/cnpq_sync.py` and `src/flows/cnpq/groups.py`; no new adapter import in `src/core/logic/`. |
| **II. Domain-First** | ✅ Compliant | No new entity. `ResearcherRef` is reused as-is from feature 007; `Researcher` remains the canonical entity. |
| **III. Prefect Flow** | ✅ Compliant | No new flow. `sync_single_group` remains a task with the same Telegram state handlers; only its parameter list and cache policy change. |
| **IV. Audit-Driven** | ✅ Neutral | No change to what is recorded — `tracking_recorder` calls inside `sync_members` are untouched. |
| **V. LGPD** | ✅ Neutral | `ResearcherRef` carries the same fields already exposed by feature 007 (no new PII surface); nothing here is exported or logged in bulk. |
| **Data Integrity** | ✅ Reinforced | FR-003/FR-004 require the matched/created researcher and role sets to be identical to today's behavior — the feature explicitly targets performance only, with equivalence as a gate. |
| **Quality Gates** | ✅ Compliant | black/isort/flake8 on touched files; full test suite must show no regression (SC-004). |

**Gate before Phase 0**: PASS. **Gate after Phase 1**: PASS.

## Project Structure

### Documentation (this feature)

```text
specs/011-cnpq-sync-index-reuse/
├── plan.md              # This file
├── spec.md              # What and why
├── research.md          # Design decisions (Phase 0)
├── data-model.md         # Index/session shape (Phase 1)
├── quickstart.md         # How to verify (Phase 1)
├── contracts/
│   └── sync_members_contract.md   # Call-site contract for the touched function
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/flows/cnpq/
└── groups.py                    # CHANGED — build the researcher index once
                                 #   in sync_cnpq_groups_flow, pass it into
                                 #   sync_single_group (NO_CACHE), forward it
                                 #   to CnpqSyncLogic.sync_members

src/core/logic/strategies/
└── cnpq_sync.py                 # CHANGED — sync_members accepts the index as
                                 #   a parameter instead of calling
                                 #   self.res_ctrl.get_all(); role lookup
                                 #   hoisted out of the per-member loop

tests/
└── test_cnpq_sync.py            # CHANGED — coverage for: index read once per
                                 #   run, cross-group researcher reuse,
                                 #   role read once per group
```

**Structure Decision**: the fix stays inside the two files that already own
this logic — no new module. The researcher index is built in the flow
(`groups.py`), matching where its Lattes counterpart already lives
(`src/flows/lattes/advisorships.py`, `src/flows/lattes/projects.py`), so
anyone comparing the two ingestion paths finds the same shape in both places.

## Complexity Tracking

| Point | Description | Mitigation |
|---|---|---|
| **`sync_members` gains a required parameter** | Any other caller of `sync_members` (if one exists beyond `sync_single_group`) must be updated too, or the change is incomplete. | Verified by grep before implementation that `sync_members` has exactly one caller in `src/`, inside `sync_single_group`. Task list includes an explicit check for this. |
| **Index staleness across groups** | If the append-on-create behavior in `resolve_or_create_researcher` were ever bypassed for this call site, a later group could silently duplicate a researcher created by an earlier one — the exact failure class feature 008 exists to guard against. | Reused, not reimplemented: `resolve_or_create_researcher` already appends in the correct shape for `ResearcherRef` lists (feature 007), and this feature adds a dedicated cross-group test (User Story 1, Acceptance Scenario 3) rather than trusting the existing feature-007 test coverage by inference. |
