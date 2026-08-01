"""SessionArenaWidget domain screen for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.3, §7.1, §7.2, §7.3, §14.8 Steps 1-6 (Phase D)
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from textual import work
from textual.events import Key, Resize
from textual.widgets import Static

from kin.schemas import DecisionKind
from kin.tui.layout import Breakpoint, classify_breakpoint
from kin.tui.local_state import (
    cancel_session_command,
    decide_pending_approval,
    get_approvals_for_session,
    get_artifacts_for_session,
    get_local_contacts_summaries,
    get_session_detail,
    get_session_events,
    get_session_list,
    get_stale_peer_card_count,
    pause_session,
    resume_session,
)
from kin.tui.state import ApprovalView, ArtifactView, RecoverableError, SessionSummary, UiEvent
from kin.tui.tokens import get_glyph
from kin.tui.widgets.activity_feed import ActivityFeedWidget
from kin.tui.widgets.approval_card import ApprovalCardWidget
from kin.tui.widgets.approval_modals import ApproveConfirmModal, DenyReasonModal, EditConstraintsModal, PatchApplyConfirmModal
from kin.tui.widgets.artifact_list import ArtifactListWidget
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.inspector import InspectorWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.session_map import SessionMapWidget
from kin.tui.widgets.session_state_modal import SessionStateMenuModal
from kin.tui.widgets.trust_strip import TrustStripWidget


class SessionArenaWidget(LifecycleWidgetMixin, Static):
    """Session Arena domain widget composing header, session map, exchange timeline, activity feed, artifacts, and inspector (§14.8 Phase D).

    Supports Focus/Cockpit modes and 5 active lane views (§5.3, §7.1, §14.8):
    - Cockpit mode: breakpoint-driven multi-lane composition (wide 3-column, standard 2-column, compact/minimal stacked).
    - Focus mode (z key): full-bleed active lane view hiding session map and inspector.
    - Lanes:
      - Transcript lane (t): ExchangeTimelineWidget with DEFAULT_ALLOWED_CLASSES.
      - Activity lane (e): ActivityFeedWidget with activity/security events.
      - Outputs lane (o): ArtifactListWidget with session artifacts.
      - Decisions lane (c): ExchangeTimelineWidget filtered to checkpoints.
      - Needs-you lane (u): Pending approval cards with interactive [a]pprove, [d]eny, [e]dit, [b]ounded actions.
    - Inspector toggle (i): toggles Arena-local inspector panel.
    - Session State Menu (s): opens pause/resume/cancel modal surface with disabled hand-back option.
    """

    can_focus = True

    DEFAULT_CSS = """
    SessionArenaWidget {
        width: 100%;
        height: 100%;
        background: $surface;
        color: $text;
        overflow-y: auto;
    }
    SessionArenaWidget:focus {
        border: double $accent;
    }
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        profile_name: str = "default",
        profile_dir: Optional[Path] = None,
        session_summary: Optional[SessionSummary] = None,
        events: Optional[List[UiEvent]] = None,
        artifacts: Optional[List[ArtifactView]] = None,
        approvals: Optional[List[ApprovalView]] = None,
        selected_event_id: Optional[str] = None,
        reduced_motion: bool = False,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(id="session-arena-widget", now=now, **kwargs)
        self.session_id = session_id
        self.profile_name = profile_name
        self.profile_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)

        self._session_summary_override = session_summary
        self._events_override = events
        self._artifacts_override = artifacts
        self._approvals_override = approvals

        self.selected_event_id = selected_event_id
        self.reduced_motion = reduced_motion
        self.selected_event: Optional[UiEvent] = None
        self.session_summary: Optional[SessionSummary] = None
        self.last_arena_error: Optional[RecoverableError] = None
        self.last_trust_error: Optional[str] = None
        self.breakpoint: Breakpoint = "wide"

        # Phase D layout & lane state (§5.3, §14.8 Phase D)
        self.focus_mode: bool = False
        self.active_lane: str = "transcript"
        self.inspector_visible: bool = True
        self.selected_approval_index: int = 0

        # Sub-widgets
        self.trust_strip_widget = TrustStripWidget()
        self.session_map_widget = SessionMapWidget()
        self.exchange_timeline_widget = ExchangeTimelineWidget()
        self.activity_feed_widget = ActivityFeedWidget()
        self.artifact_list_widget = ArtifactListWidget()
        self.inspector_widget = InspectorWidget()

        self.load_arena_data()

    def load_arena_data(self) -> None:
        """Load session data using Phase A data functions (§14.8 Phase B/D)."""
        if self._session_summary_override is not None:
            self.session_summary = self._session_summary_override
        else:
            self.session_summary = get_session_detail(self.profile_dir, self.session_id, self.profile_name)
            if self.session_summary is None:
                self.last_arena_error = RecoverableError(
                    what_happened="Session Not Found",
                    impact="Session details and event logs cannot be loaded.",
                    preserved="No local data lost.",
                    next_action="Select a valid session from the sidebar or Home screen.",
                    technical_detail=f"Session ID '{self.session_id}' not found in profile '{self.profile_name}' database.",
                )
                self.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)
                return

        # 2. Trust check
        self.trust_strip_widget.session_summary = self.session_summary
        try:
            contacts = get_local_contacts_summaries(self.profile_dir, self.profile_name) or []
            peer_username = self.session_summary.receiver_username
            peer_contact = next((c for c in contacts if c.username == peer_username), None)

            if peer_contact:
                self.trust_strip_widget.card_view = peer_contact
            else:
                self.trust_strip_widget.card_view = None

            stale_count = get_stale_peer_card_count(self.profile_dir, self.profile_name)
            self.trust_strip_widget.is_stale_peer = (peer_contact.status == "stale") if peer_contact else False
            self.trust_strip_widget.is_missing_peer = (peer_contact is None)
            self.trust_strip_widget.is_trust_unknown = False

        except Exception as exc:
            self.last_trust_error = str(exc)
            self.trust_strip_widget.is_trust_unknown = True
            self.trust_strip_widget.is_missing_peer = False
            self.trust_strip_widget.is_stale_peer = False

        # 3. Events resolution
        if self._events_override is not None:
            self.events = self._events_override
        else:
            self.events = get_session_events(self.profile_dir, self.session_id, self.profile_name)

        # 4. Artifacts resolution
        if self._artifacts_override is not None:
            self.artifacts = self._artifacts_override
        else:
            self.artifacts = get_artifacts_for_session(self.profile_dir, self.session_id, self.profile_name)

        # 5. Approvals resolution
        if self._approvals_override is not None:
            self.approvals = self._approvals_override
        else:
            self.approvals = get_approvals_for_session(self.profile_dir, self.session_id, self.profile_name)

        # 6. Session map resolution
        all_sessions = get_session_list(self.profile_dir, self.profile_name)
        self.session_map_widget = SessionMapWidget(
            sessions=all_sessions,
            active_session_id=self.session_id,
        )

        self.exchange_timeline_widget = ExchangeTimelineWidget(
            events=self.events,
            selected_event_id=self.selected_event_id,
            allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES if self.active_lane == "transcript" else {"checkpoint"},
            on_event_selected=self._on_event_selected,
            reduced_motion=self.reduced_motion,
        )
        self.activity_feed_widget = ActivityFeedWidget(events=self.events)
        self.artifact_list_widget = ArtifactListWidget(artifacts=self.artifacts)

        # Initial selected event for inspector
        if self.events and not self.selected_event:
            self.selected_event = self.events[0]

        self.inspector_widget = InspectorWidget(
            selected_event=self.selected_event,
        )

    def _on_event_selected(self, event: UiEvent) -> None:
        self.selected_event = event
        self.inspector_widget.selected_event = event
        self.refresh()

    def toggle_focus_mode(self) -> None:
        """Toggle Focus vs Cockpit mode (z key) (§5.3, §14.8 Phase D)."""
        self.focus_mode = not self.focus_mode
        mode_str = "Focus (Full-Bleed)" if self.focus_mode else "Cockpit (Multi-Lane)"
        if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
            self.app.status_bar.status_message = f"Arena layout set to {mode_str}."
            self.app.status_bar.refresh()
        self.refresh()

    def switch_lane(self, lane: str) -> None:
        """Switch active lane view (t=transcript, e=activity, o=outputs, c=decisions) (§5.3, §14.8 Phase D)."""
        self.active_lane = lane
        if lane == "transcript":
            self.exchange_timeline_widget.allowed_presentation_classes = ExchangeTimelineWidget.DEFAULT_ALLOWED_CLASSES
        elif lane == "decisions":
            self.exchange_timeline_widget.allowed_presentation_classes = {"checkpoint"}

        lane_labels = {
            "transcript": "Transcript Lane (t)",
            "activity": "Activity Lane (e)",
            "outputs": "Outputs Lane (o)",
            "decisions": "Decisions Lane (c)",
            "needs_you": "Needs-You Queue (u)",
        }
        if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
            self.app.status_bar.status_message = f"Switched to {lane_labels.get(lane, lane)}."
            self.app.status_bar.refresh()
        self.refresh()

    def toggle_inspector(self) -> None:
        """Toggle inspector panel visibility inside Arena (i key) (§5.3, §14.8 Phase D)."""
        self.inspector_visible = not self.inspector_visible
        vis_str = "visible" if self.inspector_visible else "hidden"
        if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
            self.app.status_bar.status_message = f"Arena Inspector {vis_str}."
            self.app.status_bar.refresh()
        self.refresh()

    def open_needs_you_lane(self) -> None:
        """Open Needs-you Queue lane (u key) (§5.3, §14.8 Phase D)."""
        self.switch_lane("needs_you")

    def open_session_state_menu(self) -> None:
        """Open Session State Menu modal (s key) (§5.3, §14.8 Phase D)."""
        if not (self.is_mounted and hasattr(self, "app") and self.app):
            return
        curr_status = self.session_summary.status if self.session_summary else "active"
        modal = SessionStateMenuModal(session_id=self.session_id or "sess-unknown", current_status=curr_status)

        def handle_action(action: Optional[str]) -> None:
            if not action:
                return
            if action == "pause":
                self.app.gate_consequential_action(
                    "Pause Session",
                    f"Pause session {self.session_id[:12]}?",
                    on_confirm=lambda: self._execute_session_state_change("pause")
                )
            elif action == "resume":
                self.app.gate_consequential_action(
                    "Resume Session",
                    f"Resume session {self.session_id[:12]}?",
                    on_confirm=lambda: self._execute_session_state_change("resume")
                )
            elif action == "cancel":
                self.app.gate_consequential_action(
                    "Cancel Session",
                    f"Cancel session {self.session_id[:12]} permanently?",
                    on_confirm=lambda: self._execute_session_state_change("cancel")
                )

        self.app.push_screen(modal, handle_action)

    def _execute_session_state_change(self, action: str) -> None:
        if action == "pause":
            ok, err = pause_session(self.profile_dir, self.profile_name, session_id=self.session_id)
            msg = "Session paused."
        elif action == "resume":
            ok, err = resume_session(self.profile_dir, self.profile_name, session_id=self.session_id)
            msg = "Session resumed."
        elif action == "cancel":
            ok, err = cancel_session_command(self.profile_dir, self.profile_name, session_id=self.session_id)
            msg = "Session cancelled."
        else:
            return

        if ok:
            self.load_arena_data()
            if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = msg
                self.app.status_bar.refresh()
            self.refresh()
        elif err and self.is_mounted and hasattr(self, "app") and self.app:
            self.last_arena_error = err
            self.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)
            self.refresh()

    def handle_approval_key(self, key: str) -> None:
        """Handle interactive approval actions from inside Session Arena Needs-You lane (§14.8 Phase D)."""
        if not self.approvals or not (0 <= self.selected_approval_index < len(self.approvals)):
            return

        app_view = self.approvals[self.selected_approval_index]
        app_req = app_view.request
        if not app_req:
            return

        app_id = app_req.approval_id
        if not (self.is_mounted and hasattr(self, "app") and self.app):
            return

        if key == "a":
            modal = ApproveConfirmModal("APPROVE ONCE", f"Approve request {app_id[:8]} once?")
            def on_confirm(confirmed: bool) -> None:
                if confirmed:
                    self._execute_approval_decision(app_id, DecisionKind.APPROVE_ONCE)
            self.app.push_screen(modal, on_confirm)

        elif key == "d":
            modal = DenyReasonModal(approval_id=app_id)
            def on_reason(reason: Optional[str]) -> None:
                if reason:
                    self._execute_approval_decision(app_id, DecisionKind.DENY, reason=reason)
            self.app.push_screen(modal, on_reason)

        elif key == "e":
            modal = EditConstraintsModal(approval_id=app_id)
            def on_constraints(constraints: Optional[dict]) -> None:
                if constraints is not None:
                    self._execute_approval_decision(app_id, DecisionKind.EDIT_CONSTRAINTS, constraints=constraints)
            self.app.push_screen(modal, on_constraints)

        elif key == "b":
            modal = ApproveConfirmModal("ALWAYS ALLOW BOUNDED", f"Always allow request {app_id[:8]} within bounds?")
            def on_confirm(confirmed: bool) -> None:
                if confirmed:
                    self._execute_approval_decision(app_id, DecisionKind.ALWAYS_ALLOW_BOUNDED)
            self.app.push_screen(modal, on_confirm)

    def _execute_approval_decision(self, approval_id: str, decision: DecisionKind, reason: Optional[str] = None, constraints: Optional[dict] = None) -> None:
        ok, err = decide_pending_approval(
            self.profile_dir,
            approval_id=approval_id,
            session_id=self.session_id or "",
            decision=decision,
            reason=reason,
            constraints=constraints,
            profile_name=self.profile_name,
        )
        if ok:
            self.load_arena_data()
            if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = f"Approval decision '{decision.value}' applied to request {approval_id[:8]}."
                self.app.status_bar.refresh()
            self.refresh()
        elif err and self.is_mounted and hasattr(self, "app") and self.app:
            self.last_arena_error = err
            self.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)

    def handle_artifact_key(self, key: str) -> None:
        """Handle interactive artifact import/patch actions in Outputs lane (§14.8 Phase D)."""
        selected_art = self.artifact_list_widget.get_selected_artifact()
        if not selected_art:
            if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = "No artifact selected in Outputs lane."
                self.app.status_bar.refresh()
            return

        meta = selected_art.metadata
        artifact_id = meta.artifact_id
        session_id = self.session_id or ""
        rel_target = meta.relative_target_path or f"imported_{artifact_id[:8]}.txt"

        if key == "v":
            # Import action
            title = f"CONFIRM WORKSPACE ARTIFACT IMPORT [{artifact_id[:8]}]"
            desc = (
                f"Write raw artifact bytes directly to workspace target file?\n\n"
                f"Target Relative Path: [bold cyan]{rel_target}[/bold cyan]"
            )
            modal = ApproveConfirmModal(title=title, description=desc)

            def _on_import_confirm(confirmed: Optional[bool]) -> None:
                if confirmed:
                    self._execute_import_artifact(artifact_id, rel_target)

            if self.is_mounted and hasattr(self, "app") and self.app:
                self.app.push_screen(modal, _on_import_confirm)

        elif key == "a":
            # Apply Patch action
            from kin.tui.local_state import preview_patch_action
            preview, rec_err = preview_patch_action(self.profile_dir, artifact_id=artifact_id, relative_target_path=rel_target)

            unified_diff = preview.unified_diff if preview else "--- a/target\n+++ b/target\n@@ -1 +1 @@\n-old\n+new"
            modal = PatchApplyConfirmModal(
                artifact_id=artifact_id,
                relative_target_path=rel_target,
                unified_diff=unified_diff,
            )

            def _on_patch_confirm(confirmed: Optional[bool]) -> None:
                if confirmed:
                    self._execute_apply_patch(artifact_id, rel_target)

            if self.is_mounted and hasattr(self, "app") and self.app:
                self.app.push_screen(modal, _on_patch_confirm)

    def _execute_import_artifact(self, artifact_id: str, relative_target_path: str) -> None:
        from kin.tui.local_state import import_artifact_action
        success, rec_err = import_artifact_action(
            self.profile_dir,
            session_id=self.session_id or "",
            artifact_id=artifact_id,
            relative_target_path=relative_target_path,
            profile_name=self.profile_name,
        )
        if success:
            msg = f"Imported artifact '{artifact_id[:8]}' into '{relative_target_path}'."
            if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = msg
                self.app.status_bar.refresh()
            self.load_arena_data()
            self.refresh()
        elif rec_err and self.is_mounted and hasattr(self, "app") and self.app:
            self.last_arena_error = rec_err
            self.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)

    def _execute_apply_patch(self, artifact_id: str, relative_target_path: str) -> None:
        from kin.tui.local_state import apply_patch_action
        success, rec_err = apply_patch_action(
            self.profile_dir,
            session_id=self.session_id or "",
            artifact_id=artifact_id,
            relative_target_path=relative_target_path,
            profile_name=self.profile_name,
        )
        if success:
            msg = f"Applied patch '{artifact_id[:8]}' to '{relative_target_path}'."
            if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = msg
                self.app.status_bar.refresh()
            self.load_arena_data()
            self.refresh()
        elif rec_err and self.is_mounted and hasattr(self, "app") and self.app:
            self.last_arena_error = rec_err
            self.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)
            self.refresh()

    def on_resize(self, event: Resize) -> None:
        self.breakpoint = classify_breakpoint(event.size.width, event.size.height)
        self.refresh()

    def on_key(self, event: Key) -> None:
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        k = event.key

        # 1. Needs-You Approval Actions (checked first to prevent key collision on 'e' with activity lane switch)
        if self.active_lane == "needs_you" and k in ("a", "d", "e", "b"):
            self.handle_approval_key(k)
            event.stop()
            return

        # 2. Outputs Lane Artifact Actions ('v' import, 'a' apply patch)
        if self.active_lane == "outputs" and k in ("v", "a"):
            self.handle_artifact_key(k)
            event.stop()
            return

        if k == "z":
            self.toggle_focus_mode()
            event.stop()
        elif k == "t":
            self.switch_lane("transcript")
            event.stop()
        elif k == "e":
            self.switch_lane("activity")
            event.stop()
        elif k == "c":
            self.switch_lane("decisions")
            event.stop()
        elif k == "o":
            self.switch_lane("outputs")
            event.stop()
        elif k == "u":
            self.open_needs_you_lane()
            event.stop()
        elif k == "i":
            self.toggle_inspector()
            event.stop()
        elif k == "s":
            self.open_session_state_menu()
            event.stop()
        elif k == "m":
            if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = "Compose message not yet available (Phase D2)."
                self.app.status_bar.refresh()
            event.stop()
        elif k == "r":
            if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = "Replay scrubber not yet available."
                self.app.status_bar.refresh()
            event.stop()
        elif k in ("down", "j"):
            if self.active_lane in ("transcript", "decisions"):
                self.exchange_timeline_widget.cursor_down()
                self.selected_event = self.exchange_timeline_widget.get_selected_event()
                self.inspector_widget.selected_event = self.selected_event
            elif self.active_lane == "needs_you" and self.approvals:
                self.selected_approval_index = min(self.selected_approval_index + 1, len(self.approvals) - 1)
            self.refresh()
            event.stop()
        elif k in ("up", "k"):
            if self.active_lane in ("transcript", "decisions"):
                self.exchange_timeline_widget.cursor_up()
                self.selected_event = self.exchange_timeline_widget.get_selected_event()
                self.inspector_widget.selected_event = self.selected_event
            elif self.active_lane == "needs_you" and self.approvals:
                self.selected_approval_index = max(self.selected_approval_index - 1, 0)
            self.refresh()
            event.stop()
        elif k == "g":
            if self.active_lane in ("transcript", "decisions"):
                self.exchange_timeline_widget.selected_index = 0
                self.selected_event = self.exchange_timeline_widget.get_selected_event()
                self.inspector_widget.selected_event = self.selected_event
            elif self.active_lane == "needs_you":
                self.selected_approval_index = 0
            self.refresh()
            event.stop()
        elif k in ("G", "end"):
            if self.active_lane in ("transcript", "decisions"):
                self.exchange_timeline_widget.jump_to_tail()
                self.selected_event = self.exchange_timeline_widget.get_selected_event()
                self.inspector_widget.selected_event = self.selected_event
            elif self.active_lane == "needs_you" and self.approvals:
                self.selected_approval_index = len(self.approvals) - 1
            self.refresh()
            event.stop()

    def append_events(self, new_events: List[UiEvent], now: Optional[Union[datetime, str, float]] = None) -> None:
        """Forward new events to ExchangeTimelineWidget and update selected inspector item (§14.8 Phase C2)."""
        self.exchange_timeline_widget.append_events(new_events, now=now)
        self.activity_feed_widget.events = self.exchange_timeline_widget.events
        self.events = self.exchange_timeline_widget.events
        self.selected_event = self.exchange_timeline_widget.get_selected_event()
        self.inspector_widget.selected_event = self.selected_event

    def append_event(self, evt: UiEvent, now: Optional[Union[datetime, str, float]] = None) -> None:
        self.append_events([evt], now=now)

    def handle_reconnect(self, replayed_events: List[UiEvent], now: Optional[Union[datetime, str, float]] = None) -> None:
        """Forward transport reconnect replayed events (§14.8 Phase C2)."""
        self.exchange_timeline_widget.handle_reconnect(replayed_events, now=now)
        self.activity_feed_widget.events = self.exchange_timeline_widget.events
        self.events = self.exchange_timeline_widget.events
        self.selected_event = self.exchange_timeline_widget.get_selected_event()
        self.inspector_widget.selected_event = self.selected_event

    def jump_to_tail(self) -> None:
        self.exchange_timeline_widget.jump_to_tail()
        self.selected_event = self.exchange_timeline_widget.get_selected_event()
        self.inspector_widget.selected_event = self.selected_event

    def _run_event_polling_worker_logic(self) -> None:
        """Core polling worker logic (§14.8 Phase C2)."""
        import time

        # Standing requirement guard: NEVER poll when session_id is empty or None
        if not self.session_id:
            return

        last_count = len(self.events)
        while getattr(self, "is_polling_active", False):
            time.sleep(getattr(self, "polling_interval_sec", 0.5))
            try:
                fetched = get_session_events(self.profile_dir, self.session_id, self.profile_name) or []
                if len(fetched) > last_count:
                    new_evts = fetched[last_count:]
                    last_count = len(fetched)
                    if hasattr(self, "is_mounted") and self.is_mounted and hasattr(self, "app") and self.app:
                        self.app.call_from_thread(self.append_events, new_evts)
            except Exception:
                pass

    @work(thread=True, exclusive=True, name="arena_event_poller")
    def run_event_polling_worker(self) -> None:
        """Background polling worker fetching new session events off main thread (§14.8 Phase C2)."""
        self._run_event_polling_worker_logic()

    def _render_needs_you_queue(self) -> str:
        lines = ["[bold yellow]─── NEEDS-YOU QUEUE (Pending Approvals & Security Items) ───[/bold yellow]"]
        sec_events = [e for e in (self.events or []) if e.presentation_class == "security" or "security" in str(e.kind).lower()]

        if not self.approvals and not sec_events:
            lines.append("[dim]No pending approvals or security decisions required for this session.[/dim]")
            return "\n\n".join(lines)

        if sec_events:
            glyph_alert = get_glyph("▲")
            glyph_x = get_glyph("✖")
            lines.append(f"[bold red]{glyph_alert} SECURITY REJECTION CARDS ({len(sec_events)}) — PERSISTENT ALERT[/bold red]")
            for sec_evt in sec_events:
                actor = sec_evt.actor_username or "unknown"
                lines.append(
                    f"  [bold red]{glyph_x} SECURITY REJECTION CARD [{sec_evt.event_id[:8]}][/bold red]\n"
                    f"     [red]Kind: {sec_evt.kind} | Actor: @{actor} | Timestamp: {sec_evt.created_at}[/red]\n"
                    f"     [red]Status: Validation Failed — Persistent Alert (No auto-dismiss)[/red]"
                )

        if self.approvals:
            lines.append(f"\nPending Approvals ({len(self.approvals)}): Press [a]pprove, [d]eny, [e]dit, [b]ounded\n")
            for idx, app_view in enumerate(self.approvals):
                is_selected = (idx == self.selected_approval_index)
                prefix = "▶ " if is_selected else "  "
                card_widget = ApprovalCardWidget(approval_view=app_view)
                lines.append(f"{prefix}{card_widget.render()}")

        return "\n\n".join(lines)

    def render(self) -> Union[str, Group]:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Session Arena...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Session Arena disabled"
            return f"[dim]Session Arena (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            error_msg = self.last_arena_error.what_happened if self.last_arena_error else "Session load error"
            error_detail = self.last_arena_error.technical_detail if (self.last_arena_error and self.last_arena_error.technical_detail) else ""
            return (
                f"[bold red]{glyph} Arena Error: {error_msg}[/bold red]\n"
                f"[dim]{error_detail}[/dim]\n\n"
                f"[yellow]Press [Retry] to attempt reloading session data.[/yellow]"
            )

        if state == WidgetLifecycleState.EMPTY or not self.session_summary:
            return "[dim]Session Arena: No active session selected.[/dim]"

        header_str = self.trust_strip_widget.render()
        map_str = self.session_map_widget.render()
        inspector_str = self.inspector_widget.render()

        # Classify terminal size breakpoint (§3.2, §14.8)
        app_size = None
        try:
            if self.is_mounted and self.app and self.app.size:
                app_size = self.app.size
        except Exception:
            app_size = None

        if app_size and app_size.width > 0 and app_size.height > 0:
            width, height = app_size.width, app_size.height
        elif self.size and self.size.width > 0 and self.size.height > 0:
            width, height = self.size.width, self.size.height
        else:
            width, height = 160, 44

        bp = classify_breakpoint(width, height)

        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        # Active center lane renderable (§14.8 Phase D)
        if self.active_lane in ("transcript", "decisions"):
            center_renderable = self.exchange_timeline_widget.render()
        elif self.active_lane == "activity":
            center_renderable = self.activity_feed_widget.render()
        elif self.active_lane == "outputs":
            center_renderable = self.artifact_list_widget.render()
        elif self.active_lane == "needs_you":
            center_renderable = self._render_needs_you_queue()
        else:
            center_renderable = self.exchange_timeline_widget.render()

        lane_title_map = {
            "transcript": "[bold green]EXCHANGE TIMELINE[/bold green]",
            "activity": "[bold green]ACTIVITY FEED[/bold green]",
            "outputs": "[bold green]OUTPUTS / ARTIFACTS[/bold green]",
            "decisions": "[bold green]DECISIONS / CHECKPOINTS[/bold green]",
            "needs_you": "[bold yellow]NEEDS-YOU QUEUE[/bold yellow]",
        }
        lane_title = lane_title_map.get(self.active_lane, f"[bold green]LANE: {self.active_lane.upper()}[/bold green]")

        # 1. FOCUS MODE (z key active) -> full-bleed active lane view hiding session map and inspector
        if self.focus_mode:
            return Group(
                header_str + focus_mark + " [bold yellow][FOCUS MODE][/bold yellow]",
                Panel(center_renderable, title=f"[bold cyan]FOCUS LANE: {self.active_lane.upper()}[/bold cyan]", border_style="cyan"),
            )

        # 2. COCKPIT MODE -> Breakpoint-driven layout
        if bp == "wide":
            grid = Table.grid(expand=True)
            grid.add_column("map", ratio=1)
            grid.add_column("timeline", ratio=2)
            if self.inspector_visible:
                grid.add_column("inspector", ratio=1)

            panel_map = Panel(map_str, title="[bold cyan]SESSION MAP[/bold cyan]", border_style="cyan")
            panel_timeline = Panel(center_renderable, title=lane_title, border_style="green")

            if self.inspector_visible:
                panel_inspector = Panel(inspector_str, title="[bold magenta]DETAIL INSPECTOR[/bold magenta]", border_style="magenta")
                grid.add_row(panel_map, panel_timeline, panel_inspector)
            else:
                grid.add_row(panel_map, panel_timeline)

            return Group(
                header_str + focus_mark,
                grid,
            )

        # 3. DOCKED INSPECTOR MODE (standard breakpoint: 120x36 - 159x43) -> 2-lane side-by-side Rich Table grid (§7.1, §14.8)
        elif bp == "standard":
            grid = Table.grid(expand=True)
            grid.add_column("timeline", ratio=2)
            if self.inspector_visible:
                grid.add_column("inspector", ratio=1)

            panel_timeline = Panel(center_renderable, title=lane_title, border_style="green")
            if self.inspector_visible:
                panel_inspector = Panel(inspector_str, title="[bold magenta]DOCKED INSPECTOR[/bold magenta]", border_style="magenta")
                grid.add_row(panel_timeline, panel_inspector)
            else:
                grid.add_row(panel_timeline)

            return Group(
                header_str + focus_mark,
                grid,
            )

        # 4. STACKED COMPACT MODE (compact/minimal breakpoint: <=90x24) -> vertically stacked compact lanes
        else:
            parts = [header_str + focus_mark, center_renderable]
            if self.inspector_visible:
                parts.append(inspector_str)
            return "\n\n".join(parts)
