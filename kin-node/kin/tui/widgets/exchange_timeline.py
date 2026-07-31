"""ExchangeTimeline domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime
from typing import List, Optional, Union

from textual.events import Key
from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.state import UiEvent
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.timeline import TimelineItem, TimelineWidget


class ExchangeTimelineWidget(LifecycleWidgetMixin, Static):
    """ExchangeTimeline domain widget for dialogue and session events (§14.5).

    Filters List[UiEvent] strictly to presentation classes:
    {'message', 'artifact', 'approval', 'state_transition', 'checkpoint'}.
    Sanitizes free-form event kind and body text against secret or local path leakage.
    """

    can_focus = True
    ALLOWED_PRESENTATION_CLASSES = {"message", "artifact", "approval", "state_transition", "checkpoint"}

    DEFAULT_CSS = """
    ExchangeTimelineWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    ExchangeTimelineWidget:focus {
        border: double $accent;
    }
    """

    def __init__(
        self,
        events: Optional[List[UiEvent]] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.raw_events: List[UiEvent] = events or []
        self.timeline = TimelineWidget(items=[])
        self._rebuild_timeline()

    def _rebuild_timeline(self) -> None:
        filtered = [e for e in self.raw_events if e.presentation_class in self.ALLOWED_PRESENTATION_CLASSES]
        items = []
        for e in filtered:
            glyph = "→" if e.presentation_class == "message" else "●"
            raw_title = f"[{e.presentation_class.upper()}] {e.kind}"
            raw_body = f"actor={e.actor_username or 'system'} session={e.session_id[:8]}"
            items.append(TimelineItem(
                timestamp=e.created_at[:8] if e.created_at else "00:00:00",
                glyph_symbol=glyph,
                title=redact_ui_text(raw_title),
                body=redact_ui_text(raw_body),
            ))
        self.timeline = TimelineWidget(items=items)

    def set_events(self, events: List[UiEvent]) -> None:
        self.raw_events = events
        self._rebuild_timeline()
        self.refresh()

    def on_key(self, event: Key) -> None:
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        if event.key in ("down", "j"):
            self.timeline.scroll_down()
            self.refresh()
            event.stop()
        elif event.key in ("up", "k"):
            self.timeline.scroll_up()
            self.refresh()
            event.stop()

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Exchange Timeline...[/dim]"

        filtered = [e for e in self.raw_events if e.presentation_class in self.ALLOWED_PRESENTATION_CLASSES]
        if state == WidgetLifecycleState.EMPTY or not filtered:
            return "[dim]ExchangeTimeline: No dialogue/session events recorded.[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "ExchangeTimeline disabled"
            return f"[dim]ExchangeTimeline (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} ExchangeTimeline Error: Event log unreadable. Press [Retry].[/bold red]"

        # Synchronize lifecycle state to wrapped timeline widget
        self.timeline.set_lifecycle_state(state, disabled_reason=self.disabled_reason)

        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""
        header = f"[bold cyan]Exchange Timeline ({len(filtered)} events)[/bold cyan]{focus_mark}\n"
        return header + self.timeline.render()
