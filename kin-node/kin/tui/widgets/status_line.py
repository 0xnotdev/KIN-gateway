"""StatusLine foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime
from typing import Optional, Union

from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.tokens import get_glyph, validate_widget_role_consumption
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class StatusLineWidget(LifecycleWidgetMixin, Static):
    """StatusLine 1-line contextual status foundation widget.

    Takes an injectable clock ('now') for deterministic timestamp formatting without wall-clock coupling (§14.5).
    Sanitizes free-form status message text against secret or local path leakage.
    """

    DEFAULT_CSS = """
    StatusLineWidget {
        width: 100%;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        message: str = "System Ready",
        glyph_symbol: str = "✓",
        role: str = "state.live",
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.message = message
        self.glyph_symbol = glyph_symbol
        self.role = validate_widget_role_consumption(role)

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable."""
        try:
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def render(self) -> str:
        state = self.lifecycle_state
        warn = self._c("state.waiting", "#e0af68")
        err = self._c("state.error", "#f7768e")
        ok = self._c("state.live", "#73daca")

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            time_str = self.last_updated_at.strftime("%H:%M:%S") if self.last_updated_at else "00:00:00"
            return f"[dim]{glyph} Loading status... ({time_str})[/dim]"

        if state == WidgetLifecycleState.EMPTY:
            return "[dim]Status: Idle / No Activity[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Disabled by policy"
            return f"[dim]Status Offline | [{warn}]Reason: {reason}[/{warn}][/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} Status Error: Connection interrupted. Press [Retry].[/bold {err}]"

        scrubbed_msg = redact_ui_text(self.message)

        if state == WidgetLifecycleState.NARROW:
            glyph = get_glyph(self.glyph_symbol)
            return f"{glyph} {scrubbed_msg[:18]}"

        glyph = get_glyph(self.glyph_symbol)
        time_str = self.last_updated_at.strftime("%H:%M:%S") if self.last_updated_at else ""
        time_part = f" | [dim]{time_str}[/dim]" if time_str else ""
        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""

        return f"[{ok}]{glyph}[/{ok}] [bold]{scrubbed_msg}[/bold]{time_part}{focus_mark}"
