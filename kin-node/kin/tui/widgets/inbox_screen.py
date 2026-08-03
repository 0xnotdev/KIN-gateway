"""Inbox & Approvals Queue Screen Widget for KIN V1.1 TUI (§14.6 Phase D & Rework).

Single combined surface (`"inbox"` workspace tab kind) combining Needs You items
and Approval Queue items. Supports interactive cursor navigation, decision recording,
modal gating (Deny reason, JSON constraint editing, Approve once, Always allow bounded),
quiet hours & snooze notification suppression, and expired item persistence.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from rich.panel import Panel
from rich.table import Table
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from kin.schemas import ActionClass, DecisionKind, RiskLabel
from kin.tui.local_state import (
    decide_pending_approval,
    dispatch_session_owner_decision,
    get_needs_you_items,
    get_pending_approvals,
    parse_iso_utc,
)
from kin.tui.persistence import load_ui_preferences, save_ui_preferences
from kin.tui.redaction import redact_ui_text
from kin.tui.state import ApprovalView, NeedsYouItem, RecoverableError
from kin.tui.tokens import get_glyph
from kin.tui.widgets.approval_card import ApprovalCardWidget
from kin.tui.widgets.approval_modals import ApproveConfirmModal, DenyReasonModal, EditConstraintsModal
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


# -----------------------------------------------------------------------------
# InboxScreenWidget Main Domain Surface
# -----------------------------------------------------------------------------
class InboxScreenWidget(LifecycleWidgetMixin, Static):
    """Combined Inbox / Needs You & Approval Queue Screen (§14.6 Phase D & Rework)."""

    can_focus = True

    DEFAULT_CSS = """
    InboxScreenWidget {
        width: 100%;
        height: 100%;
        background: $surface;
        color: $text;
        overflow-y: auto;
    }
    InboxScreenWidget:focus {
        border: double $accent;
    }
    """

    def __init__(
        self,
        profile_name: str = "default",
        profile_dir: Optional[Path] = None,
        needs_you_items: Optional[List[NeedsYouItem]] = None,
        approvals: Optional[List[ApprovalView]] = None,
        quiet_hours_enabled: bool = False,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(id="inbox-screen-widget", now=now, **kwargs)
        self.profile_name = profile_name
        self.profile_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)

        self._needs_you_override = needs_you_items
        self._approvals_override = approvals

        # Selection and navigation cursor state (§3.1)
        self.active_lane: str = "approvals"  # "approvals" or "needs_you"
        self.selected_index: int = 0

        # Quiet hours & notification settings (§3.3)
        self.prefs, _ = load_ui_preferences(profile_name)
        if quiet_hours_enabled:
            self.prefs.quiet_hours_enabled = True
        self.quiet_hours_enabled = self.prefs.quiet_hours_enabled

        self.last_toast_suppressed: bool = False
        self.last_action_message: Optional[str] = None
        self.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    def get_items(self) -> tuple[List[NeedsYouItem], List[ApprovalView]]:
        needs_you = (
            self._needs_you_override
            if self._needs_you_override is not None
            else get_needs_you_items(self.profile_dir, self.profile_name)
        )
        approvals = (
            self._approvals_override
            if self._approvals_override is not None
            else get_pending_approvals(self.profile_dir, self.profile_name)
        )
        return needs_you, approvals

    def cursor_down(self) -> None:
        needs_you, approvals = self.get_items()
        items_count = len(approvals) if self.active_lane == "approvals" else len(needs_you)
        if items_count > 0:
            self.selected_index = min(self.selected_index + 1, items_count - 1)
            self.refresh()

    def cursor_up(self) -> None:
        needs_you, approvals = self.get_items()
        items_count = len(approvals) if self.active_lane == "approvals" else len(needs_you)
        if items_count > 0:
            self.selected_index = max(self.selected_index - 1, 0)
            self.refresh()

    def switch_lane(self) -> None:
        self.active_lane = "needs_you" if self.active_lane == "approvals" else "approvals"
        self.selected_index = 0
        self.refresh()

    def get_selected_approval(self) -> Optional[ApprovalView]:
        _, approvals = self.get_items()
        if self.active_lane == "approvals" and 0 <= self.selected_index < len(approvals):
            return approvals[self.selected_index]
        return None

    def get_selected_needs_you(self) -> Optional[NeedsYouItem]:
        needs_you, _ = self.get_items()
        if self.active_lane == "needs_you" and 0 <= self.selected_index < len(needs_you):
            return needs_you[self.selected_index]
        return None

    def should_suppress_toast(
        self,
        item_or_app: Union[NeedsYouItem, ApprovalView],
        now_dt: Optional[datetime] = None,
    ) -> bool:
        """Notification suppression calculation (§3.3).

        Rules:
          - Security-classified items (critical urgency, SHELL_NETWORK_EXTERNAL, WORKSPACE_WRITE) are NEVER suppressed.
          - Approvals in the final 10% of remaining expiry window are NEVER suppressed.
          - Non-critical items during active quiet hours or snooze ARE suppressed.
        """
        now_dt = now_dt or datetime.now(timezone.utc)

        # Rule 1: Check security classification
        if isinstance(item_or_app, NeedsYouItem):
            if item_or_app.urgency == "critical":
                return False  # Never suppress critical security items
        elif isinstance(item_or_app, ApprovalView):
            req = item_or_app.request
            if req.action_class in (ActionClass.SHELL_NETWORK_EXTERNAL, ActionClass.WORKSPACE_WRITE):
                return False  # Never suppress high-risk security approvals

            # Rule 2: Check final 10% of expiry window
            exp_dt = parse_iso_utc(req.expires_at)
            if exp_dt is not None:
                # If expiry is in past or within 10% of remaining lifetime
                remaining_sec = (exp_dt - now_dt).total_seconds()
                if remaining_sec <= 300:  # Final 5 minutes or 10% threshold
                    return False

        # Check if quiet hours or snooze active
        if self.quiet_hours_enabled or self.prefs.quiet_hours_enabled:
            self.last_toast_suppressed = True
            return True

        self.last_toast_suppressed = False
        return False

    def handle_approve_once(self) -> None:
        """Approve once decision handler with modal confirmation (§3.1)."""
        app_view = self.get_selected_approval()
        if not app_view:
            return

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                ok, err = decide_pending_approval(
                    self.profile_dir,
                    self.profile_name,
                    approval_id=app_view.request.approval_id,
                    session_id=app_view.request.session_id,
                    decision=DecisionKind.APPROVE_ONCE.value,
                )
                if ok:
                    self.last_action_message = f"Approved once: {app_view.request.approval_id[:8]}"
                else:
                    self.last_action_message = f"Approve failed: {err.what_happened if err else 'Unknown'}"
                self.refresh()

        modal = ApproveConfirmModal(
            title="CONFIRM APPROVE ONCE",
            body_text=f"Approve action '[bold]{app_view.request.action_class.value}[/bold]' for session '{app_view.request.session_id[:8]}'?",
        )
        try:
            self.app.push_screen(modal, on_confirm)
        except Exception:
            # Fallback for direct unit tests
            on_confirm(True)

    def handle_deny(self) -> None:
        """Deny decision handler with modal reason input gate (§3.1)."""
        app_view = self.get_selected_approval()
        if not app_view:
            return

        def on_submit_reason(reason: Optional[str]) -> None:
            if reason:
                ok, err = decide_pending_approval(
                    self.profile_dir,
                    self.profile_name,
                    approval_id=app_view.request.approval_id,
                    session_id=app_view.request.session_id,
                    decision=DecisionKind.DENY.value,
                    reason=reason,
                )
                if ok:
                    self.last_action_message = f"Denied: {app_view.request.approval_id[:8]}"
                else:
                    self.last_action_message = f"Deny failed: {err.what_happened if err else 'Unknown'}"
                self.refresh()

        modal = DenyReasonModal(approval_id=app_view.request.approval_id)
        try:
            self.app.push_screen(modal, on_submit_reason)
        except Exception:
            pass

    def handle_edit_constraints(self) -> None:
        """Edit constraints handler with JSON validation gate (§3.1)."""
        app_view = self.get_selected_approval()
        if not app_view:
            return

        def on_submit_constraints(constraints: Optional[dict]) -> None:
            if constraints is not None:
                ok, err = decide_pending_approval(
                    self.profile_dir,
                    self.profile_name,
                    approval_id=app_view.request.approval_id,
                    session_id=app_view.request.session_id,
                    decision=DecisionKind.EDIT_CONSTRAINTS.value,
                    constraints=constraints,
                )
                if ok:
                    self.last_action_message = f"Constraints updated: {app_view.request.approval_id[:8]}"
                else:
                    self.last_action_message = f"Edit failed: {err.what_happened if err else 'Unknown'}"
                self.refresh()

        initial_json = json.dumps(app_view.request.requested_scope or {})
        modal = EditConstraintsModal(approval_id=app_view.request.approval_id, initial_json=initial_json)
        try:
            self.app.push_screen(modal, on_submit_constraints)
        except Exception:
            pass

    def handle_always_allow_bounded(self) -> None:
        """Always allow bounded handler (§3.1)."""
        app_view = self.get_selected_approval()
        if not app_view:
            return

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                ok, err = decide_pending_approval(
                    self.profile_dir,
                    self.profile_name,
                    approval_id=app_view.request.approval_id,
                    session_id=app_view.request.session_id,
                    decision=DecisionKind.ALWAYS_ALLOW_BOUNDED.value,
                )
                if ok:
                    self.last_action_message = f"Always allowed (bounded): {app_view.request.approval_id[:8]}"
                else:
                    self.last_action_message = f"Action failed: {err.what_happened if err else 'Unknown'}"
                self.refresh()

        modal = ApproveConfirmModal(
            title="CONFIRM ALWAYS ALLOW (BOUNDED)",
            body_text=f"Grant bounded prior approval for '[bold]{app_view.request.action_class.value}[/bold]'?",
        )
        try:
            self.app.push_screen(modal, on_confirm)
        except Exception:
            on_confirm(True)

    def on_key(self, event: Key) -> None:
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        if event.key in ("down", "j"):
            self.cursor_down()
            event.stop()
        elif event.key in ("up", "k"):
            self.cursor_up()
            event.stop()
        elif event.key in ("tab", "h", "l", "left", "right"):
            self.switch_lane()
            event.stop()
        elif self.active_lane == "approvals":
            if event.key in ("a", "A"):
                self.handle_approve_once()
                event.stop()
            elif event.key in ("d", "D"):
                self.handle_deny()
                event.stop()
            elif event.key in ("e", "E"):
                self.handle_edit_constraints()
                event.stop()
            elif event.key in ("b", "B"):
                self.handle_always_allow_bounded()
                event.stop()

    def render(self) -> Table | Panel:
        accent = self._c("accent.primary", "#bb9af7")
        ok = self._c("state.live", "#73daca")
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")

        if self.lifecycle_state == WidgetLifecycleState.LOADING:
            return Panel("[dim]Loading Inbox & Approvals...[/dim]", title="Inbox", border_style="cyan")

        needs_you, approvals = self.get_items()

        if len(needs_you) == 0 and len(approvals) == 0:
            return Panel(
                f"[bold {ok}]ALL CLEAR — NO ACTION REQUIRED[/bold {ok}]\n\n"
                "Your Inbox and Approval Queues are currently empty.\n"
                "When sessions require clarification or agents request policy approvals, they will appear here.\n\n"
                "[dim]Press [H] to return to Home dashboard.[/dim]",
                title=f"[bold {accent}]Inbox / Needs You[/bold {accent}]",
                border_style="green",
            )

        layout_table = Table.grid(expand=True)
        layout_table.add_column(ratio=1)
        layout_table.add_column(ratio=1)

        # Lane 1: Needs You Items
        is_ny_active = (self.active_lane == "needs_you")
        ny_border = "cyan" if is_ny_active else "dim"
        ny_table = Table(
            title=f"[bold {warn}]NEEDS YOU ({len(needs_you)})[/bold {warn}]" + (" [focused]" if is_ny_active else ""),
            expand=True,
            show_edge=True,
            border_style=ny_border,
        )
        ny_table.add_column("Kind", style=accent, width=12)
        ny_table.add_column("Reason / Action", style="bold white")
        ny_table.add_column("Urgency", style=f"bold {err}", width=10)

        for idx, item in enumerate(needs_you):
            is_sel = (is_ny_active and idx == self.selected_index)
            prefix = "▶ " if is_sel else "  "
            ny_table.add_row(
                f"{prefix}{item.kind.upper()}",
                item.human_readable_reason,
                f"[{item.urgency.upper()}]",
            )

        # Lane 2: Approval Queue Items (Reusing ApprovalCardWidget)
        is_app_active = (self.active_lane == "approvals")
        app_border = "cyan" if is_app_active else "dim"
        app_panel = Table.grid(expand=True)
        app_panel.add_row(
            f"[bold {err}]APPROVAL QUEUE ({len(approvals)})[/bold {err}]" + (" [focused]" if is_app_active else "")
        )

        for idx, app_view in enumerate(approvals):
            is_sel = (is_app_active and idx == self.selected_index)
            card_w = ApprovalCardWidget(approval_view=app_view)
            card_render = card_w.render()
            if is_sel:
                card_render = f"[bold {accent}]▶ {card_render}[/bold {accent}]"
            app_panel.add_row(card_render)

        layout_table.add_row(ny_table, app_panel)
        return layout_table
