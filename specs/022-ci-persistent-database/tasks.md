---

description: "Task list for the persistent database between GitHub Actions weekly runs"
---

# Tasks: Persistent Database Between GitHub Actions Weekly Runs

**Input**: Design documents from `specs/022-ci-persistent-database/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/restore-cli.md, contracts/workflow-steps.md, quickstart.md

**Tests**: requested by the spec (FR-012 local simulation; validation before any CI run), so each story starts with its tests.

**Organization**: tasks are grouped by user story; US1 and US2 are both P1 and
share the module, so US2 follows US1.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md

Scratch folder for downloaded artifacts and simulations: `$R` = this session's
scratchpad (never the repository, never `db/horizon.db`).

---

## Phase 1: Setup

- [X] T001 Record the baseline: run `.venv/bin/python -m pytest -q -p no:cacheprovider` and save the list of failing tests to `$R/c_fail_base.txt` (expected: the 6 failures known since spec 021); note the current workflow facts (step order, artifact `path`, `retention-days: 30`, compression command) from `.github/workflows/weekly-etl.yml` in `$R/C_BASE.txt`.
- [X] T002 [P] Download the artifact of the fork run 40856179199 into `$R/artifact_40856179199/` with `gh run download 40856179199 --repo RafaelDeps/horizon_etl -n weekly-etl-artifacts -D ...`; list its top-level folders and every `*.zip` under `data/raw/` in `$R/C_BASE.txt` (R3: are raw files compressed in a real artifact?), plus the sizes of `db/horizon.db`, `data/raw/` and (absent) `cache/`.

---

## Phase 2: Foundational

**Purpose**: the module skeleton, its outcome record and the make target that every story uses.

- [X] T003 Create `src/scripts/restore_weekly_artifact.py` with: an `Outcome` dataclass (`outcome`, `reason`, `source_run`, `restored` sizes, `checked_at`) as in data-model.md; `report(outcome, target, summary_path)` that writes one log line, `data/reports/restore_outcome.json` under the target and, when a summary path is given, the Markdown block of contracts/restore-cli.md; and an `argparse` `main()` with the modes `--github`, `--from-dir`, `--from-zip`, `--disabled` and the options `--target`, `--summary`, `--outcome`. `main()` always returns 0 for `restored` and `rebuilt` (FR-003).
- [X] T004 [P] Add `restore-weekly` to `Makefile` (listed in `.PHONY`, with a `##` description): `$(PYTHON) -m src.scripts.restore_weekly_artifact --github`, or `--disabled` when `FRESH_DATABASE` is `true`.
- [X] T005 [P] Create `tests/test_restore_weekly_artifact.py` with the shared fixtures: an `artifact_dir(tmp_path)` builder (a real small SQLite `db/horizon.db` with `persons` and `horizon_meta`, a `data/raw/` and a `cache/` with a few files), and a `fake_gh(tmp_path, monkeypatch, runs, artifacts, download_from)` that puts a `gh` script on `PATH` answering `run list`, `api .../artifacts` and `run download` from recorded JSON and a source folder.

**Checkpoint**: the module runs with `--disabled` and writes a "rebuilt: restore disabled" outcome.

---

## Phase 3: User Story 1 - A weekly CI run continues from the previous run's database (Priority: P1) 🎯 MVP

**Goal**: restore `db/horizon.db`, `data/raw` and `cache/` from the newest successful run of the branch before the phases (FR-001, FR-002, FR-004, FR-008).

**Independent Test**: on a scratch target, `--from-dir` on the real artifact of T002 places the three items and the database passes the check; with the fake `gh`, `--github` restores from the newest successful run.

### Tests for User Story 1

- [X] T006 [P] [US1] In `tests/test_restore_weekly_artifact.py`:
  - `--from-dir` places the database, `data/raw` and `cache/` under the target, replaces an existing database and removes its `-wal`/`-shm`, and leaves `data/exports`, `data/reports` (except the outcome file) and `data/lattes_json` of the target untouched;
  - `--from-zip` gives the same result from a zip of the artifact;
  - with the fake `gh`, `--github` lists runs with `--status success` on the given branch and repository, picks the newest one whose artifact is not expired (an expired newest run is passed over for an older live one), downloads it and records its id, date and sha in the outcome.
- [X] T007 [P] [US1] In `tests/test_weekly_etl_workflow.py` assert that `.github/workflows/weekly-etl.yml`:
  - has a step "Restore previous weekly run" running `make restore-weekly` before the step running `make weekly-flows`;
  - gives that step `GH_TOKEN: ${{ github.token }}` and `continue-on-error: true`.

### Implementation for User Story 1

- [X] T008 [US1] Implement the `--github` source in `src/scripts/restore_weekly_artifact.py` (research R2):
  - `gh run list --repo --workflow weekly-etl.yml --branch --status success --limit 20 --json databaseId,createdAt,headSha,event`;
  - for each run in order, `gh api repos/<repo>/actions/runs/<id>/artifacts`; skip it when `weekly-etl-artifacts` is missing or `expired`;
  - `gh run download <id> -n weekly-etl-artifacts -D <tmp>`;
  - all calls through `subprocess.run(..., capture_output=True, text=True, timeout=...)`;
  - repository and branch default to `GITHUB_REPOSITORY` and `GITHUB_REF_NAME`.
- [X] T009 [P] [US1] Implement the `--from-dir` (use the folder as is) and `--from-zip` (extract to a temporary folder) sources in `src/scripts/restore_weekly_artifact.py`.
- [X] T010 [US1] Implement the database check in `src/scripts/restore_weekly_artifact.py` (research R4): file present, `PRAGMA quick_check` returns `ok`, tables `persons` and `horizon_meta` exist; read-only connection (`mode=ro`).
- [X] T011 [US1] Implement the placement in `src/scripts/restore_weekly_artifact.py` (research R6, contract "Behaviour" 5):
  - `data/raw/` and `cache/` replace the working copies with a move;
  - the database is placed only when the check passed, after deleting `db/horizon.db`, `-wal` and `-shm`;
  - sizes are recorded; the temporary folder is removed at the end.
- [X] T012 [US1] Add the step "Restore previous weekly run" to `.github/workflows/weekly-etl.yml` after "Validate required secrets" and before "Run weekly flows", as in contracts/workflow-steps.md (`continue-on-error: true`, `GH_TOKEN`, `FRESH_DATABASE`, `run: make restore-weekly`).
- [X] T013 [US1] Local simulation (quickstart §2) on `$R/artifact_40856179199/` into `$R/restore_target/`:
  - outcome `restored`, three items placed, `quick_check` ok;
  - then run `DATABASE_URL=sqlite:///$R/restore_target/db/horizon.db make db-ensure` from that folder: it keeps the database and applies migrations.
  - Record the result in `$R/C_BASE.txt`. Never point it at the repository's `db/horizon.db`.

**Checkpoint**: US1 tests pass; the simulation restores the real artifact.

---

## Phase 4: User Story 2 - A run without a usable artifact rebuilds as today (Priority: P1)

**Goal**: every failure to restore ends as "rebuilt" with its reason and exit 0; the database is then created by `make db-ensure` (FR-003, FR-004).

**Independent Test**: each fallback case run with the fake `gh` or a broken artifact folder gives outcome `rebuilt`, the expected reason, exit 0, and no database placed.

### Tests for User Story 2

- [X] T014 [P] [US2] In `tests/test_restore_weekly_artifact.py`, one test per reason, each asserting exit 0, outcome `rebuilt`, the reason text of data-model.md, and that a pre-existing target database is left as it was (or absent):
  - `no successful run` (empty run list);
  - `artifact expired` (every run's artifact expired);
  - `download failed: ...` (`gh run download` exits non-zero);
  - `database missing` (artifact without `db/`; `data/raw` and `cache/` still placed);
  - `database check failed: ...` (a truncated database file);
  - `restore disabled`.
  - Also: `gh` missing from `PATH` gives `download failed`.

### Implementation for User Story 2

- [X] T015 [US2] In `src/scripts/restore_weekly_artifact.py`, map every failure of T008–T011 to an `Outcome("rebuilt", reason)`:
  - wrap `subprocess` errors, timeouts, JSON errors and file errors;
  - keep `source_run` when one had been chosen;
  - only an unexpected exception propagates (contract "Exit status").
- [X] T016 [US2] Add the `fresh_database` boolean input to `workflow_dispatch` in `.github/workflows/weekly-etl.yml` (contracts/workflow-steps.md) and pass it to the restore step as `FRESH_DATABASE`; add its assertion to `tests/test_weekly_etl_workflow.py`.
- [X] T017 [US2] Local simulation of the failure cases (quickstart §2) on `$R/restore_target/`:
  - a copy of the artifact without `db/`;
  - a truncated copy of the database;
  - `--disabled`.
  - Each gives its reason and leaves the target ready for `make db-ensure` to create the database. Record in `$R/C_BASE.txt`.

**Checkpoint**: US1 and US2 tests pass; no failure path fails the step.

---

## Phase 5: User Story 3 - The restored files are exactly what the phases read (Priority: P2)

**Goal**: no restored file is a compressed copy; `cache/` travels in the artifact; retention 90 days (FR-005, FR-006, FR-007, FR-009).

**Independent Test**: an artifact whose `data/raw` holds `PJ_X.pdf.zip` (only member `PJ_X.pdf`) restores `PJ_X.pdf` with the original bytes; the workflow test sees the new compression filter, `cache` in the upload and `retention-days: 90`.

### Tests for User Story 3

- [X] T018 [P] [US3] In `tests/test_restore_weekly_artifact.py`:
  - a `data/raw/.../X.zip` whose only member is `X` is restored as `X` with the same sha256;
  - a zip with other members, or whose member name differs, is left as it is;
  - `cache/` content is restored byte for byte.
- [X] T019 [P] [US3] In `tests/test_weekly_etl_workflow.py` assert that:
  - the compression step excludes `data/raw/*`;
  - the upload `path` lists `cache`;
  - `retention-days: 90`;
  - `!data/exports/exports_canonical.zip` is still excluded.

### Implementation for User Story 3

- [X] T020 [US3] Implement the unzip safety net in `src/scripts/restore_weekly_artifact.py` (research R3), applied to the downloaded `data/raw` before placement.
- [X] T021 [US3] In `.github/workflows/weekly-etl.yml`:
  - add `! -path 'data/raw/*'` to the "Compress large export files" `find`;
  - add `cache` to the "Upload ETL artifacts" `path`;
  - set `retention-days: 90`;
  - update the step comment to say why `data/raw` is not compressed.
- [X] T022 [US3] Check FR-009: confirm with a test or an existing one that `SigPesqAdapter._clean_download_dir` (`src/adapters/sources/sigpesq/adapter.py`) still clears `data/raw/sigpesq/` before the download (add an assertion to `tests/test_sigpesq_adapter.py` if none covers it).

**Checkpoint**: US3 tests pass; a restored artifact holds the files the phases read.

---

## Phase 6: User Story 4 - The run says where its database came from (Priority: P3)

**Goal**: the job summary and the outcome file state restored (run id, date, sha, sizes) or rebuilt (reason) (FR-011).

**Independent Test**: the summary file written for a restored and for a rebuilt outcome contains the texts of contracts/restore-cli.md, with a link to the source run.

### Tests for User Story 4

- [X] T023 [P] [US4] In `tests/test_restore_weekly_artifact.py`:
  - with `--summary FILE`, a restored outcome appends "Restored from run [<id>](https://github.com/<repo>/actions/runs/<id>) of <date> (`<sha7>`)" and the three sizes in MB;
  - a rebuilt outcome appends "Rebuilt from scratch: <reason>.";
  - `GITHUB_STEP_SUMMARY` is used when `--summary` is absent;
  - the outcome JSON matches data-model.md and holds no other field.

### Implementation for User Story 4

- [X] T024 [US4] Finish `report()` in `src/scripts/restore_weekly_artifact.py`:
  - summary block with the run link (from `GITHUB_SERVER_URL` and the repository);
  - sizes in MB;
  - the log line formats of contracts/restore-cli.md.

**Checkpoint**: all stories pass their tests.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T025 [P] Add a "Persistent database in GitHub Actions (spec 022)" section to `docs/flows-and-entrypoints.md`:
  - how a run restores from the last successful run of its branch, and what it restores;
  - the 90-day retention;
  - how to force a rebuild (`fresh_database`);
  - how to read the summary and `data/reports/restore_outcome.json`;
  - that a new branch starts with a rebuild.
- [X] T026 [P] Format and lint the new and changed files (`black`, `flake8`), run the full suite and compare with `$R/c_fail_base.txt`: no new failure.
- [ ] T027 First dispatch on the fork (quickstart §3), after the maintainer's go-ahead to push:
  - push `025-ci-persistent-database` to `origin` (the RafaelDeps fork) and dispatch `weekly-etl.yml` on it;
  - expected summary: "Rebuilt from scratch: no successful run";
  - record the run id, duration and per-phase document counts.
- [ ] T028 Second dispatch on the same branch after T027 succeeded:
  - expected summary: "Restored from run <T027 id>", the Lattes phases skipping at least 95% of the CVs (SC-002), and a duration of at most about 60% of T027's (SC-001, a reference target);
  - compare its `exports_canonical.zip` with T027's: same files and fields (SC-006).
- [ ] T029 Optional third dispatch with `fresh_database: true`: summary "restore disabled", a rebuild (US2 on CI).
- [ ] T030 Write `docs/reports/2026-XX-XX-ci-persistent-database-validation.md`:
  - results per success criterion SC-001 to SC-007;
  - the local simulation (T013, T017);
  - the dispatches (T027–T029) with durations and summaries;
  - the artifact sizes and the restore time.

---

## Dependencies & Execution Order

- **Setup (T001–T002)**: none; T002 needs network access to the fork.
- **Foundational (T003–T005)**: after Setup; T004 and T005 in parallel with T003's later parts.
- **US1 (T006–T013)**: after Foundational. T008–T011 touch the same module: sequential. T012 is independent of the module. T013 needs T002 and T008–T011.
- **US2 (T014–T017)**: after US1 (it maps US1's failure points). T016 touches the workflow after T012.
- **US3 (T018–T022)**: after US1. T020 is in the module (after T011); T021 is in the workflow (after T016).
- **US4 (T023–T024)**: after Foundational; T024 is in the module, after T020.
- **Polish (T025–T030)**: after all stories. T027–T029 need the push and the dispatches, so the maintainer's go-ahead; T028 needs T027 to succeed.

### Parallel Opportunities

- T002 beside T001; T004 and T005 beside T003.
- Test tasks of a story together (T006 and T007; T018 and T019).
- T025 and T026 together.

## Parallel Example: User Story 1

```bash
Task: "tests/test_restore_weekly_artifact.py — from-dir, from-zip and --github restore tests"
Task: "tests/test_weekly_etl_workflow.py — restore step before make weekly-flows"
```

## Implementation Strategy

1. **MVP** (Setup, Foundational, US1, US2): a run restores when it can and rebuilds otherwise. US2 is the safety half of the MVP, so do not dispatch on CI before it is done.
2. **US3**: the compressed raw files and `cache/`. Until it lands, a restored run still works but may download project PDFs over 10 MB again.
3. **US4**: the summary, then Polish and the two dispatches.

## Notes

- The module never writes to the repository's `db/horizon.db` in tests or simulations: always a temporary or scratch target.
- No Prefect flow, ETL phase, table or export changes in this spec.
- Commit only when the maintainer asks.
