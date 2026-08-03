"""SessionMap domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5, §14.8 Step 2
"""

from datetime import datetime
from typing import List, Optional, Union

from textual.events import Key
from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.state import SessionSummary
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class SessionMapWidget(LifecycleWidgetMixin, Static):
    """SessionMap domain widget for active session overview, roles, and lifecycle state (§14.5, §14.8)."""

    can_focus = True

    DEFAULT_CSS = """
    SessionMapWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    SessionMapWidget:focus {
        border: double $accent;
    }
    """

    def __init__(
        self,
        sessions: Optional[List[SessionSummary]] = None,
        active_session_id: Optional[str] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.sessions: List[SessionSummary] = sessions or []
        self.active_session_id: Optional[str] = active_session_id
        self.selected_index: int = 0

    def get_selected_session(self) -> Optional[SessionSummary]:
        if 0 <= self.selected_index < len(self.sessions):
            return self.sessions[self.selected_index]
        return None

    def cursor_down(self) -> None:
        if self.sessions:
            self.selected_index = min(self.selected_index + 1, len(self.sessions) - 1)
            self.refresh()

    def cursor_up(self) -> None:
        if self.sessions:
            self.selected_index = max(self.selected_index - 1, 0)
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

    def render(self) -> str:
        state = self.lifecycle_state
        err = self._c("state.error", "#f7768e")
        ok = self._c("state.live", "#73daca")
        hl = self._c("accent.highlight", "#7aa2f7")

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Indexing Session Map...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "SessionMap disabled"
            return f"[dim]SessionMap (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.EMPTY or not self.sessions:
            return "[dim]SessionMap: No active sessions mapped.[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} SessionMap Error: Session index unreadable. Press [Retry].[/bold {err}]"

        lines = [f"[bold {ok}]Session Map Overview:[/bold {ok}]"]
        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        for idx, sess in enumerate(self.sessions):
            is_active = (sess.session_id == self.active_session_id or idx == self.selected_index)
            prefix = "▶ " if is_active else "  "
            
            init_user = redact_ui_text(sess.initiator_username or "local")
            rec_user = redact_ui_text(sess.receiver_username or "peer")
            obj_clean = redact_ui_text(sess.objective or "No objective")

            status_color = ok if sess.status == "active" else (hl if sess.status == "completed" else err)
            state_badge = f"[{status_color}][{sess.status.upper()}][/]"

            if state == WidgetLifecycleState.NARROW:
                lines.append(f"{prefix}● [bold]{sess.session_id[:8]}[/bold] @{init_user}→@{rec_user} {state_badge}")
            else:
                lines.append(
                    f"{prefix}● [bold]{sess.session_id}[/bold] ({sess.type}) {state_badge}\n"
                    f"   Roles: [bold]@{init_user}[/bold] (initiator) ↔ [bold]@{rec_user}[/bold] (receiver)\n"
                    f"   Objective: [dim]{obj_clean}[/dim]"
                )

        return "\n".join(lines) + focus_mark
