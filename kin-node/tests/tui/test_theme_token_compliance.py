"""Systemic Theme Token Compliance Scanner (§14.9 Phase A).

Validates the theme infrastructure is complete and correct:
1. All 6 spec themes are registered and cover all 20 required roles.
2. DEFAULT_CSS blocks in widgets do NOT contain hardcoded hex colors
   (they should use Textual CSS variables like $surface-base).
3. The get_role_color() API resolves all 20 roles for every theme.

Note: Rich markup in widget render() methods (e.g. [bold cyan]) is
exempted because Rich's parser only understands actual color names,
not semantic tokens. Theme switching for rendered content is handled
via Textual CSS variables and the non-teardown refresh mechanism.
"""

import re
from pathlib import Path
import pytest

from kin.tui.tokens import (
    _THEME_REGISTRY,
    RECOGNIZED_THEME_NAMES,
    REQUIRED_ROLES,
    validate_theme,
)

KIN_TUI_DIR = Path(__file__).resolve().parent.parent.parent / "kin" / "tui"

EXEMPT_FILES = {
    "tokens.py",
    "palette.py",
}

# Regex matching hardcoded hex colors inside DEFAULT_CSS blocks
HARDCODED_HEX_IN_CSS = re.compile(r"#[0-9a-fA-F]{3,6}")


def extract_css_blocks(content: str) -> list[str]:
    """Extract all DEFAULT_CSS multiline string blocks from file content."""
    blocks: list[str] = []
    for match in re.finditer(r'DEFAULT_CSS\s*=\s*"""([\s\S]*?)"""', content):
        blocks.append(match.group(1))
    for match in re.finditer(r"DEFAULT_CSS\s*=\s*'''([\s\S]*?)'''", content):
        blocks.append(match.group(1))
    return blocks


def test_all_six_themes_cover_required_roles():
    """Assert all 6 spec-required themes are registered and each covers all 20 semantic roles."""
    assert len(_THEME_REGISTRY) == 6
    assert set(_THEME_REGISTRY.keys()) == RECOGNIZED_THEME_NAMES

    for name, theme in _THEME_REGISTRY.items():
        role_map = theme.get_role_map()
        missing = REQUIRED_ROLES - set(role_map.keys())
        assert not missing, f"Theme '{name}' missing roles: {missing}"
        # Also validate no empty color values
        validate_theme(theme)


def test_default_css_blocks_use_variables_not_hex():
    """Assert DEFAULT_CSS blocks in widget files use Textual CSS variables, not hardcoded hex colors."""
    violations: list[str] = []

    for py_file in KIN_TUI_DIR.glob("**/*.py"):
        if py_file.name in EXEMPT_FILES:
            continue

        try:
            content = py_file.read_text(encoding="utf-8")
        except Exception:
            continue

        css_blocks = extract_css_blocks(content)
        for block in css_blocks:
            for line_idx, line in enumerate(block.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("/*") or stripped.startswith("*"):
                    continue
                matches = HARDCODED_HEX_IN_CSS.findall(line)
                for hex_val in matches:
                    rel_path = py_file.relative_to(KIN_TUI_DIR)
                    violations.append(
                        f"{rel_path}: DEFAULT_CSS contains hardcoded hex '{hex_val}' — "
                        f"use Textual CSS variable instead"
                    )

    assert not violations, (
        f"Found {len(violations)} hardcoded hex colors in DEFAULT_CSS blocks:\n"
        + "\n".join(violations)
    )


def test_get_role_color_resolves_all_roles_all_themes():
    """Assert get_role_color() returns a valid hex string for every role across all themes."""
    hex_pattern = re.compile(r"^#[0-9a-fA-F]{6}$")

    for name, theme in _THEME_REGISTRY.items():
        for role in REQUIRED_ROLES:
            color = theme.get_role_color(role)
            assert hex_pattern.match(color), (
                f"Theme '{name}' role '{role}' returned invalid color: {color}"
            )
