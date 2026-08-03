"""Timeline foundation collection widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from dataclasses import dataclass
from typing import List, Optional

from textual.widgets import Static

from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


@dataclass(frozen=True)
class TimelineItem:
    """Dataclass defining a single event item in TimelineWidget."""

    timestamp: str
    glyph_symbol: str
    title: str
    body: str = ""


class TimelineWidget(LifecycleWidgetMixin, Static):
    """Timeline chronological event collection foundation widget.

    Features virtualized windowing over 10,000+ event scale and scroll-lock protection on live event appends (§14.5).
    """

    DEFAULT_CSS = """
    TimelineWidget {
        width: 100%;
        height: auto;
        background: $surface;
        border: solid $border-subtle;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        items: Optional[List[TimelineItem]] = None,
        visible_items_window: int = 8,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.items: List[TimelineItem] = items or []
        self.visible_items_window = visible_items_window
        self.selected_index: int = max(0, len(self.items) - 1)
        self.window_offset: int = max(0, len(self.items) - self.visible_items_window)
        self.user_scrolled_up: bool = False

    def scroll_up(self) -> None:
        """Scroll up in timeline, activating scroll lock (§14.5)."""
        if self.items and self.selected_index > 0:
            self.selected_index -= 1
            self.user_scrolled_up = True
            if self.selected_index < self.window_offset:
                self.window_offset = self.selected_index
            self.refresh()

    def scroll_down(self) -> None:
        """Scroll down in timeline."""
        if self.items and self.selected_index < len(self.items) - 1:
            self.selected_index += 1
            if self.selected_index >= len(self.items) - 1:
                self.user_scrolled_up = False
            if self.selected_index >= self.window_offset + self.visible_items_window:
                self.window_offset = self.selected_index - self.visible_items_window + 1
            self.refresh()

    def append_event(self, item: TimelineItem) -> None:
        """Append new event item with SCROLL-LOCK PROTECTION (§14.5).

        If user has scrolled up away from bottom (user_scrolled_up=True), scroll offset
        and selected_index are strictly preserved without forcing auto-scroll.
        """
        self.items.append(item)
        if not self.user_scrolled_up:
            # Auto-scroll to newly appended item at bottom
            self.selected_index = len(self.items) - 1
            self.window_offset = max(0, len(self.items) - self.visible_items_window)
        self.refresh()

    def _get_app_instance(self):
        app = getattr(self, "_app", None)
        if app is None:
            try:
                app = self.app
            except Exception:
                app = None
        return app

    def _g(self, symbol: str) -> str:
        """Resolve a glyph symbol using ASCII fallback if app.is_ascii_fallback_active is True."""
        app = self._get_app_instance()
        ascii_fallback = getattr(app, "is_ascii_fallback_active", False) if app is not None else False
        from kin.tui.tokens import get_glyph
        return get_glyph(symbol, ascii_fallback=ascii_fallback)

    def render(self) -> str:
        state = self.lifecycle_state
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent = self._c("accent.primary", "#bb9af7")
        err_tag = f" {err}".rstrip()
        warn_tag = f" {warn}".rstrip()
        accent_tag = f" {accent}".rstrip()

        if state == WidgetLifecycleState.LOADING:
            glyph = self._g("◌")
            return f"[dim]{glyph} Streaming timeline events...[/dim]"

        if state == WidgetLifecycleState.EMPTY or not self.items:
            next_act = self._g("→")
            act_str = f" {next_act} Action: {self._next_action_label}" if self._next_action_label else ""
            return f"[dim]Timeline Empty (0 events){act_str}[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Timeline paused"
            return f"[dim]Timeline (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = self._g("!")
            return f"[bold{err_tag}]{glyph} Timeline Error: Event stream lost. Press [Retry].[/bold{err_tag}]"

        if state == WidgetLifecycleState.NARROW:
            return f"[bold]Timeline ({len(self.items)} events)[/bold] | Latest: {self.items[-1].title[:15]}"

        # Virtualized Windowing: Only render visible_items_window items
        start = self.window_offset
        end = min(len(self.items), start + self.visible_items_window)
        visible_items = self.items[start:end]

        lines = []
        play_glyph = self._g("▶")
        for idx_in_window, item in enumerate(visible_items):
            actual_idx = start + idx_in_window
            is_selected = (actual_idx == self.selected_index)
            prefix = f"{play_glyph} " if is_selected else "  "

            glyph = self._g(item.glyph_symbol)
            ts = f"[dim]{item.timestamp}[/dim]"
            title = f"[bold]{item.title}[/bold]"
            body_part = f" - {item.body}" if item.body else ""

            if is_selected:
                lines.append(f"[bold{warn_tag}]{prefix}[{ts}] {glyph} {title}{body_part}[/bold{warn_tag}]")
            else:
                lines.append(f"{prefix}[{ts}] {glyph} {title}{body_part}")

        scroll_lock_indicator = f" [bold{err_tag}][SCROLL LOCK ACTIVE][/bold{err_tag}]" if self.user_scrolled_up else ""
        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""

        header = f"[bold{accent_tag}]Timeline ({len(self.items)} events)[/bold{accent_tag}]{scroll_lock_indicator}{focus_mark}"
        return f"{header}\n" + "\n".join(lines)
