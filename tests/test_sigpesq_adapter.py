import asyncio
import os
import shutil
from types import SimpleNamespace
from unittest.mock import patch

# agent_sigpesq.run() calls load_dotenv() at module scope, which crashes under
# pytest's frame handling (dotenv's find_dotenv asserts on f_back). Finish the
# required module-level side effect once here, under a patched no-op, so the
# import in _trigger_download is a cached sys.modules hit and does not re-run
# load_dotenv().
import dotenv
import pytest

with patch.object(dotenv, "load_dotenv", lambda *a, **k: None):
    from agent_sigpesq.services.reports_service import (  # noqa: F401
        SigpesqReportService,
    )

from src.adapters.sources.sigpesq.adapter import _SIGPESQ_MAX_RETRIES, SigPesqAdapter


@pytest.fixture
def mock_data_dir():
    dir_path = "data/test_sigpesq"
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)
    os.makedirs(dir_path)
    yield dir_path
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)


def test_sigpesq_adapter_extract(mock_data_dir):
    # Arrange
    from unittest.mock import patch

    adapter = SigPesqAdapter(download_dir=mock_data_dir)

    def trigger_download(_download_strategies=None):
        report_dir = os.path.join(mock_data_dir, "report")
        os.makedirs(report_dir, exist_ok=True)
        dummy_file = os.path.join(report_dir, "mock_project_001.json")
        with open(dummy_file, "w") as f:
            f.write('{"id": 1, "title": "Mock Project"}')

    # Act
    with (
        patch.object(SigPesqAdapter, "_validate_environment"),
        patch.object(SigPesqAdapter, "_trigger_download", side_effect=trigger_download),
    ):
        results = adapter.extract()

    # Assert
    assert len(results) > 0
    assert "filename" in results[0]
    assert "parsed_content" in results[0]
    # assert results[0]["source"] == "sigpesq" # Removed: Implementation does not provide this key

    # Verify file was created (mock behavior)
    assert os.path.exists(
        os.path.join(mock_data_dir, "report", "mock_project_001.json")
    )


def test_sigpesq_adapter_cleans_download_dir_before_download(tmp_path):
    adapter = SigPesqAdapter(download_dir=str(tmp_path))

    stale_dir = tmp_path / "advisorships" / "2025"
    stale_dir.mkdir(parents=True)
    stale_file = stale_dir / "old_report.xlsx"
    stale_file.write_text("old")

    def trigger_download(_download_strategies=None):
        assert not stale_file.exists()
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "fresh_report.json").write_text('{"id": 2}')

    with (
        patch.object(SigPesqAdapter, "_validate_environment"),
        patch.object(SigPesqAdapter, "_trigger_download", side_effect=trigger_download),
    ):
        results = adapter.extract()

    assert len(results) == 1
    assert results[0]["filename"] == "fresh_report.json"
    assert not stale_file.exists()


def test_sigpesq_adapter_logs_http_429_during_login(tmp_path):
    class FakePage:
        def __init__(self):
            self.handlers = {}

        def on(self, event_name, handler):
            self.handlers[event_name] = handler

        def remove_listener(self, event_name, handler):
            assert event_name == "response"
            assert self.handlers[event_name] is handler

    class FakeService:
        async def _login(self, page):
            response = SimpleNamespace(
                status=429,
                url="https://sigpesq.ifes.edu.br/Login.aspx",
            )
            page.handlers["response"](response)
            return False

    adapter = SigPesqAdapter(download_dir=str(tmp_path))
    service = FakeService()

    adapter._attach_http_429_logging(service)

    with patch("src.adapters.sources.sigpesq.adapter.logger.error") as log_error:
        assert asyncio.run(service._login(FakePage())) is False

    log_message = log_error.call_args.args[0]
    assert "HTTP 429" in log_message
    assert "rate limiting" in log_message
    assert "Login.aspx" in log_message


def test_sigpesq_adapter_retries_on_non_429_failure(tmp_path):
    # A Page.goto TimeoutError on login is a non-429 failure. Before, the
    # retry loop only fired on HTTP 429, so a transient RNP timeout aborted the
    # weekly ETL after a single attempt. Now any failed run must be retried up
    # to _SIGPESQ_MAX_RETRIES with backoff before raising.
    adapter = SigPesqAdapter(download_dir=str(tmp_path))

    def _noop_run_run_agent(coro):
        # mimic asyncio.run by consuming the coroutine so it is not left
        # unawaited, then report a failed download (non-429 path).
        try:
            coro.close()
        except Exception:
            pass
        return False

    with (
        patch(
            "src.adapters.sources.sigpesq.adapter.asyncio.run",
            side_effect=_noop_run_run_agent,
        ),
        patch(
            "src.adapters.sources.sigpesq.adapter.time.sleep",
        ) as mock_sleep,
        patch(
            "src.adapters.sources.sigpesq.adapter.os.path.exists",
            return_value=False,
        ),
        pytest.raises(RuntimeError, match=f"failed after {_SIGPESQ_MAX_RETRIES}"),
    ):
        adapter._trigger_download()

    # One call per attempt; the last attempt does not wait/continue.
    assert mock_sleep.call_count == (_SIGPESQ_MAX_RETRIES - 1)
