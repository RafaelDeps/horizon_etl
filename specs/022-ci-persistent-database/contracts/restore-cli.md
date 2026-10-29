# Contract: `src/scripts/restore_weekly_artifact.py`

Restores the previous weekly run's database, raw downloads and Lattes cache
into the working tree. Called by `make restore-weekly` (CI) and directly for
the local simulation.

## Modes

```text
python -m src.scripts.restore_weekly_artifact --github [--repo OWNER/NAME] [--branch NAME]
python -m src.scripts.restore_weekly_artifact --from-dir PATH
python -m src.scripts.restore_weekly_artifact --from-zip PATH
python -m src.scripts.restore_weekly_artifact --disabled
```

| Mode | Source | Defaults |
|---|---|---|
| `--github` | newest successful `weekly-etl.yml` run of the branch with a non-expired `weekly-etl-artifacts`, downloaded with `gh` | `--repo $GITHUB_REPOSITORY`, `--branch $GITHUB_REF_NAME` |
| `--from-dir` | an unpacked artifact (a folder holding `db/`, `data/`, `cache/`) | — (local simulation) |
| `--from-zip` | the artifact zip as downloaded from the GitHub UI | — (local simulation) |
| `--disabled` | nothing; records "rebuilt: restore disabled" | used when `fresh_database` is true |

Common options: `--target DIR` (default: the current directory, the
repository root), `--summary FILE` (default: `$GITHUB_STEP_SUMMARY` when set,
otherwise none), `--outcome FILE` (default:
`data/reports/restore_outcome.json` under the target).

## Behaviour

1. Choose the source (mode). In `--github`, list up to 20 successful runs
   newest first; take the first whose artifact is not expired.
2. Download (or copy/unzip) into a temporary folder inside the target's
   parent filesystem (moves are cheap and atomic per file).
3. Under the downloaded `data/raw`, replace each `X.zip` whose only member is
   `X` by `X` (artifacts made before the compression change).
4. Check `db/horizon.db`: present, `PRAGMA quick_check` = `ok`, tables
   `persons` and `horizon_meta` present.
5. Place: for `data/raw/` and `cache/`, remove the working copy and move the
   restored one in; for the database, only when step 4 passed, remove
   `db/horizon.db`, `-wal`, `-shm` and move the restored file in.
6. Report: one log line, the outcome JSON, and the Markdown block in the
   summary file.

## Exit status

Always `0` when the outcome is `restored` or `rebuilt`, whatever the reason
(FR-003). A non-zero exit only means a programming error inside the module;
the workflow step also has `continue-on-error: true`, so even then the weekly
runs, as a rebuild.

## Log line and summary

```text
restore: restored db/horizon.db (318 MB), data/raw (223 MB), cache (66 MB) from run 40856179199 (2026-10-29, 4d93988)
restore: rebuilt — artifact expired (newest successful run 40856179199, 2026-10-29)
```

Summary block:

```markdown
### Database
Restored from run [40856179199](https://github.com/<repo>/actions/runs/40856179199) of 2026-10-29 (`4d93988`):
database 318 MB, data/raw 223 MB, cache 66 MB.
```

or `Rebuilt from scratch: <reason>.`

## Guarantees

- Never restores an artifact of a failed, cancelled or running run, of
  another branch, or of another repository (FR-002, FR-010).
- Never leaves a partly placed folder: each of the three items is moved as a
  whole, after the download and the checks finished.
- Never touches `data/exports`, `data/reports` (except the outcome file),
  `data/lattes_json` or anything outside the three restored items.
- Reads no personal data and writes none; the outcome file holds ids, dates,
  sizes and reasons only.
