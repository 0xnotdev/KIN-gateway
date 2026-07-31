"""Inspector foundation UI component for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import Optional

from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class InspectorWidget(LifecycleWidgetMixin, Static):
    """Inspector sidebar preview foundation widget.

    Extends LifecycleWidgetMixin to support all 7 lifecycle states (§14.5).
    Sanitizes title and detail preview strings against secret or local path leakage.
    """

    DEFAULT_CSS = """
    InspectorWidget {
        width: 100%;
        height: 100%;
        background: $surface-darken-1;
        border-left: solid $border-subtle;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        title: str = "Inspector",
        details: Optional[str] = None,
        collapsed: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.details = details
        self.collapsed = collapsed

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Fetching item details...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Inspector disabled"
            return f"[dim]Inspector (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} Inspector Error: Item details unreadable. Press [Retry].[/bold red]"

        if self.collapsed:
            return "i\nn\ns\np"

        scrubbed_title = redact_ui_text(self.title)
        scrubbed_details = redact_ui_text(self.details) if self.details else None

        if state == WidgetLifecycleState.EMPTY or not scrubbed_details:
            act_str = f" → Action: {self._next_action_label}" if self._next_action_label else ""
            return f"[bold]{scrubbed_title}[/bold]\n[dim]No item selected for preview.{act_str}[/dim]"

        if state == WidgetLifecycleState.NARROW:
            return f"[bold]{scrubbed_title}[/bold] | {scrubbed_details[:15]}..."

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        return f"[bold cyan]{scrubbed_title}[/bold cyan]{focus_mark}\n{scrubbed_details}"
