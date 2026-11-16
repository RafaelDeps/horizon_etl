# Contract: settings, Makefile, workflow, report and summary

## Environment variables

| Variable | Default | Accepted values |
|---|---|---|
| `HORIZON_LATTES_RETRY_WORKERS` | `1` | integer ≥ 0; `0` turns the second pass off |
| `HORIZON_LATTES_RETRY_PAUSE_MIN` | `5` | number ≥ 0, in minutes (decimals allowed); `0` = no wait |

- **Where they are read:** by `access_check_retry_settings(env=None) ->
  AccessCheckRetrySettings`, in `src/core/logic/access_check_retry.py`.
- **Blank and invalid values:** blank means the default. Anything else
  invalid is logged as `Invalid <NAME>=<value>; using <default>` and the
  default is used. The function never raises.
- **Independence:** they work independently of `HORIZON_PORTAL_EARLY_STOP`.

## Makefile

They are optional variables, forwarded only when set, in the same style as
the spec 024 `PORTAL_STOP_ENV` block. They are added to that block, which
`weekly-flows` and `ingest-lattes-download` already use:

```make
$(if $(LATTES_RETRY_WORKERS),HORIZON_LATTES_RETRY_WORKERS="$(LATTES_RETRY_WORKERS)") \
$(if $(LATTES_RETRY_PAUSE_MIN),HORIZON_LATTES_RETRY_PAUSE_MIN="$(LATTES_RETRY_PAUSE_MIN)")
```

The help texts of `weekly-flows` and `ingest-lattes-download` name them.

## Workflow `weekly-etl.yml`

These are new `workflow_dispatch` inputs, taking the total from 9 to 11
(GitHub's limit is 25; research R6):

| Input | Type | Default | Description |
|---|---|---|---|
| `lattes_retry_workers` | string | `""` | "Workers that ask again, in the same run, for the Lattes curricula that got the access check page (blank = 1; 0 = off)." |
| `lattes_retry_pause_min` | string | `""` | "Minutes to wait before asking again for those curricula (blank = 5)." |

- **Mapping:** the "Run weekly flows" step maps them to the two variables.
- **Scheduled runs:** they pass no inputs, so the defaults apply.
- **The spec 024 test** `len(inputs) <= 10` becomes `<= 25`, with the
  changelog reason in a comment.

## Report file `data/reports/portal_stops.json`

- **Format:** version 1, plus the additive `retries` key of
  [data-model.md](../data-model.md).
- **New helpers in `src/flows/portal_stops.py`:**
  - `record_access_check_retry(source, entry, path=None)`: reads the whole
    file if it exists, sets `retries[source]`, keeps every other key, and
    writes atomically (`atomic_write_json`). It never raises; a write error
    is logged as a WARNING.
  - `read_access_check_retries(path=None) -> dict`: returns `{}` when the
    file or the key is missing or unreadable.
- **Changed:** `record_portal_stop` reads the whole file and keeps the keys
  it does not own, `retries` included. Its entry is unchanged.
- **Unchanged:**
  - `read_portal_stops` still returns only `stops`;
  - `clear_portal_stops` still removes the whole file at the start of each
    weekly;
  - the test redirection of `PORTAL_STOPS_PATH` in `tests/conftest.py`.

## Weekly summary

At the end of `run_weekly`, after the spec 024 stop lines, the orchestrator
adds one line per retries entry:

```text
↻ lattes: 38 access check pages asked again after 5 min; 35 recovered, 3 still missing
```

- **"still missing"** is `retried − recovered`. That includes those
  rejected again, those failed, and those not tried.
- **In Telegram,** `_notify` adds the same line in Portuguese, after the
  stop lines:

  ```text
  🔁 lattes: 38 páginas de captcha pedidas de novo após 5 min; 35 recuperadas, 3 ainda faltando
  ```

- **No entry** means no line, so a healthy weekly's summary is unchanged.
- **The exit code** does not change.
