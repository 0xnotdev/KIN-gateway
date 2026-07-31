"""DataTable foundation collection widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from textual.widgets import Static

from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


@dataclass(frozen=True)
class ColumnDef:
    """Column definition for DataTableWidget."""

    name: str
    title: str
    width: int = 15
    align: str = "left"


class DataTableWidget(LifecycleWidgetMixin, Static):
    """DataTable generic tabular collection foundation widget.

    Implements virtualized windowing over large datasets (10,000+ rows) to guarantee bounded rendering overhead (§14.5).
    """

    DEFAULT_CSS = """
    DataTableWidget {
        width: 100%;
        height: auto;
        background: $surface;
        border: solid $border-subtle;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        columns: Optional[List[ColumnDef]] = None,
        rows: Optional[List[Dict[str, Any]]] = None,
        visible_rows_window: int = 10,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.columns = columns or [
            ColumnDef("id", "ID", width=8),
            ColumnDef("name", "Name", width=20),
            ColumnDef("status", "Status", width=12),
        ]
        self.rows = rows or []
        self.selected_index: int = 0
        self.window_offset: int = 0
        self.visible_rows_window = visible_rows_window

    def cursor_down(self) -> None:
        """Move cursor down with virtual window auto-scroll."""
        if self.rows and self.selected_index < len(self.rows) - 1:
            self.selected_index += 1
            if self.selected_index >= self.window_offset + self.visible_rows_window:
                self.window_offset = self.selected_index - self.visible_rows_window + 1
            self.refresh()

    def cursor_up(self) -> None:
        """Move cursor up with virtual window auto-scroll."""
        if self.rows and self.selected_index > 0:
            self.selected_index -= 1
            if self.selected_index < self.window_offset:
                self.window_offset = self.selected_index
            self.refresh()

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading table data...[/dim]"

        if state == WidgetLifecycleState.EMPTY or not self.rows:
            act_str = f" → Action: {self._next_action_label}" if self._next_action_label else ""
            return f"[dim]Table Empty (0 rows){act_str}[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Table disabled"
            return f"[dim]DataTable (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} Table Error: Failed to load dataset. Press [Retry].[/bold red]"

        if state == WidgetLifecycleState.NARROW:
            return f"[bold]Table ({len(self.rows)} rows)[/bold] | Selected: #{self.selected_index + 1}"

        # Render Header Line
        header_cells = [f"[bold]{col.title:<{col.width}}[/bold]" for col in self.columns]
        header_line = " | ".join(header_cells)
        divider = "-" * len(header_line)

        # Virtualized Bounded Rendering: Only slice visible_rows_window rows regardless of total length (e.g. 10,000)
        window_start = self.window_offset
        window_end = min(len(self.rows), window_start + self.visible_rows_window)
        visible_rows = self.rows[window_start:window_end]

        row_lines = []
        for idx_in_window, row_data in enumerate(visible_rows):
            actual_idx = window_start + idx_in_window
            is_selected = (actual_idx == self.selected_index)
            prefix = "▶ " if is_selected else "  "

            cells = []
            for col in self.columns:
                val_str = str(row_data.get(col.name, ""))[: col.width]
                cells.append(f"{val_str:<{col.width}}")

            line_content = " | ".join(cells)
            if is_selected:
                row_lines.append(f"[bold yellow]{prefix}{line_content}[/bold yellow]")
            else:
                row_lines.append(f"{prefix}{line_content}")

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        row_count_info = f" [dim]({self.selected_index + 1}/{len(self.rows)} rows)[/dim]"

        return f"{header_line}{focus_mark}{row_count_info}\n{divider}\n" + "\n".join(row_lines)
