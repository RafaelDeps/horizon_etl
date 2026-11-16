# Quickstart: validating spec 040

Validation is on the RafaelDeps fork only (no local weekly), as decided with
the maintainer.

## 1. Tests

```bash
.venv/bin/python -m pytest tests/test_notify_slack.py tests/test_weekly_etl_workflow.py tests/test_weekly_orchestrator.py -q
.venv/bin/python -m pytest -q
```

## 2. Message preview (no network)

```bash
JOB_STATUS=success ARCHIVE_COMMIT=unchanged GITHUB_REF_NAME=main GITHUB_EVENT_NAME=workflow_dispatch \
GITHUB_REPOSITORY=RafaelDeps/horizon_etl GITHUB_RUN_ID=1 GITHUB_SERVER_URL=https://github.com \
  .venv/bin/python -m src.scripts.notify_slack end --dry-run
```

`--dry-run` prints the message and sends nothing. Without
`HORIZON_SLACK_WEBHOOK_URL`, the real command only prints the warning.

## 3. Fork runs (when the maintainer asks; never upstream; push without force)

1. **Normal run**:
   `gh workflow run weekly-etl.yml -R RafaelDeps/horizon_etl --ref 040-slack-weekly-notice`.
   Expect two messages: start, then end with "passou" (or "passou com
   avisos"), the time, the link and the commit or "não mudaram".
2. **Failure before the ETL**:
   - push a throwaway branch from 040 with one extra step that runs `exit 1`
     before "Validate required secrets";
   - dispatch it;
   - expect the end message "falhou" with that step's name;
   - delete the branch afterwards (it is never merged).
3. **Secret unset**: only if the maintainer wants it, since it means removing
   the secret for one run and adding it again. Otherwise the unit tests cover
   it.
4. **No leak**: in each run, search the log for `hooks.slack.com`; expect 0
   matches.
