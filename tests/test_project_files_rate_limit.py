"""Spec 031: the extraction stage paces its calls and retries a rate limit.

A scripted extractor answers per document and per try ("ok", "429",
"429:<retry_after>" or an exception); ``sleep`` only advances a fake clock, so
no test calls Mistral or waits for real.
"""

import json
import os
import zipfile

import pytest
from agent_sigpesq.extraction import Projeto
from loguru import logger

from src.adapters.sources.sigpesq.project_files import SigPesqProjectFilesAdapter
from src.core.logic.extraction_pacing import ExtractionPacingSettings

DEFAULTS = ExtractionPacingSettings(
    retries=3, pause_s=2.0, first_wait_s=30.0, wait_budget_s=1200.0
)


class RateLimitError(Exception):
    """Shaped like mistralai's SDKError for a 429."""

    def __init__(self, retry_after=None):
        super().__init__(
            'API error occurred: Status 429. Body: {"object":"error",'
            '"message":"Rate limit exceeded","type":"rate_limited"}'
        )
        self.status_code = 429
        self.headers = {"retry-after": retry_after} if retry_after else {}


class ServerError(Exception):
    def __init__(self):
        super().__init__("API error occurred: Status 500")
        self.status_code = 500
        self.headers = {}


class FakeClock:
    """Each call takes ``call_s``; ``sleep`` moves the clock forward."""

    def __init__(self, call_s=0.0):
        self.now = 0.0
        self.call_s = call_s
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class ScriptedExtractor:
    def __init__(self, script, clock):
        self.script = {stem: list(outcomes) for stem, outcomes in script.items()}
        self.clock = clock
        self.calls = []

    def extract_project(self, pdf_path):
        stem = os.path.splitext(os.path.basename(pdf_path))[0]
        self.calls.append(stem)
        self.clock.now += self.clock.call_s
        outcomes = self.script.get(stem) or ["ok"]
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome.startswith("429"):
            _, _, retry_after = outcome.partition(":")
            raise RateLimitError(retry_after or None)
        return Projeto.model_validate(
            {
                "codigo": stem.replace("_", " "),
                "titulo": f"extracted {stem}",
                "_meta": {"arquivo": f"{stem}.pdf"},
            }
        )


@pytest.fixture
def adapter(tmp_path):
    return SigPesqProjectFilesAdapter(
        pdf_root=str(tmp_path / "pdfs"),
        json_dir=str(tmp_path / "exports" / "project_sigpesq_files_json"),
    )


@pytest.fixture
def messages():
    lines = []
    sink = logger.add(lambda m: lines.append(str(m)), level="INFO")
    yield lines
    logger.remove(sink)


def make_pdfs(adapter, *stems):
    os.makedirs(adapter.pdf_dir, exist_ok=True)
    for stem in stems:
        with open(os.path.join(adapter.pdf_dir, f"{stem}.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 fake")


def run(adapter, monkeypatch, script, settings=DEFAULTS, call_s=0.0, stems=None):
    clock = FakeClock(call_s)
    extractor = ScriptedExtractor(script, clock)
    built = []

    def build():
        built.append(1)
        return extractor

    monkeypatch.setattr(adapter, "_build_extractor", build)
    make_pdfs(adapter, *(stems or script))
    stats = adapter.extract_json(settings=settings, sleep=clock.sleep, clock=clock)
    return stats, extractor, clock, built


def json_files(adapter):
    if not os.path.isdir(adapter.json_dir):
        return {}
    return {
        name: open(os.path.join(adapter.json_dir, name), "rb").read()
        for name in sorted(os.listdir(adapter.json_dir))
    }


def assert_invariants(stats):
    assert stats["present"] + stats["reused"] + stats["to_extract"] == stats["pdfs"]
    assert (
        stats["extracted"]
        + stats["failed_rate_limit"]
        + stats["failed_other"]
        + stats["left"]
        == stats["to_extract"]
    )
    assert stats["recovered"] <= stats["retried"] <= stats["to_extract"]
    assert stats["errors"] == stats["failed_rate_limit"] + stats["failed_other"]
    assert stats["skipped"] == stats["present"]


# ------------------------------------------------------------------- US1
def test_a_document_refused_once_is_recovered(adapter, monkeypatch):
    stats, extractor, clock, _ = run(adapter, monkeypatch, {"PJ_1": ["429", "ok"]})

    assert list(json_files(adapter)) == ["PJ_1.json"]
    assert extractor.calls == ["PJ_1", "PJ_1"]
    assert clock.sleeps == [30.0]
    assert (stats["extracted"], stats["recovered"], stats["retried"]) == (1, 1, 1)
    assert stats["retries"] == 1
    assert stats["waited_s"] == 30.0
    assert_invariants(stats)


def test_the_wait_doubles_on_each_refusal(adapter, monkeypatch):
    stats, _, clock, _ = run(adapter, monkeypatch, {"PJ_1": ["429", "429", "ok"]})

    assert clock.sleeps == [30.0, 60.0]
    assert stats["recovered"] == 1
    assert stats["retries"] == 2


def test_a_longer_retry_after_is_honoured(adapter, monkeypatch):
    _, _, clock, _ = run(adapter, monkeypatch, {"PJ_1": ["429:90", "ok"]})

    assert clock.sleeps == [90.0]


def test_a_document_refused_on_every_try_fails_as_today(adapter, monkeypatch):
    stats, extractor, clock, _ = run(adapter, monkeypatch, {"PJ_1": ["429"]})

    assert extractor.calls == ["PJ_1"] * 4
    assert clock.sleeps == [30.0, 60.0, 120.0]
    assert json_files(adapter) == {}
    assert stats["failed_rate_limit"] == 1
    assert stats["errors"] == 1
    assert stats["extracted"] == 0
    assert_invariants(stats)


def test_calls_are_spaced_by_the_pause(adapter, monkeypatch):
    script = {"PJ_1": ["ok"], "PJ_2": ["ok"], "PJ_3": ["ok"]}
    _, _, clock, _ = run(adapter, monkeypatch, script, call_s=0.5)

    # No pause before the first call; 2 s since the end of the previous call.
    assert clock.sleeps == [2.0, 2.0]


def test_no_pause_is_added_after_a_backoff(adapter, monkeypatch):
    script = {"PJ_1": ["429", "ok"], "PJ_2": ["ok"]}
    _, _, clock, _ = run(adapter, monkeypatch, script, call_s=0.5)

    # The retry of PJ_1 waits its backoff only; PJ_2 gets the normal pause.
    assert clock.sleeps == [30.0, 2.0]


def test_a_slow_call_needs_no_extra_pause(adapter, monkeypatch):
    script = {"PJ_1": ["ok"], "PJ_2": ["ok"]}
    _, _, clock, _ = run(adapter, monkeypatch, script, call_s=5.0)

    # The pause counts from the end of the previous call, which just ended.
    assert clock.sleeps == [2.0]


def test_a_recovered_document_is_written_like_any_other(tmp_path, monkeypatch):
    first = SigPesqProjectFilesAdapter(
        pdf_root=str(tmp_path / "a" / "pdfs"), json_dir=str(tmp_path / "a" / "json")
    )
    second = SigPesqProjectFilesAdapter(
        pdf_root=str(tmp_path / "b" / "pdfs"), json_dir=str(tmp_path / "b" / "json")
    )
    run(first, monkeypatch, {"PJ_1": ["ok"]})
    run(second, monkeypatch, {"PJ_1": ["429", "ok"]})

    assert json_files(first) == json_files(second)


# ------------------------------------------------------------------- US2
def test_another_error_is_not_retried(adapter, monkeypatch):
    script = {"PJ_1": [ValueError("bad pdf")], "PJ_2": ["ok"]}
    stats, extractor, clock, _ = run(adapter, monkeypatch, script)

    assert extractor.calls == ["PJ_1", "PJ_2"]
    assert 30.0 not in clock.sleeps
    assert stats["failed_other"] == 1
    assert stats["extracted"] == 1
    assert_invariants(stats)


def test_another_http_error_is_not_retried(adapter, monkeypatch):
    stats, extractor, _, _ = run(adapter, monkeypatch, {"PJ_1": [ServerError()]})

    assert extractor.calls == ["PJ_1"]
    assert stats["failed_other"] == 1
    assert stats["failed_rate_limit"] == 0


def test_the_wait_budget_leaves_the_rest_for_the_next_run(
    adapter, monkeypatch, messages
):
    script = {f"PJ_{n}": ["429"] for n in range(1, 6)}
    settings = ExtractionPacingSettings(
        retries=3, pause_s=0.0, first_wait_s=30.0, wait_budget_s=100.0
    )
    stats, extractor, clock, _ = run(adapter, monkeypatch, script, settings)

    # 30 + 60 fit in 100 s; the 120 s wait does not.
    assert extractor.calls == ["PJ_1"] * 3
    assert clock.sleeps == [30.0, 60.0]
    assert stats["failed_rate_limit"] == 1
    assert stats["left"] == 4
    assert stats["waited_s"] == 90.0
    assert any("4 PDF(s) left for the next run" in m for m in messages)
    assert_invariants(stats)


def test_a_zero_budget_stops_at_the_first_refusal(adapter, monkeypatch):
    script = {"PJ_1": ["ok"], "PJ_2": ["429"], "PJ_3": ["ok"]}
    settings = ExtractionPacingSettings(
        retries=3, pause_s=0.0, first_wait_s=30.0, wait_budget_s=0.0
    )
    stats, extractor, clock, _ = run(adapter, monkeypatch, script, settings)

    assert extractor.calls == ["PJ_1", "PJ_2"]
    assert clock.sleeps == []
    assert (stats["extracted"], stats["failed_rate_limit"], stats["left"]) == (1, 1, 1)
    assert_invariants(stats)


def test_a_mix_of_outcomes_never_raises(adapter, monkeypatch):
    script = {
        "PJ_1": ["ok"],
        "PJ_2": ["429", "ok"],
        "PJ_3": [ValueError("bad")],
        "PJ_4": ["429"],
        "PJ_5": [RuntimeError("boom")],
    }
    stats, _, _, _ = run(adapter, monkeypatch, script)

    assert stats["extracted"] == 2
    assert stats["recovered"] == 1
    assert stats["failed_other"] == 2
    assert stats["failed_rate_limit"] == 1
    assert_invariants(stats)


# ------------------------------------------------------------------- US3
def test_counts_and_lines_tell_every_case_apart(adapter, monkeypatch, messages):
    make_pdfs(adapter, "PJ_1", "PJ_2", "PJ_3", "PJ_4")
    os.makedirs(adapter.json_dir, exist_ok=True)
    for stem in ("PJ_1", "PJ_2"):
        with open(os.path.join(adapter.json_dir, f"{stem}.json"), "w") as f:
            f.write("{}")
    archive = os.path.join(os.path.dirname(adapter.json_dir), "exports_canonical.zip")
    archived = {"codigo": "PJ 3", "titulo": "archived", "_meta": {"arquivo": "x"}}
    with zipfile.ZipFile(archive, "w") as zf:
        for stem in ("PJ_3", "PJ_4"):
            zf.writestr(f"project_sigpesq_files_json/{stem}.json", json.dumps(archived))
    script = {"PJ_5": ["ok"], "PJ_6": ["429", "ok"], "PJ_7": [ValueError("bad")]}

    stats, _, _, _ = run(adapter, monkeypatch, script)

    assert stats["pdfs"] == 7
    assert (stats["present"], stats["reused"], stats["to_extract"]) == (2, 2, 3)
    assert (stats["extracted"], stats["recovered"], stats["failed_other"]) == (2, 1, 1)
    assert_invariants(stats)
    assert any("7 PDFs | 2 already present | 5 pending" in m for m in messages)
    assert any("2 restored from the archive | 3 to extract" in m for m in messages)
    assert any("PJ_6 -> PJ_6.json (after 2 tries)" in m for m in messages)
    assert any("Extraction finished:" in m for m in messages)


def test_nothing_pending_builds_nothing_and_waits_nothing(
    adapter, monkeypatch, messages
):
    make_pdfs(adapter, "PJ_1")
    os.makedirs(adapter.json_dir, exist_ok=True)
    with open(os.path.join(adapter.json_dir, "PJ_1.json"), "w") as f:
        f.write("{}")

    stats, _, clock, built = run(adapter, monkeypatch, {}, stems=["PJ_1"])

    assert built == []
    assert clock.sleeps == []
    assert stats["to_extract"] == 0
    assert adapter.pacing_settings is None
    assert any("1 PDFs | 1 already present | 0 pending" in m for m in messages)
    assert not any("to extract" in m for m in messages)


# ------------------------------------------------------------------- US4
def test_retry_off_and_no_pause_behave_as_before(adapter, monkeypatch):
    script = {"PJ_1": ["ok"], "PJ_2": ["429", "ok"], "PJ_3": [ValueError("bad")]}
    settings = ExtractionPacingSettings(
        retries=0, pause_s=0.0, first_wait_s=30.0, wait_budget_s=1200.0
    )
    stats, extractor, clock, _ = run(adapter, monkeypatch, script, settings)

    # One call per document and no wait, as before spec 031.
    assert extractor.calls == ["PJ_1", "PJ_2", "PJ_3"]
    assert clock.sleeps == []
    assert list(json_files(adapter)) == ["PJ_1.json"]
    assert stats["errors"] == 2
    assert stats["retried"] == 0


def test_settings_come_from_the_environment_when_not_given(adapter, monkeypatch):
    monkeypatch.setenv("HORIZON_EXTRACT_RETRIES", "0")
    monkeypatch.setenv("HORIZON_EXTRACT_PAUSE_S", "0")
    clock = FakeClock()
    extractor = ScriptedExtractor({"PJ_1": ["429", "ok"]}, clock)
    monkeypatch.setattr(adapter, "_build_extractor", lambda: extractor)
    make_pdfs(adapter, "PJ_1")

    stats = adapter.extract_json(sleep=clock.sleep, clock=clock)

    assert adapter.pacing_settings.retries == 0
    assert stats["failed_rate_limit"] == 1
    assert clock.sleeps == []


def test_the_flow_reports_the_counts_and_the_settings(adapter, monkeypatch):
    from src.flows.sigpesq import project_files as flow_module

    recorded = []
    monkeypatch.setattr(flow_module, "record_extraction", lambda *a: recorded.append(a))
    stats, _, _, _ = run(adapter, monkeypatch, {"PJ_1": ["429", "ok"]})

    flow_module._record_extraction(adapter, stats)

    source, entry = recorded[0]
    assert source == "sigpesq_project_files"
    assert entry["recovered"] == 1
    assert entry["settings"]["retries"] == 3
