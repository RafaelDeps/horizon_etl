# Contract: notice steps of the weekly workflow

Applies to `.github/workflows/weekly-etl.yml`, job `run-etl`. Checked by
`tests/test_weekly_etl_workflow.py`.

1. **Step "Notify Slack: start"**:
   - comes right after "Checkout repository" and before "Set up Python";
   - has `continue-on-error: true`;
   - runs `python3 -m src.scripts.notify_slack start`;
   - its `env` sets `HORIZON_SLACK_WEBHOOK_URL: ${{ secrets.HORIZON_SLACK_WEBHOOK_URL }}`.
2. **Step "Notify Slack: end"**:
   - is the last step of the job;
   - has `if: always()` and `continue-on-error: true`;
   - its `env` sets:
     - `HORIZON_SLACK_WEBHOOK_URL` from the secret;
     - `JOB_STATUS: ${{ job.status }}`;
     - `ARCHIVE_COMMIT: ${{ steps.archives.outputs.commit }}`;
     - `GITHUB_TOKEN: ${{ github.token }}`;
   - runs the script when `src/scripts/notify_slack.py` exists, and otherwise
     the curl fallback.
3. **The commit step** "Commit the export archives if changed":
   - has `id: archives`;
   - writes `commit=<sha>` after its push, or `commit=unchanged` when there
     was nothing to commit, to `$GITHUB_OUTPUT`.
4. `HORIZON_SLACK_WEBHOOK_URL` is set only in the `env` of the two notice
   steps, never at job level.
5. No step echoes or prints `HORIZON_SLACK_WEBHOOK_URL`.
6. Every other step keeps its name, order and content.
