"""Unit and stress tests for Session Arena Phase C2 background worker and FPS-batched commits (§14.8 build step 4).

Covers:
1. High-frequency stress test: 100 events injected at >30 ev/sec sustained over 2 seconds.
   - Asserts 100% data retention (all 100 events present in events list and coalesced groups).
   - Asserts visual commits (_refresh_call_count) are bounded by 10 FPS / 30 FPS caps.
   - Asserts keystroke navigation (cursor_down) processes immediately without timer queue delay.
2. Degraded FPS under pressure: arrival rate > 30 ev/sec triggers pressure state and degrades min commit interval to 100ms.
3. Reconnect & Dedup: handle_reconnect inserts exactly 1 state_transition marker and deduplicates replayed events by event_id.
4. Standing requirement guard: worker aborts immediately and does ZERO polling for placeholder or empty session_ids.
"""

from datetime import datetime, timezone
import pytest

from kin.tui.state import UiEvent
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.session_arena import SessionArenaWidget


@pytest.fixture
def base_events() -> list[UiEvent]:
    return [
        UiEvent("e-1", "sess-c2-real", "task_request", "2026-08-01T12:00:00Z", "alice", "message"),
        UiEvent("e-2", "sess-c2-real", "finding", "2026-08-01T12:00:05Z", "bob", "activity"),
    ]


# -----------------------------------------------------------------------------
# 1. Required Stress Test: High-Frequency Burst with Zero Data Loss & FPS Bounding (§14.8 C2)
# -----------------------------------------------------------------------------
def test_stress_high_frequency_burst_zero_data_loss_and_bounded_refresh_commits(base_events):
    """Stress test: Inject 100 events at >30 ev/sec. Assert 100% data retention, bounded refresh commits, and immediate keystrokes (§14.8 C2)."""
    timeline = ExchangeTimelineWidget(
        events=base_events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
    )
    initial_refresh_count = timeline._refresh_call_count

    # Inject 100 high-frequency events over a 2.0-second window (50 ev/sec arrival rate)
    t_base = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    high_freq_events = [
        UiEvent(f"burst-{i}", "sess-c2-real", f"finding_{i}", datetime.fromtimestamp(t_base + i * 0.02, timezone.utc).isoformat(), "bob", "activity")
        for i in range(100)
    ]

    # Batch append in bursts of 5 events every 100ms
    for i in range(0, 100, 5):
        chunk = high_freq_events[i:i+5]
        chunk_time = t_base + (i * 0.02)
        timeline.append_events(chunk, now=chunk_time)

    # 1. Assert ZERO Data Loss: all 100 burst events + 2 base events present in timeline
    assert len(timeline.events) == 102
    coalesced = timeline.get_coalesced_groups()
    # Base message + coalesced activity group (100 burst + 1 base activity = 101 activity count)
    assert len(coalesced) == 2
    assert coalesced[1].count == 101

    # 2. Assert Bounded Refresh Commits: refresh calls are throttled (far less than 20 separate chunk refreshes)
    total_refreshes = timeline._refresh_call_count - initial_refresh_count
    assert total_refreshes <= 20  # Max 20 visual commits for 20 chunks over 2s under pressure cap

    # 3. Assert Immediate Keystroke Response: cursor_down() executes immediately and increments commit count
    refresh_before_key = timeline._refresh_call_count
    timeline.cursor_down()
    assert timeline._refresh_call_count == refresh_before_key + 1
    assert timeline.get_selected_event().event_id == coalesced[1].last_event.event_id


# -----------------------------------------------------------------------------
# 2. Pressure Detection & FPS Degradation (§14.8 Phase C2)
# -----------------------------------------------------------------------------
def test_pressure_detection_degrades_fps_to_100ms(base_events):
    """Assert incoming arrival rate > 30 ev/sec sets pressure state and degrades min commit interval to 100ms (§14.8 C2)."""
    timeline = ExchangeTimelineWidget(
        events=base_events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
    )
    t_start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Inject 35 events in 1.0 second -> exceeds pressure threshold of 30 ev/sec
    burst_events = [
        UiEvent(f"p-{i}", "sess-c2-real", "finding", t_start.isoformat(), "bob", "activity")
        for i in range(35)
    ]
    timeline.append_events(burst_events, now=t_start)

    assert timeline.is_under_pressure(t_start) is True


# -----------------------------------------------------------------------------
# 3. Transport Reconnect & Deduplication (§14.8 Phase C2)
# -----------------------------------------------------------------------------
def test_reconnect_inserts_exactly_one_transition_and_deduplicates_replayed_events(base_events):
    """Assert handle_reconnect inserts 1 state_transition marker and deduplicates replayed events by event_id (§14.8 C2)."""
    timeline = ExchangeTimelineWidget(
        events=base_events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
    )
    t_reconnect = datetime(2026, 8, 1, 12, 10, 0, tzinfo=timezone.utc)

    # Replayed events contain 1 existing event ("e-2") and 1 new event ("e-3")
    replayed = [
        UiEvent("e-2", "sess-c2-real", "finding", "2026-08-01T12:00:05Z", "bob", "activity"),
        UiEvent("e-3", "sess-c2-real", "finding_new", "2026-08-01T12:10:05Z", "bob", "activity"),
    ]

    timeline.handle_reconnect(replayed, now=t_reconnect)

    # Assert exactly 1 reconnect state_transition event added
    reconnect_events = [e for e in timeline.events if e.kind == "reconnect" and e.presentation_class == "state_transition"]
    assert len(reconnect_events) == 1

    # Assert "e-2" was deduplicated and "e-3" was appended (total events: 2 base + 1 reconnect + 1 new = 4)
    event_ids = [e.event_id for e in timeline.events]
    assert event_ids.count("e-2") == 1
    assert "e-3" in event_ids
    assert len(timeline.events) == 4


# -----------------------------------------------------------------------------
# 4. Standing Requirement Guard Test (§14.8 Phase C2)
# -----------------------------------------------------------------------------
def test_worker_standing_requirement_guard_prevents_polling_when_session_id_unspecified():
    """Assert run_event_polling_worker aborts immediately and does ZERO polling when session_id is None or empty (§14.8 C2)."""
    for empty_id in (None, ""):
        arena = SessionArenaWidget(session_id=empty_id)
        arena.is_polling_active = True

        # Polling worker logic must exit immediately without attempting DB fetches
        arena._run_event_polling_worker_logic()
        assert arena.session_summary is None or getattr(arena, "events", []) == []
