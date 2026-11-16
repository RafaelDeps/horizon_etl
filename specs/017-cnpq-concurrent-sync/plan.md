# Implementation Plan: Concurrent CNPq Group Sync with a Single Writer

**Branch**: `020-cnpq-concurrent-sync` | **Date**: 2026-10-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/017-cnpq-concurrent-sync/spec.md`

## Summary

The CNPq phase spends 71% of its time waiting for the DGP portal, one group at a
time, and re-reads the whole researcher register for every group. The plan has
five parts:

1. **Split each group's work in two.** A fetch stage calls the existing
   `CnpqCrawlerAdapter.get_group_data` from worker threads, up to 4 in flight. A
   write stage, the Prefect task `sync_single_group`, now receives the fetched
   data and runs today's database steps, on the flow thread only, in the
   original group order.
2. **Adaptive gate.** It bounds the fetches in flight, halves the limit when
   ≥ 4 failures happen within 60 s, and restores it one step after 120 s
   without failures.
3. **ETL-level retries.** Up to 3 attempts, waiting 30 s and 90 s ±20% outside
   the gate, on top of the library's own 3 tries.
4. **Researcher index.** `load_researcher_index` is loaded once per phase and
   passed to `sync_members`, replacing the per-group `get_all()` (TD-008). Its
   order and content were verified identical.
5. **Summary line and validation.** A final `CNPq fetch: …` line. Validation is
   a controlled replay with the 350 captured payloads, plus a full timing run.

Evidence and rejected alternatives are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 in CI; 3.14 locally.

**Primary Dependencies**: Prefect 3.6.23, `concurrent.futures` / `threading` (standard library), `dgp_cnpq_lib` (unchanged, Playwright sync API), loguru. No new dependency.

**Storage**: SQLite. A single writer (the flow thread). No schema change.

**Testing**: pytest with a fake adapter: controllable delays and failures, an injected sleep and clock. Controlled replay with captured payloads. A full timing run.

**Target Platform**: Linux, local first, then GitHub Actions (`ubuntu-latest`).

**Project Type**: Batch ETL (Prefect flow run as the `cnpq` subprocess phase).

**Performance Goals**: The `cnpq` phase clearly below the 54.4 min of the spec 016 run, ~20–35 min expected (guidance, not a hard bar).

**Constraints**:
- At most `HORIZON_CNPQ_WORKERS` (default 4) concurrent portal fetches.
- No database access in worker threads.
- Identical produced data.
- `dgp_cnpq_lib` untouched.

**Scale/Scope**: ~350 groups, ~7 600 researchers and payloads of ~15 KB each. All payloads fit in memory.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment | Result |
|---|---|---|
| **I. Ports & Adapters** | Fetching still goes through `CnpqCrawlerAdapter` (`src/adapters/sources/`). The concurrency and retry orchestration lives in the flow (`src/flows/cnpq/`). `CnpqSyncLogic` (core logic) only gains an optional parameter. No adapter import is added to core logic. | PASS |
| **II. Domain-First Data Modeling** | No new domain concept. `FetchOutcome` and `AdaptiveGate` are transient orchestration structures, never persisted. | PASS |
| **III. Prefect Flow Orchestration** | The phase remains the `Sync CNPq Research Groups` flow, with its Telegram hooks. The per-group write remains a Prefect task. Fetch workers are plain threads doing network I/O only, like the adapter call that already runs inside the task today. | PASS |
| **IV. Audit-Driven Data Quality** | The summary report is unchanged. A new summary line covers retries, failures after retries and concurrency reductions. Equivalence is proven by the replay with captured payloads. | PASS |
| **V. LGPD Compliance** | New log lines hold counts only. Captured payloads used for the replay stay outside the repository, in the session scratchpad. | PASS |
| **Data Integrity & Clean-State Ingestion** | No persisted state between runs. The researcher index is rebuilt per phase. | PASS |
| **Quality gates** | Tests are added for the flow and for `sync_members`. The touched files are formatted. The repository-wide `make ci-check` failures pre-date these specs. | PASS (pre-existing repo-wide failures documented) |

**Post-design re-check**: unchanged; all PASS. The SigPesq phase stays sequential.

## Findings during planning

1. **Write exceptions are not caught today.** `sync_single_group` lets
   database-stage exceptions propagate, which fails the CNPq flow. The spec's
   edge case was corrected to say this behaviour is **preserved**.
2. **The library already retries.** `dgp_cnpq_lib` retries each page 3 times
   (1–10 s), and the adapter turns any failure into `None`. The ETL retry is a
   slower second layer (R4).
3. **The replay inputs already exist.** The spec 016 validation database
   contains all 350 `cnpq_group_payload` records. They were exported read-only to
   the scratchpad, before a future `make weekly-flows` resets the database (R8).
4. **Playwright's sync API works from worker threads.** 4 threads, 8 fetches,
   peak 4, all correct (R2).

## Project Structure

### Documentation (this feature)

```text
specs/017-cnpq-concurrent-sync/
├── spec.md
├── plan.md              # This file
├── research.md          # R1–R9
├── data-model.md        # FetchOutcome, AdaptiveGate, lifecycle, writer, counters
├── quickstart.md        # Tests, controlled replay, timing run
├── contracts/
│   └── cnpq-sync.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks (not created here)
```

### Source Code (repository root)

```text
src/
├── flows/cnpq/
│   ├── groups.py              # CHANGED: flow = bounded fetch + ordered writer; sync_single_group
│   │                          #          takes data/researcher_index; summary line
│   └── concurrent_fetch.py    # NEW: AdaptiveGate, fetch_with_retries, fetch_all
│                              #      (pure orchestration, injectable sleep/clock)
└── core/logic/strategies/
    └── cnpq_sync.py           # CHANGED: sync_members(researcher_index=None) + hit/created counters

tests/
├── test_cnpq_concurrent_fetch.py  # NEW: gate bound, order, retries, burst rule, N=1, config
└── test_cnpq_sync.py              # EXTENDED: researcher_index path, created-then-found
```

**Structure Decision**: The existing single-project layout. The new module sits
next to the flow it serves, because it is orchestration, not business logic.

## Implementation outline (for `/speckit-tasks`)

1. **Base copy for the replay.** Copy the spec 016 source into the scratchpad,
   and build `pre_cnpq.db` from the frozen SigPesq inputs.
2. **Tests first:**
   - the gate bound, through a fake adapter that records concurrency;
   - writes on the flow thread, in order, with completions deliberately out of
     order;
   - retries, with an injected sleep recording the waits;
   - the burst rule, with an injected clock;
   - N = 1 and invalid configuration;
   - `sync_members` with `researcher_index`, including a researcher created by
     group A and found by group B, and `get_all` not called.
3. **`concurrent_fetch.py`:** `AdaptiveGate`, `fetch_with_retries` and
   `fetch_all(groups, adapter_factory, max_workers, sleep, clock)`, which yields
   `FetchOutcome`s by index.
4. **`sync_single_group(group_info, data=_NOT_FETCHED, researcher_index=None)`.**
   Keep the old fetch path for the default.
5. **The flow.** Read `HORIZON_CNPQ_WORKERS`, load the researcher index once,
   start `fetch_all`, write in order, and log the summary line.
6. **`CnpqSyncLogic.sync_members(researcher_index=None)`** with the counters.
7. **Formatting, lint, the full suite.**
8. **Controlled replay** (base against feature).
9. **Full timing run** and the validation report.
10. **Backlog.** Close TD-008 and TD-014; note any retry or burst tuning learned
    from the run.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Custom adaptive gate instead of a fixed-size pool | FR-008 requires reducing concurrency when resets cluster, while back-off sleeps must not hold a fetch slot (FR-007). | A fixed `ThreadPoolExecutor(max_workers=4)` cannot shrink, and a sleeping worker would occupy one of the 4 slots. |
