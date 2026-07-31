"""SearchField foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime
from typing import Callable, Optional, Union

from textual.events import Key
from textual.widgets import Input, Static

from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class SearchFieldWidget(LifecycleWidgetMixin, Static):
    """SearchField interactive search input foundation widget.

    Features interactive keypress handling (on_key), debounced search callbacks using an injectable clock ('now'),
    visible match count labels, and text clearing (§14.5).
    """

    can_focus = True

    DEFAULT_CSS = """
    SearchFieldWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
    }
    SearchFieldWidget:focus {
        border: solid $accent;
    }
    """

    def __init__(
        self,
        placeholder: str = "Search...",
        value: str = "",
        match_count: Optional[int] = None,
        on_query_change: Optional[Callable[[str], None]] = None,
        debounce_ms: float = 150.0,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.placeholder = placeholder
        self.query = value
        self.match_count = match_count
        self.on_query_change = on_query_change
        self.debounce_ms = debounce_ms
        self.last_query_timestamp: float = 0.0

    def update_match_count(self, count: Optional[int]) -> None:
        """Update visible match count label ([N matches])."""
        self.match_count = count
        self.refresh()

    def set_query(self, query: str, now: Optional[Union[datetime, str, float]] = None) -> None:
        """Set query text and trigger debounced search callback using injectable clock (§14.5)."""
        self.query = query
        self.update_clock(now)

        if self.last_updated_at:
            current_ts = self.last_updated_at.timestamp() * 1000.0
        else:
            current_ts = 0.0

        # Enforce debounce window with injectable clock timestamp
        if current_ts - self.last_query_timestamp >= self.debounce_ms or self.last_query_timestamp == 0.0:
            self.last_query_timestamp = current_ts
            if self.on_query_change:
                self.on_query_change(self.query)

        self.refresh()

    def clear(self) -> None:
        """Clear query text and reset match count."""
        self.set_query("")
        self.match_count = None

    def on_key(self, event: Key) -> None:
        """Interactive keypress handling for character input accumulating into self.query (§14.5)."""
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        if event.key == "backspace":
            if self.query:
                self.set_query(self.query[:-1])
            event.stop()
        elif event.key == "escape":
            self.clear()
            self.set_lifecycle_state(WidgetLifecycleState.NORMAL)
            event.stop()
        elif event.character and len(event.character) == 1 and event.character.isprintable():
            self.set_query(self.query + event.character)
            event.stop()

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Preparing search index...[/dim]"

        if state == WidgetLifecycleState.EMPTY:
            return "[dim]/ Search field ready (0 items indexed)[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Search disabled"
            return f"[dim]/ Search (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} Search Error: Index corrupted. Press [Retry].[/bold red]"

        match_str = ""
        if self.match_count is not None:
            match_str = f" [bold yellow][{self.match_count} matches][/bold yellow]"

        if state == WidgetLifecycleState.NARROW:
            q = self.query or self.placeholder
            return f"/ {q[:12]}{match_str}"

        is_focused = (state == WidgetLifecycleState.FOCUSED or self.has_focus)
        focus_mark = " [focus]" if is_focused else ""
        query_display = self.query if self.query else f"[dim]{self.placeholder}[/dim]"

        return f"[bold yellow]/[/bold yellow] {query_display}{match_str}{focus_mark}"
