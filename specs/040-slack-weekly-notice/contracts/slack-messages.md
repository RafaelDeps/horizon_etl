# Contract: Slack messages

Sent as `{"text": "<message>"}` to the webhook in `HORIZON_SLACK_WEBHOOK_URL`.
Lines use Slack's `<url|label>` link syntax. No person or group is mentioned,
and no data total is shown.

## Start

```text
🟡 Weekly do Horizon ETL começou
Branch: main · agendada
<https://github.com/OWNER/REPO/actions/runs/RUN_ID|Ver a run>
```

The second line ends with `agendada` (schedule), `manual` (workflow_dispatch),
or the event name otherwise.

## End

```text
<emoji> Weekly do Horizon ETL <result>
Branch: main · tempo: 1h 52min
<detail lines>
<https://github.com/OWNER/REPO/actions/runs/RUN_ID|Ver a run>
```

| Result | Emoji | Detail lines |
|--------|-------|--------------|
| passou | ✅ | `Zips: <https://github.com/OWNER/REPO/commit/SHA|abc1234>`, or `Zips: não mudaram` |
| passou com avisos | ⚠️ | the `Zips:` line, then `Fases com falha: a, b` |
| falhou | ❌ | `Passo: <step name>`; if the step is "Run weekly flows" and the critical phases are known, `Fases críticas: a, b` |
| cancelada | ⏹️ | none |

- **Time**: `tempo: Xh YYmin` (`YYmin` alone under one hour). It is left out
  when the start time is unknown.
- **Failed step unknown** (API unavailable): the `Passo:` line is left out.
- **Checkout failed** (fallback with curl): one line,
  `❌ Weekly do Horizon ETL falhou antes do checkout (branch: X) <link|Ver a run>`.

## Exit behaviour of `notify_slack.py`

- Always exit code 0.
- Secret missing or empty: prints
  `::warning::Slack não configurado (HORIZON_SLACK_WEBHOOK_URL vazio); aviso pulado.`
- HTTP error: prints `::warning::Slack recusou a mensagem (HTTP <code>); aviso pulado.`
- Network error or timeout: prints `::warning::Slack não respondeu; aviso pulado.`
- Never prints the webhook address.
- Command line: `python3 -m src.scripts.notify_slack start|end`.
