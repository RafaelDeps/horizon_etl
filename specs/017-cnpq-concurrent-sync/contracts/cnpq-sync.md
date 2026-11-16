# Contract: CNPq Phase Internals

There is no external API change. `app.py cnpq_sync [campus]` and the summary or
report it produces keep their current form.

## `sync_cnpq_groups_flow(campus_name: Optional[str] = None) -> dict`

| Aspect | Contract |
|---|---|
| Return value | Same summary as today (`build_cnpq_sync_summary`): same keys and semantics. |
| Fetching | Every valid group is fetched through `CnpqCrawlerAdapter().get_group_data(url)` from worker threads, with at most `limit` (≤ `HORIZON_CNPQ_WORKERS`, default 4) in flight. |
| Retries | Up to 3 ETL-level attempts per group, with waits of 30 s and 90 s ±20% taken outside the gate. |
| Writing | Only the flow thread touches the database. It calls `sync_single_group(group_info, data, researcher_index)` once per group, in the original order. |
| Researcher index | `load_researcher_index(session)` runs once per call, before the first write. |
| Logs | Today's lines unchanged. New: the WARNING / INFO concurrency-change lines and one final `CNPq fetch: …` INFO line. |
| Failures | A group with no data after the retries gives today's failure result. An exception in the database part propagates, as today. |

## `sync_single_group(group_info: dict, data: Optional[dict] = None, researcher_index: Optional[list] = None)` (Prefect task)

| Call | Behaviour |
|---|---|
| `data` given | Skips fetching. Runs today's database steps on `data`. |
| `data is None` and called by the new flow | Today's failure path: logs `Failed to extract data for <name>` and returns `success=False`. |
| Called with only `group_info` (old signature) | Fetches by itself, exactly as today, for backward compatibility with scripts and tests. |
| `researcher_index` | Passed to `CnpqSyncLogic.sync_members`. When it is `None`, today's `get_all()` path is used. |

A sentinel distinguishes "fetch not attempted" from "fetched, no data".

## `CnpqSyncLogic.sync_members(group_id, members_data, *, source_file=None, researcher_index=None)`

- `researcher_index` omitted: unchanged behaviour (`self.res_ctrl.get_all()`).
- `researcher_index` given: that list is used as `all_res`. Researchers created
  during the call are appended to it by `resolve_or_create_researcher`. The hit
  and created counters are updated.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `HORIZON_CNPQ_WORKERS` | `4` | Ceiling for concurrent fetches. Invalid values fall back to 4 with a WARNING. `1` means sequential fetching. |
