"""Configuration contracts for the customer-local gateway data plane."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GatewaySettings(BaseModel):
    """Minimal CP0 settings for one public endpoint and one A2A upstream."""

    model_config = ConfigDict(frozen=True)

    public_base_url: str = Field(min_length=1)
    upstream_base_url: str = Field(min_length=1)

    @field_validator("public_base_url", "upstream_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        """Keep route composition deterministic."""

        return value.rstrip("/")

