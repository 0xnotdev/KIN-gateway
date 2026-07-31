"""TrustStrip domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime
from typing import Optional, Union

from textual.widgets import Static

from kin.tui.state import AgentCardView
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class TrustStripWidget(LifecycleWidgetMixin, Static):
    """TrustStrip domain widget for identity and isolation trust classification (§14.5).

    Renders trust security level ([LOCAL TRUSTED] vs [PEER VERIFIED]) and truncated agent_id summary.
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
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.card_view = card_view

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Verifying Security Credentials...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "TrustStrip disabled"
            return f"[dim]TrustStrip (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.EMPTY or not self.card_view:
            return "[dim]TrustStrip: No agent security identity bound.[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} TrustStrip Error: Identity signature verification failed. Press [Retry].[/bold red]"

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
