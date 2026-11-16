# Feature Specification: Slack notice of the GitHub Actions weekly

**Feature Branch**: `040-slack-weekly-notice`

**Created**: 2026-11-16

**Status**: Draft

**Input**: User description: "Send a Slack message when the GitHub Actions weekly starts and when it ends, with the result."

## Background

The weekly runs in GitHub Actions (`.github/workflows/weekly-etl.yml`, job
`run-etl`). It starts on a schedule (Saturday 02:00 UTC) or by manual dispatch.
Its steps, in order:

1. checkout and Python setup;
2. virtual environment, then the Playwright Chromium install (the only browser
   since spec 039);
3. secret check;
4. restore of the previous run;
5. "Run weekly flows", which runs the ETL phases;
6. "Commit the export archives if changed", which runs only when everything
   before it passed;
7. artifact preparation and upload, then stop of the Prefect server, which
   always run.

Nobody is told that a weekly started or how it ended unless they open the
Actions page. The ETL has Telegram notifications from inside the Prefect flows
(`src/notifications/telegram.py`), including a summary of the phases at the end
of the weekly. They need their own secrets, which are empty on the fork. They
also fire only once the ETL is running, so a failure in an earlier step is
never reported. On 2026-11-16, four runs on the fork's main failed at a browser
install before the ETL started, and nobody was told.

How a weekly can end:

- **Passed**: every step passed. Some non-critical ETL phases may still have
  failed: the weekly flows step exits 0 and logs "Weekly pipeline completed
  with non-critical failures: …".
- **Failed**: a step failed. Either the weekly flows step failed (a critical
  phase failed, and the log says "Weekly pipeline FAILED — critical phases:
  …"), or another step failed, before or after it.
- **Cancelled**: someone cancelled the run, or it hit the job's 300-minute
  limit.

When it passes, the commit step either pushes one bot commit "chore(exports):
update the export archives from weekly run <date>", or logs that the archives
did not change.

The maintainer created a Slack app with an Incoming Webhook that posts to one
channel. Its URL is stored as the Actions secret `HORIZON_SLACK_WEBHOOK_URL` on
the RafaelDeps fork. The URL is a credential.

## Clarifications

### Session 2026-11-16

Decided with the maintainer before this spec:

- Messages are sent when the weekly starts and when it ends, with the result.
- Only the GitHub Actions weekly sends them; local runs send none.
- No person or group is mentioned.
- The Telegram notifications stay as they are.
- The end message carries no data totals.
- Validation runs on the fork only, with no local weekly run.
- Q: Which branches send notices? → A: Every branch the weekly runs on (main and the spec branches), always with the branch name in the message.
- Q: How is a weekly reported when it passes but some non-critical phases failed? → A: As a fourth result, "passou com avisos", naming the phases that failed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Know that the weekly started and how it ended (Priority: P1)

As the maintainer, I want a message in the team's Slack channel when the weekly
starts and another when it ends, saying whether it passed, so that I know the
state of the data without opening GitHub.

**Why this priority**: it is the purpose of the feature. Today a failed or
stuck weekly goes unnoticed until someone looks.

**Independent Test**: dispatch the weekly on the fork. Two messages arrive in
the channel: one at the start, with the branch, how it was started and the link
to the run; one at the end, with the result, the branch, the total time and the
link.

**Acceptance Scenarios**:

1. **Given** the weekly starts (by schedule or by hand), **When** its first steps run, **Then** the channel receives one message saying that the weekly started, with the branch, "agendada" or "manual", and the link to the run.
2. **Given** the weekly passed, **When** the job ends, **Then** the channel receives one message saying it passed, with the branch, the total time and the link to the run.
3. **Given** the weekly passed and the archives changed, **When** the end message is sent, **Then** it shows the short hash of the bot's archive commit with a link to that commit.
4. **Given** the weekly passed and the archives did not change, **When** the end message is sent, **Then** it says the archives were not changed.
5. **Given** every step passed but some non-critical ETL phases failed, **When** the end message is sent, **Then** its result is "passou com avisos" and it names those phases, together with the archive commit or "unchanged".

---

### User Story 2 - Be told when the weekly fails, wherever it fails (Priority: P1)

As the maintainer, I want the end message even when the weekly fails before the
ETL starts or is cancelled, and I want it to say where it failed, so that I can
act without reading the whole log.

**Why this priority**: the failures nobody sees today are the ones before the
ETL. A notice that only works when the ETL runs would miss them, as Telegram
does.

**Independent Test**: on a test branch of the fork, make a step before the ETL
fail and dispatch the weekly. The end message says "falhou" and names that step.
Cancel a run, and the end message says "cancelada".

**Acceptance Scenarios**:

1. **Given** a step before "Run weekly flows" fails, **When** the job ends, **Then** the end message says the weekly failed and gives the name of that step.
2. **Given** "Run weekly flows" fails, **When** the job ends, **Then** the end message says the weekly failed in that step and names the critical phases that failed.
3. **Given** a step after "Run weekly flows" fails (for example the archive commit), **When** the job ends, **Then** the end message says the weekly failed and gives the name of that step.
4. **Given** the run is cancelled, **When** the job ends, **Then** the end message says the weekly was cancelled.

---

### User Story 3 - The notice never changes the weekly (Priority: P2)

As the maintainer, I want the weekly to pass or fail exactly as it would without
Slack, even if Slack is down or the secret is missing, and I want the webhook
address never to leak.

**Why this priority**: the notice is a convenience. It must not become a new way
for the weekly to fail, and the address is a credential.

**Independent Test**: dispatch the weekly on a fork branch with the secret unset.
It ends with the same result as before, and the log has a warning that Slack was
skipped. Read the logs and the artifact of a run with the secret set: the
address appears in neither.

**Acceptance Scenarios**:

1. **Given** the secret is not set, **When** the weekly runs, **Then** no message is sent, each notice logs a warning that Slack was skipped, and the run's result is unchanged.
2. **Given** Slack does not answer or answers with an error, **When** a notice is sent, **Then** the step logs a warning without the address and the run's result is unchanged.
3. **Given** a run with the secret set, **When** its logs, its artifact and the committed files are read, **Then** the webhook address appears in none of them.
4. **Given** a local weekly (`make weekly-flows` on a developer machine), **When** it runs, **Then** no Slack message is sent.

---

### Edge Cases

- **Failure before the start notice is sent**, for example at checkout: the end
  message is still sent, because it does not depend on the earlier steps having
  passed.
- **The 300-minute job limit**: GitHub reports the run as cancelled; the end
  message says "cancelada" when the end step gets to run.
- **A message for a run on a branch other than main** (test branches, spec
  branches): the branch is in every message, so the channel can tell them
  apart.
- **Two runs of the same branch**: the workflow already queues them (no
  parallel runs). Each run sends its own two messages.
- **The ETL phase list cannot be read** (for example the weekly flows step
  never wrote its summary): the end message still says the weekly failed in
  that step, without the phase names.
- **The webhook is revoked or changed**: Slack answers with an error; the
  notice is skipped with a warning, as when Slack is down.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The weekly job MUST send a start message to the Slack channel of the webhook. It is sent once the job starts, before the ETL steps, and gives the branch, how the run was started ("agendada" for the schedule, "manual" for a dispatch) and the link to the run.
- **FR-002**: The weekly job MUST send an end message whatever happened before it: every earlier step passed, one failed, or the run was cancelled.
- **FR-003**: The end message MUST give the result ("passou", "passou com avisos", "falhou" or "cancelada"), the branch, the total time of the run and the link to the run. "passou com avisos" is used when every step passed but at least one non-critical ETL phase failed.
- **FR-004**: When the weekly failed, the end message MUST name the first step that failed. When that step is "Run weekly flows", it MUST also name the critical ETL phases that failed, when they can be read.
- **FR-005**: When the weekly passed ("passou" or "passou com avisos"), the end message MUST give the short hash of the archive commit with a link to it, or say that the archives did not change. With "passou com avisos" it MUST also name the non-critical phases that failed.
- **FR-006**: Messages MUST be in Portuguese, plain and short. They MUST NOT mention any person or group, and MUST NOT carry data totals.
- **FR-007**: Only the GitHub Actions weekly MUST send Slack messages, from any branch it runs on (main and the spec branches alike), with the branch name in every message. A local weekly MUST send none.
- **FR-008**: If the secret is missing, empty, or Slack does not accept the message, the notice MUST be skipped with a warning in the log. The weekly's result (passed, failed, cancelled) MUST stay what it would be without the notice.
- **FR-009**: The webhook address MUST NOT appear in any log line, artifact, report or committed file. A Slack error MUST be reported without it.
- **FR-010**: The Telegram notifications MUST stay as they are.
- **FR-011**: `docs/operations/automation.md` MUST describe the notice: what is sent and when, how to create the webhook for one channel, the secret name, and that a missing secret only skips the notice.
- **FR-012**: The workflow tests MUST check that the weekly job sends the start notice before the ETL steps and the end notice whatever the outcome, that both read the webhook only from the secret, and that a failing notice cannot fail the job.
- **FR-013**: The change MUST NOT touch the ETL phases, third-party libraries or Docker.

### Key Entities

- **Start notice**: branch, how the run started, link to the run.
- **End notice**: result, branch, total time, link to the run. When failed: first failed step and, for the weekly flows step, the critical phases. When "passou" or "passou com avisos": the archive commit or "unchanged"; with "passou com avisos", the non-critical phases that failed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A weekly run on the fork that passes produces exactly 2 messages in the channel, a start and an end. The end says "passou" and shows the time, the link and the archive commit or "unchanged".
- **SC-002**: A weekly run on the fork that fails before the ETL produces an end message saying "falhou" with the name of the failed step.
- **SC-003**: A weekly run on the fork with the secret unset ends with the same result as before this feature and logs 2 warnings that Slack was skipped.
- **SC-004**: The webhook address appears 0 times in the logs and the artifact of the validation runs and in the repository.
- **SC-005**: A local weekly sends 0 Slack messages.
- **SC-006**: The test suite passes, including the new workflow tests.

## Assumptions

- One channel, one webhook: the secret holds the webhook that the maintainer
  created for the chosen channel. Changing channel is done by changing the
  secret.
- "Total time" is the time from the start of the job to the end notice, in
  hours and minutes.
- The upstream repository has no such secret. The notice is skipped there, as
  FR-008 says, until it is set up.
- Validation follows the maintainer's decision for this spec: weekly runs on
  the RafaelDeps fork only, with no local weekly run. A test run may use a
  temporary change, on a test branch that is never merged, to make a step fail
  on purpose.
