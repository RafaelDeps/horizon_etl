# Research: concurrent CNPq group fetch, serial write

**Feature**: 012-cnpq-concurrent-fetch | **Date**: 2026-09-04

## R1 — Which Prefect task runner, and why not the default

**Decision**: `ProcessPoolTaskRunner(max_workers=N)`, configured explicitly on
the flow; never the default.

**Rationale**: confirmed by reading `prefect/flows.py`, a `@flow` with no
`task_runner` argument resolves to `ThreadPoolTaskRunner()`. Running the
fetch step — which drives a synchronous Playwright/Chromium session per call
— concurrently via threads means multiple native browser processes launched
from threads inside one Python process. This project has a documented
production incident of exactly this failure mode: concurrent native browser
state corrupting memory that a later, unrelated SQLite call then crashed on,
taking an entire run down (`src/flows/pipelines/weekly_orchestrator.py`'s own
module docstring). `ProcessPoolTaskRunner` avoids this by construction: each
worker is a separate OS process.

**Alternative considered and rejected**: `ThreadPoolTaskRunner` with a
smaller worker count, on the theory that fewer threads reduce risk. Rejected
because the risk is categorical (any concurrent native browser session inside
one process), not a matter of degree — the documented incident does not
suggest a "safe" thread count, only that isolation is what fixed it
(isolation is why every weekly phase already runs in its own process).

## R2 — `ProcessPoolTaskRunner`'s isolation guarantee, verified

**Decision**: rely on `ProcessPoolTaskRunner` as documented, without
additional fork-safety workarounds.

**Rationale**: its docstring, read directly from the installed package
(Prefect 3.6.23), states it uses the **'spawn'** multiprocessing start
method "for cross-platform consistency and to avoid issues with shared state
between processes" — each worker is a fresh Python interpreter with no
inherited memory from the parent. This is strictly safer than `fork` (which
copies the parent's memory, including any already-corrupted native state)
and is the same category of protection this project's earlier CNPq
parallelization plan (`relatorio.md`, written before this feature) asked for
explicitly by name (`forkserver`, at the time `ProcessPoolTaskRunner` was not
yet confirmed available) — 'spawn' satisfies the same requirement.

## R3 — Where the fetch function must live

**Decision**: a new, small module — `src/flows/cnpq/fetch_worker.py` —
containing a single `@task`-decorated function that wraps
`CnpqCrawlerAdapter`'s existing `get_group_data`, `extract_members`,
`extract_leaders`, and `extract_research_lines` methods, returning one plain
dict bundling everything the write step needs for one group.

**Rationale**: `ProcessPoolTaskRunner` requires task parameters and return
values to be cloudpickle-serializable, and spawns a fresh interpreter that
must import whatever module the task function is defined in to reconstruct
it. `src/adapters/sources/cnpq_crawler.py` — where the four methods this
feature calls already live — imports only `re`, `typing`, `dgp_cnpq_lib`, and
`loguru` (verified by reading the file), so a spawned worker reconstructing a
task defined there pays no database/ORM/tracking import cost. Defining the
`@task` in `src/flows/cnpq/groups.py` instead was considered and rejected:
that module imports `ResearcherController`, `CnpqSyncLogic`, and
`tracking_recorder`, so a worker resolving a task by reference to that module
would import the entire database stack on every spawn — the exact overhead
this design exists to avoid, and precisely the failure mode a prior version
of this plan (documented in `relatorio.md`, before `ProcessPoolTaskRunner`
was confirmed available) already identified as the reason to reject Prefect's
process pool at the time.

A dedicated small module, rather than putting the `@task` directly inside the
`src/adapters/` layer, keeps the Prefect dependency in `src/flows/` where it
already belongs per this project's Ports & Adapters principle — adapters stay
framework-agnostic; only the flow layer knows about Prefect.

## R4 — How the write step stays serial despite concurrent fetch

**Decision**: the flow submits every group's fetch via `.submit()` against
`ProcessPoolTaskRunner`, then iterates the resulting futures **in submission
order**, calling the existing write path — `sync_group` /
`sync_members` / `sync_knowledge_areas`, today bundled inside
`sync_single_group` — as a **plain function call**, never via `.submit()`.

**Rationale**: a task invoked directly (not through `.submit()`) executes
synchronously in the calling context — the flow's own process — regardless of
what task runner the flow is configured with. This is not new behavior this
feature introduces: it is how `sync_single_group` is already called today
(`sync_single_group(g_info, researcher_index)`, direct call, in the current
011 code), so the write step's execution model is unchanged by this feature.
Every write still happens one at a time, in the same process, sharing the
same `researcher_index` list feature 011 introduced — the mutation safety
that feature already established for the sequential case is untouched, because
from the write step's point of view nothing about how it is invoked has
changed; only what feeds it (a queue of already-fetched results, arriving
out of strict real-time order but consumed in submission order) is new.

**Alternative considered and rejected**: processing fetch results as they
complete (`as_completed`-style), rather than in submission order. Rejected
for the same reason the original `relatorio.md` plan rejected it: submission
order is deterministic and reproducible run to run, which matters for
debugging and for the equivalence check in SC-002 — the trade-off is a small
amount of head-of-line blocking (the write step waits for group N's fetch
even if group N+3 finished first), which is acceptable because fetches are
now the fast, overlapped part and writes are comparatively quick (8.2 of 50.2
minutes in the current baseline).

## R5 — Concurrency configuration

**Decision**: an environment variable, `CNPQ_FETCH_CONCURRENCY`, read once at
flow start, defaulting to 4.

**Rationale**: matches this project's existing convention for exactly this
kind of external-service-tuning knob —
`SIGPESQ_429_WAIT_SECONDS` in `src/adapters/sources/sigpesq/adapter.py` is
the same shape of setting (a number that controls load against an external
portal, tunable without a code change). Four is not a guess: it is the
concurrency level already decided by the person responsible for this project
in an earlier conversation about this same phase, specifically to avoid
overloading the CNPq portal. Setting it to `1` reproduces today's fully
sequential behavior exactly (SC-003), because `ProcessPoolTaskRunner` with
`max_workers=1` still isolates the single fetch in its own process — a
detail worth confirming during implementation (see quickstart.md) but not
expected to change wall-clock behavior meaningfully at that setting.

## R6 — Failure isolation

**Decision**: no change to how a failed fetch is represented — the fetch
task returns `None` (matching `CnpqCrawlerAdapter.get_group_data`'s existing
`Optional[Dict[str, Any]]` return type) on failure, and the flow's serial
loop checks for `None` before writing, exactly as `sync_single_group` does
today (`if not data: ... return {"success": False, ...}`).

**Rationale**: `ProcessPoolTaskRunner`'s own documentation notes it provides
"proper context propagation and error handling" — a worker process crashing
or the fetched call raising is expected to surface as a failed future rather
than silently corrupting other workers, matching FR-006's requirement that
one group's failure not affect others. This feature does not need to
invent new failure semantics, only preserve the existing ones across the new
process boundary.

## R7 — What does NOT move into the concurrent step

**Decision**: `sync_group`, `sync_members`, and `sync_knowledge_areas` are
untouched — same functions, same signatures, same call site shape, just
invoked from a slightly different position in the flow (after collecting a
fetch result from a future, instead of immediately after calling the adapter
directly).

**Rationale**: this feature's entire risk surface is the fetch/write split
and the process-isolation guarantee; touching the write path itself would
reopen questions feature 011 already closed (researcher/role registry
correctness) for no benefit, since the write path is not the bottleneck this
feature addresses.
