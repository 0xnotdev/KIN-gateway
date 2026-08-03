"""EmptyState foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import Callable, Optional

from textual.widgets import Static

from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class EmptyStateWidget(LifecycleWidgetMixin, Static):
    """EmptyState zero-data collection placeholder foundation widget.

    Receives semantic inputs (title, description, icon, next_action) without owning business state (§14.5).
    """

    DEFAULT_CSS = """
    EmptyStateWidget {
        width: 100%;
        height: auto;
        background: $surface;
        border: dashed $border-subtle;
        padding: 1 2;
        content-align: center middle;
    }
    """

    def __init__(
        self,
        title: str = "No Items Available",
        description: str = "There are no active records in this collection.",
        glyph_symbol: str = "○",
        next_action_label: Optional[str] = "Create New Item",
        next_action_callback: Optional[Callable[[], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(
            next_action_label=next_action_label,
            next_action_callback=next_action_callback,
            **kwargs,
        )
        self.title = title
        self.description = description
        self.glyph_symbol = glyph_symbol

    def trigger_action(self) -> bool:
        """Trigger next action callback if defined (§14.5)."""
        if self._next_action_callback:
            self._next_action_callback()
            return True
        return False

    def render(self) -> str:
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent = self._c("accent.primary", "#bb9af7")
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Checking for items...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Collection disabled"
            return f"[dim]Empty Collection | [{warn}]Reason: {reason}[/{warn}][/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} Empty State Error: Failed to fetch collection. Press [Retry].[/bold {err}]"

        glyph = get_glyph(self.glyph_symbol)

        if state == WidgetLifecycleState.NARROW:
            return f"{glyph} {self.title}"

        action_str = ""
        if self._next_action_label:
            action_str = f"\n\n[bold {accent}][ {self._next_action_label} ][/bold {accent}]"

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""

        return (
            f"[bold {accent}]{glyph} {self.title}{focus_mark}[/bold {accent}]\n"
            f"[dim]{self.description}[/dim]"
            f"{action_str}"
        )
