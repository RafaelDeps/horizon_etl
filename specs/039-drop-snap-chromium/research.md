# Research: Weekly workflow without the snap Chromium

## R1 — Which browser does the weekly use?

- **Decision**: only the Playwright Chromium. The apt/snap Chromium is unused.
- **Rationale**:
  - `src/flows/lattes/download.py` patches scriptLattes so that `get_data`
    opens a `LattesRobot`, which drives Playwright
    (`scriptLattes/baixaLattes.py` imports `playwright.sync_api`).
  - Before the download, `validate_script_lattes_runtime()` checks only that the
    Playwright Chromium is installed.
  - `docs/operations/automation.md` already says the Playwright Chromium is
    installed because the SigPesq agent needs it.
  - No file in `src/`, `app.py` or the installed packages imports `selenium`
    (searched `.venv/lib/python3.14/site-packages`; only the `selenium` package
    itself matches).
  - No file reads `CHROME_BINARY` or `CHROMEDRIVER_PATH`, apart from the
    workflow, the Docker files and `.env.example`.
  - The fork runs that passed (43652669782, 43663739197) downloaded the
    curricula; their logs show the Playwright install and the scriptLattes run,
    and no use of `/usr/bin/chromium-browser`.
  - TD-031 (branch `fix-stale-tests`) had already moved the runtime check to
    Playwright and removed the chromedriver version helpers.
- **Alternatives considered**:
  - Keep the step and make it non-blocking (`continue-on-error`): it would hide
    a failure of something unused, and still spend time and network on it.
  - Install Chromium from a non-snap source (Google's .deb, or a PPA): it adds a
    new external dependency for a browser nothing uses.

## R2 — Why does the step fail?

- **Decision**: treat it as an external outage that the weekly must not depend on.
- **Rationale**:
  - On Ubuntu 24.04 and later, the apt package `chromium-browser` is a
    transitional package whose pre-install script installs the Chromium snap.
  - On 2026-11-16 `api.snapcraft.io` returned HTTP 408 and refused
    connections, and `snapcraft.io` returned 502. A local test from the
    maintainer's machine saw 2 of 7 requests succeed at 13:38 and 7 of 8 at
    14:00, while the package info endpoint still failed.
  - In 4 of 5 dispatches the snap install failed, dpkg exited 100, and every
    later step was skipped.
- **Alternatives considered**: retrying the step. Retries only shorten the
  outage window; they do not remove the dependency.

## R3 — What else in the repository refers to the old setup?

- **Decision**: update the docs and `.env.example`, and remove the two unused
  parameters in `download.py`.
- **Rationale**:
  - `README.md`, `docs/flows-and-entrypoints.md` and
    `docs/operations/automation.md` describe a Selenium/chromedriver version
    check that no longer exists, and show `CHROME_BINARY=...` in example
    commands.
  - `.env.example` offers both variables for local use.
  - `validate_script_lattes_runtime(chromedriver_path, chrome_binary)` and
    `patch_script_lattes_runtime(chrome_binary)` ignore their parameters, and
    every caller in `src/` and `tests/` calls them without arguments.
  - `.github/workflows/ci.yml` installs no browser. The Makefile sets neither
    variable.
- **Alternatives considered**: leaving the parameters for compatibility. No
  caller passes them, so they only suggest a configuration that does nothing.

## R4 — Docker

- **Decision**: unchanged.
- **Rationale**: the request puts Docker out of scope. The image installs
  Chromium through Debian apt (`chromium`, `chromium-driver`), which is not the
  snap and is not affected by the outage. `.env.example` keeps its Docker
  comment while the Docker files still set the variables.

## R5 — The `selenium` dependency and the PDF report script

- **Decision**: unchanged.
- **Rationale**:
  - Removing `selenium>=4.0.0` from `requirements.txt` and `pyproject.toml`
    changes the installed packages; it is harmless but outside the purpose of
    this spec and can be done later.
  - `generate_relatorio_institucional.py` looks for any installed Chromium to
    print a PDF. It runs only through its own Makefile target, never in the
    weekly.

## R6 — How to prove it

- **Decision**:
  - Workflow tests check that no step runs `apt-get install` of `chromium*` or
    `snap install`, that the env sets neither variable, and that the Playwright
    step is unchanged.
  - Then the project's usual validation: two local weeklies, and fork runs when
    the maintainer asks.
- **Rationale**: the local weekly shows the code change in `download.py` is
  harmless. Only a CI run can show that the runner has no hidden need for the
  apt Chromium.
