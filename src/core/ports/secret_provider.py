"""Port contract for secret providers (Constitution I: Ports & Adapters).

Every external secret manager (Infisical, Vault, ...) MUST be reached through
this contract, so that adapters and business logic never import a concrete
secret-manager SDK directly.
"""

from abc import ABC, abstractmethod


class CredentialResolutionError(Exception):
    """Raised when a credential cannot be resolved.

    The message MUST never contain the secret value itself (FR-009); it names
    the configuration item or the secret that could not be resolved so the
    operator can fix it.
    """


class ISecretProvider(ABC):
    @abstractmethod
    def get_secret(self, secret_name: str) -> str:
        """Return the value of ``secret_name``.

        Implementations raise :class:`CredentialResolutionError` when the
        secret is missing, empty, or cannot be reached/authenticated, so that
        callers can abort before contacting the downstream system.
        """
        raise NotImplementedError
