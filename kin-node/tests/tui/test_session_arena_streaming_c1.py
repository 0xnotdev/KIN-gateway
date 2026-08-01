"""Unit tests for Session Arena Phase C1 streaming semantics (§14.8 build step 3).

Covers:
1. Off-tail retention: cursor stays on historical event, appends 3 new events, asserts cursor did NOT move and '↓ 3 new events' control is rendered.
2. Return-to-tail: triggering jump_to_tail ('G' / 'End') moves cursor to newest event and clears counter.
3. At-tail auto-follow: cursor on last event, appends 1 new event, asserts cursor follows to new tail.
4. 120ms Tail Pulse timing: pulse badge present at <120ms from first render, absent at >=120ms.
5. Reduced motion: reduced_motion=True suppresses pulse styling unconditionally regardless of timing.
6. Activity Coalescing: 5 consecutive activity events from same actor collapse to 1 card with count=5; approval, security, and state_transition events NEVER coalesce.
"""

from datetime import datetime, timezone
import pytest

from kin.tui.persistence import UiStatePreferences
from kin.tui.state import UiEvent
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.session_arena import SessionArenaWidget


@pytest.fixture
def initial_events() -> list[UiEvent]:
    return [
        UiEvent("e-1", "sess-1", "task_request", "2026-08-01T12:00:00Z", "alice", "message"),
        UiEvent("e-2", "sess-1", "finding", "2026-08-01T12:00:05Z", "bob", "activity"),
    ]


# -----------------------------------------------------------------------------
# 1. Off-Tail Retention Test (§14.8 Phase C1)
# -----------------------------------------------------------------------------
def test_off_tail_retention_retains_reader_cursor_and_shows_counter(initial_events):
    """Assert cursor on an older event retains position when new events arrive and surfaces '↓ 3 new events' (§14.8 Phase C1)."""
    timeline = ExchangeTimelineWidget(
        events=initial_events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
    )
    # Move cursor to top (index 0)
    timeline.selected_index = 0
    assert not timeline.is_at_tail()

    new_events = [
        UiEvent("e-3", "sess-1", "checkpoint_turn_1", "2026-08-01T12:00:10Z", "system", "checkpoint"),
        UiEvent("e-4", "sess-1", "artifact_offer", "2026-08-01T12:00:15Z", "bob", "artifact"),
        UiEvent("e-5", "sess-1", "approval_request", "2026-08-01T12:00:20Z", "bob", "approval"),
    ]

    # Append 3 new events into stream
    timeline.append_events(new_events)

    # Reader position retained at index 0
    assert timeline.selected_index == 0
    assert timeline.new_events_off_tail_count == 3
    rendered = timeline.render()
    assert "↓ 3 new events" in rendered


# -----------------------------------------------------------------------------
# 2. Return-to-Tail Test (§14.8 Phase C1)
# -----------------------------------------------------------------------------
def test_return_to_tail_jumps_cursor_and_clears_counter(initial_events):
    """Assert triggering jump_to_tail ('G' / 'End') moves cursor to tail and clears counter (§14.8 Phase C1)."""
    timeline = ExchangeTimelineWidget(
        events=initial_events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
    )
    timeline.selected_index = 0
    timeline.append_events([
        UiEvent("e-3", "sess-1", "checkpoint_turn_1", "2026-08-01T12:00:10Z", "system", "checkpoint"),
        UiEvent("e-4", "sess-1", "artifact_offer", "2026-08-01T12:00:15Z", "bob", "artifact"),
    ])
    assert timeline.new_events_off_tail_count == 2

    # Trigger jump_to_tail
    timeline.jump_to_tail()

    assert timeline.is_at_tail()
    assert timeline.selected_index == len(timeline.get_coalesced_groups()) - 1
    assert timeline.new_events_off_tail_count == 0
    rendered = timeline.render()
    assert "↓" not in rendered


# -----------------------------------------------------------------------------
# 3. At-Tail Auto-Follow Test (§14.8 Phase C1)
# -----------------------------------------------------------------------------
def test_at_tail_auto_follow_moves_cursor_to_new_tail(initial_events):
    """Assert cursor already at tail automatically follows when new event arrives (§14.8 Phase C1)."""
    timeline = ExchangeTimelineWidget(
        events=initial_events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
    )
    # Move cursor to last event (index 1)
    timeline.selected_index = 1
    assert timeline.is_at_tail()

    # Append 1 new event
    timeline.append_events([
        UiEvent("e-3", "sess-1", "checkpoint_turn_1", "2026-08-01T12:00:10Z", "system", "checkpoint"),
    ])

    # Cursor follows to new tail (index 2)
    assert timeline.is_at_tail()
    assert timeline.selected_index == 2
    assert timeline.new_events_off_tail_count == 0
    rendered = timeline.render()
    assert "↓" not in rendered


# -----------------------------------------------------------------------------
# 4. 120ms Tail Pulse Timing via Injected Clock (§14.8 Phase C1)
# -----------------------------------------------------------------------------
def test_tail_pulse_timing_via_injected_clock(initial_events):
    """Assert pulse styling present <120ms from first render, absent >=120ms (§14.8 Phase C1)."""
    timeline = ExchangeTimelineWidget(
        events=initial_events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
        reduced_motion=False,
    )
    t_start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

    # First render at T_start (0ms elapsed) -> pulse active
    rendered_50ms = timeline.render(now=t_start)
    assert "[TAIL PULSE]" in rendered_50ms

    # Second render at T_start + 50ms -> pulse active
    t_50ms = datetime(2026, 8, 1, 12, 0, 0, 50000, tzinfo=timezone.utc)
    rendered_50ms_again = timeline.render(now=t_50ms)
    assert "[TAIL PULSE]" in rendered_50ms_again

    # Third render at T_start + 125ms -> pulse expired
    t_125ms = datetime(2026, 8, 1, 12, 0, 0, 125000, tzinfo=timezone.utc)
    rendered_125ms = timeline.render(now=t_125ms)
    assert "[TAIL PULSE]" not in rendered_125ms


# -----------------------------------------------------------------------------
# 5. Reduced Motion Suppression Test (§14.8 Phase C1)
# -----------------------------------------------------------------------------
def test_reduced_motion_suppresses_pulse_styling(initial_events):
    """Assert reduced_motion=True suppresses pulse styling unconditionally regardless of timing (§14.8 Phase C1)."""
    # Verify UiStatePreferences has reduced_motion field
    prefs = UiStatePreferences(reduced_motion=True)
    assert prefs.reduced_motion is True

    timeline = ExchangeTimelineWidget(
        events=initial_events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
        reduced_motion=True,
    )
    t_start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Render at 0ms with reduced_motion=True -> zero pulse styling
    rendered = timeline.render(now=t_start)
    assert "[TAIL PULSE]" not in rendered


# -----------------------------------------------------------------------------
# 6. Activity Coalescing Rules Test (§14.8 Phase C1)
# -----------------------------------------------------------------------------
def test_activity_coalescing_collapses_repeats_but_never_approval_security_state():
    """Assert 5 consecutive activity events collapse to 1 card; approval, security, and state_transition events NEVER coalesce (§14.8 Phase C1)."""
    events = [
        # 5 consecutive activity events from @bob
        UiEvent("a-1", "sess-1", "finding", "2026-08-01T12:00:00Z", "bob", "activity"),
        UiEvent("a-2", "sess-1", "finding", "2026-08-01T12:00:01Z", "bob", "activity"),
        UiEvent("a-3", "sess-1", "finding", "2026-08-01T12:00:02Z", "bob", "activity"),
        UiEvent("a-4", "sess-1", "finding", "2026-08-01T12:00:03Z", "bob", "activity"),
        UiEvent("a-5", "sess-1", "finding", "2026-08-01T12:00:04Z", "bob", "activity"),
        # Non-coalescable events from same actor @bob
        UiEvent("app-1", "sess-1", "approval_req", "2026-08-01T12:00:05Z", "bob", "approval"),
        UiEvent("sec-1", "sess-1", "security_err", "2026-08-01T12:00:06Z", "bob", "security"),
        UiEvent("st-1", "sess-1", "state_change", "2026-08-01T12:00:07Z", "bob", "state_transition"),
    ]

    timeline = ExchangeTimelineWidget(
        events=events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
    )
    groups = timeline.get_coalesced_groups()

    # 5 activity events collapse into 1 group with count=5
    # approval, security, state_transition form 3 individual groups -> Total 4 groups
    assert len(groups) == 4
    assert groups[0].count == 5
    assert groups[0].is_coalesced_activity is True

    assert groups[1].count == 1
    assert groups[1].first_event.presentation_class == "approval"

    assert groups[2].count == 1
    assert groups[2].first_event.presentation_class == "security"

    assert groups[3].count == 1
    assert groups[3].first_event.presentation_class == "state_transition"

    rendered = timeline.render()
    assert "x5" in rendered
    assert "5 events" in rendered
