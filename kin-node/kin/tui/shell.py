"""Stable Shell Regions, Responsive Layout, and Interactive Sidebar Tree for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §3.1, §3.2, §3.3, §4.3, §14.3, §14.4
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
from kin.tui.motion import EXPAND_TRANSITION_MS, milliseconds_to_seconds
from kin.tui.state import HealthSnapshot
from kin.tui.tokens import get_glyph
from kin.tui.widgets.agents_screen import AgentsScreenWidget
from kin.tui.widgets.dispatch_wizard import DispatchWizardWidget
from kin.tui.widgets.home_screen import HomeScreenWidget
from kin.tui.widgets.inbox_screen import InboxScreenWidget
from kin.tui.widgets.network_screen import NetworkScreenWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.search_field import SearchFieldWidget


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


class WorkspaceTabBar(LifecycleWidgetMixin, Static):
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
        accent = self._c("accent.primary", "#bb9af7")
        res = []
        for t in self.tabs:
            if t == self.active_tab:
                res.append(f"[bold {accent}]● {t}[/bold {accent}]")
            else:
                res.append(f"[dim]○ {t}[/dim]")
        return " | ".join(res)


class Sidebar(LifecycleWidgetMixin, Static):
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
        profile_dir: Optional[Path] = None,
        profile_name: str = "default",
        **kwargs,
    ) -> None:
        super().__init__(id="sidebar", **kwargs)
        self.sidebar_width = clamp_sidebar_width(width)
        self.collapsed = collapsed
        self.styles.width = self.sidebar_width
        self.profile_dir = profile_dir
        self.profile_name = profile_name

        # Persistent section collapse state (§4.3)
        self.section_collapse: Dict[str, bool] = section_collapse or {}
        self.expand_transition_duration_ms = EXPAND_TRANSITION_MS
        self._transitioning_section: Optional[str] = None

        # Dynamically build real tree nodes (§A2)
        self.nodes: List[SidebarNode] = []
        self.build_nodes()

        self.selected_index: int = 1  # Default selected on Home item
        self.search_field = SearchFieldWidget(
            placeholder="Filter Tree...",
            on_query_change=self._on_search_query_change,
        )

    def build_nodes(self) -> None:
        """Build real Sidebar tree nodes from local_state queries (§A2)."""
        from pathlib import Path
        from kin.schemas import AgentAvailability
        from kin.tui.local_state import (
            get_local_agents_summaries,
            get_local_contacts_summaries,
            get_needs_you_items,
            get_pending_approvals,
            get_peer_capabilities_recency,
        )

        p_dir = self.profile_dir or (Path.home() / ".kin" / "profiles" / self.profile_name)

        local_agents = get_local_agents_summaries(p_dir, self.profile_name) if p_dir.exists() else []
        contacts = get_local_contacts_summaries(p_dir, self.profile_name) if p_dir.exists() else []
        needs_you_items = get_needs_you_items(p_dir, self.profile_name) if p_dir.exists() else []
        pending_approvals = get_pending_approvals(p_dir, self.profile_name) if p_dir.exists() else []
        total_pending = len(needs_you_items) + len(pending_approvals)

        nodes: List[SidebarNode] = [
            # SPACES
            SidebarNode("sec_spaces", "SPACES", "section", "SPACES"),
            SidebarNode("space_home", "Home", "item", "SPACES", glyph="●", target_tab_id="home"),
            SidebarNode("space_inbox", "Inbox", "item", "SPACES", glyph="●" if total_pending > 0 else "○", badge=str(total_pending) if total_pending > 0 else None, target_tab_id="inbox"),
            SidebarNode("space_recents", "Recent Sessions", "item", "SPACES", glyph="○", target_tab_id="session:recent"),
            # AGENTS
            SidebarNode("sec_agents", "AGENTS", "section", "AGENTS"),
        ]

        if local_agents:
            for card in local_agents:
                is_ready = card.availability in (AgentAvailability.READY, AgentAvailability.BUSY, AgentAvailability.RESERVED) or str(card.availability) in ("ready", "busy", "reserved")
                g = "●" if is_ready else "○"
                detail = card.readiness_reason or card.adapter_kind
                nodes.append(SidebarNode(f"agent_{card.agent_id}", card.name, "item", "AGENTS", glyph=g, detail=detail, target_tab_id="agents"))
        else:
            nodes.append(SidebarNode("agent_empty", "(No local agents)", "item", "AGENTS", glyph="○", target_tab_id="agents"))

        # NETWORK
        nodes.append(SidebarNode("sec_network", "NETWORK", "section", "NETWORK"))
        if contacts:
            for c in contacts:
                recency = get_peer_capabilities_recency(p_dir, c.username) if p_dir.exists() else None
                detail = f"reachable ({recency})" if recency else "cached"
                nodes.append(SidebarNode(f"peer_{c.username}", c.display_name or c.username, "item", "NETWORK", glyph="●" if c.verified_at else "○", detail=detail, target_tab_id="network"))
        else:
            nodes.append(SidebarNode("peer_empty", "(No paired contacts)", "item", "NETWORK", glyph="○", target_tab_id="network"))

        # NEEDS YOU
        nodes.append(SidebarNode("sec_needs_you", "NEEDS YOU", "section", "NEEDS YOU", badge=str(total_pending) if total_pending > 0 else None))
        if total_pending == 0:
            nodes.append(SidebarNode("needs_you_empty", "(All clear)", "item", "NEEDS YOU", glyph="✓", target_tab_id="inbox"))
        else:
            for ny in needs_you_items:
                nodes.append(SidebarNode(f"ny_{ny.item_id}", ny.human_readable_reason, "item", "NEEDS YOU", glyph="!", badge="1", target_tab_id="inbox"))
            for app in pending_approvals:
                app_req = app.request.agent_id if app.request else "agent"
                app_id = app.request.approval_id if app.request else "app"
                nodes.append(SidebarNode(f"app_{app_id}", f"Approval: {app_req}", "item", "NEEDS YOU", glyph="→", badge="1", target_tab_id="inbox"))

        self.nodes = nodes

    def compose(self) -> ComposeResult:
        yield self.search_field

    def _on_search_query_change(self, query: str) -> None:
        vis = self.get_visible_nodes()
        self.search_field.update_match_count(len(vis) if query else None)
        self.refresh()

    @property
    def filter_query(self) -> str:
        return self.search_field.query

    @filter_query.setter
    def filter_query(self, value: str) -> None:
        self.search_field.set_query(value)

    def on_key(self, event) -> None:
        """Forward key events to SearchFieldWidget when filter is active (§14.5)."""
        if self.search_field.lifecycle_state == WidgetLifecycleState.FOCUSED or self.search_field.has_focus or self.search_field.query:
            self.search_field.on_key(event)
            self.refresh()

    def set_width(self, width: int) -> None:
        self.sidebar_width = clamp_sidebar_width(width)
        if not self.collapsed:
            self.styles.width = self.sidebar_width

    def set_collapsed(self, collapsed: bool, *, with_transition: bool = False) -> None:
        self.collapsed = collapsed
        target_width = 4 if self.collapsed else self.sidebar_width
        if with_transition and self.is_mounted:
            self.styles.animate(
                "width",
                value=target_width,
                duration=milliseconds_to_seconds(self.expand_transition_duration_ms),
            )
        else:
            self.styles.width = target_width

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
        self._begin_expand_transition(sec)
        return self.section_collapse[sec]

    def _begin_expand_transition(self, section: str) -> None:
        """Render the section transition locally for the centralized window."""
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

        accent = self._c("accent.primary", "#bb9af7")
        warn = self._c("state.waiting", "#e0af68")

        vis = self.get_visible_nodes()
        lines = []

        if self.filter_query:
            lines.append(f"[bold {warn}]/ {self.filter_query}[/bold {warn}]")

        for idx, node in enumerate(vis):
            is_selected = (idx == self.selected_index)
            prefix = "▶ " if is_selected else "  "

            if node.kind == "section":
                is_col = self.section_collapse.get(node.section, False)
                arrow = "›" if is_col else "▼"
                label = f"{arrow} [bold]{node.title}[/bold]"
                if node.section == self._transitioning_section:
                    label = f"[reverse]{label}[/reverse]"
                if is_selected:
                    lines.append(f"[bold {accent}]{prefix}{label}[/bold {accent}]")
                else:
                    lines.append(f"{prefix}{label}")
            else:  # item
                badge_str = f" [bold {warn}]({node.badge})[/bold {warn}]" if node.badge else ""
                detail_str = f" [dim]({node.detail})[/dim]" if node.detail else ""

                if is_selected:
                    lines.append(f"[bold {accent}]{prefix}{node.glyph} {node.title}{badge_str}{detail_str}[/bold {accent}]")
                else:
                    lines.append(f"{prefix}{node.glyph} {node.title}{badge_str}{detail_str}")

        return "\n".join(lines)


class MainCanvas(LifecycleWidgetMixin, Vertical):
    """Main Canvas region (#main-canvas) per §3.1, §3.3.

    Renders active workspace view content or tab placeholders (§14.6 Phase B).
    """

    DEFAULT_CSS = """
    MainCanvas {
        width: 1fr;
        height: 100%;
        background: $background;
        padding: 1 2;
    }
    """

    def __init__(
        self,
        active_tab_kind: str = "home",
        active_session_id: Optional[str] = None,
        profile_dir: Optional[Path] = None,
        profile_name: str = "default",
        home_widget: Optional[HomeScreenWidget] = None,
        agents_widget: Optional[AgentsScreenWidget] = None,
        network_widget: Optional[NetworkScreenWidget] = None,
        inbox_widget: Optional[InboxScreenWidget] = None,
        dispatch_widget: Optional[DispatchWizardWidget] = None,
        session_arena_widgets: Optional[Dict[str, Widget]] = None,
        **kwargs,
    ) -> None:
        super().__init__(id="main-canvas", **kwargs)
        self.active_tab_kind = active_tab_kind
        self.active_session_id = active_session_id
        self.profile_dir = profile_dir
        self.profile_name = profile_name
        self.home_widget = home_widget or HomeScreenWidget(profile_dir=profile_dir, profile_name=profile_name)
        self.agents_widget = agents_widget or AgentsScreenWidget(profile_dir=profile_dir, profile_name=profile_name)
        self.network_widget = network_widget or NetworkScreenWidget(profile_dir=profile_dir, profile_name=profile_name)
        self.inbox_widget = inbox_widget or InboxScreenWidget(profile_dir=profile_dir, profile_name=profile_name)
        self.dispatch_widget = dispatch_widget or DispatchWizardWidget(profile_dir=profile_dir, profile_name=profile_name)
        self.session_arena_widgets: Dict[str, Widget] = session_arena_widgets or {}

    def set_active_tab_kind(
        self,
        tab_kind: str,
        session_id: Optional[str] = None,
        profile_dir: Optional[Path] = None,
        profile_name: Optional[str] = None,
    ) -> None:
        self.active_tab_kind = tab_kind
        if session_id:
            self.active_session_id = session_id
        if profile_dir:
            self.profile_dir = profile_dir
        if profile_name:
            self.profile_name = profile_name
        self.refresh(recompose=True)

    def get_session_arena_widget(self, session_id: Optional[str] = None) -> Widget:
        sid = session_id or self.active_session_id or "default-session"
        if sid not in self.session_arena_widgets:
            from kin.tui.widgets.session_arena import SessionArenaWidget
            self.session_arena_widgets[sid] = SessionArenaWidget(
                session_id=sid,
                profile_name=self.profile_name,
                profile_dir=self.profile_dir,
            )
        return self.session_arena_widgets[sid]

    def compose(self):
        if self.active_tab_kind == "home":
            yield self.home_widget
        elif self.active_tab_kind == "agents":
            yield self.agents_widget
        elif self.active_tab_kind == "network":
            yield self.network_widget
        elif self.active_tab_kind in ("inbox", "approvals"):
            yield self.inbox_widget
        elif self.active_tab_kind == "dispatch":
            yield self.dispatch_widget
        elif self.active_tab_kind == "session":
            yield self.get_session_arena_widget()
        else:
            accent = self._c("accent.primary", "#bb9af7")
            yield Static(
                f"[bold {accent}]{self.active_tab_kind.upper()} WORKSPACE[/bold {accent}]\n"
                f"[dim]Screen arriving in Phase E/T5/T6.[/dim]\n",
                id="canvas-content",
            )
        yield Input(placeholder="Type command or query...", id="command-input")


class Inspector(LifecycleWidgetMixin, Static):
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


class StatusBar(LifecycleWidgetMixin, Static):
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
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(id="status-bar", now=now, **kwargs)
        self.health = health or HealthSnapshot(
            keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0
        )
        self.profile_name = profile_name
        self.status_message = status_message
        # A newly mounted status bar has not received a health update yet.
        # Keep the initial shell deterministic; update_health() stamps it.
        if now is None:
            self._last_updated_at = None

    def update_health(
        self,
        health: HealthSnapshot,
        status_message: Optional[str] = None,
        now: Optional[Union[datetime, str, float]] = None,
    ) -> None:
        """Update status bar in-place without disturbing focus or cursor position."""
        self.health = health
        if status_message is not None:
            self.status_message = status_message
        self.update_clock(now)
        self.refresh()

    def render(self) -> str:
        ok_color = self._c("state.live", "#73daca")
        err_color = self._c("state.error", "#f7768e")
        warn_color = self._c("state.waiting", "#e0af68")

        glyph_ok = self._g("✓")
        glyph_warn = self._g("!")
        glyph_live = self._g("●")

        def _wrap(text_str: str, col: str) -> str:
            return f"[{col}]{text_str}[/{col}]" if col else text_str

        keychain_str = _wrap(f"{glyph_ok} key", ok_color) if self.health.keychain_ok else _wrap(f"{glyph_warn} KEY", err_color)
        identity_str = _wrap(f"{glyph_ok} id", ok_color) if self.health.identity_ok else _wrap(f"{glyph_warn} ID", err_color)
        relay_str = _wrap(f"{glyph_live} relay", ok_color) if self.health.relay_reachable else _wrap(f"{glyph_warn} RELAY", warn_color)
        node_str = _wrap(f"{glyph_live} node", ok_color) if self.health.node_reachable else _wrap(f"{glyph_warn} NODE", warn_color)

        inbox_str = f"inbox:{self.health.pending_inbox_count}"

        if self.health.degraded_reason:
            msg = f" | {_wrap(f'({self.health.degraded_reason})', warn_color)}"
        elif self.status_message:
            msg = f" | [dim]{self.status_message}[/dim]"
        else:
            msg = ""

        time_str = ""
        if self._last_updated_at:
            time_str = f" | [dim]{self._last_updated_at.strftime('%H:%M:%S')}[/dim]"

        return f"profile:{self.profile_name} | {keychain_str} {identity_str} {relay_str} {node_str} | {inbox_str}{msg}{time_str}"


from kin.tui.widgets.modal import ModalScreenWidget


class ConfirmationModal(ModalScreenWidget):
    """Modal screen for gating dangerous / consequential actions (§5.3, §14.4, §14.5).

    Extends foundation ModalScreenWidget to guarantee unified keyboard handling (y/n/escape) and button consistency.
    """

    def __init__(self, action_name: str, target_name: str, **kwargs) -> None:
        accent = self._c("accent.primary", "#bb9af7")
        super().__init__(
            title="CONFIRMATION REQUIRED",
            body_text=f"Are you sure you want to execute '[bold]{action_name}[/bold]' on [{accent}]{target_name}[/{accent}]?",
            confirm_label="Confirm (y)",
            cancel_label="Cancel (n)",
            variant="error",
            **kwargs,
        )
        self.action_name = action_name
        self.target_name = target_name
