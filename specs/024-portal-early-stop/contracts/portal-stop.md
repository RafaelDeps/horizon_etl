# Contract: `src/core/logic/portal_stop.py`

Pure core logic: standard library only (`threading`, `time`, `os`, `math`)
plus loguru for the warning on invalid settings. No adapter import and no
file I/O.

## `portal_stop_settings(env: Mapping[str, str] | None = None) -> PortalStopSettings`

- Reads the four variables of [settings-and-report.md](settings-and-report.md).
  `env=None` means `os.environ`.
- **Invalid values.** A blank value gives the default. An invalid value logs
  one WARNING (`Invalid <NAME>=<value>; using <default>`) and gives the
  default.
- **Never raises.**

## `PortalStopSettings.for_source(source, clock=time.monotonic) -> PortalStop | None`

- Returns `None` when `enabled` is false, or when both rules of the source
  are 0. Lattes has only the failures rule.
- Otherwise returns a running `PortalStop`. Its `started_at` is set by
  `start()`; the flow calls `start()` right before the first request.

## `class PortalStop`

All methods are thread safe and none raises.

| Method | Contract |
|---|---|
| `start() -> None` | Sets `started_at = clock()` the first time; later calls do nothing. |
| `should_stop() -> bool` | `True` once stopped. While running, if `budget_s > 0` and `clock() - started_at >= budget_s`, it stops with reason `time_budget` and returns `True`. |
| `record(success: bool) -> None` | `success=True`: `failures_in_a_row = 0`, `successes_total += 1`. `success=False`: both failure counters go up; when running and `max_failures > 0` and `failures_in_a_row >= max_failures`, it stops with reason `failures_in_a_row`. After the stop it only counts. |
| `wait(seconds: float) -> bool` | Blocks up to `seconds` or until the stop, whichever comes first; returns `True` if stopped. Used for the CNPq back-offs. |
| `summary() -> dict` | The report entry fields of [data-model.md](../data-model.md), without `counts`. |

**Stopping**:
- happens once;
- sets `stopped`, `reason`, `stopped_at` (UTC, `%Y-%m-%dT%H:%M:%SZ`) and
  `elapsed_s`;
- wakes every waiter;
- logs one WARNING: `portal given up: <source> reason=<reason>
  limit=<n or budget> after=<elapsed>s failures=<total> successes=<total>`.

## Callers

### `fetch_with_retries(..., stop: PortalStop | None = None)`

```text
for attempt in 1..MAX_ATTEMPTS:
    if stop and stop.should_stop(): return outcome(data=None, attempts=attempt-1, stopped=True)
    with gate.slot():
        if stop and stop.should_stop(): return outcome(..., attempts=attempt-1, stopped=True)
        data = adapter.get_group_data(url)
    if stop: stop.record(bool(data))
    if data: break
    gate.record_failure()
    if attempt < MAX_ATTEMPTS:
        if stop: if stop.wait(backoff): return outcome(data=None, attempts=attempt, stopped=True)
        else: sleep(backoff)
```

`stop=None` keeps today's code path exactly.

### `fetch_all(..., stop: PortalStop | None = None)`

Calls `stop.start()` before submitting, and passes `stop` to every task.

### Lattes download tasks

`prefetch_lattes_cache` and `refresh_lattes_cache` each take
`stop: PortalStop | None = None`. Every task does this:

1. If `stop.should_stop()`, it raises `_NotTried` without calling the
   downloader.
2. It calls the downloader, then runs the existing checks: the file exists,
   and `is_curriculum_page`.
3. It records `stop.record(True)` on success, or `stop.record(False)` on any
   exception, then re-raises.

`_NotTried` is collected apart from failures and logged at INFO, not
WARNING. Both functions return the not-tried ids as well:
- `prefetch_lattes_cache` keeps returning the downloaded ids, and adds the
  not-tried ids through an optional out-list argument;
- `refresh_lattes_cache` returns `(refreshed, failed, not_tried)`.
