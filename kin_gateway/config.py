"""Configuration contracts for the customer-local gateway data plane."""

import ipaddress
import re

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_RESERVED_UPSTREAM_HEADERS = {
    "a2a-extensions",
    "a2a-version",
    "connection",
    "content-length",
    "content-type",
    "host",
    "transfer-encoding",
}


class UpstreamCredentialSettings(BaseModel):
    """Select a customer-local credential without storing its secret value."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["private", "header"] = "private"
    header_name: str | None = None
    secret_ref: str | None = None
    value_prefix: str = ""

    @field_validator("header_name")
    @classmethod
    def validate_header_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9-]+", value):
            raise ValueError("header_name must be a valid HTTP token")
        if value.lower() in _RESERVED_UPSTREAM_HEADERS:
            raise ValueError("header_name is reserved by the A2A gateway")
        return value

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "UpstreamCredentialSettings":
        if self.mode == "header" and not self.header_name:
            raise ValueError("header mode requires header_name")
        if self.mode == "header" and not self.secret_ref:
            raise ValueError("header mode requires secret_ref")
        return self


class AgentCardMirrorSettings(BaseModel):
    """Bound the public discovery surface and its private fetch behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approved_skill_ids: frozenset[str] = frozenset()
    trusted_private_hosts: frozenset[str] = frozenset()
    max_response_bytes: int = Field(default=262_144, ge=1, le=4_194_304)
    max_redirects: int = Field(default=3, ge=0, le=10)
    fetch_timeout_seconds: float = Field(default=5.0, ge=0.001, le=60)
    cache_ttl_seconds: float = Field(default=60.0, ge=0, le=3600)


class AdminPlaneSettings(BaseModel):
    """Bootstrap-only private listener and authentication configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bind_host: str = "127.0.0.1"
    port: int = Field(default=9090, ge=1, le=65535)
    authentication: Literal["token", "mtls"] = "token"
    token_secret_ref: str | None = None

    @field_validator("bind_host")
    @classmethod
    def require_private_bind_host(cls, value: str) -> str:
        if value.lower() == "localhost":
            return value
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError(
                "admin bind_host must be localhost or an explicit private IP"
            ) from exc
        if not (
            address.is_private or address.is_loopback or address.is_link_local
        ):
            raise ValueError("admin bind_host must not be publicly routable")
        return value

    @model_validator(mode="after")
    def require_authentication_configuration(self) -> "AdminPlaneSettings":
        if self.authentication == "token" and not self.token_secret_ref:
            raise ValueError("token authentication requires token_secret_ref")
        if self.authentication == "mtls" and self.token_secret_ref is not None:
            raise ValueError("mTLS authentication must not configure a token")
        return self


class GatewaySettings(BaseModel):
    """Minimal CP0 settings for one public endpoint and one A2A upstream."""

    model_config = ConfigDict(frozen=True)

    public_base_url: str = Field(min_length=1)
    bind_host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    upstream_base_url: str = Field(min_length=1)
    upstream_credential: UpstreamCredentialSettings = Field(
        default_factory=UpstreamCredentialSettings
    )
    agent_card: AgentCardMirrorSettings = Field(
        default_factory=AgentCardMirrorSettings
    )

    @field_validator("public_base_url", "upstream_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        """Keep route composition deterministic."""

        normalized = value.rstrip("/")
        try:
            parsed = urlsplit(normalized)
            parsed.port
        except ValueError as exc:
            raise ValueError(
                "base URL must include a valid host and valid numeric port"
            ) from exc
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("base URL must use http or https")
        if not parsed.hostname:
            raise ValueError("base URL must include a host")
        if any(character.isspace() for character in parsed.hostname):
            raise ValueError("base URL host must not contain whitespace")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base URL must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base URL must not contain a query or fragment")
        return normalized
