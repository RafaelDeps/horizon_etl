# Data Model: Stop Downloading When a Portal Blocks

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

No table and no export file changes. The entities below live in memory
during a phase, apart from the report entry, which is a file under
`data/reports/`.

## PortalStopSettings

Read once per phase from the environment (research R6).

| Field | Type | Default | Rule |
|---|---|---|---|
| `enabled` | bool | `True` | `HORIZON_PORTAL_EARLY_STOP` in `0`/`false`/`no` (any case) gives `False` |
| `cnpq_failures` | int ≥ 0 | 8 | `HORIZON_CNPQ_STOP_AFTER_FAILURES`; 0 turns the rule off |
| `cnpq_budget_s` | float ≥ 0 | 2700 | `HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN` × 60; 0 turns the rule off |
| `lattes_failures` | int ≥ 0 | 5 | `HORIZON_LATTES_STOP_AFTER_FAILURES`; 0 turns the rule off |

- A blank value means the default.
- An invalid value (not a number, or negative) is logged as a WARNING and the
  default is used.
- `enabled=False` makes the phases build no stop at all, which is today's
  path.

## PortalStop

One per source per phase. It is shared by every download thread of that
source and is thread safe.

| Field | Type | Meaning |
|---|---|---|
| `source` | `"cnpq"` \| `"lattes"` | the portal |
| `max_failures` | int | failures in a row that stop it; 0 = no such rule |
| `budget_s` | float | download time that stops it; 0 = no such rule |
| `started_at` | float | clock reading when the downloads started (injected clock) |
| `failures_in_a_row` | int | current count; any success resets it to 0 |
| `failures_total` | int | all failures recorded |
| `successes_total` | int | all successes recorded |
| `stopped` | bool | the decision; it never goes back to `False` |
| `reason` | `None` \| `"failures_in_a_row"` \| `"time_budget"` | why it stopped |
| `stopped_at` | `None` \| ISO-8601 UTC | wall time of the stop |
| `elapsed_s` | `None` \| float | seconds from `started_at` to the stop |

**State transitions**:

```text
running ──record(False) and failures_in_a_row == max_failures──▶ stopped (failures_in_a_row)
running ──should_stop() past started_at + budget_s────────────▶ stopped (time_budget)
running ──record(True)──▶ running (failures_in_a_row = 0)
stopped ──any call──▶ stopped (no change; record() still counts the
                      outcomes of requests that were in flight)
```

When it stops, the wake event is set, so every `wait()` returns at once.

## FetchOutcome (extended)

Spec 017's dataclass gains one field:

| Field | Type | Meaning |
|---|---|---|
| `stopped` | bool, default `False` | the task ended because of the stop |

What the writer does with each outcome:

| `data` | `stopped` | `attempts` | Meaning | Writer |
|---|---|---|---|---|
| set | any | ≥ 1 | downloaded | store and process the page (today) |
| `None` | `False` | 3 | failed after all retries | stored page if any, failure recorded (today) |
| `None` | `True` | ≥ 1 | failed, retries cut by the stop | same as the row above |
| `None` | `True` | 0 | not tried | stored page if any, **no failure recorded**; without one, a failed download (FR-004) |

## Download counts (extended)

`download_counts(plan, failed, stopped=())` keeps every spec 023 key and adds:

| Key | Meaning |
|---|---|
| `stopped` | number of items never tried because of the stop |
| `stopped_ids` | their ids, sorted |

- A stopped id that is in `plan.refresh` counts in `reused`, because its
  stored copy is used. It does not count in `refreshed`.
- A stopped id that is in `plan.new` counts in neither `new` nor `failed`.
- `failed` keeps only items that were tried and failed.

`counts_line` appends `stopped=N`.

## Portal stop report entry

The file `data/reports/portal_stops.json`, version 1:

```json
{
  "version": 1,
  "stops": {
    "cnpq": {
      "source": "cnpq",
      "reason": "failures_in_a_row",
      "limit": 8,
      "budget_s": 2700,
      "stopped_at": "2026-10-29T22:38:21Z",
      "elapsed_s": 289.4,
      "failures_total": 8,
      "successes_total": 0,
      "counts": {"new": 0, "refreshed": 0, "reused": 263, "failed": 6,
                 "reused_after_failure": 6, "stopped": 81}
    }
  }
}
```

- **Writing.** Written atomically by the phase that stopped, which adds or
  replaces its own source key.
- **Clearing.** The orchestrator deletes the file at the start of each
  weekly.
- **Not an input.** No phase reads it.
- **Content.** It holds counts, reasons and times only; ids are logged, not
  written here.
