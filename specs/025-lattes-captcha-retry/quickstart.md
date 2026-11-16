# Quickstart: Second Try for Lattes Access Check Pages

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## 1. Tests

```bash
.venv/bin/pytest tests/test_access_check_retry.py tests/test_lattes_access_check_retry.py -q
.venv/bin/pytest tests/test_lattes_rotation.py tests/test_lattes_early_stop.py tests/test_portal_stops_report.py tests/test_weekly_orchestrator.py tests/test_weekly_etl_workflow.py -q
.venv/bin/pytest -q
```

The second command is the "identical when off" check. The spec 023 and
spec 024 Lattes tests run with the second pass off (conftest) and pass
unchanged.

## 2. Local Lattes download

First back up `cache/`, `data/raw/lattes/download_manifest.json` and
`db/horizon.db`, following the memory rule on writing to the real database.
Then:

```bash
make ingest-lattes-download LATTES_RETRY_PAUSE_MIN=1
```

What to expect:
- **If some request got the access check page,** the log shows
  `Retrying N Lattes curricula that got the access check page, after 1 min,
  with 1 worker(s)`. One minute later it shows `Second try for the access
  check page: R of N recovered`, and the downloads line ends with
  `retried=N recovered=R`.
- **The report:** `data/reports/portal_stops.json` has a `retries.lattes`
  entry.
- **The cache:** every recovered curriculum is in `cache/` with today's date
  in the manifest. A curriculum rejected twice is not in `cache/` (new) or
  keeps its old copy (refresh).
- **If no request got the access check page,** none of this appears, and
  the run is the same as before the feature.

A run from scratch, or with many curricula missing from `cache/`, gives the
most requests and so the best chance to see a second pass.

To turn the feature off:

```bash
make ingest-lattes-download LATTES_RETRY_WORKERS=0
```

## 3. Fork dispatch

- **Defaults:**

  ```bash
  gh workflow run weekly-etl.yml --repo RafaelDeps/horizon_etl --ref 028-lattes-captcha-retry
  ```

  What to expect:
  - GitHub accepts the 11 inputs;
  - the run is green;
  - if a page was rejected, the summary shows the `↻ lattes` line and the
    downloads line has `retried=`/`recovered=`.

- **Off:**

  ```bash
  gh workflow run weekly-etl.yml --repo RafaelDeps/horizon_etl --ref 028-lattes-captcha-retry -f lattes_retry_workers=0
  ```

  What to expect: no `retried=` and no `↻` line.

Dispatching on the fork uses the secrets, so ask the maintainer before each
dispatch.
