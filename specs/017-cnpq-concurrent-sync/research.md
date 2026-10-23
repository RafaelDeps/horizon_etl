# Research: Concurrent CNPq Group Sync with a Single Writer

**Feature**: [spec.md](spec.md) · **Date**: 2026-10-22

## R1. Today's flow, step by step

`sync_cnpq_groups_flow` (`src/flows/cnpq/groups.py`) runs in this order:
1. `get_groups_to_sync()` returns `{"valid": [...], "invalid": [...]}`, with the
   invalid URLs filtered by the 16-digit DGP regex.
2. Inside `tracking_recorder.run_context("cnpq_sync")`, for each valid group in
   order, the Prefect task `sync_single_group(group_info)` runs:
   - `CnpqCrawlerAdapter().get_group_data(url)`: **network**. It calls
     `CnpqCrawler.get_data`, which already retries 3 times with a 1–10 s
     exponential wait (`dgp_cnpq_lib/decorators.py`). The adapter catches every
     exception, logs `Failed to extract data from …` and returns `None`.
   - On `None`, it logs `Failed to extract data for <name>` and returns
     `{"success": False, …}`.
   - Otherwise everything is **database** work, using a new `CnpqSyncLogic()` per
     group: `record_source_record(cnpq_group_payload)`, `sync_group`,
     `extract_members` + `extract_leaders`, `sync_members`, and
     `extract_research_lines` + `sync_knowledge_areas`.
   - It returns `{"success": True, …}`.
3. `build_cnpq_sync_summary(results, invalid)`; the CLI then prints the summary
   and writes the JSON report.

**Exceptions in the database part are not caught** in `sync_single_group`. They
fail the task and, with it, the flow. This is preserved (spec edge case,
corrected during planning).

## R2. Split fetching from writing

**Decision**: Fetching moves out of `sync_single_group`:
- A **fetch stage** runs `CnpqCrawlerAdapter().get_group_data(url)` in worker
  threads. One adapter per call, as today, so each call creates its own
  `CnpqCrawler` and browser. The stage is plain Python, not Prefect tasks.
- A **write stage** stays in the flow thread. It is a Prefect task
  `sync_single_group(group_info, data)` that receives the fetched data and does
  exactly today's database part. It is called **in the original group order**.

The flow submits every group's fetch up front through a bounded fetcher (R3),
then walks the groups in order. For each one it waits for that group's fetch
result and calls the write task. Later fetches keep running while earlier groups
are written.

**Rationale**:
- One writer and one order by construction (FR-003, FR-004). There is no
  database access in the workers, because the adapter's `get_group_data` touches
  no database.
- The Prefect task boundary stays per group, so per-group task runs and their
  logs keep looking as they do today.
- Workers do not touch `tracking_recorder`: `record_source_record` is called by
  the writer, as today.

**Verified**: `dgp_cnpq_lib`'s `CnpqCrawler.get_data`, which uses the Playwright
**sync** API, runs correctly from 4 threads at once. A test made 8 fetches of a
local page with 4 workers: 4 distinct threads, peak 4 in flight, all results
correct, 5.1 s. Each call creates its own `sync_playwright()` context in its own
thread.

**Alternatives considered**:
- *Prefect `ThreadPoolTaskRunner` with `.submit()` for the whole
  `sync_single_group`.* Rejected: database writes would run in parallel threads,
  which violates the single-writer rule.
- *Processes instead of threads.* Rejected: they bring nothing for I/O-bound
  waits, and they complicate Playwright and logging.

## R3. Bounded, adaptive concurrency

**Decision**:
- A `ThreadPoolExecutor` with `pool_size = max_workers + 4` threads, plus an
  **adaptive gate**: a `threading.Condition` with a mutable `limit`, starting at
  `max_workers` (default 4, from `HORIZON_CNPQ_WORKERS`).
- A worker acquires the gate only for the duration of one `get_group_data` call.
  The gate guarantees that at most `limit` (≤ `max_workers`) fetches are in
  flight (FR-001, SC-002).
- Back-off sleeps happen **outside** the gate, so they do not block other
  fetches (FR-007). The extra pool threads let other groups start while some
  sleep.

**Invalid configuration**: a value of 0, a negative value or a non-integer logs
a warning and uses 4.

## R4. ETL-level retry with back-off (FR-007, FR-009)

**Decision**: per group, up to **3 attempts** of `get_group_data`. Each attempt
already includes the library's own 3 tries.
- Between attempts, wait **30 s, then 90 s**, each with ±20% jitter. The worst
  extra wait per persistently failing group is ~2 min, plus the attempts
  themselves.
- `None` is the retry signal. The adapter does not expose the cause, so any
  failure is retried (spec assumption).
- A group that still returns `None` after the last attempt goes to the writer as
  `None`. The write task then produces exactly today's failure result and log
  line. The group lands in `failed_groups` and `cnpq_group_sync_failed`
  unchanged (FR-009, FR-010).

**Rationale**:
- In the spec 015 run, the resets came in an 8-minute burst. Waits of tens of
  seconds, combined with reduced concurrency (R5), let the portal recover
  without stretching the phase for long.
- The library's 1–10 s retry is too short for such bursts.

## R5. Failure-burst rule (FR-008)

**Decision**: the fetcher keeps a sliding window of failure timestamps.
- **Reduce**: when **≥ 4 failures** occur within **60 s**, set
  `limit = max(1, limit // 2)`, count one `concurrency_reduction`, clear the
  window, and log at WARNING:
  `CNPq fetch: failures clustering, concurrency <old> → <new>`.
- **Restore**: after **120 s with no failure**, raise the limit by 1, up to
  `max_workers`. Log at INFO.

With the default of 4, the limit goes 4 → 2 → 1 under a sustained burst, and
then climbs back one step at a time.

## R6. Researcher lookup once per phase (FR-006, TD-008)

`CnpqSyncLogic.sync_members` calls `self.res_ctrl.get_all()` once per group. That
returns ORM `Researcher` entities with four eagerly joined collections. Then, for
each member, it calls `resolve_or_create_researcher(self.res_ctrl, all_res,
name=name)`. Only `researcher.id` is used afterwards.

**Decision**:
- The flow builds `load_researcher_index(session)` once, before the first write,
  and passes it to every write.
- `sync_members` gains an optional `researcher_index` argument. When given, it
  uses that list instead of `get_all()`. When omitted, it keeps today's
  behaviour (existing callers and tests).
- `resolve_or_create_researcher` already appends a `ResearcherRef` when the list
  holds refs, so researchers created by one group are found by later groups
  (FR-006, acceptance scenario 2.2).

**Verified equivalence of order and content** on the spec 016 validation
database (7 645 researchers): `get_all()` and `load_researcher_index` return the
same set, both in ascending `id`, in the same order. `resolve_researcher_by_name`
returns the first candidate with the strictly highest score, so identical order
means identical tie-breaking.

Only `name` and `identification_id` are read during resolution, and both are
present on `ResearcherRef`. The controlled replay (R8) confirms equivalence end
to end.

## R7. Summary line (FR-011)

One INFO line at the end of the flow:

```text
CNPq fetch: workers=<n> fetched=<n> retries=<n> failed_after_retries=<n> concurrency_reductions=<n> researcher_index_loaded=<n> researcher_hits=<n> researcher_created=<n>
```

- `researcher_hits` and `researcher_created` are counted in `sync_members` when
  the index is used. A result found in the list counts as a hit; a newly created
  researcher counts as created.
- The existing `Flow finished. Successfully synchronized x/y groups.` line and
  the CLI summary (`CNPq sync: …`) are unchanged.

## R8. Controlled replay (SC-004)

**Inputs**:
- The **350 captured group payloads** from the spec 016 validation run. They are
  the `cnpq_group_payload` rows in `source_records`, keyed by group URL, 347
  distinct URLs. They were exported read-only to the scratchpad file
  `replay017/cnpq_payloads.json` before any further `make weekly-flows` could
  wipe `db/horizon.db`.
- A **pre-CNPq snapshot**: `db/create_db.py`, then the spec 015 `replay_sigpesq.py`,
  from the frozen SigPesq inputs. That is the same state the weekly run has
  before `cnpq`.

**Harness**: a throwaway Prefect flow wrapper (constitution III) that patches
`CnpqCrawlerAdapter.get_group_data` to return the captured payload for the URL.
Optionally it sleeps a random 0.5–3 s, so that completions really arrive out of
order. It then runs `sync_cnpq_groups_flow()` twice: once with the base code
(spec 016, branch `019`) and once with the feature code.

**Comparison**: the spec 015 `compare.py`, extended for this phase:
- counts of `research_groups`, `team_members`, `persons`, `researchers`,
  `knowledge_areas` and the group↔knowledge-area links;
- the name-based membership set;
- `source_records` counts per `source_entity_type`.

## R9. Rejected: reusing one `CnpqSyncLogic` across groups

Today each group builds a fresh `CnpqSyncLogic()`, with new controllers. Keeping
that is the least behaviour change: session lifetimes and identity maps stay
per group. The cost is small next to the network wait, and the researcher
`get_all()` is removed by R6 anyway.
