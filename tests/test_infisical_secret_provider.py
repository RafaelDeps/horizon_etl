"""Unit tests for InfisicalSecretProvider (C2 rules).

The external ``infisical_sdk`` is faked in ``sys.modules`` so these tests are
offline and need neither the real SDK nor a live Infisical instance. The
provider's SDK import is lazy (inside ``get_secret``), so patching
``sys.modules`` before the call is sufficient.
"""

import sys
import types

import pytest

from src.adapters.secrets.infisical import InfisicalSecretProvider
from src.core.ports.secret_provider import CredentialResolutionError


def install_fake_sdk(
    monkeypatch,
    *,
    values=None,
    login_error=None,
    get_error=None,
):
    """Install a fake ``infisical_sdk`` package into ``sys.modules``.

    Returns ``(record, APIError, InfisicalError)``. ``record`` captures the
    client constructions, logins, and secret lookups; a test may also set
    ``record["login_error"]`` / ``record["get_error"]`` after installing to make
    the fake raise (evaluated at call time).
    """
    values = values if values is not None else {}
    record = {
        "clients": [],
        "login_calls": [],
        "get_calls": [],
        "login_error": login_error,
        "get_error": get_error,
    }

    class APIError(Exception):
        def __init__(self, message, status_code=500, response=None):
            self.status_code = status_code
            self.response = response or {}
            super().__init__(f"{message} (Status: {status_code})")

    class InfisicalError(Exception):
        pass

    class FakeSecret:
        def __init__(self, value):
            self.secretValue = value

    class FakeUniversalAuth:
        def login(self, client_id, client_secret):
            record["login_calls"].append((client_id, client_secret))
            if record["login_error"] is not None:
                raise record["login_error"]

    class FakeAuth:
        def __init__(self):
            self.universal_auth = FakeUniversalAuth()

    class FakeSecrets:
        def get_secret_by_name(
            self,
            *,
            secret_name,
            project_id,
            environment_slug,
            secret_path,
            **kwargs,
        ):
            record["get_calls"].append(
                {
                    "secret_name": secret_name,
                    "project_id": project_id,
                    "environment_slug": environment_slug,
                    "secret_path": secret_path,
                }
            )
            if record["get_error"] is not None:
                raise record["get_error"]
            if secret_name not in values:
                raise APIError(
                    "Secret not found",
                    status_code=404,
                    response={"message": "Secret not found"},
                )
            return FakeSecret(values[secret_name])

    class FakeClient:
        def __init__(self, host, token=None, cache_ttl=60):
            record["clients"].append(
                {"host": host, "token": token, "cache_ttl": cache_ttl}
            )
            self.auth = FakeAuth()
            self.secrets = FakeSecrets()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    sdk_mod = types.ModuleType("infisical_sdk")
    sdk_mod.InfisicalSDKClient = FakeClient
    req_mod = types.ModuleType("infisical_sdk.infisical_requests")
    req_mod.APIError = APIError
    req_mod.InfisicalError = InfisicalError
    sdk_mod.infisical_requests = req_mod

    monkeypatch.setitem(sys.modules, "infisical_sdk", sdk_mod)
    monkeypatch.setitem(sys.modules, "infisical_sdk.infisical_requests", req_mod)

    return record, APIError, InfisicalError


def _provider(**overrides):
    config = {
        "host": "https://infisical.test",
        "client_id": "cid",
        "client_secret": "csecret",
        "project_id": "proj",
        "environment": "dev",
        "secret_path": "/",
    }
    config.update(overrides)
    return InfisicalSecretProvider(**config)


def test_get_secret_returns_value_and_authenticates_once(monkeypatch):
    # C2-01, C2-05: one Universal Auth login, one lookup, cache disabled.
    record, _, _ = install_fake_sdk(monkeypatch, values={"sigpesq-user": "alice"})

    value = _provider().get_secret("sigpesq-user")

    assert value == "alice"
    assert record["login_calls"] == [("cid", "csecret")]
    assert len(record["clients"]) == 1
    assert record["clients"][0]["cache_ttl"] is None
    assert record["get_calls"] == [
        {
            "secret_name": "sigpesq-user",
            "project_id": "proj",
            "environment_slug": "dev",
            "secret_path": "/",
        }
    ]


def test_get_secret_uses_lowercase_keyword_names(monkeypatch):
    # The pinned SDK expects snake_case kwargs (verified against 1.0.17).
    record, _, _ = install_fake_sdk(monkeypatch, values={"sigpesq-password": "pw"})

    value = _provider().get_secret("sigpesq-password")

    assert value == "pw"
    assert record["get_calls"][0]["secret_name"] == "sigpesq-password"


def test_get_secret_returns_value_exactly_as_stored(monkeypatch):
    # C2-06: no trimming, no quoting.
    record, _, _ = install_fake_sdk(monkeypatch, values={"sigpesq-user": "  alice  "})

    assert _provider().get_secret("sigpesq-user") == "  alice  "


def test_provider_applies_documented_defaults_from_env(monkeypatch):
    # C2-01: host/env/path fall back to documented defaults.
    record, _, _ = install_fake_sdk(monkeypatch, values={"sigpesq-user": "alice"})
    monkeypatch.setenv("INFISICAL_CLIENT_ID", "env-cid")
    monkeypatch.setenv("INFISICAL_CLIENT_SECRET", "env-csecret")
    monkeypatch.setenv("INFISICAL_PROJECT_ID", "env-proj")
    monkeypatch.delenv("INFISICAL_HOST", raising=False)
    monkeypatch.delenv("INFISICAL_ENV", raising=False)
    monkeypatch.delenv("INFISICAL_SECRET_PATH", raising=False)

    InfisicalSecretProvider().get_secret("sigpesq-user")

    assert record["clients"][0]["host"] == "https://app.infisical.com"
    assert record["get_calls"][0]["environment_slug"] == "dev"
    assert record["get_calls"][0]["secret_path"] == "/"
    assert record["get_calls"][0]["project_id"] == "env-proj"


def test_get_secret_rejects_empty_value(monkeypatch):
    # C2-03 (basic guard): empty must never be handed downstream.
    install_fake_sdk(monkeypatch, values={"sigpesq-user": ""})

    with pytest.raises(CredentialResolutionError) as excinfo:
        _provider().get_secret("sigpesq-user")

    assert "sigpesq-user" in str(excinfo.value)


def test_missing_required_setting_aborts_before_network(monkeypatch):
    # C2-02: name the missing setting and make no network call.
    record, _, _ = install_fake_sdk(monkeypatch, values={})
    for var in (
        "INFISICAL_CLIENT_ID",
        "INFISICAL_CLIENT_SECRET",
        "INFISICAL_PROJECT_ID",
    ):
        monkeypatch.delenv(var, raising=False)

    provider = InfisicalSecretProvider(
        host="https://infisical.test", client_secret="s", project_id="p"
    )

    with pytest.raises(CredentialResolutionError) as excinfo:
        provider.get_secret("sigpesq-user")

    assert "INFISICAL_CLIENT_ID" in str(excinfo.value)
    assert record["clients"] == []
    assert record["login_calls"] == []


def test_missing_secret_aborts_naming_it(monkeypatch):
    # C2-03: a secret absent from the location names that secret.
    install_fake_sdk(monkeypatch, values={"sigpesq-password": "pw"})

    with pytest.raises(CredentialResolutionError) as excinfo:
        _provider().get_secret("sigpesq-user")

    message = str(excinfo.value)
    assert "sigpesq-user" in message
    assert "not found" in message.lower()


def test_auth_failure_maps_to_distinct_message(monkeypatch):
    # C2-04 (auth): 401 names the machine-identity credentials.
    record, APIError, _ = install_fake_sdk(monkeypatch, values={})
    record["login_error"] = APIError("Unauthorized", status_code=401)

    with pytest.raises(CredentialResolutionError) as excinfo:
        _provider().get_secret("sigpesq-user")

    message = str(excinfo.value)
    assert "401" in message
    assert "INFISICAL_CLIENT_ID" in message
    assert "INFISICAL_CLIENT_SECRET" in message


def test_permission_failure_maps_to_distinct_message(monkeypatch):
    # C2-04 (permission): 403 names the secret and read access.
    record, APIError, _ = install_fake_sdk(monkeypatch, values={})
    record["get_error"] = APIError("Forbidden", status_code=403)

    with pytest.raises(CredentialResolutionError) as excinfo:
        _provider().get_secret("sigpesq-user")

    message = str(excinfo.value)
    assert "403" in message
    assert "sigpesq-user" in message
    assert "read access" in message.lower()


def test_connectivity_failure_maps_to_distinct_message(monkeypatch):
    # C2-04 (connectivity): a transport-level InfisicalError names the host.
    record, _, InfisicalError = install_fake_sdk(monkeypatch, values={})
    record["login_error"] = InfisicalError("Request failed: connection refused")

    with pytest.raises(CredentialResolutionError) as excinfo:
        _provider().get_secret("sigpesq-user")

    message = str(excinfo.value)
    assert "Could not reach Infisical" in message
    assert "https://infisical.test" in message


def test_error_messages_never_contain_secret_values(monkeypatch):
    # C4-01: no rendered failure path embeds a value.
    record, APIError, _ = install_fake_sdk(
        monkeypatch, values={"sigpesq-user": "super-secret-user"}
    )
    record["get_error"] = APIError("Boom", status_code=500)

    provider = _provider(client_secret="super-secret-client")
    with pytest.raises(CredentialResolutionError) as excinfo:
        provider.get_secret("sigpesq-user")

    message = str(excinfo.value)
    assert "super-secret-user" not in message
    assert "super-secret-client" not in message


def test_provider_logs_never_contain_secret_values(monkeypatch):
    # C4-01, C4-02: even at DEBUG, the resolved value never reaches the logs.
    from loguru import logger

    install_fake_sdk(monkeypatch, values={"sigpesq-user": "user-VALUE-123"})
    logs = []
    sink_id = logger.add(lambda message: logs.append(message), level="DEBUG")
    try:
        value = _provider(client_secret="client-VALUE-999").get_secret("sigpesq-user")
    finally:
        logger.remove(sink_id)

    assert value == "user-VALUE-123"
    text = "".join(str(message) for message in logs)
    assert "user-VALUE-123" not in text
    assert "client-VALUE-999" not in text
