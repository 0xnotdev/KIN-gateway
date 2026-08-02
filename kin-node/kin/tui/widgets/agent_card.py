"""AgentCard domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime
from typing import Optional, Union

from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.state import AgentCardView
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class AgentCardWidget(LifecycleWidgetMixin, Static):
    """AgentCard domain widget for displaying local or peer agent cards (§14.5).

    Enforces strict security isolation: rendered string never leaks adapter config,
    working directories, or credentials for peer cards.
    """

    can_focus = True

    DEFAULT_CSS = """
    AgentCardWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    AgentCardWidget:focus {
        border: double $accent;
    }
    """

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable or empty string if colorless mode active."""
        try:
            if getattr(self.app, "is_colorless_active", False):
                return ""
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def _g(self, symbol: str) -> str:
        """Resolve a glyph symbol using ASCII fallback if app.is_ascii_fallback_active is True."""
        try:
            ascii_fallback = getattr(self.app, "is_ascii_fallback_active", False)
        except Exception:
            ascii_fallback = False
        return get_glyph(symbol, ascii_fallback=ascii_fallback)

    def __init__(
        self,
        card_view: Optional[AgentCardView] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.card_view = card_view

    def render(self) -> str:
        err = self._c("state.error", "#f7768e")
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = self._g("◌")
            return f"[dim]{glyph} Loading Agent Card...[/dim]"

        if state == WidgetLifecycleState.EMPTY or not self.card_view:
            return "[dim]AgentCard: No agent card assigned.[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "AgentCard disabled"
            return f"[dim]AgentCard (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = self._g("!")
            color_tag = f" {err}".rstrip()
            return f"[bold{color_tag}]{glyph} AgentCard Error: Agent metadata corrupted. Press [Retry].[/bold{color_tag}]"

        card = self.card_view

        # Formatting peer vs local card
        from kin.schemas import AgentAvailability
        avail_val = card.availability.value if isinstance(card.availability, AgentAvailability) else str(card.availability)
        raw_glyph = "●" if avail_val in (AgentAvailability.READY.value, AgentAvailability.BUSY.value, AgentAvailability.RESERVED.value) else "○"
        avail_glyph = self._g(raw_glyph)
        status_str = f"{avail_glyph} {avail_val} ({card.readiness_reason})"

        name = redact_ui_text(card.name)
        description = redact_ui_text(card.description)
        peer_badge = "[PEER]" if card.is_peer else "[LOCAL]"

        if state == WidgetLifecycleState.NARROW:
            return f"{peer_badge} [bold]{name}[/bold] ({card.agent_id[:8]})"

        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""
        tags_str = ", ".join(card.capabilities_tags) if card.capabilities_tags else "none"

        # Explicitly format ONLY sanitized public card fields
        return (
            f"{peer_badge} [bold]{name}[/bold] [dim]({card.agent_id})[/dim]{focus_mark}\n"
            f"Status: {status_str}\n"
            f"Description: {description}\n"
            f"Capabilities: [dim]{tags_str}[/dim]"
        )
