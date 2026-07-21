"""YAML agent roster loader and validator for KIN profile agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import yaml
from pydantic import BaseModel, ValidationError, model_validator


class AgentLoadingError(Exception):
    """Raised when loading or validating an agent configuration fails."""
    pass


class AgentConfig(BaseModel):
    name: str
    backend_type: str  # Must be 'embedded' or 'webhook'
    provider: Optional[str] = None
    model: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    personality: Optional[str] = None
    tools: Optional[list[str]] = None
    boundaries: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_backend_fields(self) -> AgentConfig:
        if self.backend_type == "embedded":
            if not self.provider:
                raise ValueError("field 'provider' is required when backend_type is 'embedded'")
            if not self.model:
                raise ValueError("field 'model' is required when backend_type is 'embedded'")
        elif self.backend_type == "webhook":
            if not self.webhook_url:
                raise ValueError("field 'webhook_url' is required when backend_type is 'webhook'")
            if not self.webhook_secret:
                raise ValueError("field 'webhook_secret' is required when backend_type is 'webhook'")
        else:
            raise ValueError("backend_type must be either 'embedded' or 'webhook'")
        return self


def load_agent_file(path: Path) -> AgentConfig:
    """Loads and validates a single agent YAML file.
    
    Raises AgentLoadingError with details on malformed YAML or validation issues.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise AgentLoadingError(f"Malformed YAML in {path.name}: {e}")
    except Exception as e:
        raise AgentLoadingError(f"Failed to read file {path.name}: {e}")

    if not isinstance(data, dict):
        raise AgentLoadingError(f"YAML content in {path.name} must be a dictionary")

    # Check for name field early to give a clear error
    if "name" not in data or not data["name"]:
        raise AgentLoadingError(f"Missing 'name' in {path.name}")

    try:
        return AgentConfig(**data)
    except ValidationError as e:
        errors = "; ".join([f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()])
        raise AgentLoadingError(f"Validation error in {path.name}: {errors}")


def load_agent_roster(profile: str) -> dict[str, AgentConfig]:
    """Loads all agent YAML profiles for the given profile name.
    
    If the agents directory doesn't exist or is empty, returns an empty dict.
    Raises AgentLoadingError if any file is malformed or invalid.
    """
    profile_dir = Path.home() / ".kin" / "profiles" / profile
    agents_dir = profile_dir / "agents"
    if not agents_dir.is_dir():
        return {}

    roster = {}
    # Find all yaml/yml files
    for ext in ("*.yaml", "*.yml"):
        for file_path in sorted(agents_dir.glob(ext)):
            config = load_agent_file(file_path)
            if config.name in roster:
                raise AgentLoadingError(f"Duplicate agent name '{config.name}' found in profile '{profile}'")
            roster[config.name] = config

    return roster
