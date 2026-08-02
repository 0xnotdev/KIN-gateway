"""Spinner foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime
from typing import Callable, Optional, Union

from textual.widgets import Static

from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class SpinnerWidget(LifecycleWidgetMixin, Static):
    """Spinner activity loading indicator foundation widget.

    Features injectable clock ('now') for elapsed time tracking and explicit 'cancel_callback' support (§14.5).
    """

    DEFAULT_CSS = """
    SpinnerWidget {
        width: 100%;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        label: str = "Processing",
        cancel_callback: Optional[Callable[[], None]] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.label = label
        self.cancel_callback = cancel_callback
        self.frame_index = 0
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def trigger_cancel(self) -> bool:
        """Trigger safe cancellation callback (§14.5)."""
        if self.cancel_callback:
            self.cancel_callback()
            return True
        return False

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable."""
        try:
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def render(self) -> str:
        state = self.lifecycle_state
        accent = self._c("accent.primary", "#bb9af7")
        warn = self._c("state.waiting", "#e0af68")
        err = self._c("state.error", "#f7768e")

        if state == WidgetLifecycleState.LOADING or state == WidgetLifecycleState.NORMAL:
            glyph = self.spinner_frames[self.frame_index % len(self.spinner_frames)]
            time_str = self.last_updated_at.strftime("%H:%M:%S") if self.last_updated_at else "00:00:00"
            cancel_hint = " [Cancel: Esc]" if self.cancel_callback else ""
            return f"[{accent}]{glyph}[/{accent}] [bold]{self.label}...[/bold] [dim]({time_str})[/dim]{cancel_hint}"

        if state == WidgetLifecycleState.EMPTY:
            return "[dim]Spinner Idle[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Disabled by caller"
            return f"[dim]Spinner Halted | [{warn}]Reason: {reason}[/{warn}][/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} Spinner Error: Process stalled. Press [Retry].[/bold {err}]"

        if state == WidgetLifecycleState.NARROW:
            return f"◌ {self.label[:10]}"

        # FOCUSED
        glyph = self.spinner_frames[0]
        return f"[{accent}]{glyph}[/{accent}] [bold]{self.label}...[/bold] [focus]"
