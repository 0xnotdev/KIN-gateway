"""QuickSwitcher foundation modal and widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.modal import ModalScreenWidget


class QuickSwitcherWidget(LifecycleWidgetMixin, Static):
    """QuickSwitcher inner content widget extending LifecycleWidgetMixin (§14.5)."""

    DEFAULT_CSS = """
    QuickSwitcherWidget {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        query: str = "",
        candidates: Optional[List[Tuple[str, str, str]]] = None,
        selected_index: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.query = query
        self.candidates = candidates or []
        self.selected_index = selected_index

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading quick switcher index...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Quick switcher disabled"
            return f"[dim]QuickSwitcher (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} QuickSwitcher Error: Candidate index corrupted. Press [Retry].[/bold red]"

        filtered = [
            (target_id, title, category)
            for target_id, title, category in self.candidates
            if not self.query or self.query.lower() in title.lower() or self.query.lower() in category.lower()
        ]

        if state == WidgetLifecycleState.EMPTY or not filtered:
            act_str = f" → Action: {self._next_action_label}" if self._next_action_label else ""
            return f"[dim]No matching quick switcher items for '{self.query}'.{act_str}[/dim]"

        lines = []
        for idx, (target_id, title, category) in enumerate(filtered[:8]):
            is_selected = (idx == self.selected_index)
            prefix = "▶ " if is_selected else "  "

            if is_selected:
                lines.append(f"[bold yellow]{prefix}[{category}] {title}[/bold yellow]")
            else:
                lines.append(f"{prefix}[dim][{category}][/dim] {title}")

        if state == WidgetLifecycleState.NARROW:
            top_title = filtered[0][1] if filtered else "None"
            return f"Switcher ({len(filtered)}): {top_title}"

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        return "\n".join(lines) + focus_mark


class QuickSwitcherModal(ModalScreenWidget):
    """QuickSwitcher modal overlay screen extending ModalScreenWidget (§14.5)."""

    DEFAULT_CSS = """
    QuickSwitcherModal {
        align: center top;
        padding-top: 3;
        background: rgba(0, 0, 0, 0.7);
    }
    #switcher-container {
        width: 60;
        height: auto;
        min-height: 10;
        background: $surface-darken-1;
        border: thick $primary;
        padding: 1 2;
    }
    """

    def __init__(self, candidates: List[Tuple[str, str, str]], **kwargs) -> None:
        super().__init__(
            title="QUICK SWITCHER (Ctrl+P)",
            body_text="Type workspace tab or agent name...",
            confirm_label="Select (Enter)",
            cancel_label="Close (Esc)",
            variant="accent",
            **kwargs,
        )
        self.candidates = candidates
        self.query = ""
        self.selected_index = 0
        self.switcher_widget = QuickSwitcherWidget(candidates=candidates)

    def compose(self) -> ComposeResult:
        with Vertical(id="switcher-container"):
            yield Static("[bold cyan]QUICK SWITCHER (Ctrl+P)[/bold cyan]", id="switcher-header")
            yield Input(placeholder="Type workspace or agent...", id="switcher-input")
            yield self.switcher_widget

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query = event.value
        self.selected_index = 0
        self.switcher_widget.query = self.query
        self.switcher_widget.refresh()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key in ("enter", "return"):
            filtered = [
                item for item in self.candidates
                if not self.query or self.query.lower() in item[1].lower() or self.query.lower() in item[2].lower()
            ]
            if filtered and 0 <= self.selected_index < len(filtered):
                self.dismiss(filtered[self.selected_index][0])
        elif event.key in ("down", "j"):
            filtered = [
                item for item in self.candidates
                if not self.query or self.query.lower() in item[1].lower() or self.query.lower() in item[2].lower()
            ]
            if filtered:
                self.selected_index = min(self.selected_index + 1, len(filtered) - 1)
                self.switcher_widget.selected_index = self.selected_index
                self.switcher_widget.refresh()
        elif event.key in ("up", "k"):
            filtered = [
                item for item in self.candidates
                if not self.query or self.query.lower() in item[1].lower() or self.query.lower() in item[2].lower()
            ]
            if filtered:
                self.selected_index = max(self.selected_index - 1, 0)
                self.switcher_widget.selected_index = self.selected_index
                self.switcher_widget.refresh()
