"""SigPesq credential-mode selection and Infisical hand-off.

Owns:
- parsing of the mandatory ``SIGPESQ_CREDENTIALS_SOURCE`` mode flag (FR-003),
- resolution of the SigPesq pair from an ``ISecretProvider`` (FR-001/FR-005),
- exporting the resolved pair to ``os.environ`` under the exact names the
  unchanged ``agent_sigpesq`` download step reads (FR-008).
"""

import os
from typing import Optional

from loguru import logger

from src.core.ports.secret_provider import CredentialResolutionError, ISecretProvider

CREDENTIALS_SOURCE_VAR = "SIGPESQ_CREDENTIALS_SOURCE"
VALID_CREDENTIAL_SOURCES = ("infisical", "legacy")

SIGPESQ_USER_SECRET = "sigpesq-user"
SIGPESQ_PASSWORD_SECRET = "sigpesq-password"

# Names the external download step reads (see research.md R6).
_HANDOFF_ENV_VARS = ("SIGPESQ_USERNAME", "SIGPESQ_USER", "SIGPESQ_PASSWORD")


def parse_credential_source(value: Optional[str] = None) -> str:
    """Return the selected credential mode.

    Explicit, mandatory selection (FR-003): an absent or unrecognized value
    aborts with a message naming the variable and both accepted values. There
    is no implicit default and no auto-detection.
    """
    if value is None:
        value = os.getenv(CREDENTIALS_SOURCE_VAR)

    normalized = (value or "").strip().lower()
    if normalized not in VALID_CREDENTIAL_SOURCES:
        raise CredentialResolutionError(
            f"Missing or invalid {CREDENTIALS_SOURCE_VAR}: expected "
            f"'{VALID_CREDENTIAL_SOURCES[0]}' or '{VALID_CREDENTIAL_SOURCES[1]}', "
            f"got {value!r}. Set it explicitly in the environment (or .env); "
            "there is no default."
        )
    return normalized


def resolve_infisical_credentials(provider: ISecretProvider) -> int:
    """Resolve both SigPesq secrets and export them for the download step.

    Never reads or falls back to operator-set ``SIGPESQ_*`` variables (FR-004).
    Returns the number of secrets resolved (for non-secret observability,
    FR-010). Raises :class:`CredentialResolutionError` on the first failure.
    """
    username = provider.get_secret(SIGPESQ_USER_SECRET)
    password = provider.get_secret(SIGPESQ_PASSWORD_SECRET)

    if not username:
        raise CredentialResolutionError(
            f"Infisical secret '{SIGPESQ_USER_SECRET}' resolved to an empty "
            "value; SigPesq credentials must not be empty."
        )
    if not password:
        raise CredentialResolutionError(
            f"Infisical secret '{SIGPESQ_PASSWORD_SECRET}' resolved to an empty "
            "value; SigPesq credentials must not be empty."
        )

    resolved = {
        "SIGPESQ_USERNAME": username,
        "SIGPESQ_USER": username,
        "SIGPESQ_PASSWORD": password,
    }
    for name in _HANDOFF_ENV_VARS:
        os.environ[name] = resolved[name]

    logger.debug("Exported resolved SigPesq credentials to the process environment.")
    return 2
