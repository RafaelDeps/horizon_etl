# Contract: the fetch/write split

**Feature**: 012-cnpq-concurrent-fetch | **Date**: 2026-09-04

Internal contract between the new concurrent fetch step and the unchanged
serial write step — not a public API, documented because getting this
boundary wrong is exactly how the feature's two hard constraints (FR-003,
FR-005) would be violated.

## What runs concurrently (in worker processes)

- `fetch_worker`'s single task: `get_group_data`, `extract_members`,
  `extract_leaders`, `extract_research_lines` — all read-only against the
  CNPq portal, all defined in `src/adapters/sources/cnpq_crawler.py`.
- Nothing here touches the database, `researcher_index`, or any shared
  mutable state. Every worker's inputs (`group_info`) and outputs (the fetch
  result dict) are plain, cloudpickle-serializable data.

## What runs serially (in the flow's own process, direct calls only)

- `sync_group`, `sync_members`, `sync_knowledge_areas` — all database writes,
  all reads/mutations of `researcher_index`.
- These MUST be invoked as plain function calls on the flow's collected
  future results, in a simple `for` loop — never via `.submit()`, never via
  `.map()`, never from inside the fetch task.

## The one invariant that must never be violated

> At any instant during a run, at most one group's write step
> (`sync_group`/`sync_members`/`sync_knowledge_areas`) may be executing.

This is what makes the fetch/write split safe despite `researcher_index`
being unsynchronized, ordinary, mutable Python state. If a future
implementation change ever calls the write step via `.submit()` — even by
accident, even "just to see if it's faster" — this invariant breaks silently
(no exception, just occasional duplicate researchers under load), which is
exactly the failure mode feature 011's tests were written to catch in the
sequential case but cannot catch under concurrency. Any test suite for this
feature MUST include a test that asserts write calls never overlap in time,
not just that they produce correct results in the common case.

## Failure contract

A fetch that fails (portal error, timeout, malformed page) produces a result
with `success: False`. The write loop checks this before calling any write
function, exactly mirroring `sync_single_group`'s current
`if not data: ... return {"success": False, ...}` check. A failed fetch never
raises out of the loop and never prevents subsequent futures from being
processed.
