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

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable."""
        try:
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def render(self) -> str:
        state = self.lifecycle_state
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent = self._c("accent.primary", "#bb9af7")
        ok = self._c("state.live", "#73daca")
        hl = self._c("accent.highlight", "#7aa2f7")

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Verifying Security Credentials...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "TrustStrip disabled"
            return f"[dim]TrustStrip (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} TrustStrip Error: Security state unreadable. Press [Retry].[/bold {err}]"

        # Mode A: Render Session Header / Trust Strip (§14.8 Step 1)
        if self.session_summary:
            sess = self.session_summary
            init_user = redact_ui_text(sess.initiator_username or "local_user")
            
            if self.is_trust_unknown:
                peer_trust = f"[bold {err}][TRUST STATUS UNKNOWN / CHECK ERROR][/bold {err}]"
                rec_user = f"@{redact_ui_text(sess.receiver_username or 'unknown')}"
            elif self.is_missing_peer:
                rec_user = f"@{redact_ui_text(sess.receiver_username or 'unknown')} [bold {warn}][UNKNOWN PEER][/bold {warn}]"
                peer_trust = f"[bold {err}][UNVERIFIED PEER][/bold {err}]"
            else:
                rec_user = f"@{redact_ui_text(sess.receiver_username or 'peer')}"
                peer_trust = f"[bold {accent}][PEER VERIFIED][/bold {accent}]"

            transport_badge = f"[bold {ok}][DIRECT TRANSPORT][/bold {ok}]" if self.is_direct_transport else f"[bold {warn}][RELAY TRANSPORT][/bold {warn}]"
            stale_badge = f" [bold {err}][STALE PEER CARD][/bold {err}]" if self.is_stale_peer else ""

            status_style = ok if sess.status == "active" else (hl if sess.status == "completed" else err)
            obj_clean = redact_ui_text(sess.objective or "No objective declared")

            if state == WidgetLifecycleState.NARROW:
                return f"🔒 Arena: @{init_user} → {rec_user} | {transport_badge}"

            focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""
            return (
                f"🔒 SESSION TRUST STRIP: {peer_trust} {transport_badge}{stale_badge}{focus_mark}\n"
                f"Session ID: [bold]{sess.session_id}[/bold] | Type: [{accent}]{sess.type}[/{accent}] | Status: [{status_style}]{sess.status}[/]\n"
                f"Participants: [bold]@{init_user}[/bold] (initiator) → [bold]{rec_user}[/bold]\n"
                f"Objective: [dim]{obj_clean}[/dim]"
            )

        # Mode B: Render Agent Card Trust Strip
        if state == WidgetLifecycleState.EMPTY or not self.card_view:
            return "[dim]TrustStrip: No agent security identity or session summary bound.[/dim]"

        card = self.card_view
        badge = f"[bold {accent}][PEER VERIFIED][/bold {accent}]" if card.is_peer else f"[bold {ok}][LOCAL TRUSTED][/bold {ok}]"
        truncated_id = card.agent_id[:8] if len(card.agent_id) >= 8 else card.agent_id
        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        if state == WidgetLifecycleState.NARROW:
            return f"{badge} ID:{truncated_id}"

        return (
            f"🔒 TRUST STRIP: {badge}{focus_mark}\n"
            f"Agent ID: [bold]{card.agent_id}[/bold] (FPR: [{warn}]{truncated_id}...[/{warn}])\n"
            f"Isolation Boundary: [dim]sandbox-isolated | readiness={card.readiness_reason}[/dim]"
        )
