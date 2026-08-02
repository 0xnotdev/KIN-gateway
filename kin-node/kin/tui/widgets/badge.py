"""Badge foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import Optional, Union

from textual.widgets import Static

from kin.tui.tokens import validate_widget_role_consumption
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class BadgeWidget(LifecycleWidgetMixin, Static):
    """Badge status counter pill foundation widget.

    Consumes semantic role tokens from tokens.py, not literal colors (§14.5).
    """

    DEFAULT_CSS = """
    BadgeWidget {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable."""
        try:
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def __init__(
        self,
        value: Union[int, str] = 0,
        role: str = "accent.primary",
        label: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        # Validate role token consumption
        self.role = validate_widget_role_consumption(role)
        self.value = value
        self.label = label

    def render(self) -> str:
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            return "[dim]● ...[/dim]"

        if state == WidgetLifecycleState.EMPTY:
            return "[dim]0[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Disabled"
            return f"[dim](DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            return f"[bold {err}]![Err][/bold {err}]"

        if state == WidgetLifecycleState.NARROW:
            return f"● {self.value}"

        val_str = str(self.value)
        lbl_str = f" {self.label}" if self.label else ""
        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""

        return f"[bold {warn}]({val_str}{lbl_str}){focus_mark}[/bold {warn}]"
