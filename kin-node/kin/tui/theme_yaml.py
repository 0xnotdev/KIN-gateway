"""Validated YAML Theme Override Parser for KIN V1.1 TUI (§14.9 Phase A Build Step 1).

Parses and validates user-supplied YAML files containing semantic token role overrides.
Enforces strict validation rules per spec:
1. ONLY known semantic token role names (§8.1) are accepted (exact match on REQUIRED_ROLES).
2. ONLY valid color specifications (6-char or 3-char hex strings) are accepted.
3. On ANY validation error (unrecognized key, invalid color spec), the entire file is rejected
   (no partial-application state) and a clear ValueError is raised.
"""

import re
from pathlib import Path
from typing import Dict, Union, Optional

import yaml

from kin.tui.tokens import (
    KIN_GRAPHITE_THEME,
    REQUIRED_ROLES,
    Theme,
    validate_theme,
)

HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def _normalize_role_name(raw_key: str) -> str:
    """Convert underscore role names (e.g., surface_base) to dot notation (surface.base)."""
    normalized = raw_key.replace("_", ".")
    return normalized


def parse_theme_yaml_override(yaml_content: str) -> Dict[str, str]:
    """Parse a YAML string containing semantic token role overrides.

    Raises ValueError if:
    - YAML syntax is invalid
    - Root YAML structure is not a dictionary
    - Any key is not a recognized semantic token role name in REQUIRED_ROLES
    - Any value is not a valid hex color string (#rgb or #rrggbb)
    """
    try:
        data = yaml.safe_load(yaml_content)
    except Exception as exc:
        raise ValueError(f"Invalid YAML syntax: {exc}")

    if not isinstance(data, dict):
        raise ValueError("Theme YAML override must be a key-value dictionary of semantic roles.")

    if not data:
        raise ValueError("Theme YAML override dictionary cannot be empty.")

    overrides: Dict[str, str] = {}

    for raw_key, raw_val in data.items():
        if not isinstance(raw_key, str):
            raise ValueError(f"Unrecognized theme key type '{type(raw_key).__name__}': keys must be strings.")

        role_key = _normalize_role_name(raw_key.strip())

        # Strict validation rule 1: ONLY known semantic token role names
        if role_key not in REQUIRED_ROLES:
            raise ValueError(
                f"Unrecognized theme token key '{raw_key}' (normalized: '{role_key}'). "
                f"Arbitrary custom CSS or unknown properties are not supported. "
                f"Valid tokens are: {sorted(list(REQUIRED_ROLES))}"
            )

        if not isinstance(raw_val, str):
            raise ValueError(f"Invalid color value type for '{role_key}': must be a color spec string.")

        color_val = raw_val.strip()

        # Strict validation rule 2: ONLY valid hex color specs
        if not HEX_COLOR_PATTERN.match(color_val):
            raise ValueError(
                f"Invalid color spec '{raw_val}' for token '{role_key}'. "
                f"Must be a valid hex color string (e.g. #1a1b26 or #fff)."
            )

        overrides[role_key] = color_val

    return overrides


def load_theme_yaml_override(
    source: Union[str, Path],
    base_theme: Optional[Theme] = None,
    theme_name: str = "custom-yaml",
) -> Theme:
    """Load a YAML theme override from a file path or string content and build a new Theme.

    Combines overrides with base_theme (defaults to kin-graphite).
    Validates the complete Theme object before returning.
    Raises ValueError on ANY validation failure.
    """
    if isinstance(source, Path) or (isinstance(source, str) and ("\n" not in source and Path(source).exists())):
        path = Path(source)
        if not path.exists():
            raise ValueError(f"Theme YAML file not found at: {path}")
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise ValueError(f"Failed to read theme YAML file '{path}': {exc}")
    else:
        content = str(source)

    overrides = parse_theme_yaml_override(content)

    base = base_theme or KIN_GRAPHITE_THEME
    role_map = base.get_role_map()

    # Apply overrides onto base role map
    role_map.update(overrides)

    # Convert dot-notation keys back to Theme class field kwargs (underscore notation)
    theme_kwargs = {"name": theme_name}
    for role_dot, color in role_map.items():
        field_name = role_dot.replace(".", "_")
        theme_kwargs[field_name] = color

    new_theme = Theme(**theme_kwargs)
    validate_theme(new_theme)
    return new_theme
