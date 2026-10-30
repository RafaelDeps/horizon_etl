# Contract: settings, Makefile, workflow and report file

## Environment variables

| Variable | Default | Accepted values |
|---|---|---|
| `HORIZON_PORTAL_EARLY_STOP` | on | blank, `1`, `true` or `yes` = on; `0`, `false` or `no` = off; anything else = on, with a warning |
| `HORIZON_CNPQ_STOP_AFTER_FAILURES` | `8` | integer ≥ 0; 0 = rule off |
| `HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN` | `45` | number ≥ 0 (minutes, decimals allowed); 0 = rule off |
| `HORIZON_LATTES_STOP_AFTER_FAILURES` | `5` | integer ≥ 0; 0 = rule off |

Every phase subprocess reads them; the orchestrator passes its environment
through, as it does today.

## Makefile (`weekly-flows`, `sync-cnpq`, `ingest-lattes-download`)

These are optional variables, forwarded only when set, in the same style as
`REFRESH_SHARE`:

```make
$(if $(EARLY_STOP),HORIZON_PORTAL_EARLY_STOP="$(EARLY_STOP)") \
$(if $(CNPQ_STOP_AFTER),HORIZON_CNPQ_STOP_AFTER_FAILURES="$(CNPQ_STOP_AFTER)") \
$(if $(CNPQ_BUDGET_MIN),HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN="$(CNPQ_BUDGET_MIN)") \
$(if $(LATTES_STOP_AFTER),HORIZON_LATTES_STOP_AFTER_FAILURES="$(LATTES_STOP_AFTER)") \
```

The `weekly-flows` help text names them.

## Workflow `weekly-etl.yml`

New `workflow_dispatch` inputs; the total goes from 5 to 9:

| Input | Type | Default | Description |
|---|---|---|---|
| `early_stop` | boolean | `true` | "Stop downloading from a portal that blocks or stops answering, and use the stored copies." |
| `cnpq_stop_after` | string | `""` | "CNPq failed attempts in a row that stop the downloads (blank = 8; 0 = off)." |
| `cnpq_budget_min` | string | `""` | "Minutes of CNPq downloads before they stop (blank = 45; 0 = off)." |
| `lattes_stop_after` | string | `""` | "Lattes failures or access check pages in a row that stop the downloads (blank = 5; 0 = off)." |

The "Run weekly flows" step maps them to the four variables. Scheduled runs
pass no inputs, so all are blank and the defaults apply. A blank
`early_stop` (schedule) means on.

## Report file `data/reports/portal_stops.json`

- **Format:** the version 1 format of [data-model.md](../data-model.md).
- **Helpers** in `src/flows/portal_stops.py`:
  - `record_portal_stop(source, stop, counts, path=PORTAL_STOPS_PATH)`: reads
    the file if it exists, sets `stops[source]`, and writes it atomically
    (`atomic_write_json`). It never raises; a write error is logged as a
    WARNING.
  - `read_portal_stops(path=PORTAL_STOPS_PATH) -> dict`: returns `{}` when
    the file is missing or unreadable.
  - `clear_portal_stops(path=PORTAL_STOPS_PATH)`: removes the file and
    ignores a missing one.
- **Tests:** `PORTAL_STOPS_PATH` is a module default read at call time, and
  `tests/conftest.py` redirects it to `tmp_path`, as it does for the spec 023
  stores.
- **Upload:** the file goes into the CI artifact with the other
  `data/reports/` files; it is never read back as an input.

## Weekly summary

`run_weekly`:

1. At the start, before the first phase, it calls `clear_portal_stops()`.
2. At the end, after the phase lines, it adds one line per entry:

   ```text
   ⚠ cnpq: portal given up (failures_in_a_row, limit 8) after 289 s; 81 not tried, 263 from stored pages, 6 failed
   ```

3. `_notify` adds the same lines, in Portuguese, after the phase list:

   ```text
   ⚠️ cnpq: portal abandonado (8 falhas seguidas) após 289 s; 81 não tentados, 263 das cópias guardadas, 6 falhas
   ```

4. The exit code does not change. A phase whose source stopped still exits 0
   unless something else failed.
