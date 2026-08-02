"""Settings Screen & Preferences Modal for KIN V1.1 TUI (§14.9 Phase B & E).

Provides user controls for Theme selection, Color Depth override,
ASCII Fallback Mode, and Reduced Motion.
"""

from typing import Callable, Optional
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Header, Footer, Label, Select, Static

from kin.tui.tokens import RECOGNIZED_THEME_NAMES, _THEME_REGISTRY
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


THEME_OPTIONS = [
    ("KIN Graphite (Default)", "kin-graphite"),
    ("KIN Night", "kin-night"),
    ("Nord", "nord"),
    ("Dracula", "dracula"),
    ("Catppuccin Mocha", "catppuccin-mocha"),
    ("High Contrast (WCAG AAA)", "high-contrast"),
]

COLOR_DEPTH_OPTIONS = [
    ("Auto (System Default)", "auto"),
    ("Truecolor (24-bit)", "truecolor"),
    ("256 Colors (8-bit)", "256"),
    ("16 Colors (4-bit)", "16"),
    ("Monochrome (1-bit)", "monochrome"),
]


class SettingsScreenWidget(Static, LifecycleWidgetMixin):
    """Inline settings widget displaying design preferences and accessibility controls."""

    DEFAULT_CSS = """
    SettingsScreenWidget {
        width: 100%;
        height: 100%;
        background: $surface-base;
        color: $text-primary;
        padding: 1 2;
    }
    .settings-section {
        margin-bottom: 1;
        border: solid $border-subtle;
        padding: 1 2;
    }
    .settings-title {
        text-style: bold;
        color: $accent-primary;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        current_theme: str = "kin-graphite",
        color_depth: str = "auto",
        ascii_mode: bool = False,
        reduced_motion: bool = False,
        on_preference_change: Optional[Callable[[str, object], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        LifecycleWidgetMixin.__init__(self, **kwargs)
        self.current_theme = current_theme
        self.color_depth = color_depth
        self.ascii_mode = ascii_mode
        self.reduced_motion = reduced_motion
        self.on_preference_change = on_preference_change

    def compose(self) -> ComposeResult:
        yield Label("KIN SYSTEM PREFERENCES & ACCESSIBILITY", classes="settings-title")

        with Vertical(classes="settings-section"):
            yield Label("Theme Selection (§8.1):")
            yield Select(
                THEME_OPTIONS,
                value=self.current_theme,
                id="select-theme",
            )

        with Vertical(classes="settings-section"):
            yield Label("Color Depth Override (§8.2):")
            yield Select(
                COLOR_DEPTH_OPTIONS,
                value=self.color_depth,
                id="select-color-depth",
            )

        with Vertical(classes="settings-section"):
            yield Checkbox(
                "ASCII Fallback Mode (ASCII-only glyphs)",
                value=self.ascii_mode,
                id="check-ascii-mode",
            )
            yield Checkbox(
                "Reduced Motion (Disable dynamic transitions/spinners)",
                value=self.reduced_motion,
                id="check-reduced-motion",
            )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "select-theme" and event.value != Select.BLANK:
            self.current_theme = str(event.value)
            if self.on_preference_change:
                self.on_preference_change("theme", self.current_theme)
        elif event.select.id == "select-color-depth" and event.value != Select.BLANK:
            self.color_depth = str(event.value)
            if self.on_preference_change:
                self.on_preference_change("color_depth", self.color_depth)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "check-ascii-mode":
            self.ascii_mode = event.value
            if self.on_preference_change:
                self.on_preference_change("ascii_fallback", self.ascii_mode)
        elif event.checkbox.id == "check-reduced-motion":
            self.reduced_motion = event.value
            if self.on_preference_change:
                self.on_preference_change("reduced_motion", self.reduced_motion)


class SettingsModal(ModalScreen[None]):
    """Modal overlay for quick preference adjustment."""

    DEFAULT_CSS = """
    SettingsModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    #settings-container {
        width: 60;
        height: auto;
        background: $surface-raised;
        border: thick $border-focus;
        padding: 1 2;
    }
    """

    def __init__(
        self,
        current_theme: str = "kin-graphite",
        color_depth: str = "auto",
        ascii_mode: bool = False,
        reduced_motion: bool = False,
    ):
        super().__init__()
        self.current_theme = current_theme
        self.color_depth = color_depth
        self.ascii_mode = ascii_mode
        self.reduced_motion = reduced_motion

    def compose(self) -> ComposeResult:
        with Container(id="settings-container"):
            yield SettingsScreenWidget(
                current_theme=self.current_theme,
                color_depth=self.color_depth,
                ascii_mode=self.ascii_mode,
                reduced_motion=self.reduced_motion,
                on_preference_change=self._handle_preference_change,
            )
            yield Button("Close", id="btn-close-settings", variant="primary")

    def _handle_preference_change(self, pref_key: str, value: object) -> None:
        if hasattr(self.app, "set_preference"):
            getattr(self.app, "set_preference")(pref_key, value)
        elif pref_key == "theme" and hasattr(self.app, "set_theme"):
            getattr(self.app, "set_theme")(str(value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close-settings":
            self.dismiss()
