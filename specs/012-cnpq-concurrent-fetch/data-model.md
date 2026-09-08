# Data Model: fetch result and concurrency shape

**Feature**: 012-cnpq-concurrent-fetch | **Date**: 2026-09-04

No database schema changes. Two things are new, both in-memory and scoped to
a single flow run.

## Fetch result

One plain dict per group, returned by the new `fetch_worker` task, replacing
what `sync_single_group` assembles inline today from four separate adapter
calls.

| Field | Comes from (today, inline in `sync_single_group`) |
|---|---|
| `group_id`, `group_name`, `url` | passed through from `group_info` |
| `success` | `False` if `get_group_data` returned falsy; `True` otherwise |
| `data` | `CnpqCrawlerAdapter.get_group_data(url)` |
| `members` | `extract_members(data)`, with leaders merged in as `{"role": "Líder", ...}` entries — exactly the merge `sync_single_group` performs today before calling `sync_members` |
| `research_lines` | `extract_research_lines(data)` |

This is a reshaping, not a redefinition: every field already exists in
today's code, just assembled in a worker process instead of the flow's own
process, and handed back as one bundle instead of several inline calls.

## Concurrency model

```text
sync_cnpq_groups_flow (task_runner=ProcessPoolTaskRunner(max_workers=N))
  │
  ├─ build researcher_index once (feature 011, unchanged)
  │
  ├─ futures = [fetch_worker.submit(g) for g in groups]   # up to N in flight
  │
  └─ for future in futures:                                # submission order
        result = future.result()                           # waits if needed
        if not result["success"]:
            record failure, continue
        # -- everything below is a DIRECT call, never .submit() --
        sync_logic.sync_group(...)
        sync_logic.sync_members(..., researcher_index=researcher_index)
        sync_logic.sync_knowledge_areas(...)
```

`N` concurrent fetches run ahead of the serial writer in separate processes;
the writer — and the shared `researcher_index` it mutates — never leaves the
flow's own process, and never runs two groups at once, regardless of `N`.

## Configuration

| Setting | Env var | Default | Meaning |
|---|---|---|---|
| Fetch concurrency | `CNPQ_FETCH_CONCURRENCY` | `4` | `max_workers` passed to `ProcessPoolTaskRunner`; `1` reproduces today's sequential timing (SC-003) |

## What does NOT change

- `sync_group`, `sync_members`, `sync_knowledge_areas` signatures and bodies.
- The `researcher_index` mutation contract established by feature 011.
- `CnpqCrawlerAdapter`'s four methods — called with the same arguments,
  returning the same shapes, just from a different process.
- The final set of rows written to any table.
