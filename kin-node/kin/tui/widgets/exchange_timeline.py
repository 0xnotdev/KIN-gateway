"""ExchangeTimeline domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §7.2, §7.3, §14.8 build steps 3-4 (Phase C1 + Phase C2)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set, Union

from textual.events import Key
from textual.widgets import Static

from kin.tui.motion import EVENT_PULSE_MS, MAX_AMBER_PULSES_PER_EVENT, AmberPulseTracker
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

        # Streaming state & pulse tracking (§7.2, §14.8 Phase C1/C2, §14.9 step 3)
        self.new_events_off_tail_count: int = 0
        self.live_appended_at_map: Dict[str, datetime] = {}
        self.pulse_tracker = AmberPulseTracker(max_pulses=MAX_AMBER_PULSES_PER_EVENT)

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

    def _get_app_instance(self):
        app = getattr(self, "_app", None)
        if app is None:
            try:
                app = self.app
            except Exception:
                app = None
        return app

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

    def _g(self, symbol: str) -> str:
        """Resolve a glyph symbol using ASCII fallback if app.is_ascii_fallback_active is True."""
        app = self._get_app_instance()
        ascii_fallback = getattr(app, "is_ascii_fallback_active", False) if app is not None else False
        from kin.tui.tokens import get_glyph
        return get_glyph(symbol, ascii_fallback=ascii_fallback)

    def _render_group_card(self, group: CoalescedTimelineGroup, is_selected: bool, now_dt: datetime) -> str:
        accent = self._c("accent.primary", "#bb9af7")
        ok = self._c("state.live", "#73daca")
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent2 = self._c("accent.secondary", "#9d7cd8")
        highlight = self._c("accent.highlight", "#7aa2f7")

        evt = group.last_event
        p_class = evt.presentation_class or "info"
        actor = redact_ui_text(evt.actor_username or "system")
        ts = redact_ui_text(evt.created_at[:19] if evt.created_at else "00:00:00")
        kind_clean = redact_ui_text(evt.kind or p_class)
        play_glyph = self._g("▶")
        prefix = f"{play_glyph} " if is_selected else "  "
        accent_tag = f" {accent}".rstrip()
        ok_tag = f" {ok}".rstrip()
        err_tag = f" {err}".rstrip()
        warn_tag = f" {warn}".rstrip()
        accent2_tag = f" {accent2}".rstrip()
        highlight_tag = f" {highlight}".rstrip()

        select_tag = f" [bold{warn_tag}][INSPECTED][/bold{warn_tag}]" if is_selected else ""

        # Live-Only Tail Pulse Tracking (§7.2, §14.8 Phase C1/C2, §14.9 step 3)
        is_pulsing = False
        if evt.event_id in self.live_appended_at_map:
            elapsed_sec = (now_dt - self.live_appended_at_map[evt.event_id]).total_seconds()
            pulse_window_sec = EVENT_PULSE_MS / 1000.0
            if (not self.reduced_motion) and (0.0 <= elapsed_sec < pulse_window_sec):
                is_pulsing = True

        pulse_badge = f" [bold{ok_tag}]⚡ [TAIL PULSE][/bold{ok_tag}]" if is_pulsing else ""
        dot_glyph = self._g("●")

        # Coalesced Activity Group (Multiple repeats)
        if group.is_coalesced_activity and group.count > 1:
            ts_start = group.first_event.created_at[:19] if group.first_event.created_at else "00:00:00"
            ts_end = group.last_event.created_at[11:19] if group.last_event.created_at else "00:00:00"
            return f"{prefix}{dot_glyph} [dim][ACTIVITY][/dim] {kind_clean} (actor: @{actor}) [bold{accent_tag}]x{group.count}[/bold{accent_tag}] ({group.count} events, {ts_start} - {ts_end}){select_tag}{pulse_badge}"

        # 1. MESSAGE: provenance-rich showing actor, timestamp, and content
        if p_class == "message":
            msg_glyph = self._g("💬")
            body_line = f"\n   [italic]\"{redact_ui_text(evt.content)}\"[/italic]" if evt.content else ""
            return (
                f"{prefix}[bold{ok_tag}]{msg_glyph} MESSAGE[/bold{ok_tag}] [dim]@{actor} at {ts}[/dim]{select_tag}{pulse_badge}\n"
                f"   [bold]Kind:[/bold] {kind_clean}{body_line}\n"
                f"   Event ID: {evt.event_id}"
            )

        # 2. ACTIVITY: concise, coalesced visual format (Single repeat)
        elif p_class == "activity":
            return f"{prefix}{dot_glyph} [dim][ACTIVITY][/dim] {kind_clean} (actor: @{actor} at {ts}){select_tag}{pulse_badge}"

        # 3. CHECKPOINT: bordered box
        elif p_class == "checkpoint":
            return (
                f"{prefix}┌─ [bold{accent_tag}]CHECKPOINT[/bold{accent_tag}] ──────────────────────┐\n"
                f"│ Event: {kind_clean:<32} │\n"
                f"│ Timestamp: {ts:<28} │\n"
                f"└────────────────────────────────────────┘{select_tag}{pulse_badge}"
            )

        # 4. ARTIFACT: metadata & preview ONLY (zero import / apply affordances)
        elif p_class == "artifact":
            acc_open = f"[{accent}]" if accent else ""
            acc_close = f"[/{accent}]" if accent else ""
            return (
                f"{prefix}[bold{highlight_tag}]📦 ARTIFACT OFFER[/bold{highlight_tag}] [dim]by @{actor} at {ts}[/dim]{select_tag}{pulse_badge}\n"
                f"   Metadata: {acc_open}{kind_clean}{acc_close} (ID: {evt.event_id[:8]})\n"
                f"   [dim](Read-only metadata preview - press Enter/inspect to view details)[/dim]"
            )

        # 5. APPROVAL: amber token (zero action buttons)
        elif p_class == "approval":
            risk_glyph = self._g("▲")
            warn_open = f"[{warn}]" if warn else ""
            warn_close = f"[/{warn}]" if warn else ""
            return (
                f"{prefix}[bold{warn_tag}]{risk_glyph} APPROVAL GATE [AMBER/POLICY][/bold{warn_tag}] [dim]at {ts}[/dim]{select_tag}{pulse_badge}\n"
                f"   {warn_open}Request: {kind_clean} by @{actor}{warn_close}\n"
                f"   [dim](Policy review required - pending owner decision)[/dim]"
            )

        # 6. STATE_TRANSITION: clear visual state divider
        elif p_class == "state_transition":
            return (
                f"{prefix}═══ [bold{accent2_tag}]STATE TRANSITION[/bold{accent2_tag}] ═════════════════════════════\n"
                f"   Event: [bold]{kind_clean}[/bold] by @{actor} at {ts}{select_tag}{pulse_badge}"
            )

        # 7. SECURITY: persistent RED card (zero action affordances)
        elif p_class == "security":
            glyph_x = self._g("!")
            err_open = f"[{err}]" if err else ""
            err_close = f"[/{err}]" if err else ""
            return (
                f"{prefix}[bold{err_tag}]{glyph_x} SECURITY REJECTION CARD[/bold{err_tag}] [dim]at {ts}[/dim]{select_tag}{pulse_badge}\n"
                f"   {err_open}Category: {kind_clean}{err_close}\n"
                f"   {err_open}Actor: @{actor} | ID: {evt.event_id}{err_close}\n"
                f"   [bold{err_tag}]CRITICAL: Security boundary rejection logged. No actions available.[/bold{err_tag}]"
            )

        # Fallback
        return f"{prefix}{dot_glyph} [{p_class.upper()}] {kind_clean} (@{actor} at {ts}){select_tag}{pulse_badge}"

    def render(self, now: Optional[Union[datetime, str, float]] = None) -> str:
        accent = self._c("accent.primary", "#bb9af7")
        ok = self._c("state.live", "#73daca")
        err = self._c("state.error", "#f7768e")
        accent_tag = f" {accent}".rstrip()
        ok_tag = f" {ok}".rstrip()
        err_tag = f" {err}".rstrip()
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = self._g("◌")
            return f"[dim]{glyph} Loading Exchange Timeline...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "ExchangeTimeline disabled"
            return f"[dim]ExchangeTimeline (DISABLED: {reason})[/dim]"

        groups = self.get_coalesced_groups()

        if state == WidgetLifecycleState.EMPTY or not groups:
            return "[dim]ExchangeTimeline: No dialogue/session events recorded.[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = self._g("!")
            return f"[bold{err_tag}]{glyph} ExchangeTimeline Error: Event timeline corrupted. Press [Retry].[/bold{err_tag}]"

        now_dt = _parse_now(now)
        down_glyph = self._g("↓")
        lines = [f"[bold{ok_tag}]Exchange Timeline ({len(groups)} cards / {len(self.get_filtered_events())} events):[/bold{ok_tag}]"]

        # Surface fixed off-tail control when reader is off tail (§7.2, §14.8 Phase C1/C2)
        if self.new_events_off_tail_count > 0 and not self.is_at_tail():
            lines.append(f"[bold{accent_tag}]{down_glyph} {self.new_events_off_tail_count} new events (press 'G' or 'End' to jump to tail)[/bold{accent_tag}]")

        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        for idx, group in enumerate(groups):
            is_selected = (idx == self.selected_index)
            lines.append(self._render_group_card(group, is_selected, now_dt))

        return "\n\n".join(lines) + focus_mark
