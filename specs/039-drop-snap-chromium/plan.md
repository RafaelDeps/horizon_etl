# Implementation Plan: Weekly workflow without the snap Chromium

**Branch**: `039-drop-snap-chromium` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/039-drop-snap-chromium/spec.md`

## Summary

The weekly workflow loses its step "Install Chromium for Lattes (Selenium)"
(`apt-get install chromium-browser chromium-driver`, which pulls the Chromium
snap from the Snap Store) and the job variables `CHROME_BINARY` and
`CHROMEDRIVER_PATH`. The Playwright Chromium step stays as it is: it is the only
browser the Lattes download and the SigPesq agent open. The two unused
parameters of `validate_script_lattes_runtime` and `patch_script_lattes_runtime`
go, the docs and `.env.example` stop asking for Selenium, `chromedriver` and the
two variables, and the workflow tests guard against the step coming back.

The research confirmed that nothing reads the two variables or the apt
Chromium: no import of `selenium` in `src/`, `app.py` or the installed packages,
no read of `CHROME_BINARY` or `CHROMEDRIVER_PATH` outside the workflow, Docker
files and `.env.example`, and the CI runs that passed downloaded the curricula
through Playwright.

## Technical Context

**Language/Version**: Python 3.12 in GitHub Actions; the local `.venv` runs 3.14; GitHub Actions YAML

**Primary Dependencies**: Playwright (already installed, unchanged); scriptLattes and agent_sigpesq unchanged; no new dependency, none removed

**Storage**: N/A (no database or export change)

**Testing**: pytest; `tests/test_weekly_etl_workflow.py` (workflow YAML), `tests/test_download_lattes_flow.py` (runtime check)

**Target Platform**: GitHub Actions `ubuntu-latest` runner and the maintainer's Linux machine

**Project Type**: ETL pipeline (Prefect flows) with a CI workflow

**Performance Goals**: none; the weekly skips one apt/snap install (about 1 to 3 minutes when the Snap Store answers)

**Constraints**: no change to ETL phases, third-party libraries or Docker; works locally and in CI; nothing upstream (fork only)

**Scale/Scope**: 1 workflow file, 1 source file (2 signatures), 3 docs, `.env.example`, 2 test files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Note |
|-----------|--------|------|
| I. Ports & Adapters | Pass | No new adapter or port; the Lattes adapter's browser does not change. |
| II. Domain-First Data Modeling | Pass | No entity or export change. |
| III. Prefect Flow Orchestration | Pass | No flow added or changed in behaviour; only two unused parameters leave two functions. |
| IV. Audit-Driven Data Quality | Pass | Phases and reports unchanged; the weekly can now reach them when the Snap Store is down. |
| V. LGPD Compliance by Default | Pass | No data handling change. |
| Data Integrity & Persistent Incremental Ingestion | Pass | No change to keys, hashes, rule version or raw caches; no database rebuild needed. |
| Development Workflow & Quality Gates | Pass | black, isort and the full pytest suite run before commit; workflow tests updated. |

Post-design re-check: unchanged, all pass.

## Project Structure

### Documentation (this feature)

```text
specs/039-drop-snap-chromium/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1 (no data entities; records the workflow facts)
├── quickstart.md        # Phase 1 (how to validate locally and on the fork)
├── contracts/
│   └── weekly-workflow-browser.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
.github/workflows/weekly-etl.yml      # drop the apt/snap step and the two env vars
src/flows/lattes/download.py          # drop the unused parameters of two functions
tests/test_weekly_etl_workflow.py     # guard: no apt/snap browser, no env vars, Playwright step kept
tests/test_download_lattes_flow.py    # still calls both functions without arguments
README.md                             # "Fluxo Lattes": Playwright Chromium
docs/flows-and-entrypoints.md         # "Lattes": Playwright Chromium
docs/operations/automation.md         # browser notes
.env.example                          # no CHROME_BINARY / CHROMEDRIVER_PATH for a local run
```

**Structure Decision**: single project; the change touches the files above
only. Docker files (`Dockerfile`, `docker-compose.yml`, `.dockerignore`),
`requirements.txt`/`pyproject.toml` (`selenium` entry) and
`src/scripts/generate_relatorio_institucional.py` stay as they are (see
research R4 and R5).

## Complexity Tracking

No constitution violation; nothing to justify.
