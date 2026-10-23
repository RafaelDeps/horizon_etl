# Tasks: Weekly CI Workflow Validation and Export Compression

**Input**: Design documents from `specs/003-workflow-ci-zip-exports/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

**Single file change**: All tasks modify `.github/workflows/weekly-etl.yml` only (plus the `.gitignore` guard in the amendment below).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

**Purpose**: Confirm baseline state before making changes.

- [X] T001 Read current `.github/workflows/weekly-etl.yml` and annotate all sections requiring changes per plan.md

---

## Phase 2: Foundational

**Purpose**: No shared infrastructure needed; all stories touch the same file — execute sequentially.

*(No foundational tasks — feature is a single YAML file edit)*

---

## Phase 3: US1 — Reliable Weekly Pipeline Execution in CI (P1)

**Story goal**: Workflow permissions allow artifact upload; Prefect cleanup always runs.

**Independent test**: Trigger `workflow_dispatch`; verify no permission error on artifact upload step and `Stop Prefect server` runs on failure.

- [X] T002 [US1] Add `actions: write` to `permissions:` block in `.github/workflows/weekly-etl.yml` (alongside existing `contents: read`)
- [X] T003 [US1] Verify `Stop Prefect server` step already has `if: always()` in `.github/workflows/weekly-etl.yml`; add it if missing

---

## Phase 4: US2 — Automatic Compression of Large Export Files (P2)

**Story goal**: Any export file >10 MB is compressed to `.zip` before artifact upload; retention set to 30 days.

**Independent test**: After pipeline run, confirm no uncompressed file >10 MB in artifact and retention shows 30 days.

- [X] T004 [US2] Insert `Compress large export files` step (with `if: always()`) before `Upload ETL artifacts` step in `.github/workflows/weekly-etl.yml`:
  ```yaml
  - name: Compress large export files
    if: always()
    run: |
      find data/ -type f -size +10M \
        -exec sh -c 'for f; do zip -m -j "$f.zip" "$f"; done' sh {} +
  ```
- [X] T005 [US2] Add `retention-days: 30` field to `actions/upload-artifact@v4` step in `.github/workflows/weekly-etl.yml`

---

## Phase 5: US3 — Lattes Flow Compatibility in CI (P3)

**Story goal**: Lattes Selenium flow locates a compatible Chrome binary and chromedriver in the CI environment.

**Independent test**: Run `make ingest-lattes-download` step in CI; verify it exits without `ChromeDriverRuntimeError`.

- [X] T006 [US3] Add `CHROME_BINARY: /usr/bin/chromium-browser` and `CHROMEDRIVER_PATH: /usr/bin/chromedriver` to job-level `env:` block in `.github/workflows/weekly-etl.yml`
- [X] T007 [US3] Insert `Install Chromium for Lattes (Selenium)` step after `Install Playwright Chromium` step in `.github/workflows/weekly-etl.yml`:
  ```yaml
  - name: Install Chromium for Lattes (Selenium)
    run: |
      sudo apt-get update -qq
      sudo apt-get install -y chromium-browser chromium-driver
  ```

---

## Phase 6: Polish & Validation

**Purpose**: Verify final YAML is valid and all acceptance criteria pass.

- [X] T008 Validate YAML syntax of `.github/workflows/weekly-etl.yml` by running `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/weekly-etl.yml'))"` from repo root
- [X] T009 Review full diff of `.github/workflows/weekly-etl.yml` against original to confirm all 4 changes are present: permissions, Chromium install step, compression step, retention-days

---

## Phase 7: US4 — Versioned Archive Publishing (P2)

**Amendment 2026-10-14**. Story goal: the workflow commits `exports_canonical.zip` byte-for-byte as the flow generated it, when it changed, and stops publishing it as a downloadable artifact.

**Independent test**: Trigger `workflow_dispatch`; verify the committed `data/exports/exports_canonical.zip` unzips to the canonical exports (no nested `exports_canonical.zip` member), that a re-run with identical content produces no commit, and that the artifact no longer contains the archive.

- [X] T010 [US4] Change `permissions.contents` from `read` to `write` in `.github/workflows/weekly-etl.yml` (required to push the archive commit)
- [X] T011 [US4] Add `! -name '*.zip'` to the `find` in the `Compress large export files` step so `exports_canonical.zip` is never re-wrapped (FR-003, SC-006)
- [X] T012 [US4] Insert `Commit exports_canonical.zip if changed` step (with `if: success()`, bot identity, `git diff --cached --quiet` no-op guard, `git push origin HEAD:${{ github.ref_name }}`) after `Compress large export files` and before `Upload ETL artifacts` (FR-009, FR-010)
- [X] T013 [US4] Add `!data/exports/exports_canonical.zip` to the `Upload ETL artifacts` `path:` so the archive is not downloadable (FR-011)
- [X] T014 [US4] Add `.gitignore` guard for `data/exports/exports_canonical.zip.zip` (never version the double-wrapped archive)
- [X] T015 [US4] Update the docs that describe the archive delivery: `specs/003-workflow-ci-zip-exports/{spec,plan,research,checklists/requirements}.md`, `specs/013-curate-export-zip/{spec,plan,research,data-model,quickstart}.md`, `docs/outputs-and-artifacts.md`, `docs/operations/automation.md`
- [X] T016 [US4] Validate the workflow: `python -c "import yaml; yaml.safe_load(open('.github/workflows/weekly-etl.yml'))"` from repo root

---

## Dependencies

```
T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009
                                                        ↓
                          T010 → T011 → T012 → T013 → T014 → T015 → T016
```

All sequential (same file). No parallel opportunities — single-file YAML edit
(T014 `.gitignore` and T015 docs are independent but trivial).

## Implementation Strategy

**MVP**: T001–T003 (US1 only) — fixes the critical permission bug so artifact upload works.

**Archive publishing**: T010–T016 — commit `exports_canonical.zip` when changed and stop publishing it as an artifact.

**Full**: T001–T016 — all stories complete.

**Suggested order for a single session**: Complete all tasks in order T001→T016; the file only needs to be edited once.
