---

description: "Task list for spec 038: Parquet export archive"
---

# Tasks: Parquet export archive

**Input**: Design documents from `specs/038-parquet-export-archive/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/parquet-archive.md, quickstart.md

**Tests**: Included. The constitution's development workflow requires tests,
and the plan writes them before the change (they must fail first).

**Organization**: Tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 to US3)

Code: `src/core/logic/parquet_layout.py` (new, the column rule and the layout),
`src/flows/exports/parquet_archive.py` (new, the task and the flow),
`src/flows/exports/canonical_data.py` (in-process path, `SKIP_DIRS` comment),
`src/flows/pipelines/weekly_orchestrator.py` (the phase),
`src/scripts/export_parquet.py` (manual command over the module),
`app.py` (dispatch), `Makefile` (target), `.github/workflows/weekly-etl.yml`
(commit step), `.github/workflows/ci.yml` (archive check), `.githooks/pre-commit`
(archive check).
Tests: `tests/test_parquet_layout.py`, `tests/test_parquet_archive.py` (new),
`tests/test_export_parquet.py`, `tests/test_weekly_orchestrator.py`,
`tests/test_app_zip_exports.py`, `tests/test_zip_excludes_source_documents.py`,
`tests/test_weekly_etl_workflow.py`, `tests/test_check_publishable_archive.py`.

Terms used below (data-model.md, contracts/parquet-archive.md):

- **JSON archive**: `data/exports/exports_canonical.zip` (input, unchanged).
- **Parquet archive**: `data/exports/exports_parquet.zip` (output).
- **Top-level member**: a member of the JSON archive with no `/` in its name,
  other than `export_manifest.json`.
- **Column rule**: the table "Column rule" of data-model.md.
- **Layout**: the table "Layout of one JSON member" of data-model.md.
- **Equality**: "Equality of a table read back" of data-model.md (same rows in
  order, missing key = empty, JSON columns decoded, integers as integers).
- **Report**: `data/reports/parquet_archive_report.json`, fields in data-model.md.

---

## Phase 1: Setup

- [X] T001 Record the starting point in this file under this task: branch `038-parquet-export-archive` and its commit (`git log --oneline -1`), the full suite before any change (`.venv/bin/python -m pytest -q > logs/pytest_038_before.log 2>&1`; expected 1454 passed, 10 skipped) and the flake8 count of the repository (`.venv/bin/python -m flake8 src tests | wc -l`; expected 579). No code change.
  - Result: branch `038-parquet-export-archive` at `a43c7b7` (the tip of branch 037, with the spec, plan and tasks of 038 not committed); full suite before any change: 1454 passed, 10 skipped, 0 failed in 9m18 (logs/pytest_038_before.log, line 32); flake8 on `src tests`: 579. The suite ran in the background while T002 to T013 were written; it collected only the 1454 tests that existed when it started, and the counts match the end of spec 037.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the conversion every story uses: the column rule, the layout of one member, and reading a member back.

- [X] T002 Create tests/test_parquet_layout.py importing from `src.core.logic.parquet_layout`, with: (a) one parametrized test per row of the column rule (mixed text + integer + list + object like `value_json`; nested only; whole numbers → integer dtype that reads back as `int`; numbers with a fraction → float; text only; booleans with empties; all empty), each checking the column type, whether the column is in `json_columns`, and that every value reads back with its original kind and value; (b) a text value inside a JSON column that looks like JSON (`"123"`, `"[1]"`) reads back as the same text; (c) columns in first-seen order and a key missing from a row reads back empty; (d) `layout_members(name, data)` for a list of rows, an empty list, a graph, each of the three wrapped tables (also with an empty rows list) and a plain object, checking the member names of data-model.md, the `.meta.json` content and that a plain object comes back as the exact input bytes; (e) `read_member_back` rebuilds each of those values and `equal_to_json` accepts it, while `equal_to_json` rejects a changed value, a missing row and a reordered row; (f) the same input gives the same bytes for every member, twice; (g) a value the column rule cannot write raises `ParquetLayoutError` whose message names the member. Run and see it fail on the import.
  - Result: tests/test_parquet_layout.py written: 9 cases of the column rule, JSON-looking text, column order and missing keys, 7 layouts (rows, empty list, graph, the three wrapped tables, a plain object), byte copy of a plain object, meta files, equality, same bytes twice, and the error naming the member (an unreadable member is the case used). It failed on the import.
- [X] T003 Create src/core/logic/parquet_layout.py with a module docstring (what the layout is, branch 038, the dashboard reader it serves), `ParquetLayoutError`, `WRAPPED_TABLES` (moved from src/scripts/export_parquet.py), `encode_table(rows) -> tuple[bytes, list[str]]` (column rule; Parquet written in memory with zstd, no index), `layout_members(json_name, raw_bytes) -> list[tuple[str, bytes]]` (parses the member, applies the layout; sidecars and meta files as JSON with `ensure_ascii=False`; a plain object returns the raw bytes unchanged), `read_member_back(archive, json_name)` (rules 1 to 6 of contracts/parquet-archive.md section 1, from an open `zipfile.ZipFile`) and `equal_to_json(rebuilt, original)`; pandas, pyarrow and the standard library only; no file or database access besides the archive object it is given. Run tests/test_parquet_layout.py until every test passes.
  - Result: src/core/logic/parquet_layout.py written with pyarrow directly (no pandas: the arrays are built from the rule, so no dtype guessing). 23 passed. Checked on the local exports_canonical.zip of 2026-11-13: the 48 top-level members give a 50,424,097-byte archive and all 48 read back equal, the three wrapped tables included (66.5 s and 1.6 GB for build plus read-back).

**Checkpoint**: one member can be converted and read back equal. Nothing is built or published yet.

---

## Phase 3: User Story 1 - The weekly run publishes a Parquet archive (Priority: P1) 🎯 MVP

**Goal**: every weekly run writes `exports_parquet.zip` from the JSON archive, and the weekly workflow commits both archives together.

**Independent Test**: build the Parquet archive from a JSON archive made in the test; open it; every top-level member reads back equal; the JSON archive is unchanged.

### Tests for User Story 1

- [X] T004 [P] [US1] Create tests/test_parquet_archive.py with a fixture that writes a small JSON archive in `tmp_path` (a list of rows with a mixed column, an empty list, a graph, `horizon_ids_canonical.json` wrapped, a plain object, a member under `research_group_relationship_graphs/`, and `export_manifest.json`), and tests that `build_parquet_archive(output_dir)` from `src.flows.exports.parquet_archive`: writes `exports_parquet.zip` whose members are the layout of every top-level member plus `export_manifest.json`, in name order with the manifest last; holds nothing from the folder member; every top-level member reads back equal (`read_member_back` + `equal_to_json`); leaves the JSON archive byte-identical; writes the report with `status` `built`, `members`, `archive_bytes`, `largest_member`, `largest_member_bytes`, `seconds` and `json_archive_sha256` equal to the sha256 of the JSON archive (report path passed in or patched to `tmp_path`). Run and see it fail on the import.
  - Result: tests/test_parquet_archive.py written with a JSON archive made in the test (a mixed column, an empty list, a graph, a wrapped table, a plain object, a folder member and the manifest): layout of every top-level member in name order with the manifest last, no folder member, every member read back equal, JSON archive unchanged, the report, and the flow. It failed on the import.
- [X] T005 [P] [US1] In tests/test_weekly_orchestrator.py add tests that `_PHASES` has `("parquet_archive", ["parquet_archive"], 900, False, "app")` right after `zip_exports`; that `_run_phase` passes the output folder to `parquet_archive` as it does for `zip_exports`; that `run_weekly` runs it when `zip_exports` passed and records it skipped (`rc` `skipped`, not critical, not run) when `zip_exports` failed or was skipped; and that its failure leaves the weekly "completed with non-critical failures" (exit 0). Follow the existing tests of the `zip_exports` gate in that file. Run and see them fail.
  - Result: 5 tests added to tests/test_weekly_orchestrator.py (phase entry after zip_exports, output folder passed, runs after zip_exports, skipped with the log line when zip_exports failed or was skipped, its failure leaves exit 0). Four failed; the last one passed before the change, because a phase that does not exist cannot fail the run.
- [X] T006 [P] [US1] In tests/test_app_zip_exports.py add tests that `app.py parquet_archive` runs `parquet_archive_flow` with `data/exports` by default and with the folder given as `sys.argv[2]`; that `export_canonical_data_flow(zip_exports=True)` calls the Parquet task after the zip task and still returns when the Parquet task fails; that `zip_exports=False` calls neither; and that `zip_exports_flow` still calls only the zip task. Run and see them fail.
  - Result: 5 tests added to tests/test_app_zip_exports.py (Parquet task after the zip task, the export flow returns when it fails, no Parquet task without the zip, the command with and without a folder); all 5 failed. The existing test that zip_exports_flow calls only the zip task is unchanged.
- [X] T007 [P] [US1] In tests/test_zip_excludes_source_documents.py add a test that a JSON archive built with an `exports_parquet.zip` (and its `.tmp`) present in the folder holds neither, and that its member list equals the one built without them (FR-008, FR-011). Run it (it may already pass: record that).
  - Result: test added to tests/test_zip_excludes_source_documents.py. It passed before any change: zip_exports_task already skips every nested .zip, and the .tmp file is not a text extension.
- [X] T008 [P] [US1] In tests/test_weekly_etl_workflow.py replace the step lookup of "Commit exports_canonical.zip if changed" with "Commit the export archives if changed" and add tests that its `run` checks each archive with `--ref HEAD --warn-only`, stages both paths, commits once with `chore(exports): update the export archives from weekly run`, and pushes once. Run and see them fail.
  - Result: the step lookup now uses 'Commit the export archives if changed'; the gate test looks for the check on "$ARCHIVE" before git add; a new test checks both paths, one git commit, one git push and the commit message. Both failed.

### Implementation for User Story 1

- [X] T009 [US1] Create src/flows/exports/parquet_archive.py: `REPORT_PATH = "data/reports/parquet_archive_report.json"`, `PARQUET_ARCHIVE_NAME = "exports_parquet.zip"`, a function `build_parquet_archive(output_dir, report_path=REPORT_PATH) -> dict` (opens `exports_canonical.zip` in `output_dir`, takes the top-level members in name order, writes each layout member and finally the JSON archive's `export_manifest.json` bytes to `exports_parquet.zip.tmp` with date 1980-01-01, permissions 0644 and DEFLATE; renames it over the archive; writes the report; logs the success line of contracts/parquet-archive.md section 6; never prints a value), a Prefect task `parquet_archive_task(output_dir)` returning the report, and a flow `parquet_archive_flow(output_dir="data/exports")` with `telegram_flow_state_handlers()` that raises when the report says `failed`. Run tests/test_parquet_archive.py until the US1 tests pass.
  - Result: src/flows/exports/parquet_archive.py written as the task says; build_parquet_archive never raises (the report carries the failure) and the flow raises on a failed report. The 5 US1 tests of T004 pass.
- [X] T010 [US1] In app.py add the dispatch `parquet_archive` (folder from `sys.argv[2]`, default `data/exports`), beside `zip_exports`; in Makefile add `parquet-archive: prefect-server ## Build exports_parquet.zip from exports_canonical.zip in OUTPUT_DIR` running `$(FLOW_PYTHON) app.py parquet_archive "$(OUTPUT_DIR)"`, after `export-canonical`, and add it to `.PHONY`. Run the T006 dispatch tests.
  - Result: app.py dispatches parquet_archive (also run by app.py all, after zip_exports, as that command already runs the zip); Makefile has parquet-archive after export-canonical and in .PHONY. The dispatch tests pass.
- [X] T011 [US1] In src/flows/exports/canonical_data.py, in `export_canonical_data_flow`, after `zip_exports_task(output_dir)` call `parquet_archive_task(output_dir)` inside a `try` that logs an error and the "earlier run" warning on any exception (never raising); update the `SKIP_DIRS` comment for `parquet/` (stale folder of before spec 013, never produced or read; the Parquet archive is a separate file built from the JSON archive). Run tests/test_app_zip_exports.py and tests/test_export_canonical_data_flow.py.
  - Result: export_canonical_data_flow builds the Parquet archive after the JSON archive inside a try that logs the error and the earlier-run warning; SKIP_DIRS comment updated. tests/test_export_canonical_data_flow.py::test_export_canonical_data_flow_calls_tracking_exports_individually failed: it mocks the zip task but not the new one, so the real Parquet task ran and wrote a failed report under data/reports (that file was deleted). The test now mocks parquet_archive_task and checks it is called with the output folder. tests/test_app_zip_exports.py: 11 passed; tests/test_export_canonical_data_flow.py: 5 passed.
- [X] T012 [US1] In src/flows/pipelines/weekly_orchestrator.py add the phase `("parquet_archive", ["parquet_archive"], 900, False, "app")` right after `zip_exports` with a comment (spec 038: non-critical, built from the JSON archive just written, so both come from the same run); in `_run_phase` pass `output_dir` to it as to `zip_exports`; in `run_weekly`, before running it, skip it unless the `zip_exports` result of this run has `ok` true, logging `phase 'parquet_archive' skipped: zip_exports did not build the archive` and appending `{"name": "parquet_archive", "ok": False, "rc": SKIPPED, "critical": False}`. Run tests/test_weekly_orchestrator.py.
  - Result: phase added after zip_exports with the comment; _run_phase passes the output folder; run_weekly skips it unless zip_exports has ok in this run, logging the line of the contract and recording rc skipped, not critical. tests/test_weekly_orchestrator.py and tests/test_weekly_orchestrator_finalize.py: 43 passed.
- [X] T013 [US1] In .github/workflows/weekly-etl.yml rename the step to "Commit the export archives if changed" and rewrite its `run`: for each of `data/exports/exports_canonical.zip` and `data/exports/exports_parquet.zip` that exists, run `python -m src.scripts.check_publishable_archive <path> --ref HEAD --warn-only` and stage it if it still exists; warn when neither exists; exit 0 when nothing is staged; otherwise commit once with `chore(exports): update the export archives from weekly run $(date -u +%Y-%m-%d)` and push as today. Keep the spec 029 comment and add one line for spec 038. Run tests/test_weekly_etl_workflow.py.
  - Result: step renamed and rewritten as a loop over the two archives (gate with --warn-only, stage if still present), one commit with the new message and one push; spec 029 comment kept and a spec 038 line added; the YAML parses. tests/test_weekly_etl_workflow.py: 29 passed with tests/test_zip_excludes_source_documents.py.
- [X] T014 [US1] Run tests/test_zip_excludes_source_documents.py (T007); if it fails, fix it in `zip_exports_task` without changing the member list for any other file.
  - Result: tests/test_zip_excludes_source_documents.py passes with no change to zip_exports_task.
- [X] T015 [US1] In tests/test_export_parquet.py keep the existing test (it must still pass, importing `convert_dir` from src/scripts/export_parquet.py) and add tests that `convert_dir` converts a folder holding a mixed column and an unconvertible file, writing every other file and counting the failure, and that `main()` exits 1 and names the failed file. See them fail; then rewrite src/scripts/export_parquet.py as a thin command over `src.core.logic.parquet_layout` (same `--src`/`--dst` options and defaults; `convert_file` and `convert_dir` kept; files written as loose files in the layout; `sys.exit(1)` when any file failed). Run the file.
  - Result: two tests added (a mixed column converts and an unreadable file is counted; main exits 1 and logs the failed file's name). Both failed, the first with the original error ('Expected bytes, got a int object', column value_json). src/scripts/export_parquet.py rewritten over parquet_layout (convert_file, convert_dir, the same options; failures logged as errors; exit 1 when any file failed). The existing spec 020 test then failed on one line: it compared the id column with the pandas type 'Int64', and the column rule writes 64-bit integers that pandas reads as 'int64'. The line now checks that the column is an integer type, which is what it protects (numeric ids stay integers; horizon ids stay text). tests/test_export_parquet.py: 3 passed. No other code imports the script.

**Checkpoint**: a local build (`make parquet-archive`) writes the Parquet archive; the weekly has the phase; the workflow commits both archives.

---

## Phase 4: User Story 2 - The Parquet archive is as safe as the JSON archive (Priority: P1)

**Goal**: the Parquet archive carries only values that went through the safety net, the same manifest, and passes the same gate everywhere.

**Independent Test**: a JSON archive whose member had an e-mail and a phone replaced gives a Parquet archive with the same replacements and no plain value; the gate refuses a bad Parquet archive as it refuses a bad JSON archive.

### Tests for User Story 2

- [X] T016 [P] [US2] In tests/test_parquet_archive.py add tests that: the JSON archive is built by `zip_exports_task.fn` (with the same setup as tests/test_zip_exports_scan.py: the `HORIZON_PII_HMAC_KEY` it relies on and its fixture that patches `canonical_data.SCAN_REPORT_PATH` to `tmp_path`) from a folder whose export holds a plain e-mail and phone; the Parquet archive built from it reads back with the same replaced values and, after `json.dumps` of every member read back, `scan_text` counts 0 everywhere; the Parquet archive's `export_manifest.json` is byte-identical to the JSON archive's; a JSON archive without `export_manifest.json` stops the build (report `failed`, reason names the manifest, no Parquet archive written).
  - Result: 3 tests added to tests/test_parquet_archive.py: a JSON archive built by the real zip task from an export with a plain e-mail and phone gives Parquet values equal to the published ones, without the plain values and with no scan match; the manifest is byte-identical; a JSON archive without manifest stops the build (failed, reason names the manifest, no archive). They passed at once: T009 already copies the manifest and stops without it.
- [X] T017 [P] [US2] In tests/test_check_publishable_archive.py add tests that run `refusals` on Parquet archives built by `build_parquet_archive`: no manifest (refused), `official` false (refused), a different key from the archive at the ref (refused), and a good one (publishable); follow the existing helpers of that file.
  - Result: 4 tests added to tests/test_check_publishable_archive.py on Parquet archives built by the real build in a throwaway repository (no manifest, not official, other key: refused; good: publishable). They passed at once.
- [X] T018 [P] [US2] In tests/test_weekly_etl_workflow.py change the CI test so `ci.yml` "Check the export archive" checks each of the two archive paths that changed since the base; add a test that `.githooks/pre-commit` runs the check on each of the two archives when staged. See them fail.
  - Result: the CI test now also requires the Parquet archive's path; a new test requires the hook to check both paths. Both failed.

### Implementation for User Story 2

- [X] T019 [US2] Make T016 pass in src/flows/exports/parquet_archive.py (the manifest copy and the stop when it is missing, if T009 did not already cover it) and T017 pass with no change to src/scripts/check_publishable_archive.py; if that script needs a change, record why.
  - Result: nothing to change: T016 and T017 passed with the code of T009, and src/scripts/check_publishable_archive.py is unchanged (it already takes any archive path).
- [X] T020 [US2] In .github/workflows/ci.yml make the step "Check the export archive" loop over `data/exports/exports_canonical.zip` and `data/exports/exports_parquet.zip`, checking each that changed since `BASE_SHA` and printing "did not change" for the others; in .githooks/pre-commit loop the archive check over both paths, keeping the block message per path. Leave the 50,000,000-byte rule of the hook as it is (research R9). Run tests/test_weekly_etl_workflow.py.
  - Result: ci.yml checks each of the two archives that changed since BASE_SHA in a loop; .githooks/pre-commit checks each staged archive in a loop with the same block message; the 50,000,000-byte rule of the hook is unchanged. The YAML parses, sh -n passes the hook, tests/test_weekly_etl_workflow.py: 19 passed.

**Checkpoint**: the Parquet archive is built only from scanned text, carries the manifest, and is gated in the weekly, in CI and in the hook.

---

## Phase 5: User Story 3 - A failed or repeated build changes nothing (Priority: P2)

**Goal**: the same JSON archive gives the same Parquet bytes; any failure keeps the previous Parquet archive and never touches the JSON archive.

**Independent Test**: build twice and compare the bytes; force each failure and check the previous archive and the report.

### Tests for User Story 3

- [X] T021 [P] [US3] In tests/test_parquet_archive.py add tests that: two builds from the same JSON archive give byte-identical Parquet archives; every member has date `(1980, 1, 1, 0, 0, 0)`; a member that cannot be converted (patch `layout_members` to raise `ParquetLayoutError` for one name) fails the build with the previous Parquet archive byte-identical, no `.tmp` file left, the report `failed` with `failed_member` and `reason`, the "earlier run" warning in the log (loguru sink), and the JSON archive byte-identical; a member over the limit and an archive over the limit (patch the limit constant low) fail the same way; with no previous Parquet archive a failure leaves none; `parquet_archive_flow` raises on a failed build.
  - Result: 6 tests added to tests/test_parquet_archive.py (same bytes twice and the fixed date; a member that cannot be converted; a member over the limit (400 bytes, the largest member is 1,020); the archive over the limit (2,500 bytes: every member fits, the archive is 3,691); a failure with no previous archive; the flow raises on a failed build). Each failure checks the previous archive byte for byte, no .tmp left, the report failed with the reason, the earlier-run warning, and the JSON archive unchanged. They passed at once: T009 already had the limits, the clean-up and the warning, so they were not seen failing.

### Implementation for User Story 3

- [X] T022 [US3] Make T021 pass in src/flows/exports/parquet_archive.py: `MAX_ARCHIVE_BYTES` (same value as the JSON archive's, spec 029) checked for each member before it is written and for the finished file; every error caught around the build removes the temporary file, writes the report `failed` with the member and reason, logs the error and the warning `exports_parquet.zip is now from an earlier run than exports_canonical.zip`, and returns the report (the flow raises from it).
  - Result: nothing to change: the code of T009 already does what the task asks. tests/test_parquet_archive.py: 14 passed.

**Checkpoint**: the Parquet archive changes only when the JSON archive does, and a failure leaves both archives as they were.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T023 [P] Update docs: in docs/2 - implementacao/ADR/003-parquet-canonical-storage.md add an amendment (2026-11-14, feature 038): the Parquet layout is published again, as `exports_parquet.zip`, built by the weekly phase `parquet_archive` from `exports_canonical.zip` after the safety net, with the new column rule; in docs/outputs-and-artifacts.md describe the second archive (contents, layout, column rule, reading rules, limits, manifest and gate, report, that the ETL never reads it, and that the old `data/exports/parquet/` folder is obsolete and can be removed by hand); in docs/flows-and-entrypoints.md add the phase after `zip_exports`, `app.py parquet_archive`, `make parquet-archive` and the manual command; in docs/backlog.md add TD-054 "The Parquet archive grows the repository history" (about 40 to 50 MB per run in which the data changed; options: release asset, history rewrite, a separate data repository), checking the next free number first.
  - Result: ADR-003 has a second amendment (2026-11-14, feature 038) and its status line names both; docs/outputs-and-artifacts.md has a section for exports_parquet.zip (built from, members, column rule, limits, failure, report, publishing, never read by the ETL, the obsolete parquet/ folder, the commands) and the commit item names both archives; docs/flows-and-entrypoints.md has a section 'Parquet export archive (branch 038)' before the SQLite settings; docs/backlog.md has TD-054 (no entry had that number). New text in English, the older Portuguese lines of outputs-and-artifacts.md left as they were.
- [X] T024 [P] Run black, isort and flake8 (`--check`/`--diff` first) on the touched files only: the two new source files, src/flows/exports/canonical_data.py, src/flows/pipelines/weekly_orchestrator.py, src/scripts/export_parquet.py, app.py and the touched test files; apply the formatters only to lines of this branch; record the flake8 count of the repository (must not grow from T001).
  - Result: black reformatted the two new source files (one blank line at the end, one long condition) and one assertion of tests/test_weekly_etl_workflow.py written in this branch; isort moved the new import into place in app.py and src/flows/exports/canonical_data.py. flake8 on the 15 touched files: 0 findings. Repository: 579 (579 at T001).
- [X] T025 Run the full suite (`.venv/bin/python -m pytest -q > logs/pytest_038_full.log 2>&1`) and record the result under this task; expected: every test of T001 still passes plus the new ones, 0 failed. Record `make ci-check` as in spec 037 T025.
  - Result: 1511 passed, 10 skipped, 0 failed in 7m40 (logs/pytest_038_full.log, line 38): the 1454 of T001 plus 57 new. No report or archive was left under data/ by the tests. flake8 of the repository: 579. make ci-check was not run again; it fails on the repository before this branch (spec 033 T026).
- [X] T026 Build from the current local JSON archive, no weekly run (back up `data/exports/exports_parquet.zip` if it exists): quickstart.md sections 2 to 7. Record under this task the report, the archive size, the largest member, the member dates, the count of members compared and different, the safety-net matches, the two hashes of section 6 and the gate's answer. Confirm with `git status` which files changed.
  - Result: (2026-11-14, passed) no data/exports/exports_parquet.zip existed before, so there was nothing to back up. Built with `make -o prefect-server parquet-archive` (the Prefect server was already running; -o keeps make from calling docker compose, which cannot read the local .env). Report: status built, 126 members, 50,424,272 bytes, largest source_records_canonical.parquet 7,816,047 bytes, 25.25 s; json_archive_sha256 674422d7…0787 equals sha256sum of the JSON archive (local archive of the second run of spec 037, 2026-11-13). Member dates: only (1980, 1, 1, 0, 0, 0); attribute_assertions_canonical.parquet present. Section 4: 48 members compared, 0 different. Section 5: no member with a safety-net match. Manifest byte-identical to the JSON archive's. Section 6: two builds, same sha256 (85b60f29…e206). Section 7: refused, 'the archive was not built by the official workflow' only; the local JSON archive is refused for the same reason and also for 'the anonymization key differs from the archive at HEAD', a check the Parquet archive cannot fail yet because HEAD has no Parquet archive. git status: the code, tests, docs and spec files of this branch, plus data/exports/exports_parquet.zip (new, local, carries the local LinkedIn links like the JSON archive, not to be committed) and the JSON archive already changed by the spec 037 runs.
- [X] T027 Local weekly run (ask the maintainer first; back up `db/horizon.db`, `data/lattes_json` and `data/raw` before): quickstart.md section 8. Record the phase line of `parquet_archive`, its time, sections 3 to 5 on the new archives, that `json_archive_sha256` equals the JSON archive's hash, and that the JSON archive's member list equals the one before the change.
  - Result: (2026-11-14, passed) backup in data/_backup_2026-11-14_pre038/ (horizon.db, lattes_json, raw, both archives, RESTORE.txt), database hash checked. Weekly 18:51-19:33 with make weekly-flows, exit 0, 24 phases with exit 0, parquet_archive right after zip_exports; rule version 6, no reset (logs/weekly_038_run1.log). Phase line: 'Parquet archive built: 126 members, 50497579 bytes, largest source_records_canonical.parquet (7825302), 27.24 s'; the phase took 34 s (zip_exports ended 19:30:33, parquet_archive 19:31:07). Report: built, json_archive_sha256 equal to the JSON archive of the run. Section 3: one member date (1980-01-01), manifest byte-identical. Section 4: 48 members compared, 0 different. Section 5: no safety-net match. researchers_canonical read back from the Parquet archive: 18,330 entries, 148 with linkedin_url. JSON archive member list identical to the one before the change (732 members). Sources: 7 of 435 curricula processed again in each Lattes phase (428 skipped); linkedin links unchanged (added 0, changed 0, removed 0).
- [X] T028 Second local weekly run (ask the maintainer first): the same records as T027, plus whether the Parquet archive changed and, if it did, that the JSON archive changed too.
  - Result: (2026-11-14, passed) database after T027 copied to data/_backup_2026-11-14_pre038/horizon_after_run1.db. Weekly 19:36-20:15, exit 0, 24 phases with exit 0, rule version 6, no reset (logs/weekly_038_run2.log). Phase line: 'Parquet archive built: 126 members, 50525276 bytes, largest source_records_canonical.parquet (7831571), 20.25 s'; the phase took 24 s. Report built, json_archive_sha256 equal to the JSON archive of the run; one member date; manifest byte-identical; 48 members compared, 0 different; no safety-net match; researchers 18,334 with 148 linkedin_url; JSON archive member list identical to the one before the change. Both archives changed from T027 (JSON 979917108fe592e5 -> e47683bb3ebdae42, Parquet 88735ea35a9d3a6c -> f83bace1f5cf8066): the JSON archive changed first, from the sources (2 SigPesq groups and 4 of 435 curricula processed again; persons 18,330 -> 18,334, horizon ids 75,763 -> 75,779) and from the run records it always carries, so the Parquet archive changed with it, as expected. Linkedin links unchanged (added 0, changed 0, removed 0).
- [ ] T029 GitHub Actions (only if the maintainer asks; only on the RafaelDeps fork, never upstream; push without force): one weekly run on this branch; record that the phase passed, that the commit step checked and committed both archives in one commit, and the size of `exports_parquet.zip` in the commit. Or record that the maintainer chose not to run it.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001; blocks every story (all use `parquet_layout`).
- **US1 (Phase 3)**: after Phase 2.
- **US2 (Phase 4)**: after T009 (the build function); its workflow and hook changes (T020) after T013, which rewrites the same workflow file family.
- **US3 (Phase 5)**: after T009.
- **Polish (Phase 6)**: after the stories; T026 before T027, T027 before T028, T028 before T029.

### Within Each User Story

- Tests are written first and seen failing, then the code.
- T009 before T010, T011, T012; T013 after T008.
- Files touched by more than one task (tests/test_parquet_archive.py: T004, T016, T021; src/flows/exports/parquet_archive.py: T009, T019, T022; tests/test_weekly_etl_workflow.py: T008, T018) are edited in task order.

### Parallel Opportunities

- T004, T005, T006, T007, T008 touch different files and can be written together.
- T016, T017, T018 touch different files.
- T023 and T024 touch different files.

---

## Parallel Example: User Story 1

```bash
Task: "T004 tests/test_parquet_archive.py: build from a small JSON archive"
Task: "T005 tests/test_weekly_orchestrator.py: the phase and its skip rule"
Task: "T006 tests/test_app_zip_exports.py: dispatch and the in-process path"
Task: "T007 tests/test_zip_excludes_source_documents.py: the JSON archive never holds the Parquet archive"
Task: "T008 tests/test_weekly_etl_workflow.py: one commit for both archives"
```

---

## Implementation Strategy

### MVP First (User Stories 1 and 2)

1. Phase 1 and Phase 2: the conversion reads every member back equal.
2. Phase 3 (US1): the archive is built locally and in the weekly, and committed.
3. Phase 4 (US2): it is as safe as the JSON archive. US1 is not published without US2.
4. Validate with quickstart.md sections 2 to 7 (T026).

### Incremental Delivery

1. Foundation → US1 + US2 → T026 (local build) → the dashboard work can start from a local archive.
2. US3 → failures and repeated builds are safe.
3. Polish → docs, full suite, two local weekly runs, the fork run if asked.

---

## Notes

- No database, rule version, Docker, third-party library or dashboard change.
- The JSON archive is only read by this feature; tests check it stays byte-identical.
- No export value is printed by the build, the tests' failure messages or the quickstart checks (counts and names only).
- Weekly runs and the fork run happen only with the maintainer's go-ahead.
