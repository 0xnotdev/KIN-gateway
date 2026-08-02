"""Home Screen Widget for KIN V1.1 TUI (§14.6 Phase B).

Composes Agent Roster preview, Network summary, Needs You approval queue,
and Live/Recent sessions into a unified responsive dashboard.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from kin.tui.local_state import (
    get_local_agents_summaries,
    get_local_contacts_summaries,
    query_health_snapshot,
)
from kin.tui.state import (
    AgentCardView,
    ApprovalView,
    ContactSummary,
    HealthSnapshot,
    SessionSummary,
)
from kin.tui.widgets.approval_card import ApprovalCardWidget
from kin.tui.widgets.badge import BadgeWidget
from kin.tui.widgets.empty_state import EmptyStateWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.panel import PanelWidget
from kin.tui.widgets.session_map import SessionMapWidget
from kin.tui.widgets.status_line import StatusLineWidget


class HomeScreenWidget(LifecycleWidgetMixin, Static):
    """Home Screen & Live Dashboard Widget (§14.6 Phase B).

    Combines real local data (agents, contacts, health) with fixture data (sessions, approvals).
    Implements bounded rendering for 100-sessions / 20-agents scale performance.
    """

    can_focus = True

    DEFAULT_CSS = """
    HomeScreenWidget {
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
        agents: Optional[List[AgentCardView]] = None,
        contacts: Optional[List[ContactSummary]] = None,
        sessions: Optional[List[SessionSummary]] = None,
        approvals: Optional[List[ApprovalView]] = None,
        health: Optional[HealthSnapshot] = None,
        client: Optional[httpx.Client] = None,
        max_visible_sessions: int = 10,
        max_visible_agents: int = 6,
        **kwargs,
    ) -> None:
        super().__init__(id="home-screen-widget", **kwargs)
        self.profile_name = profile_name
        self.profile_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)

        # Injectable / overridden state
        self._agents_override = agents
        self._contacts_override = contacts
        self.sessions = sessions or []
        self.approvals = approvals or []
        self._health_override = health
        self.client = client
        self.max_visible_sessions = max_visible_sessions
        self.max_visible_agents = max_visible_agents

        self.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    def get_agents(self) -> List[AgentCardView]:
        if self._agents_override is not None:
            return self._agents_override
        return get_local_agents_summaries(self.profile_dir)

    def get_contacts(self) -> List[ContactSummary]:
        if self._contacts_override is not None:
            return self._contacts_override
        return get_local_contacts_summaries(self.profile_dir, self.profile_name)

    def get_health(self) -> HealthSnapshot:
        if self._health_override is not None:
            return self._health_override
        return query_health_snapshot(self.profile_name, self.profile_dir, client=self.client)

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable."""
        try:
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def render(self) -> RenderableType:
        accent = self._c("accent.primary", "#bb9af7")
        ok = self._c("state.live", "#73daca")
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent2 = self._c("accent.secondary", "#9d7cd8")
        highlight = self._c("accent.highlight", "#7aa2f7")

        if self.lifecycle_state == WidgetLifecycleState.LOADING:
            return Panel("[dim]Loading Home Dashboard...[/dim]", title="Home", border_style="cyan")

        if self.lifecycle_state == WidgetLifecycleState.RECOVERABLE_ERROR and self.recoverable_error:
            return Panel(
                f"[bold {err}]Home Dashboard Error[/bold {err}]\n{self.recoverable_error.what_happened}",
                title="Error",
                border_style="red",
            )

        health = self.get_health()
        agents = self.get_agents()
        contacts = self.get_contacts()

        layout_table = Table.grid(expand=True)
        layout_table.add_column()

        # 1. Health & Status Banner
        if health.identity_ok and health.relay_reachable:
            status_label, status_code, health_color, health_hex = "HEALTHY", 100, "green", ok
            detail = f"Profile '{self.profile_name}' online • Relay connected"
        elif health.identity_ok:
            status_label, status_code, health_color, health_hex = "DEGRADED", 50, "yellow", warn
            detail = health.degraded_reason or f"Profile '{self.profile_name}' local only • Relay offline"
        else:
            status_label, status_code, health_color, health_hex = "NO_IDENTITY", 0, "red", err
            detail = health.degraded_reason or "No local identity initialized • Run First Flight setup"

        header_panel = Panel(
            f"[{health_hex}][bold]{status_label}[/bold] ({status_code}/100)[/{health_hex}] — {detail}\n"
            f"[dim]Profile: {self.profile_name} | Agents: {len(agents)} | Contacts: {len(contacts)} | Needs You: {len(self.approvals)} | Sessions: {len(self.sessions)}[/dim]",
            title=f"[bold {accent}]KIN V1.1 HOME DASHBOARD[/bold {accent}]",
            border_style=health_color,
        )
        layout_table.add_row(header_panel)

        # 5-Second Discovery Affordance for brand-new empty profiles (§14.6 Phase B)
        if len(agents) == 0 and len(contacts) == 0:
            discovery_panel = Panel(
                f"[bold {warn}]🚀 FIRST FLIGHT ONBOARDING RECOMMENDED[/bold {warn}]\n\n"
                "Welcome to KIN V1.1! Your profile is empty. To get started:\n"
                " • Run First Flight wizard to initialize identity, connect agents & relay.\n"
                " • Or press [Ctrl+P] / type [bold]/init[/bold] in command bar.\n\n"
                "[dim]Next Action: Complete First Flight setup step to unlock agent dispatch.[/dim]",
                title="[bold gold1]Getting Started[/bold gold1]",
                border_style="yellow",
            )
            layout_table.add_row(discovery_panel)

        # 2. Needs You Approval Queue Section
        if self.approvals:
            approval_table = Table(title=f"[bold {warn}]⚠️ Needs You (Pending Approvals)[/bold {warn}]", expand=True, show_edge=True)
            approval_table.add_column("Agent / Requester", style=accent)
            approval_table.add_column("Action / Reason", style="white")
            approval_table.add_column("Risk", style=f"bold {err}")

            for app_v in self.approvals[:5]:  # Bounded top 5
                req = app_v.request
                agent_id = getattr(req, "agent_id", getattr(req, "requester_username", "system"))
                action_class = getattr(req, "action_class", getattr(req, "action_type", "action"))
                reason = getattr(req, "reason", "")
                risk = str(getattr(req, "risk_label", "HIGH")).upper()
                approval_table.add_row(
                    str(agent_id),
                    f"{action_class}: {reason}",
                    risk,
                )
            layout_table.add_row(approval_table)

        # 3. Agent Roster Preview Section (Bounded rendering for scale performance)
        agent_table = Table(title=f"[bold {ok}]Agent Roster Preview ({len(agents)} Total)[/bold {ok}]", expand=True, show_edge=True)
        agent_table.add_column("ID / Name", style="bold white")
        agent_table.add_column("Description", style="dim")
        agent_table.add_column("Status", style=f"bold {accent}")
        agent_table.add_column("Capabilities", style=highlight)

        visible_agents = agents[: self.max_visible_agents]
        for ag in visible_agents:
            agent_table.add_row(
                f"{ag.name} ({ag.agent_id})",
                ag.description or "-",
                ag.availability.upper(),
                ", ".join(ag.capabilities_tags) if ag.capabilities_tags else "general",
            )
        if len(agents) > self.max_visible_agents:
            agent_table.add_row(
                f"[dim]+ {len(agents) - self.max_visible_agents} more agents...[/dim]",
                "[dim]View full list in Agents tab[/dim]",
                "",
                "",
            )
        layout_table.add_row(agent_table)

        # 4. Network Summary Section (Contacts)
        network_table = Table(title=f"[bold {accent2}]Network Summary ({len(contacts)} Paired Contacts)[/bold {accent2}]", expand=True, show_edge=True)
        network_table.add_column("Contact", style="bold white")
        network_table.add_column("Endpoint", style=accent)
        network_table.add_column("Fingerprint", style="dim")
        network_table.add_column("Autonomy", style=ok)

        if contacts:
            for c in contacts[:5]:  # Bounded top 5
                network_table.add_row(
                    f"{c.display_name} (@{c.username})",
                    c.endpoint,
                    c.fingerprint[:16] + "..." if c.fingerprint else "Unverified",
                    c.autonomy_level,
                )
        else:
            network_table.add_row("[dim]No paired contacts yet[/dim]", "-", "-", "-")
        layout_table.add_row(network_table)

        # 5. Live & Recent Sessions Section (Bounded rendering for virtualization scale)
        session_table = Table(title=f"[bold {highlight}]Live & Recent Sessions ({len(self.sessions)} Total)[/bold {highlight}]", expand=True, show_edge=True)
        session_table.add_column("Session ID", style="bold white")
        session_table.add_column("Participants", style="white")
        session_table.add_column("Status", style=f"bold {warn}")
        session_table.add_column("Last Activity", style="dim")

        visible_sessions = self.sessions[: self.max_visible_sessions]
        for s in visible_sessions:
            session_table.add_row(
                s.session_id,
                ", ".join(s.participant_display_names) if s.participant_display_names else "Session",
                s.status.upper(),
                s.last_activity_at[:19] if s.last_activity_at else "-",
            )
        if len(self.sessions) > self.max_visible_sessions:
            session_table.add_row(
                f"[dim]+ {len(self.sessions) - self.max_visible_sessions} more sessions...[/dim]",
                "[dim]Use SessionMap for full virtualization[/dim]",
                "",
                "",
            )
        layout_table.add_row(session_table)

        return layout_table
