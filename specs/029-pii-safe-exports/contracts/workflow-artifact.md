# Contract: Weekly Workflow and Artifact

## Steps, in order

| Step | Condition | Change |
|---|---|---|
| Validate required secrets | | None; the state key is not required |
| Restore previous weekly run | `continue-on-error` | Gets `HORIZON_STATE_KEY`, `HORIZON_STATE_KEY_PREVIOUS` |
| Run weekly flows | | None |
| Compress large export files | | **Removed** |
| Commit exports_canonical.zip | `success()` | Runs `check_publishable_archive` first |
| Prepare artifact | `always()`, `continue-on-error` | **New**: `make seal-weekly`, gets `HORIZON_STATE_KEY` |
| Upload ETL artifacts | `always()` | **Path is `artifact_out` only** |
| Logs, stop Prefect | | None |

## Artifact content

```text
weekly-etl-artifacts/
├── weekly_state.bundle          # absent with no key
└── public/
    ├── data/reports/...         # text files passing the scan
    ├── data/exports/docentes/...
    └── artifact_stage_report.json
```

Anything else is not uploaded. Not a filter on `data`: an allow-list by construction.

## Outcomes

| Situation | Bundle | Plain data uploaded | Run result |
|---|---|---|---|
| Normal | Yes | No | From the phases |
| Phase failed | Yes | No | Failed; previous archive stays |
| No key, or a passphrase-sized value | No | No | Unchanged; warning |
| Seal error | No | No | Unchanged; warning |
| Job timeout | If the `always()` steps get to run | No | Failed |

## First run after the merge

1. Restore finds the old plain artifact and restores as `legacy`.
2. Phases run; unchanged documents are skipped, as files are the same.
3. Backfill sanitizes the database and VACUUMs; consolidation merges duplicates.
4. Archive built with tokens; published.
5. Artifact holds only the bundle and public files.
6. The next run restores `format: bundle`; the old artifacts can then be deleted (FR-016).

## `check_publishable_archive.py`

```text
python -m src.scripts.check_publishable_archive PATH [--ref HEAD] [--warn-only]
```

Refuses: no manifest; `official` false; over 100 MiB; fingerprint differs from the one at `--ref` when that has a manifest.

`--warn-only` (commit step): `::warning`, `git checkout -- PATH`, exit 0.
Without it (`ci.yml` and `.githooks/pre-commit`, when the archive changed): exit 1.
