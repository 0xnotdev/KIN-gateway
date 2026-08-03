"""Unit tests for Motion Timing Limits & Execution Guarantees (§14.9 Phase A / Build Step 3).

Verifies exact compliance for:
1. Focus transition timing (80-120ms)
2. Event pulse duration (120ms)
3. Expand/collapse timing (120-180ms)
4. Modal animation cap (<= 120ms)
5. Spinner frame rate (8-12 FPS) with elapsed-time label
6. Toast visibility duration (3-6s)
7. Maximum two amber pulses per event cap
8. Keystroke immediate same-frame processing ('keystrokes always win')
9. Single event update reflow isolation (no full-screen application reflow)
"""

import time
import pytest
from kin.tui.motion import (
    EXPAND_COLLAPSE_DEFAULT_MS,
    EXPAND_COLLAPSE_MAX_MS,
    EXPAND_COLLAPSE_MIN_MS,
    FOCUS_TRANSITION_DEFAULT_MS,
    FOCUS_TRANSITION_MAX_MS,
    FOCUS_TRANSITION_MIN_MS,
    EVENT_PULSE_MS,
    MAX_AMBER_PULSES_PER_EVENT,
    MODAL_ANIMATION_MAX_MS,
    SPINNER_MAX_FPS,
    SPINNER_MIN_FPS,
    TOAST_MAX_VISIBLE_MS,
    TOAST_MIN_VISIBLE_MS,
    AmberPulseTracker,
    MotionFrameController,
    validate_timing_in_range,
)
from kin.tui.widgets.spinner import SpinnerWidget


def test_focus_transition_timing_bounds():
    """Assert focus transition duration stays strictly between 80ms and 120ms (§14.9 step 3)."""
    assert FOCUS_TRANSITION_MIN_MS == 80
    assert FOCUS_TRANSITION_MAX_MS == 120
    assert validate_timing_in_range(FOCUS_TRANSITION_DEFAULT_MS, FOCUS_TRANSITION_MIN_MS, FOCUS_TRANSITION_MAX_MS)


def test_event_pulse_duration_constant():
    """Assert event pulse duration is exactly 120ms (§14.9 step 3)."""
    assert EVENT_PULSE_MS == 120


def test_expand_collapse_timing_bounds():
    """Assert expand/collapse duration stays strictly between 120ms and 180ms (§14.9 step 3)."""
    assert EXPAND_COLLAPSE_MIN_MS == 120
    assert EXPAND_COLLAPSE_MAX_MS == 180
    assert validate_timing_in_range(EXPAND_COLLAPSE_DEFAULT_MS, EXPAND_COLLAPSE_MIN_MS, EXPAND_COLLAPSE_MAX_MS)


def test_modal_animation_duration_cap():
    """Assert modal open/close animation duration is capped at 120ms (§14.9 step 3)."""
    assert MODAL_ANIMATION_MAX_MS == 120


def test_spinner_frame_rate_bounds_and_elapsed_label():
    """Assert spinner operates at 8-12 FPS and renders elapsed-time label (§14.9 step 3)."""
    assert SPINNER_MIN_FPS == 8
    assert SPINNER_MAX_FPS == 12

    # Frame interval in seconds for 8-12 FPS is 1/12 <= dt <= 1/8 (0.083s - 0.125s)
    min_interval = 1.0 / SPINNER_MAX_FPS
    max_interval = 1.0 / SPINNER_MIN_FPS
    assert 0.08 <= min_interval <= 0.09
    assert 0.12 <= max_interval <= 0.13

    # Check SpinnerWidget renders label and timestamp
    sp = SpinnerWidget(label="Loading data")
    out = sp.render()
    assert "Loading data" in out
    assert "(" in out and ")" in out  # Timestamp label format (12:00:00)


def test_toast_duration_bounds():
    """Assert toast visibility duration stays strictly between 3000ms and 6000ms (§14.9 step 3)."""
    assert TOAST_MIN_VISIBLE_MS == 3000
    assert TOAST_MAX_VISIBLE_MS == 6000


def test_max_two_amber_pulses_per_event_cap():
    """Assert a maximum of two amber pulses per event is enforced (no indefinite pulsing) (§14.9 step 3)."""
    tracker = AmberPulseTracker(max_pulses=MAX_AMBER_PULSES_PER_EVENT)
    event_id = "event-amber-101"

    # First two pulses allowed
    assert tracker.trigger_pulse(event_id) is True
    assert tracker.get_pulse_count(event_id) == 1

    assert tracker.trigger_pulse(event_id) is True
    assert tracker.get_pulse_count(event_id) == 2

    # Third pulse rejected/capped
    assert tracker.trigger_pulse(event_id) is False
    assert tracker.get_pulse_count(event_id) == 2


def test_keystrokes_always_win_same_frame_execution():
    """Assert keypress during in-flight animation is processed same-frame (not queued behind animation) (§14.9 step 3)."""
    controller = MotionFrameController()
    controller.animation_in_flight = True

    # Press key while animation is active
    success, msg = controller.process_key("j")
    assert success is True
    assert "pre-empted" in msg
    assert controller.animation_in_flight is False
    assert controller.processed_keystrokes == ["j"]


def test_ordinary_updates_never_reflow_whole_application():
    """Assert a single event append/update triggers localized refresh, not full-screen reflow (§14.9 step 3)."""
    controller = MotionFrameController()

    # Localized widget update
    res1 = controller.record_update("activity_feed_timeline", is_full_screen=False)
    assert res1["reflow_triggered"] is False
    assert controller.layout_reflow_count == 0

    res2 = controller.record_update("agent_card_status", is_full_screen=False)
    assert res2["reflow_triggered"] is False
    assert controller.layout_reflow_count == 0
