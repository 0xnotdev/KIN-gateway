"""SessionArenaWidget domain screen for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.3, §7.1, §7.2, §14.8 Steps 1-2 (Static Rendering)
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
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
from kin.tui.state import ApprovalView, ArtifactView, RecoverableError, SessionSummary, UiEvent
from kin.tui.tokens import get_glyph
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.inspector import InspectorWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.session_map import SessionMapWidget
from kin.tui.widgets.trust_strip import TrustStripWidget


class SessionArenaWidget(LifecycleWidgetMixin, Static):
    """Static Session Arena domain widget composing header, session map, exchange timeline, and inspector (§14.8).

    Supports three responsive layout modes via classify_breakpoint():
    1. Cockpit mode (full breakpoint): 3-lane side-by-side grid layout (Session Map | Exchange Timeline | Inspector).
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
        self.breakpoint: Breakpoint = "full"

        # Child sub-widgets
        self.trust_strip_widget = TrustStripWidget()
        self.session_map_widget = SessionMapWidget()
        self.exchange_timeline_widget = ExchangeTimelineWidget()
        self.inspector_widget = InspectorWidget()

        self.load_arena_data()

    def load_arena_data(self) -> None:
        """Load session data using Phase A data functions (§14.8 Phase B Round 2)."""
        # 1. Session summary resolution (Zero fake SessionSummary synthesis)
        if self._session_summary_override is not None:
            self.session_summary = self._session_summary_override
        else:
            self.session_summary = get_session_detail(self.profile_dir, self.session_id, self.profile_name)
            if self.session_summary is None:
                self.last_arena_error = RecoverableError(
                    what_happened="Session Not Found",
                    impact="Session details and event logs cannot be loaded.",
                    preserved="Your local database and profile keyrings remain intact.",
                    next_action="Select a valid, existing session ID from the Session Map or Inbox.",
                    technical_detail=f"Session ID '{self.session_id}' not found in profile '{self.profile_name}'.",
                )
                self._lifecycle_state = WidgetLifecycleState.RECOVERABLE_ERROR
                return

        # 2. Events
        if self._events_override is not None:
            self.events = self._events_override
        else:
            self.events = get_session_events(self.profile_dir, self.session_id, self.profile_name) or []

        # 3. Artifacts
        if self._artifacts_override is not None:
            self.artifacts = self._artifacts_override
        else:
            self.artifacts = get_artifacts_for_session(self.profile_dir, self.session_id, self.profile_name) or []

        # 4. Approvals
        if self._approvals_override is not None:
            self.approvals = self._approvals_override
        else:
            self.approvals = get_approvals_for_session(self.profile_dir, self.session_id, self.profile_name) or []

        # 5. Peer trust checks (Narrow exception handling - surface trust errors, never reassure on failure)
        is_trust_unknown = False
        is_missing_peer = False
        is_stale_peer = False
        try:
            contacts = get_local_contacts_summaries(self.profile_dir)
            contact_usernames = {c.username for c in contacts}
            rec_user = self.session_summary.receiver_username
            is_missing_peer = bool(rec_user and rec_user not in contact_usernames)
            peer_u = rec_user or ""
            stale_count = get_stale_peer_card_count(self.profile_dir, peer_u) if peer_u else 0
            is_stale_peer = (stale_count > 0)
        except Exception as exc:
            self.last_trust_error = str(exc)
            is_trust_unknown = True
            is_missing_peer = True
            is_stale_peer = False

        # Configure sub-widgets
        self.trust_strip_widget = TrustStripWidget(
            session_summary=self.session_summary,
            is_stale_peer=is_stale_peer,
            is_direct_transport=True,
            is_missing_peer=is_missing_peer,
            is_trust_unknown=is_trust_unknown,
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
            reduced_motion=self.reduced_motion,
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
        elif event.key == "g":
            self.exchange_timeline_widget.selected_index = 0
            self.selected_event = self.exchange_timeline_widget.get_selected_event()
            self.inspector_widget.selected_event = self.selected_event
            self.refresh()
            event.stop()
        elif event.key in ("G", "end"):
            self.exchange_timeline_widget.jump_to_tail()
            self.selected_event = self.exchange_timeline_widget.get_selected_event()
            self.inspector_widget.selected_event = self.selected_event
            self.refresh()
            event.stop()

    def render(self) -> Union[str, Group]:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Session Arena...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "SessionArena disabled"
            return f"[dim]SessionArena (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR or self.session_summary is None:
            err = getattr(self, "last_arena_error", None)
            err_msg = err.what_happened if err else "Session Not Found"
            tech_detail = f"\n[dim]{err.technical_detail}[/dim]" if err and err.technical_detail else ""
            glyph = get_glyph("!")
            return (
                f"[bold red]{glyph} SessionArena Error: {err_msg}[/bold red]{tech_detail}\n"
                f"[dim]No synthetic data constructed. Select a valid session ID.[/dim]"
            )

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

        # 1. COCKPIT MODE (full breakpoint: >=140x30) -> Genuine side-by-side Rich Table grid (§7.1, §14.8 Round 2)
        if bp == "full":
            grid = Table.grid(expand=True)
            grid.add_column("map", ratio=1)
            grid.add_column("timeline", ratio=2)
            grid.add_column("inspector", ratio=1)

            panel_map = Panel(map_str, title="[bold cyan]SESSION MAP[/bold cyan]", border_style="cyan")
            panel_timeline = Panel(timeline_str, title="[bold green]EXCHANGE TIMELINE[/bold green]", border_style="green")
            panel_inspector = Panel(inspector_str, title="[bold magenta]DETAIL INSPECTOR[/bold magenta]", border_style="magenta")

            grid.add_row(panel_map, panel_timeline, panel_inspector)
            return Group(
                header_str + focus_mark,
                grid,
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
