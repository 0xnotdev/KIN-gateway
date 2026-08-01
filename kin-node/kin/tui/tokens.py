"""Design tokens, theme definitions, theme validator, and glyph registry for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §8.1, §8.2, §11
"""

from dataclasses import dataclass, fields
from typing import Dict, List, Optional, Set, Tuple

# All 20 semantic roles required by spec §8.1
REQUIRED_ROLES: Set[str] = {
    "surface.base",
    "surface.raised",
    "surface.selected",
    "text.primary",
    "text.secondary",
    "text.muted",
    "text.inverse",
    "border.subtle",
    "border.focus",
    "border.strong",
    "state.live",
    "state.waiting",
    "state.approval",
    "state.error",
    "accent.primary",
    "accent.secondary",
    "accent.highlight",
    "diff.add",
    "diff.remove",
    "diff.context",
}

RECOGNIZED_THEME_NAMES: Set[str] = {
    "kin-graphite",
    "kin-night",
    "nord",
    "dracula",
    "catppuccin-mocha",
    "high-contrast",
}


@dataclass(frozen=True)
class Theme:
    """Dataclass mapping every semantic role to a concrete color value."""

    name: str
    surface_base: str
    surface_raised: str
    surface_selected: str
    text_primary: str
    text_secondary: str
    text_muted: str
    text_inverse: str
    border_subtle: str
    border_focus: str
    border_strong: str
    state_live: str
    state_waiting: str
    state_approval: str
    state_error: str
    accent_primary: str
    accent_secondary: str
    accent_highlight: str
    diff_add: str
    diff_remove: str
    diff_context: str

    def get_role_map(self) -> Dict[str, str]:
        """Map role dot-notation strings to their color values."""
        return {
            "surface.base": self.surface_base,
            "surface.raised": self.surface_raised,
            "surface.selected": self.surface_selected,
            "text.primary": self.text_primary,
            "text.secondary": self.text_secondary,
            "text.muted": self.text_muted,
            "text.inverse": self.text_inverse,
            "border.subtle": self.border_subtle,
            "border.focus": self.border_focus,
            "border.strong": self.border_strong,
            "state.live": self.state_live,
            "state.waiting": self.state_waiting,
            "state.approval": self.state_approval,
            "state.error": self.state_error,
            "accent.primary": self.accent_primary,
            "accent.secondary": self.accent_secondary,
            "accent.highlight": self.accent_highlight,
            "diff.add": self.diff_add,
            "diff.remove": self.diff_remove,
            "diff.context": self.diff_context,
        }

    def get_role_color(self, role_name: str) -> str:
        """Resolve a semantic role name to its color value, validating role existence."""
        if role_name not in REQUIRED_ROLES:
            raise KeyError(f"Invalid semantic role name '{role_name}'. Must be one of {sorted(REQUIRED_ROLES)}")
        return self.get_role_map()[role_name]


# kin-graphite default theme (§8.2: graphite/indigo surfaces, mint live state, violet focus)
KIN_GRAPHITE_THEME = Theme(
    name="kin-graphite",
    surface_base="#16161e",
    surface_raised="#1a1b26",
    surface_selected="#292e42",
    text_primary="#c0caf5",
    text_secondary="#a9b1d6",
    text_muted="#565f89",
    text_inverse="#15161e",
    border_subtle="#27a1b9",
    border_focus="#bb9af7",
    border_strong="#7aa2f7",
    state_live="#73daca",
    state_waiting="#e0af68",
    state_approval="#ff9e64",
    state_error="#f7768e",
    accent_primary="#bb9af7",
    accent_secondary="#7aa2f7",
    accent_highlight="#7dcfff",
    diff_add="#41a6b5",
    diff_remove="#f7768e",
    diff_context="#565f89",
)

# Registry of implemented themes
_THEME_REGISTRY: Dict[str, Theme] = {
    "kin-graphite": KIN_GRAPHITE_THEME,
}


@dataclass
class ThemeResolutionResult:
    """Result of resolving a requested theme, tracking fallback if applicable."""

    theme: Theme
    requested_name: str
    is_fallback: bool
    fallback_reason: Optional[str] = None


def resolve_theme(theme_name: str) -> ThemeResolutionResult:
    """Resolve a theme by name.

    If theme_name is recognized but not implemented yet (kin-night, nord, dracula,
    catppuccin-mocha, high-contrast), falls back to kin-graphite and records requested_name.
    """
    if theme_name in _THEME_REGISTRY:
        return ThemeResolutionResult(
            theme=_THEME_REGISTRY[theme_name],
            requested_name=theme_name,
            is_fallback=False,
        )
    elif theme_name in RECOGNIZED_THEME_NAMES:
        return ThemeResolutionResult(
            theme=KIN_GRAPHITE_THEME,
            requested_name=theme_name,
            is_fallback=True,
            fallback_reason=f"Theme '{theme_name}' is recognized but deferred to T7; fell back to kin-graphite.",
        )
    else:
        # Unknown theme name falls back to kin-graphite with fallback flag set
        return ThemeResolutionResult(
            theme=KIN_GRAPHITE_THEME,
            requested_name=theme_name,
            is_fallback=True,
            fallback_reason=f"Theme '{theme_name}' is unrecognized; fell back to kin-graphite.",
        )


def validate_theme(theme: Theme) -> None:
    """Validate that a Theme instance covers all required semantic roles.

    Raises ValueError if any role is missing or invalid.
    """
    role_map = theme.get_role_map()
    missing_roles = REQUIRED_ROLES - set(role_map.keys())
    if missing_roles:
        raise ValueError(f"Theme '{theme.name}' is missing required roles: {sorted(missing_roles)}")

    for role_name, color_val in role_map.items():
        if not color_val or not isinstance(color_val, str):
            raise ValueError(f"Theme '{theme.name}' role '{role_name}' has empty or invalid color value: {color_val!r}")


def validate_widget_role_consumption(role_or_color: str) -> str:
    """Widget-level assertion validating that widgets consume role names, never literal colors.

    Raises ValueError if a literal color or unrecognized role name is passed.
    """
    if role_or_color.startswith("#") or role_or_color.startswith("rgb") or role_or_color.startswith("hsl"):
        raise ValueError(f"Literal color '{role_or_color}' passed to widget. Widgets must consume semantic role names.")
    if role_or_color not in REQUIRED_ROLES:
        raise ValueError(f"Unregistered role name '{role_or_color}'. Must be one of {sorted(REQUIRED_ROLES)}")
    return role_or_color


# Glyph Registry with ASCII fallbacks (spec §11 + implied working/idle state glyphs)
GLYPH_REGISTRY: Dict[str, str] = {
    "●": "*",
    "✓": "OK",
    "!": "!",
    "→": "->",
    "○": "o",
    "◌": ".",
    "✖": "X",
    "▲": "^",
}


def get_glyph(glyph_symbol: str, ascii_fallback: bool = False) -> str:
    """Resolve a glyph symbol, returning ASCII fallback if ascii_fallback mode is True."""
    if glyph_symbol not in GLYPH_REGISTRY:
        raise KeyError(f"Glyph '{glyph_symbol}' is not registered in GLYPH_REGISTRY.")
    if ascii_fallback:
        return GLYPH_REGISTRY[glyph_symbol]
    return glyph_symbol
