"""Unit tests for TUI token system and glyph registry.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §8.1, §8.2, §11
"""

import pytest

from kin.tui.tokens import (
    GLYPH_REGISTRY,
    KIN_GRAPHITE_THEME,
    RECOGNIZED_THEME_NAMES,
    REQUIRED_ROLES,
    Theme,
    get_glyph,
    resolve_theme,
    validate_theme,
    validate_widget_role_consumption,
)


def test_every_required_role_resolves_under_kin_graphite():
    """Assert all 20 required semantic roles resolve under kin-graphite theme."""
    role_map = KIN_GRAPHITE_THEME.get_role_map()
    assert set(role_map.keys()) == REQUIRED_ROLES
    for role_name in REQUIRED_ROLES:
        val = KIN_GRAPHITE_THEME.get_role_color(role_name)
        assert isinstance(val, str)
        assert len(val) > 0


def test_missing_role_theme_is_rejected_by_validator():
    """Assert validator rejects a Theme missing any required semantic role."""
    # Attempting to validate a mock theme missing diff.context
    incomplete_kwargs = {
        "name": "incomplete",
        "surface_base": "#000",
        "surface_raised": "#000",
        "surface_selected": "#000",
        "text_primary": "#fff",
        "text_secondary": "#fff",
        "text_muted": "#fff",
        "text_inverse": "#000",
        "border_subtle": "#000",
        "border_focus": "#000",
        "border_strong": "#000",
        "state_live": "#000",
        "state_waiting": "#000",
        "state_approval": "#000",
        "state_error": "#000",
        "accent_primary": "#000",
        "accent_secondary": "#000",
        "accent_highlight": "#000",
        "diff_add": "#000",
        "diff_remove": "#000",
        "diff_context": "",  # Empty color
    }
    theme = Theme(**incomplete_kwargs)
    with pytest.raises(ValueError, match="empty or invalid color value"):
        validate_theme(theme)


def test_unimplemented_theme_name_falls_back_to_kin_graphite():
    """Assert requesting recognized unimplemented themes falls back to kin-graphite without raising."""
    unimplemented_names = RECOGNIZED_THEME_NAMES - {"kin-graphite"}
    assert len(unimplemented_names) == 5

    for theme_name in unimplemented_names:
        res = resolve_theme(theme_name)
        assert res.theme == KIN_GRAPHITE_THEME
        assert res.requested_name == theme_name
        assert res.is_fallback is True
        assert res.fallback_reason is not None
        assert "deferred to T7" in res.fallback_reason


def test_widget_role_consumption_validator():
    """Assert widget consumption layer rejects literal colors and unregistered role names."""
    # Registered role name passes
    assert validate_widget_role_consumption("surface.base") == "surface.base"
    assert validate_widget_role_consumption("state.live") == "state.live"

    # Literal colors fail
    with pytest.raises(ValueError, match="Literal color"):
        validate_widget_role_consumption("#1a1b26")

    with pytest.raises(ValueError, match="Literal color"):
        validate_widget_role_consumption("rgb(255, 0, 0)")

    # Unregistered role fails
    with pytest.raises(ValueError, match="Unregistered role name"):
        validate_widget_role_consumption("surface.nonexistent")


def test_glyph_registry_ascii_fallbacks():
    """Assert every registered glyph has an explicit ASCII fallback."""
    expected_glyphs = {
        "●": "*",
        "✓": "OK",
        "!": "!",
        "→": "->",
        "○": "o",
        "◌": ".",
    }
    for symbol, expected_ascii in expected_glyphs.items():
        assert symbol in GLYPH_REGISTRY
        assert get_glyph(symbol, ascii_fallback=False) == symbol
        assert get_glyph(symbol, ascii_fallback=True) == expected_ascii

    # Unregistered glyph raises KeyError
    with pytest.raises(KeyError, match="not registered"):
        get_glyph("▲")
