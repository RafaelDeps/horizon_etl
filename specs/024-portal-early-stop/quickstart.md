# Quickstart: Stop Downloading When a Portal Blocks

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## 1. Tests

```bash
.venv/bin/pytest tests/test_portal_stop.py tests/test_cnpq_early_stop.py tests/test_lattes_early_stop.py -q
.venv/bin/pytest tests/test_cnpq_concurrent_fetch.py tests/test_cnpq_rotation.py tests/test_lattes_rotation.py tests/test_weekly_orchestrator.py -q
.venv/bin/pytest -q
```

The second command is the "identical when healthy" check: the spec 017 and
spec 023 tests pass unchanged.

## 2. Local run with tight limits

Back up first: `db/horizon.db`, `data/raw/` and `cache/` (see the memory rule
on writing to the real database). Then run each source with a limit that
stops it at once:

```bash
make sync-cnpq CNPQ_BUDGET_MIN=0.5
make ingest-lattes-download LATTES_STOP_AFTER=1
```

Expected:

- **CNPq.**
  - The log shows `portal given up: cnpq reason=time_budget` after about
    30 s, plus the in-flight attempts.
  - The groups not tried are processed from `data/raw/cnpq/` and skipped as
    unchanged.
  - `downloads cnpq: ... stopped=N` appears in the log.
- **Lattes.** The stop comes only if the first request fails. With a healthy
  portal and `LATTES_STOP_AFTER=1`, nothing stops, which shows that the
  successes reset the count.
- **Report.** `data/reports/portal_stops.json` has an entry for each source
  that stopped.

To turn the feature off and see today's behaviour:

```bash
make sync-cnpq EARLY_STOP=0
```

## 3. Fork dispatch

- **Healthy day, defaults:**

  ```bash
  gh workflow run weekly-etl.yml --repo RafaelDeps/horizon_etl --ref 027-portal-early-stop
  ```

  Expected: no `⚠` line in the weekly summary, and the CNPq counts match
  spec 023's run 40959876147.

- **Forced stops:**

  ```bash
  gh workflow run weekly-etl.yml --repo RafaelDeps/horizon_etl --ref 027-portal-early-stop -f cnpq_budget_min=1 -f lattes_stop_after=1
  ```

  Expected:
  - the run is green;
  - the summary shows the CNPq stop, and the Lattes stop if a request
    failed first;
  - the following default run picks the untried items first.

Dispatching on the fork sends the Telegram summary and uses the secrets, so
ask the maintainer before each dispatch.
