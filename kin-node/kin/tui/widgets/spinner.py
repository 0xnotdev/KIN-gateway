"""Spinner foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime
from time import monotonic
from typing import Callable, Optional, Union

from textual.widgets import Static

from kin.tui.motion import (
    SPINNER_FPS,
    SPINNER_FPS_MAX,
    SPINNER_FPS_MIN,
    SPINNER_FRAME_INTERVAL_SECONDS,
)
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
        elapsed_clock: Callable[[], float] = monotonic,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.label = label
        self.cancel_callback = cancel_callback
        self.frame_index = 0
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.min_fps = SPINNER_FPS_MIN
        self.max_fps = SPINNER_FPS_MAX
        self.fps = SPINNER_FPS
        self.frame_interval_seconds = SPINNER_FRAME_INTERVAL_SECONDS
        self._elapsed_clock = elapsed_clock
        self._started_at = elapsed_clock()
        self._frame_timer = None

    @property
    def elapsed_seconds(self) -> int:
        """Whole seconds elapsed since this spinner was created."""
        return max(0, int(self._elapsed_clock() - self._started_at))

    def _elapsed_label(self) -> str:
        elapsed = self.elapsed_seconds
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"elapsed {hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"elapsed {minutes:02d}:{seconds:02d}"

    def advance_frame(self) -> None:
        """Advance spinner animation frame and trigger local refresh."""
        self.frame_index = (self.frame_index + 1) % len(self.spinner_frames)
        self.refresh(layout=False)

    def on_mount(self) -> None:
        """Schedule periodic frame updates bounded by 8-12 FPS frame_interval_seconds (§14.5, §14.9 step 3)."""
        self._frame_timer = self.set_interval(self.frame_interval_seconds, self.advance_frame)

    def trigger_cancel(self) -> bool:
        """Trigger safe cancellation callback (§14.5)."""
        if self.cancel_callback:
            self.cancel_callback()
            return True
        return False

    def render(self) -> str:
        state = self.lifecycle_state
        accent = self._c("accent.primary", "#bb9af7")
        warn = self._c("state.waiting", "#e0af68")
        err = self._c("state.error", "#f7768e")

        if state == WidgetLifecycleState.LOADING or state == WidgetLifecycleState.NORMAL:
            glyph = self.spinner_frames[self.frame_index % len(self.spinner_frames)]
            start_time = self.last_updated_at.strftime("%H:%M:%S") if self.last_updated_at else "00:00:00"
            elapsed_label = self._elapsed_label()
            cancel_hint = " [Cancel: Esc]" if self.cancel_callback else ""
            return (
                f"[{accent}]{glyph}[/{accent}] [bold]{self.label}...[/bold] "
                f"[dim](started {start_time} | {elapsed_label})[/dim]{cancel_hint}"
            )

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
