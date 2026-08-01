"""ExchangeTimeline domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5, §14.8 Step 3
"""

from datetime import datetime
from typing import Callable, List, Optional, Set, Union

from textual.events import Key
from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.state import UiEvent
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class ExchangeTimelineWidget(LifecycleWidgetMixin, Static):
    """ExchangeTimeline domain widget rendering session events across presentation classes (§14.5, §14.8 Step 3).

    Classes rendered:
    1. message: provenance-rich (actor username, created_at, content)
    2. activity: concise, coalesced format
    3. checkpoint: bordered box
    4. artifact: metadata/preview ONLY (zero import/apply affordances)
    5. approval: amber token (zero action buttons)
    6. state_transition: clear visual state divider
    7. security: persistent red card (zero action affordances)
    """

    can_focus = True
    DEFAULT_ALLOWED_CLASSES: Set[str] = {"message", "artifact", "approval", "state_transition", "checkpoint"}
    ALL_7_CLASSES: Set[str] = {"message", "activity", "checkpoint", "artifact", "approval", "state_transition", "security"}

    DEFAULT_CSS = """
    ExchangeTimelineWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    ExchangeTimelineWidget:focus {
        border: double $accent;
    }
    """

    def __init__(
        self,
        events: Optional[List[UiEvent]] = None,
        selected_event_id: Optional[str] = None,
        allowed_presentation_classes: Optional[Set[str]] = None,
        on_event_selected: Optional[Callable[[UiEvent], None]] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.events: List[UiEvent] = events or []
        self.selected_event_id: Optional[str] = selected_event_id
        self.allowed_presentation_classes: Set[str] = (
            allowed_presentation_classes
            if allowed_presentation_classes is not None
            else self.DEFAULT_ALLOWED_CLASSES
        )
        self.selected_index: int = 0
        self.on_event_selected = on_event_selected

        filtered = self.get_filtered_events()
        if selected_event_id and filtered:
            for idx, e in enumerate(filtered):
                if e.event_id == selected_event_id:
                    self.selected_index = idx
                    break

    def get_filtered_events(self) -> List[UiEvent]:
        return [e for e in self.events if e.presentation_class in self.allowed_presentation_classes]

    def get_selected_event(self) -> Optional[UiEvent]:
        filtered = self.get_filtered_events()
        if 0 <= self.selected_index < len(filtered):
            return filtered[self.selected_index]
        return None

    def cursor_down(self) -> None:
        filtered = self.get_filtered_events()
        if filtered:
            self.selected_index = min(self.selected_index + 1, len(filtered) - 1)
            selected = self.get_selected_event()
            if selected and self.on_event_selected:
                self.on_event_selected(selected)
            self.refresh()

    def cursor_up(self) -> None:
        filtered = self.get_filtered_events()
        if filtered:
            self.selected_index = max(self.selected_index - 1, 0)
            selected = self.get_selected_event()
            if selected and self.on_event_selected:
                self.on_event_selected(selected)
            self.refresh()

    def on_key(self, event: Key) -> None:
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        if event.key in ("down", "j"):
            self.cursor_down()
            event.stop()
        elif event.key in ("up", "k"):
            self.cursor_up()
            event.stop()
        elif event.key == "enter":
            selected = self.get_selected_event()
            if selected and self.on_event_selected:
                self.on_event_selected(selected)
            event.stop()

    def _render_event_card(self, evt: UiEvent, is_selected: bool) -> str:
        p_class = evt.presentation_class
        actor = redact_ui_text(evt.actor_username or "system")
        ts = redact_ui_text(evt.created_at[:19] if evt.created_at else "00:00:00")
        kind_clean = redact_ui_text(evt.kind or p_class)
        prefix = "▶ " if is_selected else "  "
        select_tag = " [bold yellow][INSPECTED][/bold yellow]" if is_selected else ""

        # 1. MESSAGE: provenance-rich showing actor, timestamp, and content
        if p_class == "message":
            return (
                f"{prefix}[bold green]💬 MESSAGE[/bold green] [dim]@{actor} at {ts}[/dim]{select_tag}\n"
                f"   [bold]Kind:[/bold] {kind_clean}\n"
                f"   Event ID: {evt.event_id}"
            )

        # 2. ACTIVITY: concise, coalesced visual format
        elif p_class == "activity":
            return f"{prefix}● [dim][ACTIVITY][/dim] {kind_clean} (actor: @{actor} at {ts}){select_tag}"

        # 3. CHECKPOINT: bordered box
        elif p_class == "checkpoint":
            return (
                f"{prefix}┌─ [bold cyan]CHECKPOINT[/bold cyan] ──────────────────────┐\n"
                f"│ Event: {kind_clean:<32} │\n"
                f"│ Timestamp: {ts:<28} │\n"
                f"└────────────────────────────────────────┘{select_tag}"
            )

        # 4. ARTIFACT: metadata & preview ONLY (zero import / apply affordances)
        elif p_class == "artifact":
            return (
                f"{prefix}[bold blue]📦 ARTIFACT OFFER[/bold blue] [dim]by @{actor} at {ts}[/dim]{select_tag}\n"
                f"   Metadata: [cyan]{kind_clean}[/cyan] (ID: {evt.event_id[:8]})\n"
                f"   [dim](Read-only metadata preview - press Enter/inspect to view details)[/dim]"
            )

        # 5. APPROVAL: amber token (zero action buttons)
        elif p_class == "approval":
            return (
                f"{prefix}[bold yellow]▲ APPROVAL GATE [AMBER/POLICY][/bold yellow] [dim]at {ts}[/dim]{select_tag}\n"
                f"   [yellow]Request: {kind_clean} by @{actor}[/yellow]\n"
                f"   [dim](Policy review required - pending owner decision)[/dim]"
            )

        # 6. STATE_TRANSITION: clear visual state divider
        elif p_class == "state_transition":
            return (
                f"{prefix}═══ [bold magenta]STATE TRANSITION[/bold magenta] ═════════════════════════════\n"
                f"   Event: [bold]{kind_clean}[/bold] by @{actor} at {ts}{select_tag}"
            )

        # 7. SECURITY: persistent RED card (zero action affordances)
        elif p_class == "security":
            return (
                f"{prefix}[bold red]✖ SECURITY REJECTION CARD[/bold red] [dim]at {ts}[/dim]{select_tag}\n"
                f"   [red]Category: {kind_clean}[/red]\n"
                f"   [red]Actor: @{actor} | ID: {evt.event_id}[/red]\n"
                f"   [bold red]CRITICAL: Security boundary rejection logged. No actions available.[/bold red]"
            )

        # Fallback
        return f"{prefix}● [{p_class.upper()}] {kind_clean} (@{actor} at {ts}){select_tag}"

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Exchange Timeline...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "ExchangeTimeline disabled"
            return f"[dim]ExchangeTimeline (DISABLED: {reason})[/dim]"

        filtered = self.get_filtered_events()

        if state == WidgetLifecycleState.EMPTY or not filtered:
            return "[dim]ExchangeTimeline: No dialogue/session events recorded.[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} ExchangeTimeline Error: Event timeline corrupted. Press [Retry].[/bold red]"

        lines = [f"[bold green]Exchange Timeline ({len(filtered)} events):[/bold green]"]
        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        for idx, evt in enumerate(filtered):
            is_selected = (idx == self.selected_index)
            lines.append(self._render_event_card(evt, is_selected))

        return "\n\n".join(lines) + focus_mark
