"""AgentPicker domain modal overlay widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.5, §14.5, §14.7 Phase B
"""

from datetime import datetime
from typing import Callable, List, Optional, Union

from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from kin.schemas import AgentAvailability
from kin.tui.redaction import redact_ui_text
from kin.tui.state import AgentCardView
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class AgentPickerWidget(LifecycleWidgetMixin, ModalScreen[Optional[AgentCardView]]):
    """AgentPicker modal screen overlay for selecting an agent (§5.5, §14.7 Phase B)."""

    can_focus = True

    DEFAULT_CSS = """
    AgentPickerWidget {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
        padding: 0 1;
    }
    """

    def __init__(
        self,
        agents: Optional[List[AgentCardView]] = None,
        prompt: str = "Select an agent for collaboration",
        preselected_id: Optional[str] = None,
        on_select: Optional[Callable[[AgentCardView], None]] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)

        def _sort_key(a: AgentCardView) -> int:
            avail = a.availability.value if isinstance(a.availability, AgentAvailability) else str(a.availability)
            return 0 if avail in ("ready", AgentAvailability.READY.value) else 1

        self.agents: List[AgentCardView] = sorted(agents or [], key=_sort_key)
        self.prompt = prompt
        self.preselected_id = preselected_id
        self.on_select = on_select
        self.selected_index: int = 0
        self.drawer_open: bool = False  # Toggled by Tab key (§B2)

        # Preselect if specified
        if preselected_id:
            for idx, a in enumerate(self.agents):
                if a.agent_id == preselected_id:
                    self.selected_index = idx
                    break

    def cursor_down(self) -> None:
        if self.agents:
            self.selected_index = min(self.selected_index + 1, len(self.agents) - 1)
            self.refresh()

    def cursor_up(self) -> None:
        if self.agents:
            self.selected_index = max(self.selected_index - 1, 0)
            self.refresh()

    def toggle_drawer(self) -> None:
        """Toggle details drawer showing boundary summary and rationale notice (§B2)."""
        self.drawer_open = not self.drawer_open
        self.refresh()

    def get_selected_agent(self) -> Optional[AgentCardView]:
        if 0 <= self.selected_index < len(self.agents):
            return self.agents[self.selected_index]
        return None

    def confirm_selection(self) -> Optional[AgentCardView]:
        """Confirm selection on Enter press (§B3). Zero auto-preselection."""
        selected = self.get_selected_agent()
        if selected and self.on_select:
            self.on_select(selected)
        try:
            self.dismiss(selected)
        except Exception:
            pass
        return selected

    def cancel_selection(self) -> None:
        """Cancel selection on Esc press (§B3)."""
        try:
            self.dismiss(None)
        except Exception:
            pass

    def on_key(self, event: Key) -> None:
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        if event.key in ("down", "j"):
            self.cursor_down()
            event.stop()
        elif event.key in ("up", "k"):
            self.cursor_up()
            event.stop()
        elif event.key == "tab":
            self.toggle_drawer()
            event.stop()
        elif event.key == "enter":
            self.confirm_selection()
            event.stop()
        elif event.key == "escape":
            self.cancel_selection()
            event.stop()

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Agent Roster...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "AgentPicker disabled"
            return f"[dim]AgentPicker (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.EMPTY or not self.agents:
            return "[dim]AgentPicker: No agents available for selection.[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} AgentPicker Error: Failed to query roster. Press [Retry].[/bold red]"

        lines = [f"[bold green]{self.prompt}[/bold green]"]
        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""
        lines[0] += focus_mark

        for idx, agent in enumerate(self.agents):
            is_selected = (idx == self.selected_index)
            prefix = "▶ " if is_selected else "  "

            # Status glyph
            avail_str = agent.availability.value if isinstance(agent.availability, AgentAvailability) else str(agent.availability)
            if avail_str in (AgentAvailability.READY.value, AgentAvailability.BUSY.value, AgentAvailability.RESERVED.value, "ready", "busy", "reserved"):
                status_g = "●"
            elif avail_str in (AgentAvailability.NEEDS_KEY.value, AgentAvailability.NEEDS_WORKSPACE.value, "needs_key", "needs_workspace"):
                status_g = "!"
            else:
                status_g = "○"

            adapter_lbl = f"[{agent.adapter_kind.upper()}]" if agent.adapter_kind else ("[PEER]" if agent.is_peer else "[LOCAL]")
            name = redact_ui_text(agent.name)
            desc = redact_ui_text(agent.description)
            tags_str = ", ".join(agent.capabilities_tags) if agent.capabilities_tags else "none"
            accepts_str = ", ".join(agent.accepts) if agent.accepts else "any"
            produces_str = ", ".join(agent.produces) if agent.produces else "any"

            line = (
                f"{prefix}{adapter_lbl} [bold]{name}[/bold] {status_g} [dim]({avail_str})[/dim]\n"
                f"    [dim]Desc:[/dim] {desc}\n"
                f"    [dim]Tags:[/dim] {tags_str} | [dim]Accepts:[/dim] {accepts_str} | [dim]Produces:[/dim] {produces_str}"
            )

            # Details drawer toggle (§B2)
            if is_selected and self.drawer_open:
                b_sum = agent.boundary_summary or "Workspace restricted"
                line += (
                    f"\n    ↳ [bold cyan]Boundary Summary:[/bold cyan] {b_sum}\n"
                    f"    ↳ [bold yellow]Rationale:[/bold yellow] Ordered by readiness status (READY agents first)"
                )

            if is_selected:
                lines.append(f"[cyan]{line}[/cyan]")
            else:
                lines.append(line)

        lines.append("\n[dim]j/k: navigate | Tab: toggle details drawer | Enter: select | Esc: cancel[/dim]")
        return "\n".join(lines)
