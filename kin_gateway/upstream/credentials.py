"""Customer-local secret resolution for protected upstream calls."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from kin_gateway.config import UpstreamCredentialSettings


class SecretProvider(Protocol):
    """Resolve a configured secret reference inside the customer trust domain."""

    def get_secret(self, secret_ref: str) -> str:
        """Return the secret value or raise when the reference is unavailable."""


@dataclass(frozen=True)
class MappingSecretProvider:
    """In-memory provider for tests and explicit embedded integrations."""

    secrets: Mapping[str, str]

    def get_secret(self, secret_ref: str) -> str:
        try:
            return self.secrets[secret_ref]
        except KeyError as exc:
            raise ValueError("Configured upstream secret is unavailable") from exc


def resolve_upstream_headers(
    settings: UpstreamCredentialSettings,
    secret_provider: SecretProvider | None,
) -> dict[str, str]:
    """Build only customer-local upstream credential headers."""

    if settings.mode == "private":
        return {}
    if secret_provider is None:
        raise ValueError("Header credential mode requires a secret provider")

    secret = secret_provider.get_secret(settings.secret_ref or "")
    if not secret:
        raise ValueError("Configured upstream secret is empty")
    return {settings.header_name or "": f"{settings.value_prefix}{secret}"}
