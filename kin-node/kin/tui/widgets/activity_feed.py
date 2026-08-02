"""ActivityFeed domain widget for KIN V1.1 TUI.

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


class ActivityFeedWidget(LifecycleWidgetMixin, Static):
    """ActivityFeed domain widget for system activity and security log events (§14.5).

    Filters List[UiEvent] strictly to presentation classes:
    {'activity', 'security'}.
    Sanitizes free-form event kind and body text against secret or local path leakage.
    """

    can_focus = True
    ALLOWED_PRESENTATION_CLASSES = {"activity", "security"}

    DEFAULT_CSS = """
    ActivityFeedWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    ActivityFeedWidget:focus {
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
        self._rebuild_feed()

    def _rebuild_feed(self) -> None:
        filtered = [e for e in self.raw_events if e.presentation_class in self.ALLOWED_PRESENTATION_CLASSES]
        items = []
        for e in filtered:
            glyph = "!" if e.presentation_class == "security" else "●"
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
        self._rebuild_feed()
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

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable."""
        try:
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def render(self) -> str:
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Activity Feed...[/dim]"

        filtered = [e for e in self.raw_events if e.presentation_class in self.ALLOWED_PRESENTATION_CLASSES]
        if state == WidgetLifecycleState.EMPTY or not filtered:
            return "[dim]ActivityFeed: No background activity or security events logged.[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "ActivityFeed disabled"
            return f"[dim]ActivityFeed (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} ActivityFeed Error: System log unreadable. Press [Retry].[/bold {err}]"

        self.timeline.set_lifecycle_state(state, disabled_reason=self.disabled_reason)

        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""
        header = f"[bold {warn}]Activity & Security Feed ({len(filtered)} events)[/bold {warn}]{focus_mark}\n"
        return header + self.timeline.render()
