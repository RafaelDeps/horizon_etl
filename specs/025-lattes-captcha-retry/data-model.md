# Data Model: Second Try for Lattes Access Check Pages

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

No table and no export file changes. The entities below live in memory during
the Lattes download, apart from the report entry, which is a file under
`data/reports/`.

## AccessCheckRetrySettings

Read once per Lattes download from the environment (research R6).

| Field | Type | Default | Rule |
|---|---|---|---|
| `workers` | int ≥ 0 | 1 | `HORIZON_LATTES_RETRY_WORKERS`; 0 turns the second pass off |
| `pause_s` | float ≥ 0 | 300 | `HORIZON_LATTES_RETRY_PAUSE_MIN` × 60; 0 means no wait |

- A blank value means the default.
- An invalid value is logged as a WARNING and the default is used. Invalid
  means not a number, negative, not finite, or not an integer for
  `workers`.
- `enabled` is `workers > 0`.

## AccessCheckPage

An exception, a subclass of `ScriptLattesRuntimeError`. It is raised when a
request returned the portal's access check page instead of a curriculum:
`is_curriculum_page` is false. It carries the same message as today.

## The two passes

| | First pass | Second pass |
|---|---|---|
| Items | the rotation plan: new curricula, then the refresh share | the ids of the first pass that raised `AccessCheckPage`, new ones then refreshes, each once |
| Workers | `HORIZON_LATTES_DOWNLOAD_WORKERS` (3) | `AccessCheckRetrySettings.workers` (1) |
| Before it | nothing | the pause |
| Stop | the run's Lattes `PortalStop` | the same object, with its count carried over |
| Runs when | prefetch is enabled | `workers > 0`, at least one id, and the stop not triggered |

**State of one curriculum through the two passes**:

```text
first request ─┬─ real page ───────────────────────────► downloaded (date recorded)
               ├─ other failure (after its own retry) ─► failed, as today
               ├─ not tried (stop) ────────────────────► not tried, as today
               └─ access check page ─► second pass?
                       ├─ no (off, or stop triggered) ─► failed, as today
                       └─ yes, after the pause:
                            ├─ real page ──────────────► recovered (date recorded)
                            ├─ access check / failure ─► failed, as today
                            └─ not tried (stop) ───────► not tried, as today
```

The outcomes for the cache and the manifest:
- **"Failed, as today":** a new curriculum has no file in `cache/` and no
  date; a refresh keeps its cached copy and its old date.
- **"Not tried":** the same, counted as `stopped` (spec 024).

## Counts

`download_counts(plan, failed, not_tried)` (spec 023 and spec 024) is
unchanged. A recovered curriculum is not in `failed`, so it counts as new or
refreshed.

When a second pass ran, `rotate_lattes_downloads` adds:

| Key | Meaning |
|---|---|
| `retried` | ids sent to the second pass |
| `recovered` | of those, ids whose real page arrived |
| `retried_ids` | the sorted ids sent to the second pass (log and tests; not in the report) |

The relationship between them: `retried = recovered + rejected again or
failed + not tried in the second pass`.

With no second pass, the keys are absent and the counts are exactly today's.

## Report entry (`data/reports/portal_stops.json`, key `retries`)

```json
{
  "version": 1,
  "stops": {},
  "retries": {
    "lattes": {
      "source": "lattes",
      "pause_s": 300.0,
      "workers": 1,
      "retried": 38,
      "recovered": 35,
      "not_tried": 0,
      "elapsed_s": 642.3,
      "finished_at": "2026-11-10T05:12:44Z"
    }
  }
}
```

- `elapsed_s` runs from the start of the pause to the end of the second pass.
- The entry is written only when a second pass ran.
- `stops` and `retries` are independent:
  - a run can have a retry entry and no stop, or a stop during the second
    pass and both entries;
  - a stop in the first pass gives a stop entry and no retry entry.
