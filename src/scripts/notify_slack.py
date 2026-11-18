"""Slack notice of the GitHub Actions weekly (spec 040).

Called only by the two notice steps of ``.github/workflows/weekly-etl.yml``:

* ``start``: says the weekly started (branch, how it was started, link to the
  run) and writes ``WEEKLY_STARTED_AT`` to ``$GITHUB_ENV`` for the end notice.
* ``end``: says how it ended: "passou", "passou com avisos", "falhou" or
  "cancelada", with the branch, the total time and the link to the run, the
  first failed step and the critical phases when it failed, and the archive
  commit (or "não mudaram") when it passed.

Spec 041: only runs on ``main`` (``NOTIFY_BRANCH``) send; a run on any other
branch prints a ``::notice::`` naming the branch and sends nothing, so the
validation runs of feature branches do not disturb the channel.

The webhook comes only from ``HORIZON_SLACK_WEBHOOK_URL`` and is never printed.
The script always exits 0: a missing secret or a Slack error is only a
``::warning::`` line, so the notice can never change the weekly's result.
Standard library only, so it runs with the runner's ``python3`` even when the
virtual environment was never built. Local runs never call it.

Usage::

    python3 -m src.scripts.notify_slack start|end [--dry-run]
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Mapping, Optional

WEBHOOK_VARIABLE = "HORIZON_SLACK_WEBHOOK_URL"
NOTIFY_BRANCH = "main"
PHASE_SUMMARY_PATH = "data/reports/weekly_phase_summary.json"
WEEKLY_FLOWS_STEP = "Run weekly flows"
JOB_NAME = "run-etl"
TIMEOUT_S = 15
TITLE = "Weekly do Horizon ETL"

_TRIGGERS = {"schedule": "agendada", "workflow_dispatch": "manual"}
_RESULTS = {
    "passou": "✅",
    "passou com avisos": "⚠️",
    "falhou": "❌",
    "cancelada": "⏹️",
}

WARN_NOT_CONFIGURED = (
    f"::warning::Slack não configurado ({WEBHOOK_VARIABLE} vazio); aviso pulado."
)
NOTICE_OTHER_BRANCH = "::notice::Slack pulado: a branch {branch} não é a main."
WARN_REFUSED = "::warning::Slack recusou a mensagem (HTTP {code}); aviso pulado."
WARN_NO_ANSWER = "::warning::Slack não respondeu; aviso pulado."
WARN_INTERNAL = "::warning::Aviso do Slack não montado (erro interno); aviso pulado."


class SlackRefused(Exception):
    """Slack answered with an HTTP error; carries only the status code."""

    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


# --- message building (pure) -------------------------------------------------


def _run_link(env: Mapping[str, str]) -> str:
    server = env.get("GITHUB_SERVER_URL") or "https://github.com"
    return (
        f"{server}/{env.get('GITHUB_REPOSITORY', '')}"
        f"/actions/runs/{env.get('GITHUB_RUN_ID', '')}"
    )


def _commit_link(env: Mapping[str, str], sha: str) -> str:
    server = env.get("GITHUB_SERVER_URL") or "https://github.com"
    return f"{server}/{env.get('GITHUB_REPOSITORY', '')}/commit/{sha}"


def _duration(started_at, now) -> Optional[str]:
    """``Xh YYmin`` (or ``YYmin`` under one hour); None when unknown."""
    try:
        seconds = int(float(now)) - int(float(started_at))
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h {minutes:02d}min" if hours else f"{minutes}min"


def start_message(env: Mapping[str, str]) -> str:
    event = env.get("GITHUB_EVENT_NAME", "")
    trigger = _TRIGGERS.get(event, event or "desconhecida")
    return "\n".join(
        [
            f"🟡 {TITLE} começou",
            f"Branch: {env.get('GITHUB_REF_NAME', '')} · {trigger}",
            f"<{_run_link(env)}|Ver a run>",
        ]
    )


def _result(env: Mapping[str, str], summary: Optional[dict]) -> str:
    status = (env.get("JOB_STATUS") or "").strip().lower()
    if status == "success":
        if summary and summary.get("failed"):
            return "passou com avisos"
        return "passou"
    if status == "cancelled":
        return "cancelada"
    return "falhou"


def end_message(
    env: Mapping[str, str],
    summary: Optional[dict],
    failed_step: Optional[str],
    now=None,
) -> str:
    result = _result(env, summary)
    branch_line = f"Branch: {env.get('GITHUB_REF_NAME', '')}"
    duration = _duration(
        env.get("WEEKLY_STARTED_AT"), time.time() if now is None else now
    )
    if duration:
        branch_line += f" · tempo: {duration}"
    lines = [f"{_RESULTS[result]} {TITLE} {result}", branch_line]

    if result in ("passou", "passou com avisos"):
        commit = (env.get("ARCHIVE_COMMIT") or "").strip()
        if commit == "unchanged":
            lines.append("Zips: não mudaram")
        elif commit:
            lines.append(f"Zips: <{_commit_link(env, commit)}|{commit[:7]}>")
        if result == "passou com avisos":
            lines.append("Fases com falha: " + ", ".join(summary["failed"]))
    elif result == "falhou":
        if failed_step:
            lines.append(f"Passo: {failed_step}")
            critical = (summary or {}).get("critical_failed") or []
            if failed_step == WEEKLY_FLOWS_STEP and critical:
                lines.append("Fases críticas: " + ", ".join(critical))

    lines.append(f"<{_run_link(env)}|Ver a run>")
    return "\n".join(lines)


def _read_summary(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            summary = json.load(fh)
    except (OSError, ValueError):
        return None
    return summary if isinstance(summary, dict) else None


# --- I/O ---------------------------------------------------------------------


def first_failed_step(env: Mapping[str, str]) -> Optional[str]:
    """Name of the first failed step of this job, from the GitHub API; None on
    any error."""
    api = env.get("GITHUB_API_URL") or "https://api.github.com"
    url = (
        f"{api}/repos/{env.get('GITHUB_REPOSITORY', '')}/actions/runs/"
        f"{env.get('GITHUB_RUN_ID', '')}/attempts/"
        f"{env.get('GITHUB_RUN_ATTEMPT') or '1'}/jobs?per_page=100"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {env.get('GITHUB_TOKEN', '')}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for job in payload["jobs"]:
            if job.get("name") != JOB_NAME:
                continue
            for step in job.get("steps") or []:
                if step.get("conclusion") == "failure":
                    return step.get("name")
    except Exception:  # noqa: BLE001 - the notice must never fail the run
        return None
    return None


def send(text: str, webhook: str, timeout: int = TIMEOUT_S) -> bool:
    """Posts ``{"text": text}`` to the webhook. Raises ``SlackRefused`` on an
    HTTP error; other errors propagate (the caller turns them into a warning
    without their message, which may hold the address)."""
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except urllib.error.HTTPError as exc:
        raise SlackRefused(exc.code) from None


def _write_start_time(env: Mapping[str, str]) -> None:
    path = env.get("GITHUB_ENV")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"WEEKLY_STARTED_AT={int(time.time())}\n")


def _deliver(text: str, webhook: str) -> None:
    try:
        send(text, webhook)
    except SlackRefused as exc:
        print(WARN_REFUSED.format(code=exc.code))
    except Exception:  # noqa: BLE001 - network error, timeout, anything else
        print(WARN_NO_ANSWER)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Slack notice of the weekly.")
    parser.add_argument("event", choices=("start", "end"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    env = os.environ
    try:
        if args.event == "start":
            try:
                _write_start_time(env)
            except OSError:
                print("::warning::Hora de início da weekly não registrada.")
            text = start_message(env)
        else:
            summary = _read_summary(PHASE_SUMMARY_PATH)
            failed_step = None
            if (env.get("JOB_STATUS") or "").strip().lower() == "failure":
                failed_step = first_failed_step(env)
            text = end_message(env, summary, failed_step)
    except Exception:  # noqa: BLE001 - never fail the run, never echo details
        print(WARN_INTERNAL)
        return 0

    if args.dry_run:
        print(text)
        return 0
    branch = (env.get("GITHUB_REF_NAME") or "").strip()
    if branch != NOTIFY_BRANCH:
        print(NOTICE_OTHER_BRANCH.format(branch=branch or "(desconhecida)"))
        return 0
    webhook = (env.get(WEBHOOK_VARIABLE) or "").strip()
    if not webhook:
        print(WARN_NOT_CONFIGURED)
        return 0
    _deliver(text, webhook)
    return 0


if __name__ == "__main__":
    sys.exit(main())
