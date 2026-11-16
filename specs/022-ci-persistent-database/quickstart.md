# Quickstart: Persistent Database Between GitHub Actions Weekly Runs

## 1. Tests

```bash
.venv/bin/python -m pytest -q tests/test_restore_weekly_artifact.py tests/test_weekly_etl_workflow.py
```

They cover:
- run selection: newest successful run with a live artifact;
- each fallback reason;
- the unzip of compressed raw files;
- the database check;
- placement;
- the summary block.

They use a fake `gh` on `PATH` and temporary folders, so they never touch
the network or `db/horizon.db`.

## 2. Local simulation on a real artifact (FR-012)

Never restore into the repository's own `db/horizon.db`: use a scratch
target.

```bash
S=/tmp/restore-sim            # any scratch folder outside the repository
mkdir -p "$S/artifact" "$S/target"
gh run download 40856179199 --repo RafaelDeps/horizon_etl -n weekly-etl-artifacts -D "$S/artifact"
.venv/bin/python -m src.scripts.restore_weekly_artifact --from-dir "$S/artifact" --target "$S/target"
cat "$S/target/data/reports/restore_outcome.json"
```

Expected: outcome `restored`, the three items placed under `$S/target`.
`PRAGMA quick_check` must report `ok` on `$S/target/db/horizon.db`.

Also run the fallback cases on the same target:
- `--from-dir` on a folder without `db/`: reason `database missing`;
- a truncated copy of the database: reason `database check failed`;
- `--disabled`: reason `restore disabled`.

The database of that artifact was written with the CI PII key. Use it only to
check the restore logic; never upload or commit anything from it (FR-010).

## 3. Two dispatches on the fork

```bash
gh workflow run weekly-etl.yml -R RafaelDeps/horizon_etl --ref 025-ci-persistent-database
```

1. **First dispatch**: the branch has no successful run yet, so the job
   summary says "Rebuilt from scratch: no successful run". The run takes about
   as long as the 2026-10-29 rebuild (1 h 38 min).
2. **Second dispatch**, after the first succeeded: the summary says "Restored
   from run <first run id>". In the log, the Lattes phases report almost
   every CV as skipped. The run is clearly shorter (SC-001: at most about
   60%).
3. **Optional**: dispatch with `fresh_database: true`. The summary says
   "restore disabled", and the run rebuilds.

Compare the second run's `exports_canonical.zip` with the first's: same files
and fields; counts differ only where the sources changed between the two
runs (SC-006).
