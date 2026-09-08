# Implementation Plan: Concurrent CNPq group fetch, serial write

**Branch**: `012-cnpq-concurrent-fetch` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/012-cnpq-concurrent-fetch/spec.md`

## Summary

Fetching a group's page from the CNPq portal — 80.9% of the CNPq sync phase's
50.2-minute baseline — happens strictly one group at a time today, even
though each fetch is independent. This feature runs fetches concurrently
using Prefect's `ProcessPoolTaskRunner` (process isolation, required because
this project has a documented incident of concurrent native browser state
crashing a run) while keeping the database write exactly as serial as it is
today — one group at a time, in the flow's own process, sharing the same
`researcher_index` list feature 011 introduced. The fetch function moves to a
small, dependency-light module so a spawned worker process never has to
import the database/ORM stack. Concurrency is configurable via an
environment variable, defaulting to 4 — the level already agreed for this
portal.

## Technical Context

**Language/Version**: Python 3.14.4 (`.venv`)

**Primary Dependencies**: Prefect 3.6.23 (`ProcessPoolTaskRunner`,
confirmed present and 'spawn'-based), `dgp_cnpq_lib` (via
`CnpqCrawlerAdapter`)

**Storage**: SQLite (`db/horizon.db`) — write path unchanged by this feature

**Testing**: pytest — `tests/test_cnpq_groups_flow.py`,
`tests/test_cnpq_sync.py` (unchanged assertions), plus new coverage for the
fetch/write split and ordering guarantee

**Target Platform**: Linux

**Project Type**: Single-project ETL pipeline

**Performance Goals**: CNPq sync phase duration drops by ≥50% from the 50.2
minute baseline (SC-001); concurrency set to 1 reproduces today's duration
(SC-003)

**Constraints**: fetch MUST run in process isolation, never threads (FR-005,
R1); the write step MUST remain strictly serial and MUST NOT change its
invocation model relative to the already-shipped 011 behavior (R4); the fetch
function's defining module MUST NOT import the database/ORM/tracking stack
(R3)

**Scale/Scope**: 351 CNPq groups, 4 concurrent fetch workers by default

## Constitution Check

| Principle | Status | Justification |
|---|---|---|
| **I. Ports & Adapters** | ✅ Compliant | The new `@task` wrapper lives in `src/flows/cnpq/fetch_worker.py` (flow layer), calling existing `src/adapters/` methods unchanged. The adapter itself gains no Prefect dependency. |
| **II. Domain-First** | ✅ Compliant | No new entity. The fetch result is the same plain-dict shape `sync_single_group` already assembles from `get_group_data`/`extract_members`/`extract_leaders`/`extract_research_lines` today, just returned as one bundle instead of built inline. |
| **III. Prefect Flow** | ✅ Reinforced | Concurrency is expressed through Prefect's own task runner, not a hand-rolled `concurrent.futures` pool hidden in an adapter (which an earlier, superseded version of this plan — `relatorio.md` — had proposed before `ProcessPoolTaskRunner` was confirmed available). This is the more idiomatic fit for a project whose constitution privileges Prefect for orchestration. |
| **IV. Audit-Driven** | ✅ Neutral | `tracking_recorder` calls remain in the serial write step, untouched, with the same call site and same data. |
| **V. LGPD** | ✅ Neutral | Fetch results cross a process boundary via cloudpickle, not disk — no new export surface, no new file containing personal data. |
| **Data Integrity** | ✅ Reinforced | FR-003/FR-004/FR-007 require the write step's serialization and the researcher-registry guarantee to be provably unchanged — equivalence is a gate, not an assumption. |
| **Quality Gates** | ✅ Compliant | black/isort/flake8 on touched and new files; full suite must show no regression (SC-005). |

**Gate before Phase 0**: PASS. **Gate after Phase 1**: PASS.

## Project Structure

### Documentation (this feature)

```text
specs/012-cnpq-concurrent-fetch/
├── plan.md              # This file
├── spec.md              # What and why
├── research.md          # Design decisions (Phase 0)
├── data-model.md         # Fetch result shape, concurrency model (Phase 1)
├── quickstart.md         # How to verify (Phase 1)
├── contracts/
│   └── fetch_write_contract.md   # The fetch/write split, precisely
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/flows/cnpq/
├── fetch_worker.py               # NEW — @task-decorated fetch, lean imports
│                                 #   (only prefect + the adapter), so a
│                                 #   ProcessPoolTaskRunner worker never
│                                 #   imports the database/ORM stack
└── groups.py                     # CHANGED — sync_cnpq_groups_flow gains a
                                  #   task_runner=ProcessPoolTaskRunner(...);
                                  #   submits fetch_worker calls, processes
                                  #   futures in order, calls the existing
                                  #   write path (sync_group/sync_members/
                                  #   sync_knowledge_areas) as a direct call

src/adapters/sources/
└── cnpq_crawler.py               # UNCHANGED — its methods are called from
                                  #   fetch_worker.py exactly as they are
                                  #   called from groups.py today

tests/
├── test_cnpq_groups_flow.py      # CHANGED — coverage for concurrent fetch,
                                  #   serial write ordering, failure isolation
└── test_cnpq_fetch_worker.py     # NEW — the fetch wrapper in isolation
```

**Structure Decision**: one new small module (`fetch_worker.py`) rather than
adding Prefect concerns to `cnpq_crawler.py` (would blur the adapter/flow
boundary) or defining the task inline in `groups.py` (would defeat the
lean-import goal that is this feature's core technical requirement — see
research.md R3).

## Complexity Tracking

| Point | Description | Mitigation |
|---|---|---|
| **Two modules now describe "how to get one group's data"** | `fetch_worker.py` orchestrates the same four adapter calls `sync_single_group` used to make inline; a reader has to look in two places instead of one. | The fetch result's shape is documented explicitly in data-model.md and contracts/fetch_write_contract.md, and `fetch_worker.py` is intentionally small (one function) — the split exists specifically to satisfy the lean-import requirement, not for its own sake. |
| **Process-per-fetch overhead** | Spawning a fresh interpreter per task has real cost (interpreter startup, module import, cloudpickle round-trip) that a thread would not have. | Acceptable because the dominant cost per fetch (~7.0s of network/Playwright time) dwarfs interpreter startup, and `ProcessPoolTaskRunner` reuses worker processes across submitted tasks rather than spawning fresh per call — to be confirmed empirically during implementation (see quickstart.md) rather than assumed. |
| **Futures held in memory for the whole phase** | Submitting all 351 fetches up front (bounded by the pool's `max_workers`) keeps up to that many results resident while the serial writer catches up. | Each result is a small plain dict (group metadata + members + research lines); at the scale measured (351 groups), this is not a meaningful memory concern, and the alternative — a bounded sliding window — adds complexity the measured scale does not justify. |
