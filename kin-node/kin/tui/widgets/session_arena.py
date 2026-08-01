"""SessionArenaWidget domain screen for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.3, §7.2, §14.8 Steps 1-2 (Static Rendering)
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from textual.events import Key, Resize
from textual.widgets import Static

from kin.tui.layout import Breakpoint, classify_breakpoint
from kin.tui.local_state import (
    get_approvals_for_session,
    get_artifacts_for_session,
    get_local_contacts_summaries,
    get_session_detail,
    get_session_events,
    get_session_list,
    get_stale_peer_card_count,
)
from kin.tui.redaction import redact_ui_text
from kin.tui.state import ApprovalView, ArtifactView, SessionSummary, UiEvent
from kin.tui.tokens import get_glyph
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.inspector import InspectorWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.session_map import SessionMapWidget
from kin.tui.widgets.trust_strip import TrustStripWidget


class SessionArenaWidget(LifecycleWidgetMixin, Static):
    """Static Session Arena domain widget composing header, session map, exchange timeline, and inspector (§14.8).

    Supports three responsive layout modes via classify_breakpoint():
    1. Cockpit mode (full breakpoint): 3-lane layout (Session Map | Exchange Timeline | Inspector).
    2. Standard mode (standard breakpoint): Docked Inspector (Exchange Timeline | Inspector).
    3. Stacked mode (compact/minimal breakpoint): Vertically stacked lanes.
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
        session_id: str = "sess-arena-default",
        profile_name: str = "default",
        profile_dir: Optional[Path] = None,
        session_summary: Optional[SessionSummary] = None,
        events: Optional[List[UiEvent]] = None,
        artifacts: Optional[List[ArtifactView]] = None,
        approvals: Optional[List[ApprovalView]] = None,
        selected_event_id: Optional[str] = None,
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
        self.selected_event: Optional[UiEvent] = None
        self.breakpoint: Breakpoint = "full"

        # Child sub-widgets
        self.trust_strip_widget = TrustStripWidget()
        self.session_map_widget = SessionMapWidget()
        self.exchange_timeline_widget = ExchangeTimelineWidget()
        self.inspector_widget = InspectorWidget()

        self.load_arena_data()

    def load_arena_data(self) -> None:
        """Load session data using Phase A data functions."""
        # 1. Session summary
        if self._session_summary_override is not None:
            self.session_summary = self._session_summary_override
        else:
            self.session_summary = get_session_detail(self.profile_dir, self.session_id, self.profile_name)
            if self.session_summary is None:
                # Fallback summary for non-existent session
                self.session_summary = SessionSummary(
                    session_id=self.session_id,
                    status="active",
                    type="ask",
                    initiator_username="local_user",
                    receiver_username="peer_user",
                    objective="Collaborate on task",
                )

        # 2. Events
        if self._events_override is not None:
            self.events = self._events_override
        else:
            self.events = get_session_events(self.profile_dir, self.session_id, self.profile_name)

        # 3. Artifacts
        if self._artifacts_override is not None:
            self.artifacts = self._artifacts_override
        else:
            self.artifacts = get_artifacts_for_session(self.profile_dir, self.session_id, self.profile_name)

        # 4. Approvals
        if self._approvals_override is not None:
            self.approvals = self._approvals_override
        else:
            self.approvals = get_approvals_for_session(self.profile_dir, self.session_id, self.profile_name)

        # 5. Peer trust checks
        try:
            contacts = get_local_contacts_summaries(self.profile_dir)
            contact_usernames = {c.username for c in contacts}
            is_missing_peer = bool(self.session_summary.receiver_username and self.session_summary.receiver_username not in contact_usernames)
            peer_u = self.session_summary.receiver_username or ""
            stale_count = get_stale_peer_card_count(self.profile_dir, peer_u) if peer_u else 0
            is_stale_peer = (stale_count > 0)
        except Exception:
            is_missing_peer = False
            is_stale_peer = False

        # Configure sub-widgets
        self.trust_strip_widget = TrustStripWidget(
            session_summary=self.session_summary,
            is_stale_peer=is_stale_peer,
            is_direct_transport=True,
            is_missing_peer=is_missing_peer,
        )

        all_sessions = get_session_list(self.profile_dir, self.profile_name) or [self.session_summary]
        self.session_map_widget = SessionMapWidget(
            sessions=all_sessions,
            active_session_id=self.session_id,
        )

        self.exchange_timeline_widget = ExchangeTimelineWidget(
            events=self.events,
            selected_event_id=self.selected_event_id,
            allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
            on_event_selected=self._on_event_selected,
        )

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

    def on_resize(self, event: Resize) -> None:
        self.breakpoint = classify_breakpoint(event.size.width, event.size.height)
        self.refresh()

    def on_key(self, event: Key) -> None:
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        if event.key in ("down", "j"):
            self.exchange_timeline_widget.cursor_down()
            self.selected_event = self.exchange_timeline_widget.get_selected_event()
            self.inspector_widget.selected_event = self.selected_event
            self.refresh()
            event.stop()
        elif event.key in ("up", "k"):
            self.exchange_timeline_widget.cursor_up()
            self.selected_event = self.exchange_timeline_widget.get_selected_event()
            self.inspector_widget.selected_event = self.selected_event
            self.refresh()
            event.stop()

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Session Arena...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "SessionArena disabled"
            return f"[dim]SessionArena (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} SessionArena Error: Arena state unreadable. Press [Retry].[/bold red]"

        # Classify terminal size breakpoint
        size = self.size
        width = size.width if size and size.width > 0 else 160
        height = size.height if size and size.height > 0 else 44
        bp = classify_breakpoint(width, height)

        header_str = self.trust_strip_widget.render()
        timeline_str = self.exchange_timeline_widget.render()
        inspector_str = self.inspector_widget.render()
        map_str = self.session_map_widget.render()

        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        # 1. COCKPIT MODE (full breakpoint: >=140x30) -> 3-lane layout
        if bp == "full":
            return (
                f"{header_str}{focus_mark}\n\n"
                f"[bold cyan]─── SESSION MAP ───[/bold cyan]\n{map_str}\n\n"
                f"[bold green]─── EXCHANGE TIMELINE ───[/bold green]\n{timeline_str}\n\n"
                f"[bold magenta]─── DETAIL INSPECTOR ───[/bold magenta]\n{inspector_str}"
            )

        # 2. DOCKED INSPECTOR MODE (standard breakpoint: 90x28 - 140x30) -> 2-lane layout
        elif bp == "standard":
            return (
                f"{header_str}{focus_mark}\n\n"
                f"[bold green]─── EXCHANGE TIMELINE ───[/bold green]\n{timeline_str}\n\n"
                f"[bold magenta]─── DOCKED INSPECTOR ───[/bold magenta]\n{inspector_str}"
            )

        # 3. STACKED COMPACT MODE (compact/minimal breakpoint: <=90x24) -> vertically stacked compact lanes
        else:
            return (
                f"{header_str}{focus_mark}\n\n"
                f"{timeline_str}\n\n"
                f"{inspector_str}"
            )
