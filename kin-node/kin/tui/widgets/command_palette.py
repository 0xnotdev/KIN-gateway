"""CommandPalette foundation modal and widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

from kin.tui.palette import CommandItem, parse_colon_command, rank_command_palette
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.modal import ModalScreenWidget


class CommandPaletteWidget(LifecycleWidgetMixin, Static):
    """CommandPalette inner content widget extending LifecycleWidgetMixin (§14.5)."""

    DEFAULT_CSS = """
    CommandPaletteWidget {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        query: str = "",
        results: Optional[List[Tuple[CommandItem, float]]] = None,
        selected_index: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.query = query
        self.results = results or []
        self.selected_index = selected_index

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Indexing command palette actions...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Palette disabled"
            return f"[dim]CommandPalette (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} Palette Error: Action registry lost. Press [Retry].[/bold red]"

        if state == WidgetLifecycleState.EMPTY or not self.results:
            act_str = f" → Action: {self._next_action_label}" if self._next_action_label else ""
            return f"[dim]No matching command palette actions for '{self.query}'.{act_str}[/dim]"

        lines = []
        for idx, (item, score) in enumerate(self.results[:8]):
            is_selected = (idx == self.selected_index)
            prefix = "▶ " if is_selected else "  "
            cat = f"[{item.category.upper()}]"

            if is_selected:
                lines.append(f"[bold yellow]{prefix}{cat} {item.title} — {item.description}[/bold yellow]")
            else:
                lines.append(f"{prefix}[dim]{cat}[/dim] {item.title}")

        if state == WidgetLifecycleState.NARROW:
            top_title = self.results[0][0].title if self.results else "None"
            return f"Palette ({len(self.results)}): {top_title}"

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        return "\n".join(lines) + focus_mark


class CommandPaletteModal(ModalScreenWidget):
    """CommandPalette modal overlay screen extending ModalScreenWidget (§14.5)."""

    DEFAULT_CSS = """
    CommandPaletteModal {
        align: center top;
        padding-top: 3;
        background: rgba(0, 0, 0, 0.7);
    }
    #palette-container {
        width: 70;
        height: auto;
        min-height: 12;
        background: $surface-darken-1;
        border: thick $primary;
        padding: 1 2;
    }
    """

    def __init__(self, commands: List[CommandItem], active_tab: str = "home", **kwargs) -> None:
        super().__init__(
            title="COMMAND PALETTE (Ctrl+K)",
            body_text="Type a command or colon directive...",
            confirm_label="Select (Enter)",
            cancel_label="Close (Esc)",
            variant="primary",
            **kwargs,
        )
        self.commands = commands
        self.active_tab = active_tab
        self.query = ""
        self.selected_index = 0
        self.palette_widget = CommandPaletteWidget()
        self.update_results()

    def update_results() -> None:
        if self.query.startswith(":"):
            cmd_name, arg, err = parse_colon_command(self.query)
            if err:
                self.palette_widget.set_lifecycle_state(
                    WidgetLifecycleState.RECOVERABLE_ERROR,
                    retry_callback=lambda: self.update_results(),
                )
            else:
                self.palette_widget.results = []
                self.palette_widget.set_lifecycle_state(WidgetLifecycleState.NORMAL)
        else:
            res = rank_command_palette(self.query, self.commands, self.active_tab)
            self.palette_widget.query = self.query
            self.palette_widget.results = res
            if not res:
                self.palette_widget.set_lifecycle_state(
                    WidgetLifecycleState.EMPTY,
                    next_action_label="Clear Search",
                )
            else:
                self.palette_widget.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-container"):
            yield Static("[bold cyan]COMMAND PALETTE (Ctrl+K)[/bold cyan]", id="palette-header")
            yield Input(placeholder="Type command or :colon command...", id="palette-input")
            yield self.palette_widget

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query = event.value
        self.selected_index = 0
        self.update_results()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key in ("enter", "return"):
            if self.query.startswith(":"):
                cmd_name, arg, err = parse_colon_command(self.query)
                if not err:
                    self.dismiss((f"colon:{cmd_name}", arg))
            elif self.palette_widget.results and 0 <= self.selected_index < len(self.palette_widget.results):
                item, _ = self.palette_widget.results[self.selected_index]
                self.dismiss(("action", item.action_id))
        elif event.key in ("down", "j"):
            if self.palette_widget.results:
                self.selected_index = min(self.selected_index + 1, len(self.palette_widget.results) - 1)
                self.palette_widget.selected_index = self.selected_index
                self.palette_widget.refresh()
        elif event.key in ("up", "k"):
            if self.palette_widget.results:
                self.selected_index = max(self.selected_index - 1, 0)
                self.palette_widget.selected_index = self.selected_index
                self.palette_widget.refresh()
