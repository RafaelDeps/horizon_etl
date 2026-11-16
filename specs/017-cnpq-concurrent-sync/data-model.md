# Data Model: Concurrent CNPq Group Sync

**Feature**: [spec.md](spec.md) · **Research**: [research.md](research.md)

There is no database schema change. Everything below is in-memory state of one
CNPq phase run.

## Group to sync (unchanged)

`{"id", "name", "url"}` from `get_groups_to_sync()["valid"]`. Its **index** in
that list is the write order.

## FetchOutcome (new, one per group)

| Field | Type | Meaning |
|---|---|---|
| `index` | `int` | Position in the valid-group list (the write order) |
| `group_info` | `dict` | The group being fetched |
| `data` | `dict \| None` | The payload from `get_group_data`, or `None` after the last attempt |
| `attempts` | `int` | ETL-level attempts made, 1–3. Each one includes the library's own 3 tries |

It is produced by a fetch worker and consumed once by the writer.

## AdaptiveGate (new)

| Field | Type | Meaning |
|---|---|---|
| `max_workers` | `int` | Configured ceiling (default 4, from `HORIZON_CNPQ_WORKERS`) |
| `limit` | `int` | Current allowed in-flight fetches, `1 ≤ limit ≤ max_workers` |
| `in_flight` | `int` | Fetches currently inside the gate |
| `failures` | `deque[float]` | Timestamps of failures in the last 60 s |
| `last_failure_at` | `float \| None` | Used for the 120-second restore rule |
| `reductions` | `int` | Number of times `limit` was halved |

**Invariant**: `in_flight ≤ limit ≤ max_workers` at all times (SC-002).

### State transitions

```text
fetch failure recorded ──► failures within 60 s ≥ 4 ? ──yes──► limit = max(1, limit // 2); reductions += 1; clear window
                                                     └─no──► (no change)

worker asks for a slot ──► 120 s since last_failure_at and limit < max_workers ? ──yes──► limit += 1
                       └─► wait until in_flight < limit, then in_flight += 1
worker leaves the gate ──► in_flight -= 1; notify waiters
```

## Per-group fetch lifecycle

```text
attempt 1 ── get_group_data ──► data ──────────────────────────────► FetchOutcome(data, attempts=1)
          └► None ── wait 30 s ±20% (outside the gate) ──► attempt 2
attempt 2 ── data ──────────────────────────────────────────────────► FetchOutcome(data, attempts=2)
          └► None ── wait 90 s ±20% (outside the gate) ──► attempt 3
attempt 3 ── data ──────────────────────────────────────────────────► FetchOutcome(data, attempts=3)
          └► None ──────────────────────────────────────────────────► FetchOutcome(None, attempts=3)
```

## Writer (flow thread, original order)

For `index` in `0..n-1`:
1. Wait for that group's `FetchOutcome`.
2. Call the Prefect task `sync_single_group(group_info, data=outcome.data, researcher_index=index_list)`.
   - If `data` is `None`, it produces today's failure result: it logs
     `Failed to extract data for <name>` and returns `success=False`.
   - Otherwise it runs today's database steps, using the shared researcher index.
3. Append the result to `results`, as today.

## Researcher index (new usage of an existing structure)

The `List[ResearcherRef]` comes from `load_researcher_index(session)`. It is
loaded once per phase, in ascending `id` (verified identical to `get_all()`).
`resolve_or_create_researcher` appends a `ResearcherRef` for each researcher it
creates.

## Summary counters

`workers`, `fetched` (outcomes with data), `retries` (attempts − 1, summed),
`failed_after_retries`, `concurrency_reductions`, `researcher_index_loaded`,
`researcher_hits` and `researcher_created`.

They are emitted in one INFO line at the end of the flow:

```text
CNPq fetch: workers=4 fetched=350 retries=0 failed_after_retries=0 concurrency_reductions=0 researcher_index_loaded=7645 researcher_hits=... researcher_created=...
```

The line holds counts only.
