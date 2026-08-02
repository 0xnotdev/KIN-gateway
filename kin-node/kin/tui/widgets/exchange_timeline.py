"""ExchangeTimeline domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §7.2, §7.3, §14.8 build steps 3-4 (Phase C1 + Phase C2)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set, Union

from textual.events import Key
from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.state import UiEvent
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


@dataclass
class CoalescedTimelineGroup:
    """Group of consecutive timeline events (coalesced repeated activities or single events)."""

    first_event: UiEvent
    last_event: UiEvent
    events: List[UiEvent]
    count: int
    is_coalesced_activity: bool


def _parse_now(now: Optional[Union[datetime, str, float]]) -> datetime:
    """Parse injectable now timestamp for deterministic testing coupled without wall-clock."""
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    if isinstance(now, str):
        try:
            dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(now, timezone.utc)
    return datetime.now(timezone.utc)


class ExchangeTimelineWidget(LifecycleWidgetMixin, Static):
    """ExchangeTimeline domain widget rendering session events across presentation classes (§14.8 Steps 3-4, Phase C2).

    Features (Phase C2):
    1. Tail-follow: auto-follows new events when reader is at tail.
    2. Off-tail retention: retains reader cursor position when off-tail and surfaces fixed '↓ N new events' control.
    3. Jump-to-tail: 'G' / 'End' keys jump cursor to newest event and clear counter.
    4. Live-Only 120ms Tail Pulse: pulse badge renders ONLY for genuinely live-appended events within 120ms of arrival.
    5. Reduced motion: `reduced_motion=True` suppresses tail pulse animations completely.
    6. Activity Coalescing & Memoization: consecutive repeated `activity` events collapse into single cards.
    7. FPS-Batched Visual Commits: throttles visual refresh calls at 30 FPS (33ms interval), degrading gracefully
       to 10 FPS (100ms interval) under pressure (>30 events/sec arrival rate). Structured data is 100% retained immediately.
    8. Keystroke Non-Interference: user input (up/down/jump_to_tail) triggers immediate visual refresh without timer delay.
    9. Transport Reconnect & Dedup: handles disconnect/reconnect by inserting exactly 1 state_transition marker
       and deduplicating replayed events by event_id.
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
        reduced_motion: bool = False,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.events: List[UiEvent] = list(events) if events else []
        self.selected_event_id: Optional[str] = selected_event_id
        self.allowed_presentation_classes: Set[str] = (
            allowed_presentation_classes
            if allowed_presentation_classes is not None
            else self.DEFAULT_ALLOWED_CLASSES
        )
        self.selected_index: int = 0
        self.on_event_selected = on_event_selected
        self.reduced_motion: bool = reduced_motion

        # Streaming state & pulse tracking (§7.2, §14.8 Phase C1/C2)
        self.new_events_off_tail_count: int = 0
        self.live_appended_at_map: Dict[str, datetime] = {}

        # Performance memoization cache
        self._coalesced_groups_cache: Optional[List[CoalescedTimelineGroup]] = None
        self._get_coalesced_groups_call_count: int = 0

        # FPS & Throttling state (§14.8 Phase C2)
        self._last_visual_commit_at: Optional[datetime] = None
        self._pending_visual_refresh: bool = False
        self._refresh_call_count: int = 0
        self._recent_arrival_timestamps: List[datetime] = []
        self.target_fps_normal: float = 30.0       # ~33ms min interval
        self.target_fps_degraded: float = 10.0     # ~100ms min interval under pressure
        self.pressure_threshold_ev_per_sec: float = 30.0

        groups = self.get_coalesced_groups()
        if selected_event_id and groups:
            for idx, g in enumerate(groups):
                if g.last_event.event_id == selected_event_id:
                    self.selected_index = idx
                    break

    def _invalidate_cache(self) -> None:
        self._coalesced_groups_cache = None

    def is_under_pressure(self, now_dt: datetime) -> bool:
        """Determine if incoming event arrival rate exceeds 30 events/sec over rolling 1.0s window (§14.8 Phase C2)."""
        cutoff = now_dt.timestamp() - 1.0
        self._recent_arrival_timestamps = [t for t in self._recent_arrival_timestamps if t.timestamp() >= cutoff]
        return len(self._recent_arrival_timestamps) > self.pressure_threshold_ev_per_sec

    def perform_visual_commit(self, now_dt: datetime) -> None:
        """Execute visual commit: update commit timestamp and trigger local widget refresh (§14.8 Phase C2)."""
        self._last_visual_commit_at = now_dt
        self._pending_visual_refresh = False
        self._refresh_call_count += 1
        super().refresh()

    def request_visual_refresh(self, now: Optional[Union[datetime, str, float]] = None) -> None:
        """Throttle visual commits at 30 FPS (33ms), degrading to 10 FPS (100ms) under pressure (§14.8 Phase C2)."""
        now_dt = _parse_now(now)
        min_interval = 0.100 if self.is_under_pressure(now_dt) else 0.033

        if self._last_visual_commit_at is None:
            self.perform_visual_commit(now_dt)
        else:
            elapsed = (now_dt - self._last_visual_commit_at).total_seconds()
            if elapsed >= min_interval:
                self.perform_visual_commit(now_dt)
            else:
                self._pending_visual_refresh = True
                try:
                    if self.is_mounted and hasattr(self, "set_timer"):
                        self.set_timer(min_interval - elapsed, lambda: self.flush_pending_visual_commit(now=now))
                except Exception:
                    pass

    def flush_pending_visual_commit(self, now: Optional[Union[datetime, str, float]] = None) -> None:
        if self._pending_visual_refresh:
            self.perform_visual_commit(_parse_now(now))

    def get_filtered_events(self) -> List[UiEvent]:
        return [e for e in self.events if e.presentation_class in self.allowed_presentation_classes]

    def get_coalesced_groups(self) -> List[CoalescedTimelineGroup]:
        """Group consecutive events with memoization cache (§14.8 Phase C1/C2)."""
        if self._coalesced_groups_cache is not None:
            return self._coalesced_groups_cache

        self._get_coalesced_groups_call_count += 1
        filtered = self.get_filtered_events()
        groups: List[CoalescedTimelineGroup] = []

        for evt in filtered:
            if evt.presentation_class == "activity":
                if groups and groups[-1].is_coalesced_activity and groups[-1].first_event.actor_username == evt.actor_username:
                    groups[-1].events.append(evt)
                    groups[-1].last_event = evt
                    groups[-1].count += 1
                else:
                    groups.append(CoalescedTimelineGroup(
                        first_event=evt,
                        last_event=evt,
                        events=[evt],
                        count=1,
                        is_coalesced_activity=True,
                    ))
            else:
                # Approval, Security, State_Transition, Message, Artifact, Checkpoint NEVER coalesced
                groups.append(CoalescedTimelineGroup(
                    first_event=evt,
                    last_event=evt,
                    events=[evt],
                    count=1,
                    is_coalesced_activity=False,
                ))

        self._coalesced_groups_cache = groups
        return groups

    def is_at_tail(self) -> bool:
        groups = self.get_coalesced_groups()
        if not groups:
            return True
        return self.selected_index >= len(groups) - 1

    def get_selected_event(self) -> Optional[UiEvent]:
        groups = self.get_coalesced_groups()
        if 0 <= self.selected_index < len(groups):
            return groups[self.selected_index].last_event
        return None

    def append_events(self, new_events: List[UiEvent], now: Optional[Union[datetime, str, float]] = None) -> None:
        """Append new live events into stream: 100% data retention immediately, throttled visual commits (§14.8 Phase C2)."""
        if not new_events:
            return

        now_dt = _parse_now(now)
        for evt in new_events:
            self.live_appended_at_map[evt.event_id] = now_dt
            self._recent_arrival_timestamps.append(now_dt)

        was_at_tail = self.is_at_tail()
        old_groups = self.get_coalesced_groups()
        old_group_count = len(old_groups)

        self.events.extend(new_events)
        self._invalidate_cache()

        new_groups = self.get_coalesced_groups()
        new_group_count = len(new_groups)
        added_groups = new_group_count - old_group_count

        if was_at_tail:
            self.selected_index = max(0, new_group_count - 1)
            self.new_events_off_tail_count = 0
        else:
            if added_groups > 0:
                self.new_events_off_tail_count += len(new_events)

        selected = self.get_selected_event()
        if selected and self.on_event_selected and was_at_tail:
            self.on_event_selected(selected)

        # Trigger FPS-batched visual commit (Data is 100% retained)
        self.request_visual_refresh(now=now_dt)

    def append_event(self, evt: UiEvent, now: Optional[Union[datetime, str, float]] = None) -> None:
        self.append_events([evt], now=now)

    def handle_reconnect(
        self,
        replayed_events: List[UiEvent],
        now: Optional[Union[datetime, str, float]] = None,
    ) -> None:
        """Handle transport reconnect: insert exactly one state_transition marker and deduplicate replayed events (§14.8 C2)."""
        now_dt = _parse_now(now)
        existing_ids = {e.event_id for e in self.events}
        deduped = [e for e in replayed_events if e.event_id not in existing_ids]

        reconnect_evt = UiEvent(
            event_id=f"reconnect-{now_dt.timestamp()}",
            session_id=self.events[0].session_id if self.events else "sess-reconnect",
            kind="reconnect",
            created_at=now_dt.isoformat(),
            actor_username="system",
            presentation_class="state_transition",
        )

        self.append_events([reconnect_evt] + deduped, now=now_dt)

    def jump_to_tail(self) -> None:
        """Jump reader selection cursor directly to the newest event at the tail (§14.8 Phase C1/C2)."""
        groups = self.get_coalesced_groups()
        if groups:
            self.selected_index = len(groups) - 1
        self.new_events_off_tail_count = 0

        selected = self.get_selected_event()
        if selected and self.on_event_selected:
            self.on_event_selected(selected)

        # Keystroke navigation: immediate visual commit
        self.perform_visual_commit(datetime.now(timezone.utc))

    def cursor_down(self) -> None:
        groups = self.get_coalesced_groups()
        if groups:
            self.selected_index = min(self.selected_index + 1, len(groups) - 1)
            if self.is_at_tail():
                self.new_events_off_tail_count = 0
            selected = self.get_selected_event()
            if selected and self.on_event_selected:
                self.on_event_selected(selected)
            self.perform_visual_commit(datetime.now(timezone.utc))

    def cursor_up(self) -> None:
        groups = self.get_coalesced_groups()
        if groups:
            self.selected_index = max(self.selected_index - 1, 0)
            selected = self.get_selected_event()
            if selected and self.on_event_selected:
                self.on_event_selected(selected)
            self.perform_visual_commit(datetime.now(timezone.utc))

    def on_key(self, event: Key) -> None:
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        if event.key in ("down", "j"):
            self.cursor_down()
            event.stop()
        elif event.key in ("up", "k"):
            self.cursor_up()
            event.stop()
        elif event.key == "g":
            self.selected_index = 0
            selected = self.get_selected_event()
            if selected and self.on_event_selected:
                self.on_event_selected(selected)
            self.perform_visual_commit(datetime.now(timezone.utc))
            event.stop()
        elif event.key in ("G", "end"):
            self.jump_to_tail()
            event.stop()
        elif event.key == "enter":
            selected = self.get_selected_event()
            if selected and self.on_event_selected:
                self.on_event_selected(selected)
            event.stop()

    def _render_group_card(self, group: CoalescedTimelineGroup, is_selected: bool, now_dt: datetime) -> str:
        evt = group.last_event
        p_class = evt.presentation_class
        actor = redact_ui_text(evt.actor_username or "system")
        ts = redact_ui_text(evt.created_at[:19] if evt.created_at else "00:00:00")
        kind_clean = redact_ui_text(evt.kind or p_class)
        prefix = "▶ " if is_selected else "  "
        select_tag = " [bold yellow][INSPECTED][/bold yellow]" if is_selected else ""

        # Live-Only Tail Pulse Tracking (§7.2, §14.8 Phase C1/C2)
        is_pulsing = False
        if evt.event_id in self.live_appended_at_map:
            elapsed_sec = (now_dt - self.live_appended_at_map[evt.event_id]).total_seconds()
            if (not self.reduced_motion) and (0.0 <= elapsed_sec < 0.120):
                is_pulsing = True

        pulse_badge = " [bold green]⚡ [TAIL PULSE][/bold green]" if is_pulsing else ""

        # Coalesced Activity Group (Multiple repeats)
        if group.is_coalesced_activity and group.count > 1:
            ts_start = group.first_event.created_at[:19] if group.first_event.created_at else "00:00:00"
            ts_end = group.last_event.created_at[11:19] if group.last_event.created_at else "00:00:00"
            return f"{prefix}● [dim][ACTIVITY][/dim] {kind_clean} (actor: @{actor}) [bold cyan]x{group.count}[/bold cyan] ({group.count} events, {ts_start} - {ts_end}){select_tag}{pulse_badge}"

        # 1. MESSAGE: provenance-rich showing actor, timestamp, and content
        if p_class == "message":
            body_line = f"\n   [italic]\"{redact_ui_text(evt.content)}\"[/italic]" if evt.content else ""
            return (
                f"{prefix}[bold green]💬 MESSAGE[/bold green] [dim]@{actor} at {ts}[/dim]{select_tag}{pulse_badge}\n"
                f"   [bold]Kind:[/bold] {kind_clean}{body_line}\n"
                f"   Event ID: {evt.event_id}"
            )

        # 2. ACTIVITY: concise, coalesced visual format (Single repeat)
        elif p_class == "activity":
            return f"{prefix}● [dim][ACTIVITY][/dim] {kind_clean} (actor: @{actor} at {ts}){select_tag}{pulse_badge}"

        # 3. CHECKPOINT: bordered box
        elif p_class == "checkpoint":
            return (
                f"{prefix}┌─ [bold cyan]CHECKPOINT[/bold cyan] ──────────────────────┐\n"
                f"│ Event: {kind_clean:<32} │\n"
                f"│ Timestamp: {ts:<28} │\n"
                f"└────────────────────────────────────────┘{select_tag}{pulse_badge}"
            )

        # 4. ARTIFACT: metadata & preview ONLY (zero import / apply affordances)
        elif p_class == "artifact":
            return (
                f"{prefix}[bold blue]📦 ARTIFACT OFFER[/bold blue] [dim]by @{actor} at {ts}[/dim]{select_tag}{pulse_badge}\n"
                f"   Metadata: [cyan]{kind_clean}[/cyan] (ID: {evt.event_id[:8]})\n"
                f"   [dim](Read-only metadata preview - press Enter/inspect to view details)[/dim]"
            )

        # 5. APPROVAL: amber token (zero action buttons)
        elif p_class == "approval":
            return (
                f"{prefix}[bold yellow]▲ APPROVAL GATE [AMBER/POLICY][/bold yellow] [dim]at {ts}[/dim]{select_tag}{pulse_badge}\n"
                f"   [yellow]Request: {kind_clean} by @{actor}[/yellow]\n"
                f"   [dim](Policy review required - pending owner decision)[/dim]"
            )

        # 6. STATE_TRANSITION: clear visual state divider
        elif p_class == "state_transition":
            return (
                f"{prefix}═══ [bold magenta]STATE TRANSITION[/bold magenta] ═════════════════════════════\n"
                f"   Event: [bold]{kind_clean}[/bold] by @{actor} at {ts}{select_tag}{pulse_badge}"
            )

        # 7. SECURITY: persistent RED card (zero action affordances)
        elif p_class == "security":
            glyph_x = get_glyph("✖")
            return (
                f"{prefix}[bold red]{glyph_x} SECURITY REJECTION CARD[/bold red] [dim]at {ts}[/dim]{select_tag}{pulse_badge}\n"
                f"   [red]Category: {kind_clean}[/red]\n"
                f"   [red]Actor: @{actor} | ID: {evt.event_id}[/red]\n"
                f"   [bold red]CRITICAL: Security boundary rejection logged. No actions available.[/bold red]"
            )

        # Fallback
        return f"{prefix}● [{p_class.upper()}] {kind_clean} (@{actor} at {ts}){select_tag}{pulse_badge}"

    def render(self, now: Optional[Union[datetime, str, float]] = None) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Loading Exchange Timeline...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "ExchangeTimeline disabled"
            return f"[dim]ExchangeTimeline (DISABLED: {reason})[/dim]"

        groups = self.get_coalesced_groups()

        if state == WidgetLifecycleState.EMPTY or not groups:
            return "[dim]ExchangeTimeline: No dialogue/session events recorded.[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} ExchangeTimeline Error: Event timeline corrupted. Press [Retry].[/bold red]"

        now_dt = _parse_now(now)
        lines = [f"[bold green]Exchange Timeline ({len(groups)} cards / {len(self.get_filtered_events())} events):[/bold green]"]

        # Surface fixed off-tail control when reader is off tail (§7.2, §14.8 Phase C1/C2)
        if self.new_events_off_tail_count > 0 and not self.is_at_tail():
            lines.append(f"[bold cyan]↓ {self.new_events_off_tail_count} new events (press 'G' or 'End' to jump to tail)[/bold cyan]")

        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        for idx, group in enumerate(groups):
            is_selected = (idx == self.selected_index)
            lines.append(self._render_group_card(group, is_selected, now_dt))

        return "\n\n".join(lines) + focus_mark
