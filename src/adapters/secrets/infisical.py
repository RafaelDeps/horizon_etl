"""Infisical implementation of the ISecretProvider port (Constitution I).

The ``infisical_sdk`` import is deliberately lazy (inside ``get_secret``) so
that importing this module — and the SigPesq adapter that references it — never
requires the SDK or the network. Tests inject a fake ``infisical_sdk`` into
``sys.modules``.
"""

import os
from typing import Optional

from loguru import logger

from src.core.ports.secret_provider import CredentialResolutionError, ISecretProvider

_DEFAULT_HOST = "https://app.infisical.com"
_DEFAULT_ENV = "dev"
_DEFAULT_SECRET_PATH = "/"

_REQUIRED_SETTINGS = (
    "INFISICAL_CLIENT_ID",
    "INFISICAL_CLIENT_SECRET",
    "INFISICAL_PROJECT_ID",
)


class InfisicalSecretProvider(ISecretProvider):
    """Resolves secrets from an Infisical instance via Universal Auth."""

    def __init__(
        self,
        host: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        project_id: Optional[str] = None,
        environment: Optional[str] = None,
        secret_path: Optional[str] = None,
    ):
        self.host = (
            host if host is not None else os.getenv("INFISICAL_HOST", _DEFAULT_HOST)
        )
        self.client_id = (
            client_id if client_id is not None else os.getenv("INFISICAL_CLIENT_ID")
        )
        self.client_secret = (
            client_secret
            if client_secret is not None
            else os.getenv("INFISICAL_CLIENT_SECRET")
        )
        self.project_id = (
            project_id if project_id is not None else os.getenv("INFISICAL_PROJECT_ID")
        )
        self.environment = (
            environment
            if environment is not None
            else os.getenv("INFISICAL_ENV", _DEFAULT_ENV)
        )
        self.secret_path = (
            secret_path
            if secret_path is not None
            else os.getenv("INFISICAL_SECRET_PATH", _DEFAULT_SECRET_PATH)
        )

    def _validate_config(self) -> None:
        """Fail fast, naming the missing setting, before any network call."""
        values = {
            "INFISICAL_CLIENT_ID": self.client_id,
            "INFISICAL_CLIENT_SECRET": self.client_secret,
            "INFISICAL_PROJECT_ID": self.project_id,
        }
        missing = [name for name in _REQUIRED_SETTINGS if not values[name]]
        if missing:
            raise CredentialResolutionError(
                "Missing required Infisical configuration: "
                + ", ".join(missing)
                + ". Set it in the environment (or .env) before running with "
                "SIGPESQ_CREDENTIALS_SOURCE=infisical."
            )

    def _location(self) -> str:
        return (
            f"project={self.project_id} environment={self.environment} "
            f"path={self.secret_path}"
        )

    def get_secret(self, secret_name: str) -> str:
        self._validate_config()
        logger.debug(
            "Resolving Infisical secret '{}' ({}).", secret_name, self._location()
        )

        try:
            from infisical_sdk import InfisicalSDKClient
            from infisical_sdk.infisical_requests import APIError, InfisicalError
        except ImportError as exc:  # pragma: no cover - dependency is pinned
            raise CredentialResolutionError(
                "The Infisical SDK ('infisicalsdk') is not installed. "
                "Install requirements.txt before running in infisical mode."
            ) from exc

        try:
            with InfisicalSDKClient(host=self.host, cache_ttl=None) as client:
                client.auth.universal_auth.login(self.client_id, self.client_secret)
                secret = client.secrets.get_secret_by_name(
                    secret_name=secret_name,
                    project_id=self.project_id,
                    environment_slug=self.environment,
                    secret_path=self.secret_path,
                )
        except APIError as exc:
            raise self._map_api_error(secret_name, exc) from exc
        except InfisicalError as exc:
            # Connectivity / invalid-response failures surface here.
            raise CredentialResolutionError(
                f"Could not reach Infisical at {self.host} "
                f"({self._location()}): {exc}. Check the host and network "
                "access in this environment, or use the 'legacy' credential mode."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - defensive, keeps values out
            raise CredentialResolutionError(
                "Unexpected error while resolving Infisical secret "
                f"'{secret_name}' ({self._location()}): {type(exc).__name__}. "
                "No credential value was logged."
            ) from exc

        value = getattr(secret, "secretValue", None)
        if value is None or value == "":
            raise CredentialResolutionError(
                f"Infisical secret '{secret_name}' is missing or empty "
                f"({self._location()}). Populate it, or use the 'legacy' "
                "credential mode."
            )
        return value

    def _map_api_error(self, secret_name: str, exc) -> CredentialResolutionError:
        status = getattr(exc, "status_code", None)
        location = self._location()
        if status == 401:
            return CredentialResolutionError(
                "Infisical authentication failed (HTTP 401): the machine "
                "identity credentials (INFISICAL_CLIENT_ID / "
                "INFISICAL_CLIENT_SECRET) are invalid or expired."
            )
        if status == 403:
            return CredentialResolutionError(
                f"Infisical denied access to secret '{secret_name}' (HTTP 403) "
                f"({location}). Grant the identity read access to this path."
            )
        if status == 404:
            return CredentialResolutionError(
                f"Infisical secret '{secret_name}' was not found ({location}). "
                "Check INFISICAL_PROJECT_ID / INFISICAL_ENV / "
                "INFISICAL_SECRET_PATH."
            )
        return CredentialResolutionError(
            f"Infisical returned an error (HTTP {status}) while resolving secret "
            f"'{secret_name}' ({location})."
        )

    def __repr__(self) -> str:  # never expose the client secret
        return (
            f"InfisicalSecretProvider(host={self.host!r}, "
            f"project_id={self.project_id!r}, environment={self.environment!r}, "
            f"secret_path={self.secret_path!r})"
        )


__all__ = ["InfisicalSecretProvider"]
