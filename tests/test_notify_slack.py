"""Spec 040: Slack notice of the GitHub Actions weekly (src/scripts/notify_slack.py)."""

import io
import json
import urllib.error
from pathlib import Path

import pytest

import src.scripts.notify_slack as ns

FAKE_WEBHOOK = "https://hooks.slack.com/services/T000/B000/XXXX"
SHA = "bdf8f86" + "0" * 33

BASE = {
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "RafaelDeps/horizon_etl",
    "GITHUB_RUN_ID": "123",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_REF_NAME": "main",
    "GITHUB_EVENT_NAME": "schedule",
}
RUN_LINK = "https://github.com/RafaelDeps/horizon_etl/actions/runs/123"


def _env(**extra):
    env = dict(BASE)
    env.update(extra)
    return env


# --- US1: start and end messages ------------------------------------------


@pytest.mark.parametrize(
    "event, label",
    [("schedule", "agendada"), ("workflow_dispatch", "manual"), ("push", "push")],
)
def test_start_message(event, label):
    text = ns.start_message(_env(GITHUB_EVENT_NAME=event))
    assert text.splitlines()[0] == "🟡 Weekly do Horizon ETL começou"
    assert f"Branch: main · {label}" in text
    assert f"<{RUN_LINK}|Ver a run>" in text


def test_end_message_passed_with_commit():
    text = ns.end_message(
        _env(JOB_STATUS="success", ARCHIVE_COMMIT=SHA), {"failed": []}, None, None
    )
    assert text.splitlines()[0] == "✅ Weekly do Horizon ETL passou"
    link = f"https://github.com/RafaelDeps/horizon_etl/commit/{SHA}"
    assert f"Zips: <{link}|bdf8f86>" in text
    assert f"<{RUN_LINK}|Ver a run>" in text


def test_end_message_passed_archives_unchanged():
    text = ns.end_message(
        _env(JOB_STATUS="success", ARCHIVE_COMMIT="unchanged"), None, None, None
    )
    assert "Zips: não mudaram" in text


def test_end_message_passed_with_warnings():
    summary = {
        "failed": ["openalex_citations", "analyze_venues"],
        "critical_failed": [],
    }
    text = ns.end_message(
        _env(JOB_STATUS="success", ARCHIVE_COMMIT="unchanged"), summary, None, None
    )
    assert text.splitlines()[0] == "⚠️ Weekly do Horizon ETL passou com avisos"
    assert "Zips: não mudaram" in text
    assert "Fases com falha: openalex_citations, analyze_venues" in text


@pytest.mark.parametrize(
    "minutes, shown", [(59, "59min"), (112, "1h 52min"), (60, "1h 00min")]
)
def test_duration_format(minutes, shown):
    assert ns._duration(1000, 1000 + minutes * 60) == shown


def test_no_start_time_means_no_time_shown():
    text = ns.end_message(_env(JOB_STATUS="success"), None, None, None)
    assert "tempo:" not in text
    assert "Branch: main" in text


def test_end_message_shows_the_time():
    text = ns.end_message(
        _env(JOB_STATUS="success", WEEKLY_STARTED_AT="1000"), None, None, 1000 + 7200
    )
    assert "Branch: main · tempo: 2h 00min" in text


def test_start_writes_the_start_time(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "github_env"
    env_file.write_text("")
    for key, value in _env(GITHUB_ENV=str(env_file)).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("HORIZON_SLACK_WEBHOOK_URL", raising=False)
    assert ns.main(["start"]) == 0
    assert env_file.read_text().startswith("WEEKLY_STARTED_AT=")


def test_dry_run_prints_and_sends_nothing(monkeypatch, capsys):
    for key, value in _env(JOB_STATUS="success", ARCHIVE_COMMIT="unchanged").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HORIZON_SLACK_WEBHOOK_URL", FAKE_WEBHOOK)
    monkeypatch.setattr(
        ns.urllib.request,
        "urlopen",
        lambda *a, **k: pytest.fail("dry run must not send"),
    )
    assert ns.main(["end", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Weekly do Horizon ETL passou" in out
    assert FAKE_WEBHOOK not in out


def test_sends_the_message_as_json(monkeypatch):
    sent = {}

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data.decode("utf-8"))
        sent["type"] = request.get_header("Content-type")
        return _Resp()

    monkeypatch.setattr(ns.urllib.request, "urlopen", fake_urlopen)
    assert ns.send("olá", FAKE_WEBHOOK) is True
    assert sent == {
        "url": FAKE_WEBHOOK,
        "body": {"text": "olá"},
        "type": "application/json",
    }


def test_read_summary(tmp_path):
    good = tmp_path / "s.json"
    good.write_text(json.dumps({"failed": ["x"], "critical_failed": []}))
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert ns._read_summary(str(good)) == {"failed": ["x"], "critical_failed": []}
    assert ns._read_summary(str(bad)) is None
    assert ns._read_summary(str(tmp_path / "missing.json")) is None


# --- US2: failures and cancellations ----------------------------------------


def test_end_message_failed_with_step():
    text = ns.end_message(
        _env(JOB_STATUS="failure"), None, "Install Playwright Chromium", None
    )
    assert text.splitlines()[0] == "❌ Weekly do Horizon ETL falhou"
    assert "Passo: Install Playwright Chromium" in text
    assert "Fases críticas" not in text
    assert "Zips:" not in text


def test_end_message_failed_in_weekly_flows_names_critical_phases():
    summary = {
        "failed": ["sigpesq", "openalex_citations"],
        "critical_failed": ["sigpesq"],
    }
    text = ns.end_message(_env(JOB_STATUS="failure"), summary, "Run weekly flows", None)
    assert "Passo: Run weekly flows" in text
    assert "Fases críticas: sigpesq" in text


def test_end_message_failed_step_unknown():
    text = ns.end_message(_env(JOB_STATUS="failure"), None, None, None)
    assert text.splitlines()[0] == "❌ Weekly do Horizon ETL falhou"
    assert "Passo:" not in text


def test_end_message_cancelled():
    text = ns.end_message(_env(JOB_STATUS="cancelled"), None, None, None)
    lines = text.splitlines()
    assert lines[0] == "⏹️ Weekly do Horizon ETL cancelada"
    assert len(lines) == 3  # title, branch line, link
    assert "Zips:" not in text and "Passo:" not in text


def _jobs_payload(steps):
    return {
        "jobs": [
            {"name": "other", "steps": [{"name": "x", "conclusion": "failure"}]},
            {"name": "run-etl", "steps": steps},
        ]
    }


def _fake_api(payload=None, error=None):
    calls = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        calls["url"] = request.full_url
        calls["auth"] = request.get_header("Authorization")
        if error is not None:
            raise error
        return _Resp(json.dumps(payload).encode("utf-8"))

    return fake_urlopen, calls


def test_first_failed_step_from_api(monkeypatch):
    payload = _jobs_payload(
        [
            {"name": "Checkout repository", "conclusion": "success"},
            {"name": "Install Playwright Chromium", "conclusion": "failure"},
            {"name": "Run weekly flows", "conclusion": "failure"},
        ]
    )
    fake, calls = _fake_api(payload)
    monkeypatch.setattr(ns.urllib.request, "urlopen", fake)
    env = _env(GITHUB_TOKEN="tok")
    assert ns.first_failed_step(env) == "Install Playwright Chromium"
    assert calls["url"].startswith(
        "https://api.github.com/repos/RafaelDeps/horizon_etl/actions/runs/123/attempts/1/jobs"
    )
    assert calls["auth"] == "Bearer tok"


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("u", 403, "forbidden", None, None),
        urllib.error.URLError("down"),
        TimeoutError(),
    ],
)
def test_first_failed_step_api_error_gives_none(monkeypatch, error):
    fake, _ = _fake_api(error=error)
    monkeypatch.setattr(ns.urllib.request, "urlopen", fake)
    assert ns.first_failed_step(_env(GITHUB_TOKEN="tok")) is None


def test_first_failed_step_bad_json_gives_none(monkeypatch):
    fake, _ = _fake_api(payload={"unexpected": True})
    monkeypatch.setattr(ns.urllib.request, "urlopen", fake)
    assert ns.first_failed_step(_env(GITHUB_TOKEN="tok")) is None


# --- US3: never fails the weekly, never leaks the webhook -------------------


def _set_env(monkeypatch, **extra):
    for key, value in _env(**extra).items():
        monkeypatch.setenv(key, value)


def test_missing_secret_is_a_warning_and_exit_0(monkeypatch, capsys):
    _set_env(monkeypatch, JOB_STATUS="success")
    monkeypatch.delenv("HORIZON_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        ns.urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not send")
    )
    assert ns.main(["end"]) == 0
    out = capsys.readouterr().out
    assert (
        "::warning::Slack não configurado (HORIZON_SLACK_WEBHOOK_URL vazio); aviso pulado."
        in out
    )


def test_empty_secret_is_a_warning_and_exit_0(monkeypatch, capsys):
    _set_env(monkeypatch, JOB_STATUS="success")
    monkeypatch.setenv("HORIZON_SLACK_WEBHOOK_URL", "  ")
    assert ns.main(["start"]) == 0
    assert "Slack não configurado" in capsys.readouterr().out


def test_http_error_is_a_warning_without_the_url(monkeypatch, capsys):
    _set_env(monkeypatch, JOB_STATUS="success")
    monkeypatch.setenv("HORIZON_SLACK_WEBHOOK_URL", FAKE_WEBHOOK)

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "no_service", None, None)

    monkeypatch.setattr(ns.urllib.request, "urlopen", fake_urlopen)
    assert ns.main(["end"]) == 0
    captured = capsys.readouterr()
    assert (
        "::warning::Slack recusou a mensagem (HTTP 404); aviso pulado." in captured.out
    )
    assert FAKE_WEBHOOK not in captured.out + captured.err
    assert "hooks.slack.com" not in captured.out + captured.err


@pytest.mark.parametrize(
    "error", [urllib.error.URLError(f"cannot reach {FAKE_WEBHOOK}"), TimeoutError()]
)
def test_network_error_is_a_warning_without_the_url(monkeypatch, capsys, error):
    _set_env(monkeypatch, JOB_STATUS="success")
    monkeypatch.setenv("HORIZON_SLACK_WEBHOOK_URL", FAKE_WEBHOOK)

    def fake_urlopen(request, timeout=None):
        raise error

    monkeypatch.setattr(ns.urllib.request, "urlopen", fake_urlopen)
    assert ns.main(["start"]) == 0
    captured = capsys.readouterr()
    assert "::warning::Slack não respondeu; aviso pulado." in captured.out
    assert "hooks.slack.com" not in captured.out + captured.err


def test_unexpected_error_still_exits_0(monkeypatch, capsys):
    _set_env(monkeypatch, JOB_STATUS="success")
    monkeypatch.setenv("HORIZON_SLACK_WEBHOOK_URL", FAKE_WEBHOOK)
    monkeypatch.setattr(ns, "end_message", lambda *a: 1 / 0)
    assert ns.main(["end"]) == 0
    captured = capsys.readouterr()
    assert "::warning::" in captured.out
    assert "hooks.slack.com" not in captured.out + captured.err


def test_no_flow_or_makefile_calls_the_notice():
    root = Path(__file__).resolve().parents[1]
    calls = (
        "import notify_slack",
        "scripts.notify_slack import",
        "-m src.scripts.notify_slack",
    )
    sources = list((root / "src" / "flows").rglob("*.py")) + [
        root / "Makefile",
        root / "app.py",
    ]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for call in calls:
            assert call not in text, (path, call)


# --- Spec 041: notices only from runs on main --------------------------------


def _record_sends(monkeypatch):
    sent = []
    monkeypatch.setattr(
        ns, "send", lambda text, webhook, **k: sent.append(text) or True
    )
    return sent


@pytest.mark.parametrize("event", ["start", "end"])
@pytest.mark.parametrize("webhook", [FAKE_WEBHOOK, None])
def test_main_branch_keeps_spec_040_behaviour(
    monkeypatch, capsys, tmp_path, event, webhook
):
    _set_env(monkeypatch, JOB_STATUS="success", GITHUB_REF_NAME="main")
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "github_env"))
    if webhook:
        monkeypatch.setenv("HORIZON_SLACK_WEBHOOK_URL", webhook)
    else:
        monkeypatch.delenv("HORIZON_SLACK_WEBHOOK_URL", raising=False)
    sent = _record_sends(monkeypatch)
    assert ns.main([event]) == 0
    out = capsys.readouterr()
    assert "Slack pulado" not in out.out
    if webhook:
        assert len(sent) == 1
    else:
        assert sent == []
        assert "Slack não configurado" in out.out
    assert "hooks.slack.com" not in out.out + out.err


@pytest.mark.parametrize("event", ["start", "end"])
@pytest.mark.parametrize("webhook", [FAKE_WEBHOOK, None])
@pytest.mark.parametrize(
    "branch, shown",
    [
        ("041-dashboard-visible-fixes", "041-dashboard-visible-fixes"),
        ("", "(desconhecida)"),
        (None, "(desconhecida)"),
    ],
)
def test_other_branches_send_nothing(
    monkeypatch, capsys, tmp_path, event, webhook, branch, shown
):
    _set_env(monkeypatch, JOB_STATUS="success")
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "github_env"))
    if branch is None:
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    else:
        monkeypatch.setenv("GITHUB_REF_NAME", branch)
    if webhook:
        monkeypatch.setenv("HORIZON_SLACK_WEBHOOK_URL", webhook)
    else:
        monkeypatch.delenv("HORIZON_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        ns.urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not send")
    )
    sent = _record_sends(monkeypatch)
    assert ns.main([event]) == 0
    out = capsys.readouterr()
    assert sent == []
    assert f"::notice::Slack pulado: a branch {shown} não é a main." in out.out
    assert "Slack não configurado" not in out.out
    assert "hooks.slack.com" not in out.out + out.err


def test_dry_run_prints_the_text_on_any_branch(monkeypatch, capsys):
    _set_env(monkeypatch, JOB_STATUS="success", GITHUB_REF_NAME="feature-x")
    assert ns.main(["end", "--dry-run"]) == 0
    assert "Weekly do Horizon ETL" in capsys.readouterr().out


def test_notify_branch_is_main():
    assert ns.NOTIFY_BRANCH == "main"
