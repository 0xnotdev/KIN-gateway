"""TrustStrip domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5, §14.8 Step 1
"""

from datetime import datetime
from typing import Optional, Union

from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.state import AgentCardView, SessionSummary
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class TrustStripWidget(LifecycleWidgetMixin, Static):
    """TrustStrip domain widget for agent identity & session trust header (§14.5, §14.8).

    Renders trust security level ([LOCAL TRUSTED] vs [PEER VERIFIED]), transport mode,
    peer staleness alerts, missing peer fallback, and explicit trust-status-unknown error states.
    """

    can_focus = True

    DEFAULT_CSS = """
    TrustStripWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    TrustStripWidget:focus {
        border: double $accent;
    }
    """

    def __init__(
        self,
        card_view: Optional[AgentCardView] = None,
        session_summary: Optional[SessionSummary] = None,
        is_stale_peer: bool = False,
        is_direct_transport: bool = True,
        is_missing_peer: bool = False,
        is_trust_unknown: bool = False,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.card_view: Optional[AgentCardView] = card_view
        self.session_summary: Optional[SessionSummary] = session_summary
        self.is_stale_peer: bool = is_stale_peer
        self.is_direct_transport: bool = is_direct_transport
        self.is_missing_peer: bool = is_missing_peer
        self.is_trust_unknown: bool = is_trust_unknown

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Verifying Security Credentials...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "TrustStrip disabled"
            return f"[dim]TrustStrip (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} TrustStrip Error: Security state unreadable. Press [Retry].[/bold red]"

        # Mode A: Render Session Header / Trust Strip (§14.8 Step 1)
        if self.session_summary:
            sess = self.session_summary
            init_user = redact_ui_text(sess.initiator_username or "local_user")
            
            if self.is_trust_unknown:
                peer_trust = "[bold red][TRUST STATUS UNKNOWN / CHECK ERROR][/bold red]"
                rec_user = f"@{redact_ui_text(sess.receiver_username or 'unknown')}"
            elif self.is_missing_peer:
                rec_user = f"@{redact_ui_text(sess.receiver_username or 'unknown')} [bold yellow][UNKNOWN PEER][/bold yellow]"
                peer_trust = "[bold red][UNVERIFIED PEER][/bold red]"
            else:
                rec_user = f"@{redact_ui_text(sess.receiver_username or 'peer')}"
                peer_trust = "[bold cyan][PEER VERIFIED][/bold cyan]"

            transport_badge = "[bold green][DIRECT TRANSPORT][/bold green]" if self.is_direct_transport else "[bold yellow][RELAY TRANSPORT][/bold yellow]"
            stale_badge = " [bold red][STALE PEER CARD][/bold red]" if self.is_stale_peer else ""

            status_style = "green" if sess.status == "active" else ("blue" if sess.status == "completed" else "red")
            obj_clean = redact_ui_text(sess.objective or "No objective declared")

            if state == WidgetLifecycleState.NARROW:
                return f"🔒 Arena: @{init_user} → {rec_user} | {transport_badge}"

            focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""
            return (
                f"🔒 SESSION TRUST STRIP: {peer_trust} {transport_badge}{stale_badge}{focus_mark}\n"
                f"Session ID: [bold]{sess.session_id}[/bold] | Type: [cyan]{sess.type}[/cyan] | Status: [{status_style}]{sess.status}[/{status_style}]\n"
                f"Participants: [bold]@{init_user}[/bold] (initiator) → [bold]{rec_user}[/bold]\n"
                f"Objective: [dim]{obj_clean}[/dim]"
            )

        # Mode B: Render Agent Card Trust Strip
        if state == WidgetLifecycleState.EMPTY or not self.card_view:
            return "[dim]TrustStrip: No agent security identity or session summary bound.[/dim]"

        card = self.card_view
        badge = "[bold cyan][PEER VERIFIED][/bold cyan]" if card.is_peer else "[bold green][LOCAL TRUSTED][/bold green]"
        truncated_id = card.agent_id[:8] if len(card.agent_id) >= 8 else card.agent_id
        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        if state == WidgetLifecycleState.NARROW:
            return f"{badge} ID:{truncated_id}"

        return (
            f"🔒 TRUST STRIP: {badge}{focus_mark}\n"
            f"Agent ID: [bold]{card.agent_id}[/bold] (FPR: [yellow]{truncated_id}...[/yellow])\n"
            f"Isolation Boundary: [dim]sandbox-isolated | readiness={card.readiness_reason}[/dim]"
        )
