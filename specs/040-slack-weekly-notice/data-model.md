# Data Model: Slack notice of the GitHub Actions weekly

No domain entity or table changes. The database rule version stays at 6.

## Weekly phase summary (new file)

`data/reports/weekly_phase_summary.json`, written by `run_weekly` at its end,
in every run (local and CI), after the log summary:

```json
{
  "phases": [{"name": "sigpesq", "ok": true, "critical": true, "rc": 0}],
  "critical_failed": [],
  "failed": []
}
```

- `phases`: one entry per phase, in run order. `rc` is the exit code, or
  `"skipped"`.
- `critical_failed`: the names of the critical phases with `ok: false`.
- `failed`: the names of every phase with `ok: false`.

No personal data. A write error is logged as a warning and never changes the
weekly's return code.

## Notice inputs (environment of the notice steps)

| Variable | Source | Used by |
|----------|--------|---------|
| `HORIZON_SLACK_WEBHOOK_URL` | secret | both |
| `GITHUB_REPOSITORY`, `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, `GITHUB_SERVER_URL`, `GITHUB_REF_NAME`, `GITHUB_EVENT_NAME` | Actions defaults | both |
| `WEEKLY_STARTED_AT` | written by the start step to `$GITHUB_ENV` | end |
| `JOB_STATUS` | `${{ job.status }}` | end |
| `ARCHIVE_COMMIT` | `${{ steps.archives.outputs.commit }}` (sha, `unchanged`, or empty) | end |
| `GITHUB_TOKEN` | `${{ github.token }}` | end (failed step lookup) |

## Result states of the end notice

| `JOB_STATUS` | Phase summary | Result shown |
|--------------|---------------|--------------|
| success | `failed` empty | passou |
| success | `failed` not empty | passou com avisos |
| failure | — | falhou |
| cancelled | — | cancelada |
