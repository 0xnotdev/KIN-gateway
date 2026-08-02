"""ApprovalCard domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime, timezone
from typing import Optional, Union

from textual.widgets import Static

from kin.schemas import RiskLabel
from kin.tui.redaction import redact_ui_text
from kin.tui.state import ApprovalView
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class ApprovalCardWidget(LifecycleWidgetMixin, Static):
    """ApprovalCard domain widget for consequential action approval gates (§14.5).

    Supports dynamic time_remaining computation via an injectable `now` clock
    and visibly distinct risk-level styling (LOW, MEDIUM, HIGH, CRITICAL).
    """

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable or empty string if colorless mode active."""
        app = self._get_app_instance()
        if app is not None and getattr(app, "is_colorless_active", False):
            return ""
        if app is not None and hasattr(app, "theme_tokens"):
            try:
                return app.theme_tokens.get_role_color(role)
            except Exception:
                pass
        return fallback if app is None else ""

    can_focus = True

    DEFAULT_CSS = """
    ApprovalCardWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    ApprovalCardWidget:focus {
        border: double $accent;
    }
    """

    RISK_PRESENTATION = {
        "LOW": ("●", "bold green", "low_risk"),
        "MEDIUM": ("▲", "bold yellow", "medium_risk"),
        "HIGH": ("◆", "bold orange", "high_risk"),
        "CRITICAL": ("✖", "bold red", "critical_risk"),
    }

    def __init__(
        self,
        approval_view: Optional[ApprovalView] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        self.approval_view = approval_view
        super().__init__(now=now, **kwargs)

    def update_clock(self, now: Optional[Union[datetime, str, float]] = None) -> None:
        """Advance injectable clock and recalculate approval view time_remaining (§14.5)."""
        super().update_clock(now)
        if self.approval_view and self.approval_view.request and self.approval_view.request.expires_at:
            try:
                exp_dt = datetime.fromisoformat(self.approval_view.request.expires_at.replace("Z", "+00:00"))
                curr_dt = self.last_updated_at or datetime.now(timezone.utc)
                if curr_dt.tzinfo is None:
                    curr_dt = curr_dt.replace(tzinfo=timezone.utc)
                rem = max(0.0, (exp_dt - curr_dt).total_seconds())
                self.approval_view.time_remaining = rem
            except Exception:
                pass
        self.refresh()

    def render(self) -> str:
        warn = self._c("state.waiting", "#e0af68")
        err = self._c("state.error", "#f7768e")
        app_inst = self._get_app_instance()
        is_colorless = getattr(app_inst, "is_colorless_active", False) if app_inst else False

        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = self._g("◌")
            return f"[dim]{glyph} Loading Approval Gate...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "ApprovalCard disabled"
            return f"[dim]ApprovalCard (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.EMPTY or not self.approval_view:
            return "[dim]ApprovalCard: No pending approval request.[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = self._g("!")
            err_tag = f" {err}".rstrip()
            return f"[bold{err_tag}]{glyph} ApprovalCard Error: Approval request expired or invalid. Press [Retry].[/bold{err_tag}]"

        app_v = self.approval_view
        req = app_v.request
        risk_raw = getattr(req, "risk_label", "medium")
        risk = str(risk_raw.value if hasattr(risk_raw, "value") else risk_raw).upper()

        raw_glyph, style, role = self.RISK_PRESENTATION.get(risk, ("▲", "bold yellow", "medium_risk"))
        glyph = self._g(raw_glyph)

        if is_colorless:
            style = "bold"

        rem_sec = app_v.time_remaining
        time_str = f"{rem_sec:.1f}s remaining" if rem_sec is not None else "No expiration"

        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""
        raw_summary = getattr(req, "summary", "Action Request")
        summary = redact_ui_text(raw_summary)
        agent_id = getattr(req, "agent_id", "system")
        action_class = getattr(req, "action_class", "workspace_write")
        reason = redact_ui_text(getattr(req, "reason", ""))

        warn_open = f"[{warn}]" if warn else ""
        warn_close = f"[/{warn}]" if warn else ""

        if state == WidgetLifecycleState.NARROW:
            return f"[{style}]{glyph} {risk}[/{style}] {summary[:12]} ({time_str})"

        return (
            f"[{style}]{glyph} RISK: {risk}[/{style}]{focus_mark}\n"
            f"Action: [bold]{summary}[/bold] [dim]({action_class})[/dim]\n"
            f"Requester: {agent_id} | Time Remaining: {warn_open}{time_str}{warn_close}\n"
            f"Reason: [dim]{reason}[/dim]"
        )
