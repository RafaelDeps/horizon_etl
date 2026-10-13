"""Tests for SigPesq credential-mode selection and Infisical hand-off.

Uses a fake ``ISecretProvider`` so no live Infisical is required.
"""

import os

import pytest

from src.adapters.sources.sigpesq.credentials import (
    SIGPESQ_PASSWORD_SECRET,
    SIGPESQ_USER_SECRET,
    parse_credential_source,
    resolve_infisical_credentials,
)
from src.core.ports.secret_provider import CredentialResolutionError, ISecretProvider


class FakeProvider(ISecretProvider):
    def __init__(self, values=None):
        self.values = values if values is not None else {}
        self.requested = []

    def get_secret(self, secret_name: str) -> str:
        self.requested.append(secret_name)
        if secret_name not in self.values:
            raise CredentialResolutionError(
                f"Infisical secret '{secret_name}' was not found."
            )
        return self.values[secret_name]


@pytest.fixture
def clean_sigpesq_env(monkeypatch):
    for var in ("SIGPESQ_USERNAME", "SIGPESQ_USER", "SIGPESQ_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_resolve_infisical_credentials_exports_env(clean_sigpesq_env):
    # C3-01: the resolved pair is exported under the names the download step reads.
    provider = FakeProvider(
        {SIGPESQ_USER_SECRET: "alice", SIGPESQ_PASSWORD_SECRET: "s3cret"}
    )

    resolve_infisical_credentials(provider)

    assert os.environ["SIGPESQ_USERNAME"] == "alice"
    assert os.environ["SIGPESQ_USER"] == "alice"
    assert os.environ["SIGPESQ_PASSWORD"] == "s3cret"
    assert provider.requested == [SIGPESQ_USER_SECRET, SIGPESQ_PASSWORD_SECRET]


def test_resolve_infisical_credentials_reports_count(clean_sigpesq_env):
    provider = FakeProvider(
        {SIGPESQ_USER_SECRET: "alice", SIGPESQ_PASSWORD_SECRET: "s3cret"}
    )

    resolved = resolve_infisical_credentials(provider)

    assert resolved == 2


def test_infisical_mode_ignores_operator_legacy_vars(clean_sigpesq_env):
    # C3-02: operator-set legacy vars must be overwritten, never mixed.
    monkeypatch = clean_sigpesq_env
    monkeypatch.setenv("SIGPESQ_USERNAME", "operator-user")
    monkeypatch.setenv("SIGPESQ_USER", "operator-user")
    monkeypatch.setenv("SIGPESQ_PASSWORD", "operator-pw")
    provider = FakeProvider(
        {SIGPESQ_USER_SECRET: "infisical-user", SIGPESQ_PASSWORD_SECRET: "infisical-pw"}
    )

    resolve_infisical_credentials(provider)

    assert os.environ["SIGPESQ_USERNAME"] == "infisical-user"
    assert os.environ["SIGPESQ_USER"] == "infisical-user"
    assert os.environ["SIGPESQ_PASSWORD"] == "infisical-pw"


def test_single_resolvable_secret_aborts_without_partial_export(clean_sigpesq_env):
    # C3-03 / FR-005: only one secret present -> abort, no partial env export.
    provider = FakeProvider({SIGPESQ_USER_SECRET: "alice"})  # password missing

    with pytest.raises(CredentialResolutionError) as excinfo:
        resolve_infisical_credentials(provider)

    assert SIGPESQ_PASSWORD_SECRET in str(excinfo.value)
    assert os.getenv("SIGPESQ_USERNAME") is None
    assert os.getenv("SIGPESQ_USER") is None


def test_infisical_resolution_failure_aborts_before_download(
    clean_sigpesq_env, tmp_path
):
    # C3-03 / US2: no SigPesq portal access when credentials cannot resolve.
    from unittest.mock import patch

    from src.adapters.sources.sigpesq.adapter import SigPesqAdapter

    clean_sigpesq_env.setenv("SIGPESQ_CREDENTIALS_SOURCE", "infisical")
    provider = FakeProvider({})  # nothing resolves
    adapter = SigPesqAdapter(download_dir=str(tmp_path), secret_provider=provider)

    with patch.object(SigPesqAdapter, "_trigger_download") as trigger:
        with pytest.raises(CredentialResolutionError):
            adapter.extract()

    trigger.assert_not_called()


def test_resolution_logs_never_contain_values(clean_sigpesq_env):
    # C4-01, C4-02: even at DEBUG, no resolved value reaches the logs.
    from loguru import logger

    logs = []
    sink_id = logger.add(lambda message: logs.append(message), level="DEBUG")
    try:
        provider = FakeProvider(
            {
                SIGPESQ_USER_SECRET: "user-VALUE-123",
                SIGPESQ_PASSWORD_SECRET: "pass-VALUE-456",
            }
        )
        resolve_infisical_credentials(provider)
    finally:
        logger.remove(sink_id)

    text = "".join(str(message) for message in logs)
    assert "user-VALUE-123" not in text
    assert "pass-VALUE-456" not in text


def test_adapter_infisical_mode_logs_mode_and_count_without_values(
    clean_sigpesq_env, tmp_path
):
    # C4-01, C4-02, FR-010: observed at non-secret level only.
    from loguru import logger

    from src.adapters.sources.sigpesq.adapter import SigPesqAdapter

    clean_sigpesq_env.setenv("SIGPESQ_CREDENTIALS_SOURCE", "infisical")
    provider = FakeProvider(
        {
            SIGPESQ_USER_SECRET: "user-VALUE-123",
            SIGPESQ_PASSWORD_SECRET: "pass-VALUE-456",
        }
    )
    adapter = SigPesqAdapter(download_dir=str(tmp_path), secret_provider=provider)

    logs = []
    sink_id = logger.add(lambda message: logs.append(message), level="DEBUG")
    try:
        adapter._validate_environment()
    finally:
        logger.remove(sink_id)

    text = "".join(str(message) for message in logs)
    assert "infisical" in text
    assert "user-VALUE-123" not in text
    assert "pass-VALUE-456" not in text


def test_parse_credential_source_accepts_both_values(clean_sigpesq_env):
    # C1-01: exactly two valid values (case/space tolerant).
    assert parse_credential_source("infisical") == "infisical"
    assert parse_credential_source("legacy") == "legacy"
    assert parse_credential_source(" INFISICAL ") == "infisical"


def test_parse_credential_source_absent_aborts(clean_sigpesq_env):
    # C1-02: absent -> abort naming the variable and both accepted values.
    clean_sigpesq_env.delenv("SIGPESQ_CREDENTIALS_SOURCE", raising=False)

    with pytest.raises(CredentialResolutionError) as excinfo:
        parse_credential_source()

    message = str(excinfo.value)
    assert "SIGPESQ_CREDENTIALS_SOURCE" in message
    assert "infisical" in message
    assert "legacy" in message


def test_parse_credential_source_invalid_aborts(clean_sigpesq_env):
    # C1-03: any other value -> same abort.
    with pytest.raises(CredentialResolutionError) as excinfo:
        parse_credential_source("typo")

    message = str(excinfo.value)
    assert "SIGPESQ_CREDENTIALS_SOURCE" in message
    assert "typo" in message


def test_absent_mode_aborts_without_auto_detection(clean_sigpesq_env, tmp_path):
    # C1-05: partial config with no flag must not be silently interpreted.
    from unittest.mock import patch

    from src.adapters.sources.sigpesq.adapter import SigPesqAdapter

    clean_sigpesq_env.delenv("SIGPESQ_CREDENTIALS_SOURCE", raising=False)
    clean_sigpesq_env.setenv("SIGPESQ_USERNAME", "operator-user")
    clean_sigpesq_env.setenv("SIGPESQ_PASSWORD", "operator-pw")
    clean_sigpesq_env.setenv("INFISICAL_CLIENT_ID", "cid")
    adapter = SigPesqAdapter(download_dir=str(tmp_path))

    with patch.object(SigPesqAdapter, "_trigger_download") as trigger:
        with pytest.raises(CredentialResolutionError):
            adapter.extract()

    trigger.assert_not_called()


def test_credentials_never_reach_generated_artifacts(clean_sigpesq_env, tmp_path):
    # C4-03: scan produced files for the resolved values (dummy artifact).
    import json
    from unittest.mock import patch

    from src.adapters.sources.sigpesq.adapter import SigPesqAdapter

    clean_sigpesq_env.setenv("SIGPESQ_CREDENTIALS_SOURCE", "infisical")
    provider = FakeProvider(
        {
            SIGPESQ_USER_SECRET: "user-VALUE-123",
            SIGPESQ_PASSWORD_SECRET: "pass-VALUE-456",
        }
    )
    adapter = SigPesqAdapter(download_dir=str(tmp_path), secret_provider=provider)

    def trigger_download(_download_strategies=None):
        report_dir = tmp_path / "report"
        report_dir.mkdir(exist_ok=True)
        (report_dir / "report_001.json").write_text(
            json.dumps({"id": 1, "name": "grupo"})
        )
        (tmp_path / "run_metadata.json").write_text(
            json.dumps({"flow": "ingest_sigpesq"})
        )

    with patch.object(
        SigPesqAdapter, "_trigger_download", side_effect=trigger_download
    ):
        adapter.extract()

    blob = b""
    for path in tmp_path.rglob("*"):
        if path.is_file():
            blob += path.read_bytes()
    text = blob.decode("utf-8", errors="ignore")
    assert "user-VALUE-123" not in text
    assert "pass-VALUE-456" not in text
