"""OutcomeCard domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime
from typing import Optional, Union

from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.state import CommandResult, SessionSummary
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class OutcomeCardWidget(LifecycleWidgetMixin, Static):
    """OutcomeCard domain widget for completed session execution results (§14.5).

    Consumes SessionSummary and optional CommandResult[T] displaying final outcome.
    Sanitizes any potential secret or local path fragment in error messages.
    """

    can_focus = True

    DEFAULT_CSS = """
    OutcomeCardWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    OutcomeCardWidget:focus {
        border: double $accent;
    }
    """

    def __init__(
        self,
        session_summary: Optional[SessionSummary] = None,
        command_result: Optional[CommandResult] = None,
        outcome_card=None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.session_summary = session_summary
        self.command_result = command_result
        self.outcome_card = outcome_card

    def render(self) -> str:
        ok = self._c("state.live", "#73daca")
        err = self._c("state.error", "#f7768e")
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Execution Outcome...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "OutcomeCard disabled"
            return f"[dim]OutcomeCard (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.EMPTY or (not self.session_summary and not self.outcome_card):
            return "[dim]OutcomeCard: No completed session summary available.[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} OutcomeCard Error: Session result telemetry unreadable. Press [Retry].[/bold {err}]"

        if self.outcome_card is not None:
            outcome = self.outcome_card
            success = outcome.status == "completed"
            badge = f"[bold {ok}]SUCCESS[/bold {ok}]" if success else f"[bold {err}]{outcome.status.upper()}[/bold {err}]"
            if state == WidgetLifecycleState.NARROW:
                return f"{badge} {outcome.session_id[:8]} evidence={outcome.evidence_event_count}"
            return (
                f"{badge} [bold]Persisted Session Outcome[/bold]\n"
                f"Session ID: {outcome.session_id} | Final Status: {outcome.status}\n"
                f"Summary: {redact_ui_text(outcome.summary)}\n"
                f"Evidence Events: {outcome.evidence_event_count} | "
                f"Replay SHA-256: {outcome.replay_digest}"
            )

        sess = self.session_summary
        res = self.command_result

        success = res.success if res else (sess.status in ("completed", "success", "done"))
        badge = f"[bold {ok}]✔ SUCCESS[/bold {ok}]" if success else f"[bold {err}]✖ FAILED[/bold {err}]"

        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        if state == WidgetLifecycleState.NARROW:
            return f"{badge} {sess.session_id[:8]} ({sess.current_turn} turns)"

        scrubbed_err = redact_ui_text(res.error_message) if (res and res.error_message) else ""
        err_str = f"\nError: [bold {err}]{scrubbed_err}[/bold {err}]" if scrubbed_err else ""

        return (
            f"{badge} [bold]Session Outcome[/bold]{focus_mark}\n"
            f"Session ID: {sess.session_id} | Final Status: {sess.status}\n"
            f"Turns Completed: {sess.current_turn}/{sess.max_turns}\n"
            f"Participants: [dim]{', '.join(sess.participant_display_names)}[/dim]{err_str}"
        )
