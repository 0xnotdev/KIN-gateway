"""Toast foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import Callable, Optional

from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class ToastWidget(LifecycleWidgetMixin, Static):
    """Toast transient notification banner foundation widget.

    Receives semantic inputs (message, severity, dismiss_callback) without owning business state (§14.5).
    Sanitizes free-form message text against secret or local path leakage.
    """

    DEFAULT_CSS = """
    ToastWidget {
        width: 100%;
        height: 1;
        background: $surface-darken-1;
        border: solid $primary;
        padding: 0 1;
    }
    """

    SEVERITY_GLYPHS = {
        "info": "●",
        "success": "✓",
        "warning": "!",
        "error": "!",
    }

    SEVERITY_STYLES = {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "bold red",
    }

    def __init__(
        self,
        message: str = "Notification",
        severity: str = "info",
        dismiss_callback: Optional[Callable[[], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.message = message
        self.severity = severity.lower() if severity.lower() in self.SEVERITY_GLYPHS else "info"
        self.dismiss_callback = dismiss_callback

    def trigger_dismiss(self) -> bool:
        """Trigger optional dismiss callback (§14.5)."""
        if self.dismiss_callback:
            self.dismiss_callback()
            return True
        return False

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Preparing notification...[/dim]"

        if state == WidgetLifecycleState.EMPTY:
            return "[dim]No unread notifications[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Notifications muted"
            return f"[dim]Toast Muted | [yellow]Reason: {reason}[/yellow][/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} Notification Error: Failed to render toast. Press [Retry].[/bold red]"

        raw_glyph = self.SEVERITY_GLYPHS.get(self.severity, "●")
        glyph = get_glyph(raw_glyph)
        style = self.SEVERITY_STYLES.get(self.severity, "cyan")

        scrubbed_msg = redact_ui_text(self.message)

        if state == WidgetLifecycleState.NARROW:
            return f"[{style}]{glyph} {scrubbed_msg[:18]}[/{style}]"

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        dismiss_hint = " [dim][x][/dim]" if self.dismiss_callback else ""

        return f"[{style}]{glyph} [{self.severity.upper()}] {scrubbed_msg}[/{style}]{dismiss_hint}{focus_mark}"
