"""ProgressBar foundation widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from textual.widgets import Static

from kin.tui.tokens import get_glyph, validate_widget_role_consumption
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class ProgressBarWidget(LifecycleWidgetMixin, Static):
    """ProgressBar visual progress indicator foundation widget.

    Takes progress fraction (0.0 to 1.0) and consumes design token roles (§14.5).
    """

    DEFAULT_CSS = """
    ProgressBarWidget {
        width: 100%;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        progress: float = 0.0,
        label: str = "Progress",
        role: str = "accent.primary",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.progress_value = max(0.0, min(1.0, float(progress)))
        self.label = label
        self.role = validate_widget_role_consumption(role)

    def set_progress(self, progress: float) -> None:
        """Update progress value in-place (0.0 to 1.0)."""
        self.progress_value = max(0.0, min(1.0, float(progress)))
        self.refresh()

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Calculating progress...[/dim]"

        if state == WidgetLifecycleState.EMPTY:
            return "[dim]Progress: 0% [..........][/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Progress paused"
            return f"[dim]Progress Suspended | [yellow]Reason: {reason}[/yellow][/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} Progress Error: Operation failed. Press [Retry].[/bold red]"

        pct = int(self.progress_value * 100)

        if state == WidgetLifecycleState.NARROW:
            return f"{pct}% | {self.label[:8]}"

        # Render 10-block progress bar
        filled_blocks = int(self.progress_value * 10)
        empty_blocks = 10 - filled_blocks
        bar_str = "█" * filled_blocks + "░" * empty_blocks

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""

        return f"[bold cyan][{bar_str}][/bold cyan] [bold]{pct}%[/bold] {self.label}{focus_mark}"
