"""Shared pytest configuration for the Horizon ETL test suite."""

import os

# Default test-only HMAC key for the LGPD PII anonymizer. Real runs load
# HORIZON_PII_HMAC_KEY from .env (app.py / flows); tests must not depend on
# machine-local secrets. Individual test modules may override it explicitly.
TEST_HMAC_KEY = "test-only-horizon-pii-hmac-key"


def pytest_configure(config) -> None:
    os.environ.setdefault("HORIZON_PII_HMAC_KEY", TEST_HMAC_KEY)
