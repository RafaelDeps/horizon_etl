# Research: Slack notice of the GitHub Actions weekly

## R1 — Where the notices run

- **Decision**: in two workflow steps, not inside the ETL.
  - The start step comes right after checkout.
  - The end step is last, with `if: always()` and `continue-on-error: true`.
- **Rationale**:
  - A step with `if: always()` runs after failures and cancellations, so it
    sees every outcome, including failures before the ETL.
  - `continue-on-error: true` keeps a notice failure from changing the job's
    conclusion.
  - The Telegram notices live in the Prefect flows and miss every failure
    before the ETL; that is what the spec wants to fix.
- **Alternatives considered**:
  - A second job with `needs: run-etl` and `if: always()`. It sees the result
    too, but it starts a new runner (slower, more minutes).
  - A separate workflow on `workflow_run: completed`. It runs from the default
    branch only, so spec branches would not notify, against the
    clarification.

## R2 — How the message is sent

- **Decision**: a Slack Incoming Webhook, called with a JSON body `{"text": …}`
  from `src/scripts/notify_slack.py`, using `urllib.request` and a 15 s
  timeout. The script always exits 0.
- **Rationale**:
  - The maintainer created a webhook for one channel.
  - The standard library avoids a new dependency. The runner's `python3` works
    even when the venv step failed.
- **Alternatives considered**:
  - A marketplace action such as `slackapi/slack-github-action`: a third-party
    dependency in a job that holds write permissions.
  - `curl` for everything: hard to test, and the message logic would live in
    YAML. `curl` is kept only for the checkout-failure fallback.

## R3 — Keeping the webhook secret

- **Decision**:
  - the script reads the address from the environment variable only;
  - it never prints it, nor the exception text of a failed call when that
    text could contain the address; a failure is logged as "Slack recusou a
    mensagem (HTTP <code>)" or "Slack não respondeu";
  - the variable is set only on the two notice steps, not at job level.
- **Rationale**: GitHub masks secrets in logs, but only exact matches. Never
  printing the address is the real guarantee. Setting it only where needed
  keeps it out of `make weekly-flows`.

## R4 — The first failed step

- **Decision**:
  - `GET /repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs` with
    `GITHUB_TOKEN`;
  - take the job named `run-etl` and the first step whose `conclusion` is
    `failure`;
  - if the API call fails, the message says "falhou" without the step name.
- **Rationale**:
  - Inside a running job, the API already reports the conclusion of every
    finished step.
  - The workflow already has `actions: write`, which includes read.
- **Alternatives considered**: `steps.<id>.outcome` for every step (see the
  plan's Complexity Tracking).

## R5 — Phases and "passou com avisos"

- **Decision**:
  - at the end of `run_weekly`, the orchestrator writes
    `data/reports/weekly_phase_summary.json` with
    `{"phases": [{"name", "ok", "critical", "rc"}], "critical_failed": [...], "failed": [...]}`;
  - the end notice reads this file;
  - result:
    - "passou com avisos" when `job.status` is success and `failed` is not
      empty;
    - "falhou" when `job.status` is failure, listing `critical_failed` when
      the failed step is "Run weekly flows";
  - writing the file never changes the return code, and an error is logged as
    a warning.
- **Rationale**:
  - The summary already exists in memory (`results`); writing it is the
    cheapest reliable source.
  - Parsing the log would need `tee` and fragile text matching.

## R6 — The archive commit

- **Decision**:
  - the commit step gets `id: archives` and writes
    `commit=<sha>` or `commit=unchanged` to `$GITHUB_OUTPUT`;
  - the end step reads `steps.archives.outputs.commit`;
  - the link is `https://github.com/{repo}/commit/{sha}`.
- **Rationale**: the step that makes the commit knows its hash; no API call is
  needed.

## R7 — Start time, total time, how the run started

- **Decision**:
  - the start step writes `WEEKLY_STARTED_AT=<epoch>` to `$GITHUB_ENV`;
  - the end step computes the minutes and shows "Xh YYmin". When the start
    step never ran (checkout failed), the time is left out;
  - "agendada" if `github.event_name == schedule`, "manual" if
    `workflow_dispatch`, otherwise the event name;
  - the run link is `{server_url}/{repo}/actions/runs/{run_id}`.

## R8 — Local runs

- **Decision**: nothing to block.
  - The script is called only by the workflow steps.
  - `make weekly-flows` never calls it.
  - The orchestrator only writes the summary file.
- **Rationale**: FR-007 is met by construction. A test checks that no Makefile
  target or flow imports `notify_slack`.
