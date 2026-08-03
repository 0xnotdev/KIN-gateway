"""Toast foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import Callable, Optional

from textual.widgets import Static

from kin.tui.motion import TOAST_MAX_VISIBLE_MS, TOAST_MIN_VISIBLE_MS
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
        duration_ms: Optional[int] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.message = message
        self.severity = severity.lower() if severity.lower() in self.SEVERITY_GLYPHS else "info"
        self.dismiss_callback = dismiss_callback
        req_duration = duration_ms if duration_ms is not None else 4000
        self.duration_ms = min(TOAST_MAX_VISIBLE_MS, max(TOAST_MIN_VISIBLE_MS, req_duration))

    def trigger_dismiss(self) -> bool:
        """Trigger optional dismiss callback (§14.5)."""
        if self.dismiss_callback:
            self.dismiss_callback()
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
        ok = self._c("state.live", "#73daca")
        warn = self._c("state.waiting", "#e0af68")
        err = self._c("state.error", "#f7768e")

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Preparing notification...[/dim]"

        if state == WidgetLifecycleState.EMPTY:
            return "[dim]No unread notifications[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Notifications muted"
            return f"[dim]Toast Muted | [{warn}]Reason: {reason}[/{warn}][/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} Notification Error: Failed to render toast. Press [Retry].[/bold {err}]"

        raw_glyph = self.SEVERITY_GLYPHS.get(self.severity, "●")
        glyph = get_glyph(raw_glyph)
        
        severity_styles = {
            "info": accent,
            "success": ok,
            "warning": warn,
            "error": f"bold {err}",
        }
        style = severity_styles.get(self.severity, accent)

        scrubbed_msg = redact_ui_text(self.message)

        if state == WidgetLifecycleState.NARROW:
            return f"[{style}]{glyph} {scrubbed_msg[:18]}[/]"

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        dismiss_hint = " [dim][x][/dim]" if self.dismiss_callback else ""

        return f"[{style}]{glyph} [{self.severity.upper()}] {scrubbed_msg}[/]{dismiss_hint}{focus_mark}"
