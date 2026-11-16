# Research: Persistent Database Between GitHub Actions Weekly Runs

Facts checked on 2026-10-29 against `.github/workflows/weekly-etl.yml`, the
fork run 40856179199 and the local tree.

## R1. Where the database lives between runs

**Finding**: the workflow already uploads `weekly-etl-artifacts` at the end of
every run (`if: always()`, `retention-days: 30`), with `path: data` and
`db/horizon.db` (minus `exports_canonical.zip`, `.venv`, `.env*`). The upload
roots the artifact at the common ancestor, the repository root, so it holds
`data/...` and `db/horizon.db`. Run 40856179199 left an artifact of 366 MB
(compressed), expiring 2026-11-28.

**Decision**: keep the artifact as the store; restore from it at the start of
the next run. Add `cache/` to its paths (it then holds `cache/...` too) and
raise `retention-days` to 90.

**Alternatives considered**: `actions/cache` (evicted after 7 days without
access, the weekly interval, and limited to 10 GB per repository);
committing the database (318 MB, over the 100 MB file limit, and the history
would grow every week); an external database service (excluded by the spec).

## R2. Finding the run to restore

**Decision**: list the successful runs of this workflow on the run's own
branch, newest first, and take the first one that still has a non-expired
`weekly-etl-artifacts` artifact:

```bash
gh run list --repo "$GITHUB_REPOSITORY" --workflow weekly-etl.yml \
  --branch "$GITHUB_REF_NAME" --status success --limit 20 \
  --json databaseId,createdAt,headSha,event
gh api "repos/$GITHUB_REPOSITORY/actions/runs/<id>/artifacts" \
  --jq '.artifacts[] | select(.name == "weekly-etl-artifacts") | {id, expired, size_in_bytes}'
gh run download <id> --repo "$GITHUB_REPOSITORY" -n weekly-etl-artifacts -D <tmp>
```

`--status success` filters on the run's conclusion, so failed, cancelled and
in-progress runs (the current one included) are never candidates (FR-002).
The `gh` CLI is preinstalled on the runner; it needs `GH_TOKEN` set to the
workflow's own token, and `permissions: actions: write` (already granted)
covers reading artifacts of the same repository. Twenty candidates is about
five months of weeklies, more than the 90-day retention.

**Alternatives considered**: `actions/download-artifact` with `run-id` and
`github-token` (also possible, but it cannot search for the latest successful
run; a search step with `gh` would be needed anyway, so one tool is simpler);
`--limit 1` as in the description (an expired artifact on the newest run would
force a rebuild while an older one is still available; spec edge case).

## R3. The compression step and the restored files

**Finding**: "Compress large export files" runs before the upload and does
`find data/ -type f -size +10M ! -name '*.zip' -exec zip -m -j "$f.zip" "$f"`:
any file over 10 MB under `data/` is replaced by a zip. Under `data/raw` the
largest local file is a 9.7 MB project PDF (`PJ_9674.pdf`); in CI a larger
PDF or report would be zipped and look missing to `extract_project_files`.
`cache/` and `db/` are outside `data/` and are never compressed.

**Decision**: the compression step skips `data/raw` (`! -path 'data/raw/*'`):
it exists for the large export files, which stay compressed. As a safety net
for artifacts uploaded before this change, the restore treats a `X.zip` under
`data/raw` whose only member is `X` as the compressed `X` and extracts it in
place (FR-005).

**Alternatives considered**: only undoing the compression at restore time
(works, but keeps a lossy step on the files that must travel); dropping the
compression (export files would make the artifact larger for no reason).

## R4. Checking a restored database

**Decision**: before the phases, open the restored `db/horizon.db` with the
standard `sqlite3` module and require `PRAGMA quick_check` to return `ok` and
the `persons` and `horizon_meta` tables to exist. Any failure (or a missing
file) discards the restored database; the run then rebuilds it through
`make db-ensure` (FR-004). The rest of the restored files are kept: a missing
database does not make the raw downloads or the Lattes cache wrong.

`quick_check` reads every page once; on the 318 MB file it takes a few
seconds locally.

**Alternatives considered**: `PRAGMA integrity_check` (slower, also checks
index contents; not needed for a file that a successful run closed with
`finalize_sqlite_database`); a checksum recorded by the previous run (proves
the transfer, not the file; the artifact service already checks the transfer).

## R5. Where the restore logic lives

**Decision**: a small Python module, `src/scripts/restore_weekly_artifact.py`,
called by one workflow step after the virtual environment is created and
before `make weekly-flows`. It is an operational utility (constitution III: it
moves files and reads the database, it ingests nothing), testable with pytest,
and runnable locally on an artifact folder or zip (`--from-dir`, `--from-zip`)
for FR-012. In CI it calls `gh` through `subprocess` (R2). It never exits
non-zero because of a missing or bad artifact (FR-003): every such case ends
as an outcome "rebuild" with its reason. A make target, `make restore-weekly`,
wraps it.

**Alternatives considered**: inline shell in the workflow (hard to test, and
FR-012 asks for a local simulation of the same logic); a Prefect flow (the
restore runs before the Prefect phases and must work even when the flows
cannot start).

## R6. Placing the files

**Decision**: download into a temporary folder, then, for each of
`db/horizon.db`, `data/raw/`, `cache/`, replace the working copy with the
restored one (move, not copy). Nothing else of the artifact is restored:
`data/exports`, `data/reports` and `data/lattes_json` are produced again by
the run. The database's `-wal`/`-shm` companions are deleted if present (a
stale log next to another file could corrupt it; spec 018). The SigPesq
adapter still clears `data/raw/sigpesq/` before its download
(`SigPesqAdapter._clean_download_dir`), so restored reports never feed a run
(FR-009).

## R7. Reporting the outcome

**Decision**: the module writes one log line and, in CI, appends a short
Markdown block to `$GITHUB_STEP_SUMMARY`: restored from run `<id>` of
`<date>` (`<sha>`), with the sizes of the database, `data/raw` and `cache/`;
or rebuilt, with the reason (`no successful run`, `artifact expired`,
`download failed: ...`, `database check failed: ...`, `restore disabled`). It
also writes `data/reports/restore_outcome.json` with the same fields, which the
artifact then carries for later inspection (FR-011). A rule-version rebuild is
reported by the weekly itself (spec 021 log line), after the restore.

## R8. Forcing a rebuild

**Decision**: a `workflow_dispatch` boolean input, `fresh_database` (default
`false`), skips the restore (outcome "rebuilt: restore disabled"). It is how
the maintainer tests the rebuild path on demand and recovers from a bad
database without deleting artifacts. Scheduled runs always restore.

## R9. PII key and separation of databases

**Finding**: the restore only reads artifacts of this repository's own
`weekly-etl.yml` runs (R2), which are written in CI with the
`HORIZON_PII_HMAC_KEY` secret; the local `make weekly-flows` never uploads
anything. **Decision**: nothing to add beyond R2; the contract states it, and
the local simulation (`--from-dir`/`--from-zip`) is documented as a test of
the logic, whose result must not be uploaded or committed (FR-010).

## R10. Time and size budget

**Finding**: the artifact is 366 MB compressed today; GitHub-hosted runners
download artifacts at tens of MB/s, so the restore costs one to two minutes
against the hour it saves. **Decision**: log the restored sizes so growth is
visible; no extra limit. The job's `timeout-minutes: 300` is unchanged.
