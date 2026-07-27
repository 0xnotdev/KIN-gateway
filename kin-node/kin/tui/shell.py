"""Stable Shell Regions, Responsive Layout, and Interactive Sidebar Tree for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §3.1, §3.2, §3.3, §4.3, §14.3, §14.4
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Static

from kin.tui.layout import (
    INSPECTOR_DEFAULT_WIDTH,
    INSPECTOR_MAX_WIDTH,
    INSPECTOR_MIN_WIDTH,
    SIDEBAR_DEFAULT_WIDTH,
    SIDEBAR_MAX_WIDTH,
    SIDEBAR_MIN_WIDTH,
    Breakpoint,
    clamp_inspector_width,
    clamp_sidebar_width,
)
from kin.tui.state import HealthSnapshot
from kin.tui.tokens import get_glyph


@dataclass
class SidebarNode:
    """Represents a node or item within the sidebar navigation tree (§4.3)."""

    node_id: str
    title: str
    kind: str  # "section" or "item"
    section: str
    glyph: str = "○"
    badge: Optional[str] = None
    detail: str = ""
    target_tab_id: Optional[str] = None


class WorkspaceTabBar(Static):
    """Workspace tab bar region (#workspace-tab-bar) per §3.1, §4.2."""

    DEFAULT_CSS = """
    WorkspaceTabBar {
        dock: top;
        height: 1;
        background: $surface;
        color: $text;
        content-align: left middle;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(id="workspace-tab-bar", **kwargs)
        self.tabs = ["home"]
        self.active_tab = "home"

    def render(self) -> str:
        res = []
        for t in self.tabs:
            if t == self.active_tab:
                res.append(f"[bold cyan]● {t}[/bold cyan]")
            else:
                res.append(f"[dim]○ {t}[/dim]")
        return " | ".join(res)


class Sidebar(Static):
    """Sidebar region (#sidebar) per §3.1, §3.3, §4.3.

    Supports interactive tree navigation (j/k, g/G, Enter, Space, h/l, /),
    persistent section collapse state, and sticky selection with nearest sibling fallback.
    """

    DEFAULT_CSS = """
    Sidebar {
        width: 32;
        height: 100%;
        background: $surface-darken-1;
        border-right: heavy $primary-darken-2;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        width: int = SIDEBAR_DEFAULT_WIDTH,
        collapsed: bool = False,
        section_collapse: Optional[Dict[str, bool]] = None,
        **kwargs,
    ) -> None:
        super().__init__(id="sidebar", **kwargs)
        self.sidebar_width = clamp_sidebar_width(width)
        self.collapsed = collapsed
        self.styles.width = self.sidebar_width

        # Persistent section collapse state (§4.3)
        self.section_collapse: Dict[str, bool] = section_collapse or {}

        # Default tree nodes populated from fixtures (§4.3)
        self.nodes: List[SidebarNode] = [
            # SPACES
            SidebarNode("sec_spaces", "SPACES", "section", "SPACES"),
            SidebarNode("space_home", "Home", "item", "SPACES", glyph="●", target_tab_id="home"),
            SidebarNode("space_inbox", "Inbox", "item", "SPACES", glyph="○", badge="3", target_tab_id="inbox"),
            SidebarNode("space_recents", "Recent Sessions", "item", "SPACES", glyph="○", target_tab_id="session:recent"),
            # AGENTS
            SidebarNode("sec_agents", "AGENTS", "section", "AGENTS"),
            SidebarNode("agent_scout", "Code Scout", "item", "AGENTS", glyph="✓", detail="ready", target_tab_id="agents"),
            SidebarNode("agent_cleaner", "Data Cleaner", "item", "AGENTS", glyph="!", detail="working", target_tab_id="agents"),
            # NETWORK
            SidebarNode("sec_network", "NETWORK", "section", "NETWORK"),
            SidebarNode("peer_bob", "Bob", "item", "NETWORK", glyph="●", detail="3 agents", target_tab_id="network"),
            SidebarNode("peer_priya", "Priya", "item", "NETWORK", glyph="○", detail="offline", target_tab_id="network"),
            # NEEDS YOU
            SidebarNode("sec_needs_you", "NEEDS YOU", "section", "NEEDS YOU"),
            SidebarNode("req_approval", "Write Approval", "item", "NEEDS YOU", glyph="→", badge="1", target_tab_id="inbox"),
        ]

        self.selected_index: int = 1  # Default selected on Home item
        self.filter_query: str = ""

    def set_width(self, width: int) -> None:
        self.sidebar_width = clamp_sidebar_width(width)
        if not self.collapsed:
            self.styles.width = self.sidebar_width

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        if self.collapsed:
            self.styles.width = 4
        else:
            self.styles.width = self.sidebar_width

    def get_visible_nodes(self) -> List[SidebarNode]:
        """Compute list of visible nodes respecting section collapse and filter query."""
        visible: List[SidebarNode] = []
        current_section = ""
        is_section_collapsed = False

        clean_q = self.filter_query.strip().lower()

        for node in self.nodes:
            if node.kind == "section":
                current_section = node.section
                is_section_collapsed = self.section_collapse.get(current_section, False)

                # Filter check
                if clean_q:
                    # In filter mode, section is shown if any child matches
                    child_matches = any(
                        clean_q in child.title.lower() for child in self.nodes if child.section == current_section and child.kind == "item"
                    )
                    if child_matches or clean_q in node.title.lower():
                        visible.append(node)
                else:
                    visible.append(node)
            else:  # item
                if is_section_collapsed and not clean_q:
                    continue

                if clean_q:
                    if clean_q in node.title.lower() or clean_q in node.section.lower():
                        visible.append(node)
                else:
                    visible.append(node)

        return visible

    def get_selected_node(self) -> Optional[SidebarNode]:
        vis = self.get_visible_nodes()
        if not vis:
            return None
        self.selected_index = max(0, min(self.selected_index, len(vis) - 1))
        return vis[self.selected_index]

    def move_selection(self, delta: int) -> Optional[SidebarNode]:
        """Move tree selection up or down by delta."""
        vis = self.get_visible_nodes()
        if not vis:
            return None
        self.selected_index = max(0, min(self.selected_index + delta, len(vis) - 1))
        self.refresh()
        return vis[self.selected_index]

    def move_to_boundary(self, first: bool = True) -> Optional[SidebarNode]:
        """Move tree selection to top (g) or bottom (G)."""
        vis = self.get_visible_nodes()
        if not vis:
            return None
        self.selected_index = 0 if first else len(vis) - 1
        self.refresh()
        return vis[self.selected_index]

    def toggle_section_collapse(self, section_name: Optional[str] = None) -> bool:
        """Toggle collapsed state of current or specified section (§4.3)."""
        sec = section_name
        if not sec:
            selected = self.get_selected_node()
            if selected:
                sec = selected.section
            else:
                sec = "SPACES"

        current = self.section_collapse.get(sec, False)
        self.section_collapse[sec] = not current
        self.refresh()
        return self.section_collapse[sec]

    def remove_node(self, node_id: str) -> Tuple[bool, Optional[str]]:
        """Remove a node from tree and execute sticky selection fallback (§4.3).

        If the currently selected row disappears, selection moves to nearest sibling
        (or section parent) and returns a one-line status message.
        """
        target = None
        for n in self.nodes:
            if n.node_id == node_id:
                target = n
                break

        if not target:
            return False, "Node not found."

        vis_before = self.get_visible_nodes()
        curr_selected = self.get_selected_node()
        was_selected = (curr_selected and curr_selected.node_id == node_id)

        self.nodes.remove(target)
        vis_after = self.get_visible_nodes()

        if not vis_after:
            self.selected_index = 0
            return True, f"Removed '{target.title}'; tree empty."

        if was_selected:
            # Sticky selection fallback to nearest sibling
            new_idx = max(0, min(self.selected_index, len(vis_after) - 1))
            self.selected_index = new_idx
            new_selected = vis_after[new_idx]
            msg = f"Selection moved to nearest sibling '{new_selected.title}' after '{target.title}' removed."
        else:
            msg = f"Removed '{target.title}'."

        self.refresh()
        return True, msg

    def render(self) -> str:
        if self.collapsed:
            return "●\n✓\n!\n→\n(1)"

        vis = self.get_visible_nodes()
        lines = []

        if self.filter_query:
            lines.append(f"[bold yellow]/ {self.filter_query}[/bold yellow]")

        for idx, node in enumerate(vis):
            is_selected = (idx == self.selected_index)
            prefix = "▶ " if is_selected else "  "

            if node.kind == "section":
                is_col = self.section_collapse.get(node.section, False)
                arrow = "›" if is_col else "▼"
                label = f"{arrow} [bold]{node.title}[/bold]"
                if is_selected:
                    lines.append(f"[bold cyan]{prefix}{label}[/bold cyan]")
                else:
                    lines.append(f"{prefix}{label}")
            else:  # item
                badge_str = f" [bold yellow]({node.badge})[/bold yellow]" if node.badge else ""
                detail_str = f" [dim]({node.detail})[/dim]" if node.detail else ""

                if is_selected:
                    lines.append(f"[bold cyan]{prefix}{node.glyph} {node.title}{badge_str}{detail_str}[/bold cyan]")
                else:
                    lines.append(f"{prefix}{node.glyph} {node.title}{badge_str}{detail_str}")

        return "\n".join(lines)


class MainCanvas(Vertical):
    """Main canvas region (#main-canvas) per §3.1."""

    DEFAULT_CSS = """
    MainCanvas {
        width: 1fr;
        height: 100%;
        background: $background;
        padding: 1 2;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(id="main-canvas", **kwargs)

    def compose(self):
        yield Static(
            "[bold green]KIN V1.1 TUI Shell[/bold green]\n"
            "Five Stable Regions Mounted: [TabBar | Sidebar | Canvas | Inspector | StatusBar]\n\n"
            "[bold yellow]ACTIVE APPROVAL REQUEST (HIGH RISK)[/bold yellow]\n"
            "Agent 'code-scout' requests WORKSPACE_WRITE for /work/src/main.py\n",
            id="canvas-content",
        )
        yield Input(placeholder="Type command or query...", id="command-input")


class Inspector(Static):
    """Inspector panel region (#inspector) per §3.1, §3.3.

    Default width: 38; Min: 30; Max: 52.
    Renders preview information when space is pressed on a sidebar item.
    """

    DEFAULT_CSS = """
    Inspector {
        width: 38;
        height: 100%;
        background: $surface-darken-1;
        border-left: heavy $primary-darken-2;
        padding: 0 1;
    }
    """

    def __init__(self, width: int = INSPECTOR_DEFAULT_WIDTH, visible: bool = True, **kwargs) -> None:
        super().__init__(id="inspector", **kwargs)
        self.inspector_width = clamp_inspector_width(width)
        self.visible_state = visible
        self.preview_title: str = "INSPECTOR"
        self.preview_content: str = (
            "Agent: code-scout\n"
            "Status: READY\n"
            "Adapter: sonnet-3.5\n"
            "Scope: workspace_write\n"
        )
        self.styles.width = self.inspector_width
        if not visible:
            self.styles.display = "none"

    def set_width(self, width: int) -> None:
        self.inspector_width = clamp_inspector_width(width)
        self.styles.width = self.inspector_width

    def set_visible(self, visible: bool) -> None:
        self.visible_state = visible
        self.styles.display = "block" if visible else "none"

    def preview_item(self, node: SidebarNode) -> None:
        """Update inspector preview content from sidebar node selection (§4.3)."""
        self.preview_title = f"INSPECTOR: {node.title}"
        self.preview_content = (
            f"ID: {node.node_id}\n"
            f"Kind: {node.kind}\n"
            f"Section: {node.section}\n"
            f"Detail: {node.detail or 'N/A'}\n"
            f"Badge: {node.badge or 'None'}\n"
        )
        self.refresh()

    def render(self) -> str:
        return f"[bold]{self.preview_title}[/bold]\n{self.preview_content}"


class StatusBar(Static):
    """Status bar region (#status-bar) per §3.1, §5.

    Renders HealthSnapshot status in-place using tokens.py glyphs.
    Supports an injectable clock for health degradation labels.
    """

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text;
        content-align: left middle;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        health: Optional[HealthSnapshot] = None,
        profile_name: str = "default",
        status_message: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(id="status-bar", **kwargs)
        self.health = health or HealthSnapshot(
            keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0
        )
        self.profile_name = profile_name
        self.status_message = status_message
        self.last_updated_at: Optional[datetime] = None

    def update_health(
        self,
        health: HealthSnapshot,
        status_message: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> None:
        """Update status bar in-place without disturbing focus or cursor position."""
        self.health = health
        if status_message is not None:
            self.status_message = status_message

        if now is not None:
            if isinstance(now, datetime):
                self.last_updated_at = now
            elif isinstance(now, str):
                try:
                    self.last_updated_at = datetime.fromisoformat(now)
                except ValueError:
                    self.last_updated_at = datetime.now(timezone.utc)
        else:
            self.last_updated_at = datetime.now(timezone.utc)

        self.refresh()

    def render(self) -> str:
        glyph_ok = get_glyph("✓", ascii_fallback=False)
        glyph_warn = get_glyph("!", ascii_fallback=False)
        glyph_live = get_glyph("●", ascii_fallback=False)

        keychain_str = f"[green]{glyph_ok} key[/green]" if self.health.keychain_ok else f"[red]{glyph_warn} KEY[/red]"
        identity_str = f"[green]{glyph_ok} id[/green]" if self.health.identity_ok else f"[red]{glyph_warn} ID[/red]"
        relay_str = f"[green]{glyph_live} relay[/green]" if self.health.relay_reachable else f"[yellow]{glyph_warn} RELAY[/yellow]"
        node_str = f"[green]{glyph_live} node[/green]" if self.health.node_reachable else f"[yellow]{glyph_warn} NODE[/yellow]"

        inbox_str = f"inbox:{self.health.pending_inbox_count}"

        if self.health.degraded_reason:
            msg = f" | [yellow]({self.health.degraded_reason})[/yellow]"
        elif self.status_message:
            msg = f" | [dim]{self.status_message}[/dim]"
        else:
            msg = ""

        time_str = ""
        if self.last_updated_at:
            time_str = f" | [dim]{self.last_updated_at.strftime('%H:%M:%S')}[/dim]"

        return f"profile:{self.profile_name} | {keychain_str} {identity_str} {relay_str} {node_str} | {inbox_str}{msg}{time_str}"


class ConfirmationModal(ModalScreen[bool]):
    """Modal screen for gating dangerous / consequential actions (§5.3, §14.4)."""

    DEFAULT_CSS = """
    ConfirmationModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #confirm-container {
        width: 56;
        height: 11;
        background: $surface-darken-1;
        border: thick $error;
        padding: 1 2;
    }
    #confirm-buttons {
        height: 3;
        margin-top: 1;
        align: center middle;
    }
    """

    def __init__(self, action_name: str, target_name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.action_name = action_name
        self.target_name = target_name

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Static("[bold red]CONFIRMATION REQUIRED[/bold red]", id="confirm-header")
            yield Static(
                f"Are you sure you want to execute '[bold]{self.action_name}[/bold]' on [cyan]{self.target_name}[/cyan]?",
                id="confirm-body",
            )
            with Horizontal(id="confirm-buttons"):
                yield Button("Confirm (y)", id="btn-confirm", variant="error")
                yield Button("Cancel (n)", id="btn-cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def on_key(self, event) -> None:
        if event.key in ("y", "Y"):
            self.dismiss(True)
        elif event.key in ("n", "N", "escape"):
            self.dismiss(False)
