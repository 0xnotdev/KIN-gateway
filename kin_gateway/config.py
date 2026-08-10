"""Configuration contracts for the customer-local gateway data plane."""

import re

from typing import Literal

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


class GatewaySettings(BaseModel):
    """Minimal CP0 settings for one public endpoint and one A2A upstream."""

    model_config = ConfigDict(frozen=True)

    public_base_url: str = Field(min_length=1)
    upstream_base_url: str = Field(min_length=1)
    upstream_credential: UpstreamCredentialSettings = Field(
        default_factory=UpstreamCredentialSettings
    )

    @field_validator("public_base_url", "upstream_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        """Keep route composition deterministic."""

        return value.rstrip("/")
