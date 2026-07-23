"""YAML loader and validator for V1.1 Agent Cards with strict schema and boundary enforcement."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
import yaml
from pydantic import ValidationError

from kin.schemas import AgentCard
from kin.identity.storage import get_agent_credential_service


class CardLoadError(Exception):
    """Raised when an agent card file fails syntax, schema, ID, or boundary validation."""
    pass


def is_v11_card_file(raw_yaml_dict: dict[str, Any]) -> bool:
    """Return True if raw_yaml_dict specifies schema_version == '1.1'."""
    if not isinstance(raw_yaml_dict, dict):
        return False
    return raw_yaml_dict.get("schema_version") == "1.1"


def load_card_file(
    path: Path,
    expected_agent_id: str | None = None,
    profile_name: str | None = None,
) -> AgentCard:
    """Parse YAML, validate V1.1 schema, agent ID, and profile credential reference.

    Args:
        path: Path to the agent YAML file.
        expected_agent_id: Optional expected ID (e.g. filename stem during scan/import).
        profile_name: Active profile name for exact credential_ref matching.

    Returns:
        Validated AgentCard object.

    Raises:
        CardLoadError: If parsing or validation fails.
    """
    if not path.is_file():
        raise CardLoadError(f"File '{path}' does not exist or is not a regular file.")

    try:
        content = path.read_text(encoding="utf-8")
        raw = yaml.safe_load(content)
    except Exception as exc:
        raise CardLoadError(f"File '{path.name}': Malformed YAML syntax - {exc}") from exc

    if not isinstance(raw, dict):
        raise CardLoadError(f"File '{path.name}': Content is not a YAML dictionary.")

    if raw.get("schema_version") != "1.1":
        raise CardLoadError(f"File '{path.name}': Unsupported or missing schema_version (expected '1.1').")

    try:
        card = AgentCard.model_validate(raw)
    except ValidationError as exc:
        raise CardLoadError(f"File '{path.name}': Schema validation error - {exc}") from exc

    # Enforce stem/ID equality if expected_agent_id was specified
    if expected_agent_id is not None and card.id != expected_agent_id:
        raise CardLoadError(
            f"File '{path.name}': Agent ID '{card.id}' does not match expected filename ID '{expected_agent_id}'."
        )

    # Single strict rule for credential_ref validation
    if profile_name is not None and card.adapter.type == "webhook":
        expected_ref = get_agent_credential_service(profile_name, card.id, "webhook_secret")
        if card.adapter.credential_ref != expected_ref:
            raise CardLoadError(
                f"File '{path.name}': Webhook credential_ref '{card.adapter.credential_ref}' "
                f"does not match expected keychain service name '{expected_ref}' for profile '{profile_name}'."
            )

    return card
