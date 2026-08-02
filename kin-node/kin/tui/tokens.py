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

KIN_NIGHT_THEME = Theme(
    name="kin-night",
    surface_base="#0d0e15",
    surface_raised="#13141f",
    surface_selected="#1f2335",
    text_primary="#a9b1d6",
    text_secondary="#9aa5ce",
    text_muted="#565f89",
    text_inverse="#0d0e15",
    border_subtle="#1a1b26",
    border_focus="#9d7cd8",
    border_strong="#7aa2f7",
    state_live="#41a6b5",
    state_waiting="#0db9d7",
    state_approval="#ff9e64",
    state_error="#f7768e",
    accent_primary="#9d7cd8",
    accent_secondary="#7aa2f7",
    accent_highlight="#7dcfff",
    diff_add="#41a6b5",
    diff_remove="#f7768e",
    diff_context="#565f89",
)

NORD_THEME = Theme(
    name="nord",
    surface_base="#2e3440",
    surface_raised="#3b4252",
    surface_selected="#434c5e",
    text_primary="#eceff4",
    text_secondary="#e5e9f0",
    text_muted="#d8dee9",
    text_inverse="#2e3440",
    border_subtle="#4c566a",
    border_focus="#88c0d0",
    border_strong="#81a1c1",
    state_live="#a3be8c",
    state_waiting="#ebcb8b",
    state_approval="#d08770",
    state_error="#bf616a",
    accent_primary="#88c0d0",
    accent_secondary="#81a1c1",
    accent_highlight="#5e81ac",
    diff_add="#a3be8c",
    diff_remove="#bf616a",
    diff_context="#4c566a",
)

DRACULA_THEME = Theme(
    name="dracula",
    surface_base="#282a36",
    surface_raised="#44475a",
    surface_selected="#6272a4",
    text_primary="#f8f8f2",
    text_secondary="#bfbfbf",
    text_muted="#6272a4",
    text_inverse="#282a36",
    border_subtle="#44475a",
    border_focus="#bd93f9",
    border_strong="#ff79c6",
    state_live="#50fa7b",
    state_waiting="#f1fa8c",
    state_approval="#ffb86c",
    state_error="#ff5555",
    accent_primary="#bd93f9",
    accent_secondary="#ff79c6",
    accent_highlight="#8be9fd",
    diff_add="#50fa7b",
    diff_remove="#ff5555",
    diff_context="#6272a4",
)

CATPPUCCIN_MOCHA_THEME = Theme(
    name="catppuccin-mocha",
    surface_base="#1e1e2e",
    surface_raised="#181825",
    surface_selected="#313244",
    text_primary="#cdd6f4",
    text_secondary="#bac2de",
    text_muted="#6c7086",
    text_inverse="#11111b",
    border_subtle="#45475a",
    border_focus="#cba6f7",
    border_strong="#89b4fa",
    state_live="#a6e3a1",
    state_waiting="#f9e2af",
    state_approval="#fab387",
    state_error="#f38ba8",
    accent_primary="#cba6f7",
    accent_secondary="#89b4fa",
    accent_highlight="#89dceb",
    diff_add="#a6e3a1",
    diff_remove="#f38ba8",
    diff_context="#6c7086",
)

HIGH_CONTRAST_THEME = Theme(
    name="high-contrast",
    surface_base="#000000",
    surface_raised="#121212",
    surface_selected="#242424",
    text_primary="#ffffff",
    text_secondary="#e0e0e0",
    text_muted="#a0a0a0",
    text_inverse="#000000",
    border_subtle="#808080",
    border_focus="#ffff00",
    border_strong="#ffffff",
    state_live="#00ff00",
    state_waiting="#ffff00",
    state_approval="#ff8000",
    state_error="#ff0000",
    accent_primary="#ffff00",
    accent_secondary="#00ffff",
    accent_highlight="#ffffff",
    diff_add="#00ff00",
    diff_remove="#ff0000",
    diff_context="#808080",
)

# Registry of implemented themes
_THEME_REGISTRY: Dict[str, Theme] = {
    "kin-graphite": KIN_GRAPHITE_THEME,
    "kin-night": KIN_NIGHT_THEME,
    "nord": NORD_THEME,
    "dracula": DRACULA_THEME,
    "catppuccin-mocha": CATPPUCCIN_MOCHA_THEME,
    "high-contrast": HIGH_CONTRAST_THEME,
}


def get_textual_theme_variables(theme: Theme) -> Dict[str, str]:
    """Map all 20 semantic roles to Textual CSS variable names (e.g. $surface-base)."""
    role_map = theme.get_role_map()
    return {
        f"${role.replace('.', '-')}": color
        for role, color in role_map.items()
    }


def compute_relative_luminance(hex_color: str) -> float:
    """Compute WCAG 2.1 relative luminance for a hex color string."""
    clean_hex = hex_color.lstrip("#")
    if len(clean_hex) == 3:
        clean_hex = "".join([c * 2 for c in clean_hex])
    r_255 = int(clean_hex[0:2], 16) / 255.0
    g_255 = int(clean_hex[2:4], 16) / 255.0
    b_255 = int(clean_hex[4:6], 16) / 255.0

    def convert_c(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r_lum = convert_c(r_255)
    g_lum = convert_c(g_255)
    b_lum = convert_c(b_255)

    return 0.2126 * r_lum + 0.7152 * g_lum + 0.0722 * b_lum


def compute_wcag_contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """Compute WCAG 2.1 contrast ratio between two hex colors (1.0 to 21.0)."""
    l1 = compute_relative_luminance(fg_hex)
    l2 = compute_relative_luminance(bg_hex)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


@dataclass
class ThemeResolutionResult:
    """Result of resolving a requested theme, tracking fallback if applicable."""

    theme: Theme
    requested_name: str
    is_fallback: bool
    fallback_reason: Optional[str] = None


def resolve_theme(theme_name: str) -> ThemeResolutionResult:
    """Resolve a theme by name."""
    if theme_name in _THEME_REGISTRY:
        return ThemeResolutionResult(
            theme=_THEME_REGISTRY[theme_name],
            requested_name=theme_name,
            is_fallback=False,
        )
    else:
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
