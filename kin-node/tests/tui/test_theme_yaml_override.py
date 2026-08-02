"""Unit tests for Validated YAML Theme Override Parser (§14.9 Phase A Build Step 1).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.9 build step 1
- Valid token-only YAML file applies correctly.
- File with an unrecognized key is fully rejected (not partially applied), retains previous theme.
- File with an invalid color value is fully rejected (not partially applied), retains previous theme.
- Arbitrary custom CSS or non-semantic token keys are strictly rejected.
"""

import pytest
from pathlib import Path

from kin.tui.app import KinApp
from kin.tui.theme_yaml import load_theme_yaml_override, parse_theme_yaml_override
from kin.tui.tokens import KIN_GRAPHITE_THEME, REQUIRED_ROLES


def test_valid_yaml_override_applies_correctly():
    """Assert a valid token-only YAML override parses and applies token overrides onto base theme."""
    valid_yaml = """
surface.base: "#111111"
text.primary: "#eeeeee"
accent.primary: "#ff00ff"
state.live: "#00ff00"
"""
    overrides = parse_theme_yaml_override(valid_yaml)
    assert overrides["surface.base"] == "#111111"
    assert overrides["text.primary"] == "#eeeeee"
    assert overrides["accent.primary"] == "#ff00ff"
    assert overrides["state.live"] == "#00ff00"

    theme = load_theme_yaml_override(valid_yaml, theme_name="custom-valid")
    assert theme.name == "custom-valid"
    assert theme.surface_base == "#111111"
    assert theme.text_primary == "#eeeeee"
    assert theme.accent_primary == "#ff00ff"
    assert theme.state_live == "#00ff00"

    # Verify untouched roles remain from base kin-graphite theme
    assert theme.text_secondary == KIN_GRAPHITE_THEME.text_secondary


def test_unrecognized_key_yaml_override_fully_rejected():
    """Assert any unrecognized key (e.g. arbitrary CSS, typo token) causes complete rejection."""
    invalid_yaml = """
surface.base: "#111111"
text.primary: "#eeeeee"
arbitrary_css_rule: "color: red;"
"""
    with pytest.raises(ValueError, match="Unrecognized theme token key"):
        parse_theme_yaml_override(invalid_yaml)

    with pytest.raises(ValueError, match="Unrecognized theme token key"):
        load_theme_yaml_override(invalid_yaml)


def test_invalid_color_value_yaml_override_fully_rejected():
    """Assert any invalid color spec (e.g. not a valid hex string) causes complete rejection."""
    invalid_yaml = """
surface.base: "#111111"
text.primary: "blue-color-name-not-hex"
"""
    with pytest.raises(ValueError, match="Invalid color spec"):
        parse_theme_yaml_override(invalid_yaml)

    with pytest.raises(ValueError, match="Invalid color spec"):
        load_theme_yaml_override(invalid_yaml)


@pytest.mark.asyncio
async def test_colon_theme_yaml_command_in_app(tmp_path):
    """Assert :theme-yaml command loads valid YAML and rejects invalid YAML while retaining last valid theme."""
    # Create valid YAML file
    valid_file = tmp_path / "my_theme.yaml"
    valid_file.write_text("accent.primary: '#00ffff'\nstate.live: '#00ff00'\n", encoding="utf-8")

    # Create invalid YAML file with unrecognized key
    invalid_file = tmp_path / "bad_theme.yaml"
    invalid_file.write_text("accent.primary: '#00ffff'\nunknown_css_prop: '10px'\n", encoding="utf-8")

    app = KinApp(theme_name="nord")
    async with app.run_test(size=(160, 44)) as pilot:
        # Load valid YAML
        app.execute_colon_command(f":theme-yaml {valid_file}")
        await pilot.pause()

        assert app.theme_tokens.accent_primary == "#00ffff"
        assert app.active_error is None

        # Attempt invalid YAML load
        app.execute_colon_command(f":theme-yaml {invalid_file}")
        await pilot.pause()

        # Theme MUST retain last valid state (accent_primary stays #00ffff)
        assert app.theme_tokens.accent_primary == "#00ffff"
        assert app.active_error is not None
        assert "Theme YAML validation error" in app.active_error.what_happened

        await pilot.press("q")
