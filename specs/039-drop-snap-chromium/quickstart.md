# Quickstart: validating spec 039

## 1. Tests

```bash
.venv/bin/python -m pytest tests/test_weekly_etl_workflow.py tests/test_download_lattes_flow.py -q
.venv/bin/python -m pytest -q
```

Workflow checks by hand:

```bash
grep -nE "chromium-browser|chromium-driver|snap install|CHROME_BINARY|CHROMEDRIVER_PATH" .github/workflows/weekly-etl.yml   # no output
grep -n "playwright install --with-deps chromium" .github/workflows/weekly-etl.yml                                          # one line
```

## 2. Local weekly (twice, with a backup of `db/horizon.db` and `data/` first)

```bash
make weekly-flows
```

Expect every phase with exit 0, and the Lattes phases downloading and
processing the curricula as in the previous local run. A `.env` that still sets
`CHROME_BINARY` or `CHROMEDRIVER_PATH` must not change anything.

## 3. Fork run (only when the maintainer asks; RafaelDeps fork, never upstream)

```bash
gh workflow run weekly-etl.yml -R RafaelDeps/horizon_etl --ref 039-drop-snap-chromium
```

Check in the run:

- there is no step "Install Chromium for Lattes (Selenium)";
- "Install Playwright Chromium" passed;
- every phase passed;
- the Lattes download line `downloads lattes: new=… refreshed=… reused=…` is in
  the same range as run 43663739197.

The first run of a new branch starts from an empty database (restore finds no
run of the branch). It downloads every curriculum, so it takes about two hours.
