"""Network Screen Widget for KIN V1.1 TUI (§14.6 Phase D).

Displays paired contacts, word-based fingerprints, cached reachability recency,
peer-card freshness count navigation trigger, and empty state.
Zero live network calls during render; zero public-discovery/search directory controls.
"""

from pathlib import Path
from typing import List, Optional

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static

from kin.tui.local_state import (
    get_local_contacts_summaries,
    get_peer_capabilities_recency,
    get_stale_peer_card_count,
)
from kin.tui.redaction import redact_ui_text
from kin.tui.state import ContactSummary
from kin.tui.widgets.empty_state import EmptyStateWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class NetworkScreenWidget(LifecycleWidgetMixin, Static):
    """Network & Trusted Contacts Screen (§14.6 Phase D).

    Renders paired contacts, fingerprint verification status, reachability recency,
    and peer card freshness alerts.
    """

    DEFAULT_CSS = """
    NetworkScreenWidget {
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
        contacts: Optional[List[ContactSummary]] = None,
        selected_username: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(id="network-screen-widget", **kwargs)
        self.profile_name = profile_name
        self.profile_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)
        self._contacts_override = contacts
        self.selected_username = selected_username

        self.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    def get_contacts(self) -> List[ContactSummary]:
        if self._contacts_override is not None:
            return self._contacts_override
        return get_local_contacts_summaries(self.profile_dir, self.profile_name)

    def render(self) -> Panel | Table:
        accent = self._c("accent.primary", "#bb9af7")
        ok = self._c("state.live", "#73daca")
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent2 = self._c("accent.secondary", "#9d7cd8")
        hl = self._c("accent.highlight", "#7aa2f7")

        if self.lifecycle_state == WidgetLifecycleState.LOADING:
            return Panel("[dim]Loading Trusted Contacts...[/dim]", title="Network", border_style="cyan")

        contacts = self.get_contacts()

        # Unpaired State (§14.6 Phase D2.3)
        if len(contacts) == 0:
            return Panel(
                f"[bold {warn}]ZERO PAIRED TRUSTED CONTACTS[/bold {warn}]\n\n"
                "You currently have no paired contacts in your network.\n"
                "To pair a contact:\n"
                f" • Run [bold {accent}]kin pair <code>[/bold {accent}] in your terminal\n"
                " • Or complete First Flight's guided pairing step.\n\n"
                "[dim]Next Action: Pair a contact via CLI to begin peer collaboration.[/dim]",
                title=f"[bold {ok}]Network & Trusted Contacts[/bold {ok}]",
                border_style="yellow",
            )

        table = Table(
            title=f"[bold {ok}]PAIRED TRUSTED CONTACTS ({len(contacts)})[/bold {ok}]",
            expand=True,
            show_edge=True,
        )
        table.add_column("Contact", style="bold white")
        table.add_column("Autonomy", style=accent)
        table.add_column("Fingerprint", style=f"bold {warn}")
        table.add_column("Reachability (Cached)", style=hl)
        table.add_column("Peer Cards Alert", style=f"bold {ok}")

        for c in contacts:
            recency = get_peer_capabilities_recency(self.profile_dir, c.username)
            stale_count = get_stale_peer_card_count(self.profile_dir, c.username)

            reach_str = f"Last seen {recency[:16]}" if recency else "Not yet contacted"
            alert_str = f"⚠️ {stale_count} card(s) need review [Press A]" if stale_count > 0 else "Fresh"

            # Redaction & Truncation Invariants (§2.4)
            raw_fp = c.fingerprint or (c.public_key[:12] + "..." if c.public_key else "Unverified")
            safe_fp = redact_ui_text(raw_fp)
            safe_display = redact_ui_text(c.display_name or c.username)

            table.add_row(
                f"{safe_display} (@{c.username})",
                c.autonomy_level,
                safe_fp,
                reach_str,
                alert_str,
            )

        return table
