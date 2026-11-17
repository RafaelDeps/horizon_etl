# Contract: browser setup of the weekly workflow

Applies to `.github/workflows/weekly-etl.yml`, job `run-etl`. It is checked by
`tests/test_weekly_etl_workflow.py`.

1. Exactly one step installs a browser: "Install Playwright Chromium", with
   `run: .venv/bin/python -m playwright install --with-deps chromium`. It comes
   after "Create virtual environment and install dependencies" and before
   "Validate required secrets".
2. No step's `run` contains `apt-get install` of a package whose name starts
   with `chromium`, nor `snap install`.
3. No step is named "Install Chromium for Lattes (Selenium)".
4. The job `env` has neither `CHROME_BINARY` nor `CHROMEDRIVER_PATH`, and no
   step `env` sets them.
5. Every other step keeps its name, order and content.

Runtime contract (unchanged in behaviour): before the Lattes download,
`validate_script_lattes_runtime()` returns `"playwright-chromium"` when the
Playwright Chromium is installed, and raises `ScriptLattesRuntimeError` with
the install command otherwise.
