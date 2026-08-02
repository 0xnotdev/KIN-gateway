"""Theme snapshot and WCAG contrast validation test suite (§14.9 Phase B & E)."""

import pytest
from kin.tui.tokens import (
    _THEME_REGISTRY,
    REQUIRED_ROLES,
    Theme,
    compute_wcag_contrast_ratio,
    get_textual_theme_variables,
    resolve_theme,
    validate_theme,
)


def test_wcag_contrast_ratio_hardcoded_anchor():
    """Assert WCAG contrast ratio for pure white (#ffffff) on pure black (#000000) is exactly 21:1 (Anchor requirement)."""
    ratio = compute_wcag_contrast_ratio("#ffffff", "#000000")
    assert pytest.approx(ratio, 0.01) == 21.0, f"Expected 21.0 contrast ratio, got {ratio}"


def test_all_six_themes_registered_and_valid():
    """Assert all 6 themes (kin-graphite, kin-night, nord, dracula, catppuccin-mocha, high-contrast) are registered and cover all 20 roles."""
    expected_themes = {"kin-graphite", "kin-night", "nord", "dracula", "catppuccin-mocha", "high-contrast"}
    assert set(_THEME_REGISTRY.keys()) == expected_themes

    for theme_name, theme in _THEME_REGISTRY.items():
        validate_theme(theme)
        role_map = theme.get_role_map()
        assert set(role_map.keys()) == REQUIRED_ROLES
        assert theme.name == theme_name


def test_textual_theme_variables_mapping():
    """Assert get_textual_theme_variables maps all 20 roles to $role CSS variable format."""
    graphite = _THEME_REGISTRY["kin-graphite"]
    css_vars = get_textual_theme_variables(graphite)
    assert len(css_vars) == 20
    assert "$surface-base" in css_vars
    assert "$text-primary" in css_vars
    assert css_vars["$surface-base"] == "#16161e"
    assert css_vars["$text-primary"] == "#c0caf5"


def test_high_contrast_wcag_compliance():
    """Assert high-contrast theme satisfies WCAG 2.1 AAA minimum 7:1 contrast for text on base background."""
    hc_theme = _THEME_REGISTRY["high-contrast"]
    ratio = compute_wcag_contrast_ratio(hc_theme.text_primary, hc_theme.surface_base)
    assert ratio >= 7.0, f"High contrast theme text_primary contrast ratio is {ratio}, expected >= 7.0"
