"""Panel foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import Callable, List, Optional, Tuple

from textual.widgets import Static

from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class PanelWidget(LifecycleWidgetMixin, Static):
    """Panel structural container foundation widget.

    Receives semantic inputs and emits actions; does not own business state (§14.5).
    """

    DEFAULT_CSS = """
    PanelWidget {
        width: 100%;
        height: auto;
        background: $surface;
        border: solid $border-subtle;
        padding: 0 1;
    }
    PanelWidget.-focused-state {
        border: double $border-focus;
    }
    PanelWidget.-disabled-state {
        background: $surface-darken-1;
        border: ascii $text-muted;
    }
    PanelWidget.-error-state {
        border: heavy $state-error;
    }
    """

    def __init__(
        self,
        title: str = "Panel",
        content: str = "",
        footer: Optional[str] = None,
        actions: Optional[List[Tuple[str, Callable[[], None]]]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.content_text = content
        self.footer_text = footer
        self.actions = actions or []

    def render(self) -> str:
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent = self._c("accent.primary", "#bb9af7")
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            time_str = self.last_updated_at.strftime("%H:%M:%S") if self.last_updated_at else "00:00:00"
            return f"[bold {accent}]{glyph} Loading {self.title}...[/bold {accent}] [dim]({time_str})[/dim]"

        if state == WidgetLifecycleState.EMPTY:
            act_str = f" → Action: {self._next_action_label}" if self._next_action_label else ""
            return f"[bold]{self.title}[/bold]\n[dim]No items available.{act_str}[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Disabled by system policy"
            return f"[dim][bold]{self.title}[/bold] (DISABLED)[/dim]\n[{warn}]Reason: {reason}[/{warn}]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return (
                f"[bold {err}]{glyph} ERROR: {self.title}[/bold {err}]\n"
                f"[{err}]Failed to load panel content.[/{err}] [bold {warn}]Press [Retry] to attempt recovery.[/bold {warn}]"
            )

        if state == WidgetLifecycleState.NARROW:
            return f"[bold]{self.title}[/bold] | {self.content_text[:20]}..."

        # NORMAL or FOCUSED
        focused_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        header = f"[bold {accent}]{self.title}{focused_mark}[/bold {accent}]"
        body = self.content_text
        footer = f"\n[dim]{self.footer_text}[/dim]" if self.footer_text else ""
        return f"{header}\n{body}{footer}"
