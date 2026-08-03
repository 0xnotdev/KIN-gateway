"""Agents Screen & Detail View Widget for KIN V1.1 TUI (§14.6 Phase C).

Composes interactive agent roster table, capability filter bar, split-pane
detail inspector using AgentCardWidget, and stale-card review flow.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from kin.tui.local_state import (
    get_all_agent_summaries,
    get_local_contacts_summaries,
    review_peer_card_staleness,
    toggle_local_agent_enabled,
)
from kin.tui.state import AgentCardView, ContactSummary, HealthSnapshot
from kin.tui.widgets.agent_card import AgentCardWidget
from kin.tui.widgets.badge import BadgeWidget
from kin.tui.widgets.empty_state import EmptyStateWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.search_field import SearchFieldWidget


class AgentsScreenWidget(LifecycleWidgetMixin, Static):
    """Agent Roster & Detail View Widget (§14.6 Phase C).

    Provides interactive split-pane navigation, capability filtering,
    local vs peer security boundary enforcement, readiness reason displays,
    and stale-card review workflow.
    """

    DEFAULT_CSS = """
    AgentsScreenWidget {
        width: 100%;
        height: 100%;
        background: $surface;
        color: $text;
        overflow-y: auto;
    }
    """

    def __init__(
        self,
        profile_name: str = "default",
        profile_dir: Optional[Path] = None,
        local_agents: Optional[List[AgentCardView]] = None,
        peer_agents: Optional[List[AgentCardView]] = None,
        contacts: Optional[List[ContactSummary]] = None,
        selected_agent_id: Optional[str] = None,
        filter_tag: Optional[str] = None,
        search_query: str = "",
        **kwargs,
    ) -> None:
        super().__init__(id="agents-screen-widget", **kwargs)
        self.profile_name = profile_name
        self.profile_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)

        self._local_agents_override = local_agents
        self._peer_agents_override = peer_agents
        self._contacts_override = contacts

        self.selected_agent_id = selected_agent_id
        self.filter_tag = filter_tag
        self.search_query = search_query

        self.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    def get_agent_lists(self) -> tuple[List[AgentCardView], List[AgentCardView]]:
        if self._local_agents_override is not None and self._peer_agents_override is not None:
            return self._local_agents_override, self._peer_agents_override
        return get_all_agent_summaries(self.profile_dir, self.profile_name)

    def get_contacts(self) -> List[ContactSummary]:
        if self._contacts_override is not None:
            return self._contacts_override
        return get_local_contacts_summaries(self.profile_dir, self.profile_name)

    def select_agent(self, agent_id: str) -> None:
        self.selected_agent_id = agent_id
        self.refresh()

    def render(self) -> RenderableType:
        accent = self._c("accent.primary", "#bb9af7")
        ok = self._c("state.live", "#73daca")
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent2 = self._c("accent.secondary", "#9d7cd8")
        hl = self._c("accent.highlight", "#7aa2f7")

        if self.lifecycle_state == WidgetLifecycleState.LOADING:
            return Panel("[dim]Loading Agent Roster...[/dim]", title="Agents", border_style="cyan")

        if self.lifecycle_state == WidgetLifecycleState.RECOVERABLE_ERROR and self.recoverable_error:
            return Panel(
                f"[bold {err}]Agents Screen Error[/bold {err}]\n{self.recoverable_error.what_happened}",
                title="Error",
                border_style="red",
            )

        local_agents, peer_agents = self.get_agent_lists()
        contacts = self.get_contacts()
        all_agents = local_agents + peer_agents

        # Filter by search query or capability tag
        filtered_agents = all_agents
        if self.search_query:
            q = self.search_query.lower()
            filtered_agents = [
                a for a in filtered_agents
                if q in a.name.lower() or q in a.agent_id.lower() or q in (a.description or "").lower()
            ]
        if self.filter_tag:
            filtered_agents = [
                a for a in filtered_agents
                if self.filter_tag in a.capabilities_tags
            ]

        # Check unpaired / empty states
        if len(all_agents) == 0:
            return Panel(
                f"[bold {warn}]NO AGENTS CONFIGURED[/bold {warn}]\n\n"
                "Your local agent roster is empty. You can:\n"
                " • Import a local agent YAML card file\n"
                " • Or pair contacts in the Network screen to discover peer agents.\n\n"
                "[dim]Press [I] or run /import to connect an agent card file.[/dim]",
                title=f"[bold {ok}]Agents Workspace[/bold {ok}]",
                border_style="yellow",
            )

        # Unpaired state check (§14.6 Phase C)
        if len(peer_agents) == 0 and len(contacts) == 0 and len(local_agents) > 0 and self.filter_tag == "peer":
            return Panel(
                f"[bold {accent}]UNPAIRED STATE — NO PEER AGENTS VISIBLE[/bold {accent}]\n\n"
                "You currently have zero paired trusted contacts.\n"
                "Peer agents are only visible after pairing trusted contacts in the Network screen.\n\n"
                "[dim]Next Action: Pair a contact in the Network tab to view peer cards.[/dim]",
                title=f"[bold {accent2}]Peer Agents[/bold {accent2}]",
                border_style="cyan",
            )

        # Ensure default selected agent
        if not self.selected_agent_id and filtered_agents:
            self.selected_agent_id = filtered_agents[0].agent_id

        selected_card_view = next((a for a in filtered_agents if a.agent_id == self.selected_agent_id), None)
        if not selected_card_view and filtered_agents:
            selected_card_view = filtered_agents[0]
            self.selected_agent_id = selected_card_view.agent_id

        # Render Main Split Table
        main_table = Table.grid(expand=True)
        main_table.add_column(ratio=6)  # Left roster table
        main_table.add_column(ratio=5)  # Right detail inspector

        # Left Roster Table
        roster_table = Table(
            title=f"[bold {ok}]AGENTS ROSTER ({len(filtered_agents)} / {len(all_agents)})[/bold {ok}]",
            expand=True,
            show_edge=True,
        )
        roster_table.add_column("Sel", style=f"bold {warn}", width=3)
        roster_table.add_column("Agent ID / Name", style="bold white")
        roster_table.add_column("Kind", style=accent)
        roster_table.add_column("Status", style=f"bold {ok}")
        roster_table.add_column("Capabilities", style=hl)

        for ag in filtered_agents:
            sel_mark = "▶" if ag.agent_id == self.selected_agent_id else " "
            kind_str = "PEER" if ag.is_peer else "LOCAL"
            status_style = f"bold {ok}" if ag.availability == "active" or ag.availability == "ready" else f"bold {warn}"
            
            # Capability chips via Badge representation
            caps_str = ", ".join(ag.capabilities_tags[:3]) if ag.capabilities_tags else "general"

            roster_table.add_row(
                sel_mark,
                f"{ag.name} ({ag.agent_id})",
                kind_str,
                f"[{status_style}]{ag.availability.upper()}[/{status_style}]",
                caps_str,
            )

        # Right Detail Inspector Panel (Reusing AgentCardWidget as-is for peer safety)
        if selected_card_view:
            detail_widget = AgentCardWidget(card_view=selected_card_view)
            detail_rendered = detail_widget.render()

            # Render Stale Card Review Banner if applicable (§14.6 Phase C)
            if selected_card_view.is_peer and selected_card_view.readiness_reason and "updated" in selected_card_view.readiness_reason.lower():
                stale_banner = Panel(
                    f"[bold {warn}]⚠️ PEER CARD UPDATED — REVIEW REQUIRED[/bold {warn}]\n"
                    "This peer agent has published an updated card specification.\n"
                    "Review capabilities and press [Acknowledge Review] to mark fresh.",
                    title=f"[bold {warn}]Stale Review[/bold {warn}]",
                    border_style="yellow",
                )
                detail_panel = Table.grid(expand=True)
                detail_panel.add_row(stale_banner)
                detail_panel.add_row(detail_rendered)
                right_renderable = detail_panel
            else:
                right_renderable = detail_rendered
        else:
            right_renderable = Panel("[dim]Select an agent to inspect details.[/dim]", title="Detail")

        main_table.add_row(roster_table, right_renderable)
        return main_table
