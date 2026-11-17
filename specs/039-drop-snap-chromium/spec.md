# Feature Specification: Weekly workflow without the snap Chromium

**Feature Branch**: `039-drop-snap-chromium`

**Created**: 2026-11-16

**Status**: Draft

**Input**: User description: "Remove the snap-based Chromium install from the weekly workflow, so a Snap Store outage no longer stops the weekly run."

## Background

The weekly workflow (`.github/workflows/weekly-etl.yml`) installs a browser twice
before it runs the ETL:

| Step | How it installs | Used by |
|------|-----------------|---------|
| Install Playwright Chromium | `.venv/bin/python -m playwright install --with-deps chromium`, downloaded from Playwright's own servers | the Lattes download: scriptLattes, patched in `src/flows/lattes/download.py`, opens the browser with Playwright, and the flow checks the Playwright Chromium before it starts (`validate_script_lattes_runtime`) |
| Install Chromium for Lattes (Selenium) | `sudo apt-get install -y chromium-browser chromium-driver`; on the Ubuntu runner the apt package `chromium-browser` only installs the Chromium snap, so the step downloads from the Snap Store (`api.snapcraft.io`) | nothing |

The workflow also sets `CHROME_BINARY=/usr/bin/chromium-browser` and
`CHROMEDRIVER_PATH=/usr/bin/chromedriver` for the job.

Nothing in `src/`, `app.py` or the installed libraries imports Selenium or reads
`CHROME_BINARY` or `CHROMEDRIVER_PATH`. The second step is left over from the
time the Lattes download ran on Selenium. Branch `fix-stale-tests` (TD-031)
already noted that scriptLattes now runs on Playwright.

On 2026-11-16 the Snap Store was unstable: HTTP 408 on assertion downloads,
refused connections to `api.snapcraft.io`, and HTTP 502 on `snapcraft.io`. The
second step failed in 4 of 5 weekly runs on the fork's main (43884759079,
43888936897, 43900663973, 43908662006 and 43916614948). The same failure
happened on branch 036. When the step fails, every later step is skipped: the
ETL never starts and no export archive is published. The Playwright step never
failed.

Other places that still describe the old setup:

- `README.md` (lines 117-138), `docs/flows-and-entrypoints.md` (lines 60-68) and
  `docs/operations/automation.md` (lines 112-113) say the Lattes download uses
  Selenium and a local `chromedriver`, and show `CHROME_BINARY=...` in the
  commands.
- `.env.example` has `CHROME_BINARY=` and `CHROMEDRIVER_PATH=`.
- `src/flows/lattes/download.py` keeps the unused parameters `chromedriver_path`
  and `chrome_binary` in `validate_script_lattes_runtime` and
  `patch_script_lattes_runtime`.
- `requirements.txt` and `pyproject.toml` list `selenium>=4.0.0`, although no
  code imports it.
- `Dockerfile` and `docker-compose.yml` install Chromium through apt and set
  both variables; Docker is out of scope.
- `src/scripts/generate_relatorio_institucional.py` looks for any installed
  Chromium (`chromium-browser` among others) to render a PDF report. It runs only
  through its own Makefile target, never in the weekly.
- `.github/workflows/ci.yml` installs no browser.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The weekly reaches the ETL even when the Snap Store is down (Priority: P1)

As the maintainer, I want the weekly run in GitHub Actions to start the ETL
whether or not the Snap Store answers, so that a third-party outage does not stop
the weekly and the export archives keep being published.

**Why this priority**: today one unused install step decides whether the whole
weekly runs. On 2026-11-16 it stopped 4 of 5 runs, and with them every export
archive of the day.

**Independent Test**: dispatch the weekly workflow on the fork and check that no
step downloads from the Snap Store or installs a browser through apt, that the
Lattes phases download the curricula, and that every phase passes.

**Acceptance Scenarios**:

1. **Given** the weekly workflow, **When** its steps are read, **Then** no step installs a browser through apt or snap, and the Playwright Chromium install is still there, unchanged.
2. **Given** the job environment of the weekly workflow, **When** it is read, **Then** it sets neither `CHROME_BINARY` nor `CHROMEDRIVER_PATH`.
3. **Given** a weekly run in GitHub Actions on the fork, **When** it reaches the Lattes phases, **Then** the curricula are downloaded with the Playwright Chromium, as before, and every phase passes.
4. **Given** the Snap Store is unreachable, **When** the weekly runs, **Then** no step fails because of it.

---

### User Story 2 - The documentation describes the browser the download really uses (Priority: P2)

As the maintainer or a new member of the team, I want the README and the docs
to say that the Lattes download uses the Playwright Chromium, so that nobody
installs a `chromedriver` or sets `CHROME_BINARY` for nothing.

**Why this priority**: the outdated text does not break a run, but it sends
people after a setup the project no longer uses, and it hid that the snap step
was useless.

**Independent Test**: read `README.md`, `docs/flows-and-entrypoints.md`,
`docs/operations/automation.md` and `.env.example`, and check that none of them
asks for Selenium, `chromedriver`, `CHROME_BINARY` or `CHROMEDRIVER_PATH` for the
Lattes download, and that they say how to install the Playwright Chromium.

**Acceptance Scenarios**:

1. **Given** the README and the docs, **When** they describe the Lattes download, **Then** they name the Playwright Chromium and the command that installs it, and no longer mention Selenium, `chromedriver` or a version check against it.
2. **Given** the example commands in the README and the docs, **When** they are read, **Then** none of them sets `CHROME_BINARY`.
3. **Given** `.env.example`, **When** it is read, **Then** it no longer offers `CHROME_BINARY` and `CHROMEDRIVER_PATH` for a local run.

---

### User Story 3 - A local weekly still runs as before (Priority: P3)

As the maintainer, I want a local weekly run to behave exactly as before, so
that the change only removes what was unused.

**Why this priority**: the change is in the workflow and the docs; the local run
is the check that nothing the ETL needs was removed.

**Independent Test**: run `make weekly-flows` locally and check that every
phase passes and that the Lattes phases download and process the curricula as in
the previous local run.

**Acceptance Scenarios**:

1. **Given** a machine with the Playwright Chromium installed, **When** the local weekly runs, **Then** every phase passes and the Lattes download behaves as before.

---

### Edge Cases

- **The Playwright install fails**: the weekly must still stop at that step, as
  today, because the Lattes download needs it. The change does not add a fallback
  browser.
- **Some other step depends on the apt Chromium without saying so**: the
  scenarios above (CI weekly on the fork with every phase passing, and a local
  weekly) are what proves there is none.
- **A local `.env` still sets `CHROME_BINARY` or `CHROMEDRIVER_PATH`**: nothing
  reads them, so a run must behave the same with or without them.
- **Docker**: the image keeps its apt Chromium and both variables; this spec
  does not touch it.
- **The PDF report script** (`generate_relatorio_institucional.py`) keeps
  looking for any installed Chromium; it is not part of the weekly.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The weekly workflow MUST NOT have a step that installs a browser or a browser driver through apt or snap. The step "Install Chromium for Lattes (Selenium)" MUST be removed.
- **FR-002**: The weekly workflow MUST keep the step that installs the Playwright Chromium, with the same command.
- **FR-003**: The weekly workflow MUST NOT set `CHROME_BINARY` or `CHROMEDRIVER_PATH`.
- **FR-004**: The other workflows, the Makefile and the scripts MUST be checked for a browser install through apt or snap, or for `CHROME_BINARY` and `CHROMEDRIVER_PATH`. What the weekly or the local run does not use MUST be removed; Docker files and the PDF report script stay as they are.
- **FR-005**: The unused parameters `chromedriver_path` and `chrome_binary` of `validate_script_lattes_runtime` and `patch_script_lattes_runtime` MUST be removed, together with any caller that passes them. The Playwright Chromium check before the Lattes download MUST stay.
- **FR-006**: `README.md`, `docs/flows-and-entrypoints.md` and `docs/operations/automation.md` MUST say that the Lattes download uses the Playwright Chromium and how to install it, and MUST NOT ask for Selenium, `chromedriver`, `CHROME_BINARY` or `CHROMEDRIVER_PATH` for it.
- **FR-007**: `.env.example` MUST NOT offer `CHROME_BINARY` and `CHROMEDRIVER_PATH` for a local run. A comment for Docker MAY stay if the Docker files still use them.
- **FR-008**: The workflow tests MUST check that the weekly workflow has no apt or snap browser install and sets neither variable, and that the Playwright Chromium install is still there.
- **FR-009**: The ETL phases, the Lattes download and its retries, scriptLattes and every other third-party library MUST stay as they are.
- **FR-010**: The change MUST work in a local run and in the GitHub Actions weekly, with no new setting and no Docker change.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The weekly workflow contains 0 steps that install a browser through apt or snap, and 0 references to `CHROME_BINARY` or `CHROMEDRIVER_PATH`.
- **SC-002**: A weekly run dispatched in GitHub Actions on the fork starts the ETL and passes all phases, with no step that contacts the Snap Store.
- **SC-003**: In that run the Lattes phases download and process the curricula, with download counts in the same range as the fork's run of 2026-11-15 (43663739197).
- **SC-004**: A local weekly run passes all phases.
- **SC-005**: `README.md`, `docs/flows-and-entrypoints.md`, `docs/operations/automation.md` and `.env.example` contain 0 instructions that ask for Selenium, `chromedriver`, `CHROME_BINARY` or `CHROMEDRIVER_PATH` for the Lattes download.
- **SC-006**: The test suite passes, including the updated workflow tests.

## Assumptions

- The Lattes download uses only the Playwright Chromium. This was found by
  reading the code and the logs of the CI runs that passed; the CI run of
  SC-002 is the proof.
- The `selenium` entry in `requirements.txt` and `pyproject.toml` stays. Removing
  an unused dependency changes the installed packages and is left for later; it
  does not affect the weekly.
- Docker keeps its own Chromium and variables, as the request leaves Docker out
  of scope.
- The validation follows the project's practice: two local weekly runs and the
  fork runs the maintainer asks for, on the fork only.
