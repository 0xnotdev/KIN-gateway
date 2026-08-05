"""SessionArenaWidget domain screen for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.3, §7.1, §7.2, §7.3, §14.8 Steps 1-6 (Phase D)
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from rich.console import Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from textual import work
from textual.events import Key, Resize
from textual.widgets import Static

from kin.schemas import AgentAvailability, DecisionKind
from kin.tui.layout import Breakpoint, classify_breakpoint
from kin.tui.redaction import redact_ui_text
from kin.tui.local_state import (
    cancel_session_command,
    create_private_note,
    create_session_checkpoint,
    create_session_decision,
    create_session_playbook,
    decide_pending_approval,
    get_approvals_for_session,
    get_artifacts_for_session,
    get_local_agents_summaries,
    get_local_contacts_summaries,
    get_local_identity_info,
    get_private_notes,
    get_session_detail,
    get_session_events,
    get_session_events_page,
    get_session_history_events,
    get_session_budget_gauges,
    get_session_list,
    get_session_outcome_card,
    get_stale_peer_card_count,
    pause_session,
    promote_private_note_to_peer_visible,
    resume_session,
    send_human_message_to_session_action,
    tag_in_session_agent,
)
from kin.tui.state import ApprovalView, ArtifactView, PrivateNoteView, RecoverableError, SessionSummary, UiEvent
from kin.tui.tokens import get_glyph
from kin.tui.widgets.activity_feed import ActivityFeedWidget
from kin.tui.widgets.agent_picker import AgentPickerWidget
from kin.tui.widgets.approval_card import ApprovalCardWidget
from kin.tui.widgets.approval_modals import ApproveConfirmModal, DenyReasonModal, EditConstraintsModal, PatchApplyConfirmModal
from kin.tui.widgets.artifact_list import ArtifactListWidget
from kin.tui.widgets.compose_modal import ComposeMessageModal
from kin.tui.keymap import build_arena_bindings
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.inspector import InspectorWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.private_note_modal import PrivateNoteAuthoringModal
from kin.tui.widgets.outcome_card import OutcomeCardWidget
from kin.tui.widgets.session_record_modal import SessionRecordModal
from kin.tui.widgets.session_map import SessionMapWidget
from kin.tui.widgets.session_state_modal import SessionStateMenuModal
from kin.tui.widgets.trust_strip import TrustStripWidget


class SessionArenaWidget(LifecycleWidgetMixin, Static):
    """Session Arena domain widget composing header, session map, exchange timeline, activity feed, artifacts, and inspector (§14.8 Phase D)."""

    can_focus = True
    BINDINGS = build_arena_bindings()

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
        self.events: List[UiEvent] = events or []
        self.artifacts: List[ArtifactView] = artifacts or []
        self.approvals: List[ApprovalView] = approvals or []
        self.private_notes: List[PrivateNoteView] = []
        self.outcome_card = None
        self.budget_gauges = None
        self.last_arena_error: Optional[RecoverableError] = None
        self.last_trust_error: Optional[str] = None
        self.breakpoint: Breakpoint = "wide"
        self.is_polling_active: bool = False
        self._poll_generation: int = 0

        # Phase D layout & lane state (§5.3, §14.8 Phase D)
        self.focus_mode: bool = False
        self.active_lane: str = "transcript"
        self.inspector_visible: bool = True
        self.selected_approval_index: int = 0
        self.selected_note_index: int = 0
        self.is_replay_mode: bool = False
        self.replay_index: Optional[int] = None
        self.event_page_size: int = 500
        self.has_older_events: bool = False

        # Sub-widgets
        self.trust_strip_widget = TrustStripWidget()
        self.session_map_widget = SessionMapWidget()
        self.exchange_timeline_widget = ExchangeTimelineWidget()
        self.activity_feed_widget = ActivityFeedWidget()
        self.artifact_list_widget = ArtifactListWidget()
        self.inspector_widget = InspectorWidget()

        self.load_arena_data()

    def set_reduced_motion(self, active: bool) -> None:
        """Propagate effective motion state to the live timeline immediately."""
        self.reduced_motion = bool(active)
        self.exchange_timeline_widget.set_reduced_motion(active)
        if self.is_mounted:
            self.refresh(layout=False)

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
            self.events, self.has_older_events = get_session_events_page(
                self.profile_dir,
                self.session_id,
                self.profile_name,
                page_size=self.event_page_size,
            )
            history_events = get_session_history_events(
                self.profile_dir,
                self.session_id or "",
                self.profile_name,
            )
            self.events = sorted(
                [*self.events, *history_events],
                key=lambda event: (
                    event.event_order is None,
                    event.event_order if event.event_order is not None else 0,
                    event.created_at,
                    event.event_id,
                ),
            )

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

        # 6. Owner-only notes use a separate projection so they never enter
        # Timeline, Activity, Decisions, Inspector, replay, or live polling.
        self.private_notes = get_private_notes(
            self.profile_dir,
            self.session_id or "",
            self.profile_name,
        )
        if self.private_notes:
            self.selected_note_index = min(self.selected_note_index, len(self.private_notes) - 1)
        else:
            self.selected_note_index = 0
        self.outcome_card = get_session_outcome_card(
            self.profile_dir,
            self.session_id or "",
            self.profile_name,
        )
        self.budget_gauges = get_session_budget_gauges(
            self.profile_dir,
            self.profile_name,
            self.session_id or "",
        )

        # 7. Session map resolution
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

    def load_older_events(self) -> int:
        """Prepend one durable event page while preserving event IDs and selection."""
        orders = [event.event_order for event in self.events if event.event_order is not None]
        if not self.has_older_events or not orders:
            return 0
        selected_id = self.selected_event.event_id if self.selected_event else None
        older, self.has_older_events = get_session_events_page(
            self.profile_dir,
            self.session_id or "",
            self.profile_name,
            page_size=self.event_page_size,
            before_event_order=min(orders),
        )
        existing = {event.event_id for event in self.events}
        older = [event for event in older if event.event_id not in existing]
        self.events = [*older, *self.events]
        self.exchange_timeline_widget.events = list(self.events)
        if selected_id:
            for index, event in enumerate(self.events):
                if event.event_id == selected_id:
                    self.exchange_timeline_widget.selected_index = index
                    break
        self.refresh()
        return len(older)

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
            "notes": "Private Notes — Local Only (l)",
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

    def open_private_note_authoring(self) -> None:
        """Open the owner-only note editor; creation itself is non-consequential."""
        if not (self.is_mounted and hasattr(self, "app") and self.app):
            return

        def handle_note(note_text: Optional[str]) -> None:
            if not note_text:
                return
            _, identity_username, _ = get_local_identity_info(
                self.profile_name,
                self.profile_dir,
            )
            actor_username = identity_username or self.profile_name
            ok, error = create_private_note(
                self.profile_dir,
                self.profile_name,
                self.session_id or "",
                actor_username,
                note_text,
            )
            if ok:
                self.load_arena_data()
                self.switch_lane("notes")
                self.app.status_bar.status_message = "Private note saved locally."
            elif error:
                self.last_arena_error = error
                self.app.status_bar.status_message = f"Private note failed: {error.what_happened}"
            self.app.status_bar.refresh()
            self.refresh()

        self.app.push_screen(
            PrivateNoteAuthoringModal(self.session_id or "sess-unknown"),
            handle_note,
        )

    def get_selected_private_note(self) -> Optional[PrivateNoteView]:
        if not self.private_notes:
            return None
        self.selected_note_index = max(
            0,
            min(self.selected_note_index, len(self.private_notes) - 1),
        )
        return self.private_notes[self.selected_note_index]

    def promote_selected_private_note(self) -> None:
        """Gate promotion while showing the exact text that will cross the boundary."""
        note = self.get_selected_private_note()
        if note is None or not (self.is_mounted and hasattr(self, "app") and self.app):
            return

        exact_text = escape(note.note_text)
        self.app.gate_consequential_action(
            "Promote Private Note to Peer-Visible Signed Message",
            f'EXACT TEXT TO SEND: "{exact_text}"',
            on_confirm=lambda: self._execute_private_note_promotion(note.event_id),
        )

    def _execute_private_note_promotion(self, note_event_id: str) -> None:
        ok, error = promote_private_note_to_peer_visible(
            self.profile_dir,
            self.profile_name,
            self.session_id or "",
            note_event_id,
        )
        if ok:
            self.load_arena_data()
            self.app.status_bar.status_message = "Private note promoted as a signed peer-visible message."
        elif error:
            self.last_arena_error = error
            self.app.status_bar.status_message = f"Private note promotion failed: {error.what_happened}"
        self.app.status_bar.refresh()
        self.refresh()

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
            elif action == "tag_in":
                self._open_tag_in_picker()

        self.app.push_screen(modal, handle_action)

    def _open_tag_in_picker(self) -> None:
        agents = [
            agent for agent in get_local_agents_summaries(self.profile_dir, self.profile_name)
            if agent.availability not in (AgentAvailability.OFFLINE, AgentAvailability.POLICY_BLOCKED)
        ]
        if not agents:
            self.app.status_bar.status_message = "No enabled local specialist is available to tag in."
            self.app.status_bar.refresh()
            return

        def review_agent(agent) -> None:
            boundary = escape(agent.boundary_summary or "Owner-controlled local boundaries")
            self.app.gate_consequential_action(
                "Tag In Specialist",
                f"Replace your participating agent with {escape(agent.name)} ({escape(agent.agent_id)})?\n"
                f"Boundary: {boundary}\n"
                "A signed participant_changed event and bounded handoff package will be sent to the peer.",
                on_confirm=lambda: self._execute_tag_in(agent.agent_id),
            )

        self.app.push_screen(
            AgentPickerWidget(
                agents=agents,
                prompt="Choose your replacement specialist (Tab reviews boundaries)",
                on_select=review_agent,
            )
        )

    def _execute_tag_in(self, replacement_agent_id: str) -> None:
        ok, result, error = tag_in_session_agent(
            self.profile_dir,
            self.profile_name,
            session_id=self.session_id or "",
            replacement_agent_id=replacement_agent_id,
        )
        if ok:
            self.load_arena_data()
            delivery = (result or {}).get("status", "recorded")
            self.app.status_bar.status_message = f"Specialist tagged in; signed change {delivery}."
            self.app.status_bar.refresh()
            self.refresh()
        elif error:
            self.last_arena_error = error
            self.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)
            self.app.status_bar.status_message = error.what_happened
            self.app.status_bar.refresh()
            self.refresh()

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
            accent = self._c("accent.primary", "#bb9af7")
            desc = (
                f"Write raw artifact bytes directly to workspace target file?\n\n"
                f"Target Relative Path: [bold {accent}]{rel_target}[/bold {accent}]"
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

    def action_lane_focus(self) -> None:
        self.toggle_focus_mode()

    def action_lane_transcript(self) -> None:
        self.switch_lane("transcript")

    def action_lane_activity(self) -> None:
        if self.active_lane == "needs_you":
            self.handle_approval_key("e")
        else:
            self.switch_lane("activity")

    def action_lane_outputs(self) -> None:
        self.switch_lane("outputs")

    def action_lane_decisions(self) -> None:
        self.switch_lane("decisions")

    def action_lane_needs_you(self) -> None:
        self.open_needs_you_lane()

    def action_lane_notes(self) -> None:
        self.switch_lane("notes")

    def action_promote_private_note(self) -> None:
        if self.active_lane == "notes":
            self.promote_selected_private_note()

    def action_toggle_inspector_arena(self) -> None:
        self.toggle_inspector()

    def action_replay_item(self) -> None:
        if self.events:
            if self.is_replay_mode:
                self.exit_replay_mode()
            else:
                self.enter_replay_mode()
            self.refresh()

    def _open_session_record_modal(self, record_kind: str) -> None:
        if not (self.is_mounted and hasattr(self, "app") and self.app):
            return

        def handle_record(text: Optional[str]) -> None:
            if not text:
                return
            _, identity_username, _ = get_local_identity_info(self.profile_name, self.profile_dir)
            actor = identity_username or self.profile_name
            if record_kind == "checkpoint":
                ok, error = create_session_checkpoint(
                    self.profile_dir, self.profile_name, self.session_id or "", actor, text
                )
            else:
                ok, error = create_session_decision(
                    self.profile_dir, self.profile_name, self.session_id or "", actor, text
                )
            if ok:
                self.load_arena_data()
                self.switch_lane("decisions")
                self.app.status_bar.status_message = f"{record_kind.title()} persisted in ordered history."
            elif error:
                self.last_arena_error = error
                self.app.status_bar.status_message = f"{record_kind.title()} failed: {error.what_happened}"
            self.app.status_bar.refresh()
            self.refresh()

        self.app.push_screen(
            SessionRecordModal(self.session_id or "sess-unknown", record_kind),
            handle_record,
        )

    def action_record_checkpoint(self) -> None:
        self._open_session_record_modal("checkpoint")

    def action_record_decision(self) -> None:
        self._open_session_record_modal("decision")

    def action_create_playbook(self) -> None:
        if self.outcome_card is None or not (self.is_mounted and hasattr(self, "app") and self.app):
            return
        objective = self.session_summary.objective if self.session_summary else "Session"
        ok, playbook_id, error = create_session_playbook(
            self.profile_dir,
            self.profile_name,
            self.session_id or "",
            f"{(objective or 'Session')[:48]} playbook",
        )
        if ok:
            self.app.status_bar.status_message = (
                f"Local playbook {playbook_id} created; peer, agents, and approvals must be chosen fresh."
            )
        elif error:
            self.app.status_bar.status_message = error.what_happened
        self.app.status_bar.refresh()

    def _render_budget_gauges(self) -> str:
        if self.budget_gauges is None:
            return "[dim]Budget gauges unavailable.[/dim]"
        gauge = self.budget_gauges

        def percent(value: Optional[float]) -> str:
            return "uncapped" if value is None else f"{value * 100:.0f}%"

        cost = (
            "not reported"
            if gauge.local_cost_estimate is None
            else f"{gauge.local_cost_estimate:.2f} / {gauge.local_cost_limit or 'uncapped'} ({percent(gauge.cost_fraction)})"
        )
        peer = f" | Peer summary: {redact_ui_text(gauge.peer_cost_summary)}" if gauge.peer_cost_summary else ""
        return (
            "[bold]LOCAL BUDGET / IMPACT GAUGES[/bold]\n"
            f"Time: {gauge.elapsed_seconds:.0f}s / {gauge.runtime_limit_seconds or 'uncapped'} ({percent(gauge.runtime_fraction)})\n"
            f"Artifacts: {gauge.artifact_bytes}B / {gauge.artifact_limit_bytes or 'uncapped'} ({percent(gauge.artifact_fraction)})\n"
            f"Local cost estimate: {cost}{peer}"
        )

    def action_session_state_menu(self) -> None:
        self.open_session_state_menu()

    def action_compose_message(self) -> None:
        if self.is_mounted and hasattr(self, "app") and self.app:
            is_clarification = (self.session_summary.status in ("peer_review", "needs_clarification")) if self.session_summary else False
            def _handle_compose_result(content: Optional[str]) -> None:
                if content and content.strip():
                    self._dispatch_compose_message(content.strip())
            self.app.push_screen(ComposeMessageModal(self.session_id, is_clarification=is_clarification), _handle_compose_result)

    def action_approve_item(self) -> None:
        if self.active_lane == "needs_you":
            self.handle_approval_key("a")
        elif self.active_lane == "outputs":
            self.handle_artifact_key("a")

    def action_deny_item(self) -> None:
        if self.active_lane == "needs_you":
            self.handle_approval_key("d")

    def action_edit_constraints(self) -> None:
        if self.active_lane == "needs_you":
            self.handle_approval_key("e")

    def action_bounded_approval(self) -> None:
        if self.active_lane == "needs_you":
            self.handle_approval_key("b")

    def action_import_artifact(self) -> None:
        if self.active_lane == "outputs":
            self.handle_artifact_key("v")

    def on_key(self, event: Key) -> None:
        """Handle navigation keys with complex lane-dependent cursor logic.

        Command keys (z, t, e, c, o, u, i, s, m, r, a, d, b, v) are handled
        exclusively via BINDINGS → action_* methods. Only navigation keys
        remain here because they require multi-branch cursor arithmetic that
        doesn't map cleanly to a single Textual action.
        """
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        k = event.key

        if k in ("down", "j"):
            if self.active_lane in ("transcript", "decisions"):
                self.exchange_timeline_widget.cursor_down()
                self.selected_event = self.exchange_timeline_widget.get_selected_event()
                self.inspector_widget.selected_event = self.selected_event
            elif self.active_lane == "needs_you" and self.approvals:
                self.selected_approval_index = min(self.selected_approval_index + 1, len(self.approvals) - 1)
            elif self.active_lane == "notes" and self.private_notes:
                self.selected_note_index = min(self.selected_note_index + 1, len(self.private_notes) - 1)
            self.refresh()
            event.stop()
        elif k == "pageup" and self.active_lane in ("transcript", "decisions"):
            loaded = self.load_older_events()
            if self.is_mounted and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = (
                    f"Loaded {loaded} older verified events."
                    if loaded
                    else "No older verified events remain."
                )
                self.app.status_bar.refresh()
            event.stop()
        elif k in ("up", "k"):
            if self.active_lane in ("transcript", "decisions"):
                self.exchange_timeline_widget.cursor_up()
                self.selected_event = self.exchange_timeline_widget.get_selected_event()
                self.inspector_widget.selected_event = self.selected_event
            elif self.active_lane == "needs_you" and self.approvals:
                self.selected_approval_index = max(self.selected_approval_index - 1, 0)
            elif self.active_lane == "notes" and self.private_notes:
                self.selected_note_index = max(self.selected_note_index - 1, 0)
            self.refresh()
            event.stop()
        elif k == "g":
            if self.active_lane in ("transcript", "decisions"):
                self.exchange_timeline_widget.selected_index = 0
                self.selected_event = self.exchange_timeline_widget.get_selected_event()
                self.inspector_widget.selected_event = self.selected_event
            elif self.active_lane == "needs_you":
                self.selected_approval_index = 0
            elif self.active_lane == "notes":
                self.selected_note_index = 0
            self.refresh()
            event.stop()
        elif k in ("G", "end"):
            if self.is_replay_mode:
                self.exit_replay_mode()
            if self.active_lane in ("transcript", "decisions"):
                self.exchange_timeline_widget.jump_to_tail()
                self.selected_event = self.exchange_timeline_widget.get_selected_event()
                self.inspector_widget.selected_event = self.selected_event
            elif self.active_lane == "needs_you" and self.approvals:
                self.selected_approval_index = len(self.approvals) - 1
            elif self.active_lane == "notes" and self.private_notes:
                self.selected_note_index = len(self.private_notes) - 1
            self.refresh()
            event.stop()

    def enter_replay_mode(self, target_index: Optional[int] = None) -> None:
        """Enter read-only timeline replay mode (§14.8 Step 5)."""
        if not self.events:
            return
        self.is_replay_mode = True
        idx = target_index if target_index is not None else self.exchange_timeline_widget.selected_index
        idx = max(0, min(idx, len(self.events) - 1))
        self.replay_index = idx
        self.exchange_timeline_widget.events = self.events[: idx + 1]
        self.exchange_timeline_widget.selected_index = idx
        self.selected_event = self.exchange_timeline_widget.get_selected_event()
        self.inspector_widget.selected_event = self.selected_event
        if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
            self.app.status_bar.status_message = (
                f"[REPLAY MODE] Event {idx + 1}/{len(self.events)} - Press 'r' or 'G' to return to live."
            )
            self.app.status_bar.refresh()

    def exit_replay_mode(self) -> None:
        """Exit replay mode and restore live tail-follow view (§14.8 Step 5)."""
        self.is_replay_mode = False
        self.replay_index = None
        self.exchange_timeline_widget.events = list(self.events)
        self.exchange_timeline_widget.jump_to_tail()
        self.selected_event = self.exchange_timeline_widget.get_selected_event()
        self.inspector_widget.selected_event = self.selected_event
        if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
            self.app.status_bar.status_message = "Exited replay mode. Returned to live tail-follow."
            self.app.status_bar.refresh()

    def append_events(self, new_events: List[UiEvent], now: Optional[Union[datetime, str, float]] = None) -> None:
        """Forward new events to ExchangeTimelineWidget while updating master events list (§14.8 Phase C2)."""
        self.events.extend(new_events)
        if any(event.kind == "outcome" for event in new_events):
            self.outcome_card = get_session_outcome_card(
                self.profile_dir,
                self.session_id or "",
                self.profile_name,
            )
            self.budget_gauges = get_session_budget_gauges(
                self.profile_dir,
                self.profile_name,
                self.session_id or "",
            )
        if not self.is_replay_mode:
            self.exchange_timeline_widget.append_events(new_events, now=now)
            self.activity_feed_widget.events = self.exchange_timeline_widget.events
            self.selected_event = self.exchange_timeline_widget.get_selected_event()
            self.inspector_widget.selected_event = self.selected_event

    def _dispatch_compose_message(self, message_text: str) -> None:
        """Transmit composed message to session peer and update status bar (§14.8 Step 5/6)."""
        ok, res, err = send_human_message_to_session_action(
            profile_name=self.profile_name,
            session_id=self.session_id,
            message_text=message_text,
            profile_dir=self.profile_dir,
        )
        if ok and res:
            status = res.get("status", "sent")
            msg = f"Message {status} to session '{self.session_id}'."
            if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = msg
                self.app.status_bar.refresh()
        elif err:
            self.last_arena_error = err
            if self.is_mounted and hasattr(self, "app") and self.app and getattr(self.app, "status_bar", None):
                self.app.status_bar.status_message = f"Error: {err.what_happened}"
                self.app.status_bar.refresh()

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

    def on_mount(self) -> None:
        """Lifecycle hook when widget is mounted to app (§14.8 Phase C2 Round 2)."""
        self.set_reduced_motion(self._is_reduced_motion_active() or self.reduced_motion)
        self._poll_generation += 1
        self.is_polling_active = True
        if self.session_id:
            self.run_event_polling_worker(self._poll_generation)

    def on_unmount(self) -> None:
        """Lifecycle hook when widget is unmounted from app (§14.8 Phase C2 Round 2)."""
        self.is_polling_active = False
        self._poll_generation += 1

    def _run_event_polling_worker_logic(self, generation: Optional[int] = None) -> None:
        """Core polling worker logic with incremental cursor filtering (§14.8 Phase C2 Round 2)."""
        import time

        # Standing requirement guard: NEVER poll when session_id is empty or None
        if not self.session_id:
            return

        worker_generation = self._poll_generation if generation is None else generation
        seen_ids: Set[str] = {e.event_id for e in (self.events or []) if getattr(e, "event_id", None)}
        max_order: Optional[int] = max([e.event_order for e in (self.events or []) if getattr(e, "event_order", None) is not None], default=None)
        max_created: Optional[str] = max([e.created_at for e in (self.events or []) if getattr(e, "created_at", None)], default=None)

        while (
            getattr(self, "is_polling_active", False)
            and worker_generation == self._poll_generation
        ):
            time.sleep(getattr(self, "polling_interval_sec", 0.5))
            if (
                not getattr(self, "is_polling_active", False)
                or worker_generation != self._poll_generation
            ):
                break
            try:
                fetched = get_session_events(
                    self.profile_dir,
                    self.session_id,
                    self.profile_name,
                    seen_event_ids=seen_ids,
                    after_event_order=max_order,
                    after_created_at=max_created,
                ) or []
                local_history = get_session_history_events(
                    self.profile_dir,
                    self.session_id,
                    self.profile_name,
                ) or []
                fetched.extend(event for event in local_history if event.event_id not in seen_ids)
                fetched.sort(
                    key=lambda event: (
                        event.event_order is None,
                        event.event_order if event.event_order is not None else 0,
                        event.created_at,
                        event.event_id,
                    )
                )
                if fetched:
                    new_evts = [e for e in fetched if e.event_id not in seen_ids]
                    if new_evts:
                        for e in new_evts:
                            seen_ids.add(e.event_id)
                            if getattr(e, "event_order", None) is not None:
                                max_order = e.event_order if max_order is None else max(max_order, e.event_order)
                            if getattr(e, "created_at", None):
                                max_created = e.created_at if max_created is None else max(max_created, e.created_at)
                        if hasattr(self, "is_mounted") and self.is_mounted and hasattr(self, "app") and self.app:
                            self.app.call_from_thread(self.append_events, new_evts)
            except Exception as exc:
                from kin.tui.errors import convert_exception_to_recoverable_error
                convert_exception_to_recoverable_error(exc, self.profile_dir)

    @work(thread=True, exclusive=True, name="arena_event_poller")
    def run_event_polling_worker(self, generation: Optional[int] = None) -> None:
        """Background polling worker fetching new session events off main thread (§14.8 Phase C2 Round 2)."""
        self._run_event_polling_worker_logic(generation)

    def _render_needs_you_queue(self) -> str:
        warn = self._c("state.waiting", "#e0af68")
        err = self._c("state.error", "#f7768e")

        lines = [f"[bold {warn}]─── NEEDS-YOU QUEUE (Pending Approvals & Security Items) ───[/bold {warn}]"]
        sec_events = [e for e in (self.events or []) if e.presentation_class == "security" or "security" in str(e.kind).lower()]

        if not self.approvals and not sec_events:
            lines.append("[dim]No pending approvals or security decisions required for this session.[/dim]")
            return "\n\n".join(lines)

        if sec_events:
            glyph_alert = get_glyph("▲")
            glyph_x = get_glyph("✖")
            lines.append(f"[bold {err}]{glyph_alert} SECURITY REJECTION CARDS ({len(sec_events)}) — PERSISTENT ALERT[/bold {err}]")
            for sec_evt in sec_events:
                actor = sec_evt.actor_username or "unknown"
                lines.append(
                    f"  [bold {err}]{glyph_x} SECURITY REJECTION CARD [{sec_evt.event_id[:8]}][/bold {err}]\n"
                    f"     [{err}]Kind: {sec_evt.kind} | Actor: @{actor} | Timestamp: {sec_evt.created_at}[/{err}]\n"
                    f"     [{err}]Status: Validation Failed — Persistent Alert (No auto-dismiss)[/{err}]"
                )

        if self.approvals:
            lines.append(f"\nPending Approvals ({len(self.approvals)}): Press [a]pprove, [d]eny, [e]dit, [b]ounded\n")
            for idx, app_view in enumerate(self.approvals):
                is_selected = (idx == self.selected_approval_index)
                prefix = "▶ " if is_selected else "  "
                card_widget = ApprovalCardWidget(approval_view=app_view)
                lines.append(f"{prefix}{card_widget.render()}")

        return "\n\n".join(lines)

    def _render_private_notes(self) -> str:
        """Render the dedicated owner-only lane without sharing timeline state."""
        accent = self._c("accent.primary", "#bb9af7")
        warn = self._c("state.waiting", "#e0af68")
        lines = [
            f"[bold {accent}]PRIVATE NOTES — LOCAL ONLY[/bold {accent}]",
            "[dim]These encrypted scratch notes are unsigned and never transported.[/dim]",
        ]
        if not self.private_notes:
            lines.append("[dim]No private notes. Press Ctrl+S to create one.[/dim]")
            return "\n\n".join(lines)

        for index, note in enumerate(self.private_notes):
            prefix = "▶" if index == self.selected_note_index else " "
            lines.append(
                f"{prefix} [bold]Note {index + 1}[/bold] — {note.created_at} — @{note.actor_username}\n"
                f"   {escape(note.note_text)}"
            )
        lines.append(
            f"[bold {warn}]Press p to review the exact selected text and promote it as a signed peer-visible message.[/bold {warn}]"
        )
        return "\n\n".join(lines)

    def render(self) -> Union[str, Group]:
        ok = self._c("state.live", "#73daca")
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent = self._c("accent.primary", "#bb9af7")
        accent2 = self._c("accent.secondary", "#9d7cd8")

        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Session Arena...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Session Arena disabled"
            return f"[dim]Session Arena (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            if self._is_plain_mode_active():
                error = self.last_arena_error or RecoverableError(
                    what_happened="Session load error",
                    impact="The active session cannot be displayed.",
                    preserved="Existing local session data remains unchanged.",
                    next_action="Press Retry or Esc to return Home.",
                )
                return (
                    "RECOVERY\n"
                    f"1. WHAT HAPPENED: {error.what_happened}\n"
                    f"2. IMPACT: {error.impact}\n"
                    f"3. PRESERVED: {error.preserved}\n"
                    f"4. NEXT ACTION: {error.next_action}\n"
                    "ACTIONS: Retry | Esc Back"
                )
            glyph = get_glyph("!")
            error_msg = self.last_arena_error.what_happened if self.last_arena_error else "Session load error"
            error_detail = self.last_arena_error.technical_detail if (self.last_arena_error and self.last_arena_error.technical_detail) else ""
            return (
                f"[bold {err}]{glyph} Arena Error: {error_msg}[/bold {err}]\n"
                f"[dim]{error_detail}[/dim]\n\n"
                f"[{warn}]Press [Retry] to attempt reloading session data.[/{warn}]"
            )

        if state == WidgetLifecycleState.EMPTY or not self.session_summary:
            return "[dim]Session Arena: No active session selected.[/dim]"

        if self._is_plain_mode_active():
            summary = self.session_summary
            lines = [
                "SESSION ARENA",
                f"SESSION: {summary.session_id}",
                f"STATUS: {summary.status}",
                f"PARTICIPANTS: @{summary.initiator_username} -> @{summary.receiver_username}",
                f"OBJECTIVE: {summary.objective or 'No objective declared'}",
                f"ACTIVE LANE: {self.active_lane}",
                f"REPLAY: {'ON' if self.is_replay_mode else 'OFF'}",
            ]
            if self.active_lane == "needs_you":
                lines.append(f"APPROVALS: {len(self.approvals)}")
                for approval in self.approvals:
                    req = approval.request
                    risk = getattr(req.risk_label, "value", req.risk_label)
                    lines.append(f"- {req.summary}; risk={risk}; reason={req.reason}")
            elif self.active_lane == "outputs":
                lines.append(f"OUTPUTS: {len(self.artifacts)}")
                if self.outcome_card is not None:
                    lines.extend(
                        [
                            f"OUTCOME: {self.outcome_card.status} | {redact_ui_text(self.outcome_card.summary)}",
                            f"EVIDENCE EVENTS: {self.outcome_card.evidence_event_count}",
                            f"REPLAY SHA-256: {self.outcome_card.replay_digest}",
                        ]
                    )
                if self.budget_gauges is not None:
                    lines.append(
                        "BUDGETS: "
                        f"time={self.budget_gauges.elapsed_seconds:.0f}s; "
                        f"artifacts={self.budget_gauges.artifact_bytes}B; "
                        f"local_cost={self.budget_gauges.local_cost_estimate if self.budget_gauges.local_cost_estimate is not None else 'not reported'}"
                    )
                for artifact in self.artifacts:
                    meta = artifact.metadata
                    lines.append(
                        f"- {meta.artifact_id}; type={meta.mime_type}; size={artifact.display_size}; "
                        f"source={meta.source}"
                    )
            elif self.active_lane == "notes":
                lines.append(f"PRIVATE NOTES — LOCAL ONLY: {len(self.private_notes)}")
                for index, note in enumerate(self.private_notes, start=1):
                    lines.append(
                        f"{index}. {note.created_at} | actor=@{note.actor_username} | "
                        f"{escape(note.note_text)}"
                    )
            else:
                visible_events = self.exchange_timeline_widget.get_filtered_events()
                if self.is_replay_mode and self.replay_index is not None:
                    visible_events = visible_events[: self.replay_index + 1]
                lines.append(f"EVENTS: {len(visible_events)}")
                for index, event in enumerate(visible_events, start=1):
                    lines.append(
                        f"{index}. {event.created_at} | {event.presentation_class.upper()} | "
                        f"{event.kind} | actor=@{event.actor_username or 'system'} | "
                        f"{redact_ui_text(event.content or '')}"
                    )
            lines.append(
                "ACTIONS: t Transcript | e Activity | o Outputs | c Decisions | "
                "u Needs You | l Local Notes | p Promote Note | r Replay | "
                "w Checkpoint | y Decision | f Fresh Rerun | h Playbook | Ctrl+S New Note | Ctrl+E Export | Esc Back"
            )
            return "\n".join(lines)

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
            outcome_renderable = OutcomeCardWidget(
                session_summary=self.session_summary,
                outcome_card=self.outcome_card,
            ).render()
            center_renderable = Group(
                outcome_renderable,
                self._render_budget_gauges(),
                self.artifact_list_widget.render(),
            )
        elif self.active_lane == "needs_you":
            center_renderable = self._render_needs_you_queue()
        elif self.active_lane == "notes":
            center_renderable = self._render_private_notes()
        else:
            center_renderable = self.exchange_timeline_widget.render()

        lane_title_map = {
            "transcript": f"[bold {ok}]EXCHANGE TIMELINE[/bold {ok}]",
            "activity": f"[bold {ok}]ACTIVITY FEED[/bold {ok}]",
            "outputs": f"[bold {ok}]OUTPUTS / ARTIFACTS[/bold {ok}]",
            "decisions": f"[bold {ok}]DECISIONS / CHECKPOINTS[/bold {ok}]",
            "needs_you": f"[bold {warn}]NEEDS-YOU QUEUE[/bold {warn}]",
            "notes": f"[bold {accent}]PRIVATE NOTES — LOCAL ONLY[/bold {accent}]",
        }
        lane_title = lane_title_map.get(self.active_lane, f"[bold {ok}]LANE: {self.active_lane.upper()}[/bold {ok}]")

        # 1. FOCUS MODE (z key active) -> full-bleed active lane view hiding session map and inspector
        if self.focus_mode:
            return Group(
                header_str + focus_mark + f" [bold {warn}][FOCUS MODE][/bold {warn}]",
                Panel(center_renderable, title=f"[bold {accent}]FOCUS LANE: {self.active_lane.upper()}[/bold {accent}]", border_style="cyan"),
            )

        # 2. COCKPIT MODE -> Breakpoint-driven layout
        if bp == "wide":
            grid = Table.grid(expand=True)
            grid.add_column("map", ratio=1)
            grid.add_column("timeline", ratio=2)
            if self.inspector_visible:
                grid.add_column("inspector", ratio=1)

            panel_map = Panel(map_str, title=f"[bold {accent}]SESSION MAP[/bold {accent}]", border_style="cyan")
            panel_timeline = Panel(center_renderable, title=lane_title, border_style="green")

            if self.inspector_visible:
                panel_inspector = Panel(inspector_str, title=f"[bold {accent2}]DETAIL INSPECTOR[/bold {accent2}]", border_style="magenta")
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
                panel_inspector = Panel(inspector_str, title=f"[bold {accent2}]DOCKED INSPECTOR[/bold {accent2}]", border_style="magenta")
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
            if any(not isinstance(part, str) for part in parts):
                return Group(*parts)
            return "\n\n".join(parts)
