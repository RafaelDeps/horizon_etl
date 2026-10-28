"""Shared pytest configuration for the Horizon ETL test suite."""

import os

# Default test-only HMAC key for the LGPD PII anonymizer. Real runs load
# HORIZON_PII_HMAC_KEY from .env (app.py / flows); tests must not depend on
# machine-local secrets. Individual test modules may override it explicitly.
TEST_HMAC_KEY = "test-only-horizon-pii-hmac-key"


def pytest_configure(config) -> None:
    os.environ.setdefault("HORIZON_PII_HMAC_KEY", TEST_HMAC_KEY)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_rule_version_reset(monkeypatch):
    """run_weekly may rebuild DATABASE_URL when its rule version differs
    (spec 020, FR-024). Tests fake the phases: never let that touch the
    repository's db/horizon.db. Yields the real guard for the tests of it."""
    import src.flows.pipelines.weekly_orchestrator as orchestrator

    real = orchestrator._reset_if_rule_version_changed
    monkeypatch.setattr(orchestrator, "_reset_if_rule_version_changed", lambda: None)
    yield real
