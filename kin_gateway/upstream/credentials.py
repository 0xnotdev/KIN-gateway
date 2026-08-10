"""Customer-local secret resolution for protected upstream calls."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from kin_gateway.config import UpstreamCredentialSettings


class UpstreamCredentialError(Exception):
    """Customer-local upstream authority could not be safely supplied."""


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


@dataclass(frozen=True)
class RequestContext:
    """Minimal upstream call context; external authority is deliberately absent."""

    method: str
    url: str


class UpstreamCredentialProvider(Protocol):
    """Supply customer-local authority independently for each upstream call."""

    async def headers_for(
        self, request_context: RequestContext
    ) -> Mapping[str, str]:
        """Return only the headers owned by this credential provider."""


@dataclass(frozen=True)
class NoCredentialProvider:
    """Use a private upstream that requires no application credential."""

    async def headers_for(
        self, request_context: RequestContext
    ) -> Mapping[str, str]:
        return {}


@dataclass(frozen=True)
class StaticHeaderCredentialProvider:
    """Use an explicitly injected customer-owned static header value."""

    header_name: str
    header_value: str

    def __post_init__(self) -> None:
        _validate_header(self.header_name, self.header_value)

    async def headers_for(
        self, request_context: RequestContext
    ) -> Mapping[str, str]:
        return {self.header_name: self.header_value}


@dataclass(frozen=True)
class SecretBackedCredentialProvider:
    """Resolve a configured header value from customer-local secret storage."""

    header_name: str
    secret_ref: str
    value_prefix: str
    secret_provider: SecretProvider

    def __post_init__(self) -> None:
        _validate_header(self.header_name, self.value_prefix or "placeholder")
        if not self.secret_ref:
            raise ValueError("secret_ref must not be empty")

    async def headers_for(
        self, request_context: RequestContext
    ) -> Mapping[str, str]:
        try:
            secret = self.secret_provider.get_secret(self.secret_ref)
        except Exception as exc:
            raise UpstreamCredentialError(
                "Configured upstream secret is unavailable"
            ) from exc
        if not secret:
            raise UpstreamCredentialError("Configured upstream secret is empty")
        value = f"{self.value_prefix}{secret}"
        try:
            _validate_header(self.header_name, value)
        except ValueError as exc:
            raise UpstreamCredentialError(
                "Configured upstream secret is not a valid header value"
            ) from exc
        return {self.header_name: value}


def build_upstream_credential_provider(
    settings: UpstreamCredentialSettings,
    secret_provider: SecretProvider | None,
) -> UpstreamCredentialProvider:
    """Build one of the three supported CP0 credential providers."""

    if settings.mode == "private":
        return NoCredentialProvider()
    if secret_provider is None:
        raise ValueError("Header credential mode requires a secret provider")
    return SecretBackedCredentialProvider(
        header_name=settings.header_name or "",
        secret_ref=settings.secret_ref or "",
        value_prefix=settings.value_prefix,
        secret_provider=secret_provider,
    )


def _validate_header(name: str, value: str) -> None:
    """Reject reserved names and line-breaking values at the provider seam."""

    try:
        UpstreamCredentialSettings(
            mode="header",
            header_name=name,
            secret_ref="validation-only",
        )
    except ValueError as exc:
        raise ValueError("Invalid upstream credential header name") from exc
    if not value or "\r" in value or "\n" in value:
        raise ValueError("Invalid upstream credential header value")
