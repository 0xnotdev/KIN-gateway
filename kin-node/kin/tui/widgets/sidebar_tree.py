"""SidebarTree foundation UI component for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from textual.widgets import Static

from kin.tui.motion import EXPAND_TRANSITION_MS, milliseconds_to_seconds
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.search_field import SearchFieldWidget


@dataclass
class SidebarNode:
    """Dataclass defining a single node in SidebarTreeWidget."""

    node_id: str
    title: str
    kind: str  # "section" or "item"
    section: str
    badge: Optional[str] = None


class SidebarTreeWidget(LifecycleWidgetMixin, Static):
    """SidebarTree navigation tree foundation widget.

    Embeds SearchFieldWidget for real debounced query filtering and extends LifecycleWidgetMixin (§14.5).
    """

    DEFAULT_CSS = """
    SidebarTreeWidget {
        width: 100%;
        height: 100%;
        background: $surface-darken-1;
        padding: 0 1;
    }
    """

    def __init__(self, nodes: Optional[List[SidebarNode]] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.nodes: List[SidebarNode] = nodes or self._default_nodes()
        self.section_collapse: Dict[str, bool] = {}
        self.selected_index: int = 0
        self.collapsed: bool = False
        self.expand_transition_duration_ms = EXPAND_TRANSITION_MS
        self._transitioning_section: Optional[str] = None
        self.search_field = SearchFieldWidget(
            placeholder="Filter Tree...",
            on_query_change=self.handle_filter_change,
        )

    def handle_filter_change(self, query: str) -> None:
        """Handle real query change from SearchFieldWidget."""
        visible = self.get_visible_nodes()
        self.search_field.update_match_count(len(visible) if query else None)
        self.selected_index = max(0, min(self.selected_index, max(0, len(visible) - 1)))
        self.refresh()

    def set_filter_query(self, query: str) -> None:
        """Programmatically set search query."""
        self.search_field.set_query(query)

    @property
    def filter_query(self) -> str:
        return self.search_field.query

    @filter_query.setter
    def filter_query(self, value: str) -> None:
        self.search_field.set_query(value)

    def _default_nodes(self) -> List[SidebarNode]:
        return [
            SidebarNode("sec_workspaces", "WORKSPACES", "section", "workspaces"),
            SidebarNode("ws_dispatch", "Dispatch", "item", "workspaces", badge="draft"),
            SidebarNode("ws_agents", "Agents Directory", "item", "workspaces"),
            SidebarNode("ws_network", "Trusted Network", "item", "workspaces"),
            SidebarNode("ws_inbox", "Inbox", "item", "workspaces", badge="3"),
            SidebarNode("sec_sessions", "ACTIVE SESSIONS", "section", "sessions"),
            SidebarNode("ses_scout", "Code Scout", "item", "sessions", badge="live"),
            SidebarNode("ses_cleaner", "Data Cleaner", "item", "sessions"),
        ]

    def get_visible_nodes(self) -> List[SidebarNode]:
        """Compute visible nodes considering section collapse state and search query."""
        res: List[SidebarNode] = []
        query = self.filter_query.strip().lower()

        for node in self.nodes:
            if query:
                if query in node.title.lower() or (node.badge and query in node.badge.lower()):
                    res.append(node)
                continue

            if node.kind == "section":
                res.append(node)
            elif node.kind == "item":
                if not self.section_collapse.get(node.section, False):
                    res.append(node)

        return res

    def get_selected_node(self) -> Optional[SidebarNode]:
        vis = self.get_visible_nodes()
        if vis and 0 <= self.selected_index < len(vis):
            return vis[self.selected_index]
        return None

    def cursor_down(self) -> None:
        vis = self.get_visible_nodes()
        if vis and self.selected_index < len(vis) - 1:
            self.selected_index += 1
            self.refresh()

    def cursor_up(self) -> None:
        vis = self.get_visible_nodes()
        if vis and self.selected_index > 0:
            self.selected_index -= 1
            self.refresh()

    def toggle_collapse(self) -> None:
        node = self.get_selected_node()
        if node and node.kind == "section":
            self.section_collapse[node.section] = not self.section_collapse.get(node.section, False)
            self._begin_expand_transition(node.section)

    def _begin_expand_transition(self, section: str) -> None:
        """Show a local transition affordance for the spec-defined window."""
        self._transitioning_section = section
        self.refresh(layout=False)
        if self.is_mounted:
            self.set_timer(
                milliseconds_to_seconds(self.expand_transition_duration_ms),
                self._finish_expand_transition,
            )
        else:
            self._transitioning_section = None

    def _finish_expand_transition(self) -> None:
        self._transitioning_section = None
        self.refresh(layout=False)

    def render(self) -> str:
        state = self.lifecycle_state
        err = self._c("state.error", "#f7768e")
        accent = self._c("accent.primary", "#bb9af7")
        warn = self._c("state.waiting", "#e0af68")

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading workspace tree...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Sidebar disabled"
            return f"[dim]Sidebar (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} Sidebar Error: Navigation node lost. Press [Retry].[/bold {err}]"

        if self.collapsed:
            return "●\n✓\n!\n→\n(1)"

        vis = self.get_visible_nodes()

        if state == WidgetLifecycleState.EMPTY or not vis:
            search_bar = self.search_field.render()
            act_str = f"\n[dim]→ Action: {self._next_action_label}[/dim]" if self._next_action_label else ""
            return f"{search_bar}\n[dim]No matching nodes found.{act_str}[/dim]"

        lines = []
        if self.filter_query:
            lines.append(self.search_field.render())

        for idx, node in enumerate(vis):
            is_selected = (idx == self.selected_index)
            prefix = "▶ " if is_selected else "  "

            if node.kind == "section":
                is_col = self.section_collapse.get(node.section, False)
                arrow = "›" if is_col else "▼"
                lbl = f"[bold dim]{arrow} {node.title}[/bold dim]"
                if node.section == self._transitioning_section:
                    lbl = f"[reverse]{lbl}[/reverse]"
            else:
                badge_str = f" [{accent}]({node.badge})[/{accent}]" if node.badge else ""
                lbl = f"{node.title}{badge_str}"

            if is_selected:
                lines.append(f"[bold {warn}]{prefix}{lbl}[/bold {warn}]")
            else:
                lines.append(f"{prefix}{lbl}")

        if state == WidgetLifecycleState.NARROW:
            sel = self.get_selected_node()
            title = sel.title if sel else "Empty"
            return f"Tree ({len(vis)}): {title}"

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        return "\n".join(lines) + focus_mark
