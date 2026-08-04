"""Toast foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import Callable, Optional

from textual.widgets import Static

from kin.tui.motion import (
    TOAST_AMBER_PULSE_INTERVAL_MS,
    TOAST_DURATION_SEC,
    TOAST_MAX_AMBER_PULSES,
    clamp_toast_duration_seconds,
    milliseconds_to_seconds,
)
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
        auto_start: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.message = message
        self.severity = severity.lower() if severity.lower() in self.SEVERITY_GLYPHS else "info"
        self.dismiss_callback = dismiss_callback
        requested_seconds = (
            duration_ms / 1000.0 if duration_ms is not None else TOAST_DURATION_SEC
        )
        self.duration_seconds = clamp_toast_duration_seconds(requested_seconds)
        self.duration_ms = int(self.duration_seconds * 1000)
        self.amber_pulse_count = 0
        self._amber_pulse_active = False
        self._amber_pulse_timer = None
        self._dismiss_timer = None
        self._auto_start = auto_start
        self._reduced_motion = False

    def on_mount(self) -> None:
        """Schedule automatic dismissal timer using self.duration_ms (§14.5, §14.9 step 3)."""
        if self._auto_start:
            self._schedule_timers()

    def _schedule_timers(self) -> None:
        """Schedule visibility and optional attention timers for the current message."""
        if self._dismiss_timer is not None:
            self._dismiss_timer.pause()
        self._dismiss_timer = self.set_timer(self.duration_seconds, self.trigger_dismiss)
        if self._amber_pulse_timer is not None:
            self._amber_pulse_timer.pause()
        if self.severity == "warning" and not self._reduced_motion:
            self.amber_pulse_count = 1
            self._amber_pulse_active = True
            self._amber_pulse_timer = self.set_interval(
                milliseconds_to_seconds(TOAST_AMBER_PULSE_INTERVAL_MS),
                self._advance_amber_pulse,
            )
        else:
            self.amber_pulse_count = 0
            self._amber_pulse_active = False

    def show(
        self,
        message: str,
        *,
        severity: str = "info",
        duration_ms: Optional[int] = None,
    ) -> None:
        """Display a hosted toast and restart its bounded lifecycle."""
        self.message = message
        self.severity = severity.lower() if severity.lower() in self.SEVERITY_GLYPHS else "info"
        requested_seconds = (
            duration_ms / 1000.0 if duration_ms is not None else TOAST_DURATION_SEC
        )
        self.duration_seconds = clamp_toast_duration_seconds(requested_seconds)
        self.duration_ms = int(self.duration_seconds * 1000)
        if self.is_mounted:
            self.styles.visibility = "visible"
            self._schedule_timers()
            self.refresh(layout=False)

    def set_reduced_motion(self, active: bool) -> None:
        """Suppress amber pulses instantly while retaining toast text and lifetime."""
        self._reduced_motion = bool(active)
        if self._amber_pulse_timer is not None:
            self._amber_pulse_timer.pause()
        self._amber_pulse_active = False
        if self.is_mounted:
            self.refresh(layout=False)

    def _advance_amber_pulse(self) -> None:
        """Advance a warning toast through no more than two amber pulse cycles."""
        if self._amber_pulse_active:
            self._amber_pulse_active = False
            if self.amber_pulse_count >= TOAST_MAX_AMBER_PULSES:
                if self._amber_pulse_timer is not None:
                    self._amber_pulse_timer.pause()
        else:
            if self.amber_pulse_count >= TOAST_MAX_AMBER_PULSES:
                if self._amber_pulse_timer is not None:
                    self._amber_pulse_timer.pause()
                return
            self.amber_pulse_count += 1
            self._amber_pulse_active = True
        self.refresh(layout=False)

    def trigger_dismiss(self) -> bool:
        """Trigger optional dismiss callback (§14.5)."""
        dismissed = False
        if self.dismiss_callback:
            self.dismiss_callback()
            dismissed = True
        if self.is_mounted:
            # Visibility is paint-only. Removing the widget would ask its parent to
            # recompute layout, violating the ordinary-update reflow guarantee.
            self.styles.visibility = "hidden"
            self.refresh(layout=False)
            dismissed = True
        return dismissed

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
        if self.severity == "warning" and self._amber_pulse_active:
            style = f"bold {warn}"

        scrubbed_msg = redact_ui_text(self.message)

        if state == WidgetLifecycleState.NARROW:
            return f"[{style}]{glyph} {scrubbed_msg[:18]}[/]"

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        dismiss_hint = " [dim][x][/dim]" if self.dismiss_callback else ""

        return f"[{style}]{glyph} [{self.severity.upper()}] {scrubbed_msg}[/]{dismiss_hint}{focus_mark}"
