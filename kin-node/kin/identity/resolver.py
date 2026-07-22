"""Production profile context resolver and boundary security manager."""

from __future__ import annotations

import re
from pathlib import Path

from kin.identity.storage import (
    get_llm_api_key_service,
    get_private_key_service,
    get_x25519_private_key_service,
)

PROFILE_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


class AccessBoundaryViolation(Exception):
    """Raised when an active profile context attempts to access another profile's resources or escape boundaries."""
    pass


class ProfileContextResolver:
    """Production application-level profile boundary resolver."""

    def __init__(self, active_profile: str, root_dir: Path | str):
        if not PROFILE_NAME_REGEX.match(active_profile):
            raise ValueError(f"Invalid profile name '{active_profile}'. Must match [a-zA-Z0-9_-]+.")

        self.active_profile = active_profile
        self.root_dir = Path(root_dir).resolve()
        self.profile_dir = (self.root_dir / "profiles" / active_profile).resolve()

    def resolve_profile_path(self, target_profile: str, relative_path: str = "") -> Path:
        """Resolve path strictly within the active profile boundary using Path.is_relative_to()."""
        if not PROFILE_NAME_REGEX.match(target_profile):
            raise ValueError(f"Invalid target profile name '{target_profile}'.")

        if target_profile != self.active_profile:
            raise AccessBoundaryViolation(
                f"Active profile '{self.active_profile}' is forbidden from accessing target profile '{target_profile}'."
            )

        resolved = (self.profile_dir / relative_path).resolve()
        if not resolved.is_relative_to(self.profile_dir):
            raise AccessBoundaryViolation(
                f"Path traversal detected: '{resolved}' is not within profile directory '{self.profile_dir}'."
            )
        return resolved

    def resolve_keychain_service(self, target_profile: str, service_type: str, provider: str | None = None) -> str:
        """Resolve keychain service strictly within active profile boundary."""
        if not PROFILE_NAME_REGEX.match(target_profile):
            raise ValueError(f"Invalid target profile name '{target_profile}'.")

        if target_profile != self.active_profile:
            raise AccessBoundaryViolation(
                f"Active profile '{self.active_profile}' is forbidden from accessing keychain service of '{target_profile}'."
            )

        if service_type == "private_key":
            return get_private_key_service(self.active_profile)
        elif service_type == "x25519_private_key":
            return get_x25519_private_key_service(self.active_profile)
        elif service_type == "llm_api_key" and provider:
            return get_llm_api_key_service(self.active_profile, provider)
        else:
            raise ValueError(f"Unknown service type '{service_type}'.")
