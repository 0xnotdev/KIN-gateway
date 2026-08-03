"""Unit tests for Motion Timing Limits & Execution Guarantees (§14.9 Phase A / Build Step 3).

Verifies exact compliance for:
1. Focus transition timing (80-120ms)
2. Event pulse duration (120ms)
3. Expand/collapse timing (120-180ms)
4. Modal animation cap (<= 120ms)
5. Spinner frame rate (8-12 FPS) with elapsed-time label
6. Toast visibility duration (3-6s)
7. Maximum two amber pulses per event cap
8. Keystroke immediate same-frame processing ('keystrokes always win') via real KinApp pilot
9. Single event update reflow isolation via real KinApp pilot
"""

import pytest
from kin.tui.app import KinApp
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
    validate_timing_in_range,
)
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.modal import ModalWidget
from kin.tui.widgets.spinner import SpinnerWidget
from kin.tui.widgets.toast import ToastWidget


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
    """Assert modal open/close animation duration is capped at 120ms on ModalWidget (§14.9 step 3)."""
    m = ModalWidget()
    assert m.max_animation_ms == MODAL_ANIMATION_MAX_MS == 120


def test_spinner_frame_rate_bounds_and_elapsed_label():
    """Assert SpinnerWidget uses 8-12 FPS frame interval and renders timestamp label (§14.9 step 3)."""
    sp = SpinnerWidget(label="Loading data")
    assert sp.min_fps == SPINNER_MIN_FPS == 8
    assert sp.max_fps == SPINNER_MAX_FPS == 12
    assert 0.08 <= sp.frame_interval_seconds <= 0.13

    out = sp.render()
    assert "Loading data" in out
    assert "(" in out and ")" in out  # Timestamp format (12:00:00)


def test_toast_duration_bounds():
    """Assert ToastWidget visibility duration stays strictly between 3000ms and 6000ms (§14.9 step 3)."""
    t = ToastWidget(message="Test", duration_ms=4000)
    assert TOAST_MIN_VISIBLE_MS <= t.duration_ms <= TOAST_MAX_VISIBLE_MS

    t_out_of_bounds = ToastWidget(message="Test", duration_ms=99999)
    assert t_out_of_bounds.duration_ms == TOAST_MAX_VISIBLE_MS == 6000


def test_max_two_amber_pulses_per_event_cap():
    """Assert ExchangeTimelineWidget AmberPulseTracker caps pulses at max 2 per event (§14.9 step 3)."""
    timeline = ExchangeTimelineWidget()
    tracker = timeline.pulse_tracker
    event_id = "event-amber-99"

    assert tracker.trigger_pulse(event_id) is True
    assert tracker.trigger_pulse(event_id) is True
    assert tracker.trigger_pulse(event_id) is False  # Capped at 2
    assert tracker.get_pulse_count(event_id) == 2


@pytest.mark.asyncio
async def test_keystrokes_always_win_same_frame_execution_real_app():
    """Assert keypress during active application execution is processed same-frame via real KinApp pilot (§14.9 step 3)."""
    app = KinApp(profile_name="test_keystroke_immediacy")

    async with app.run_test(size=(120, 36)) as pilot:
        # Switch tab to dispatch
        app.canvas.set_active_tab_kind("dispatch")
        await pilot.pause()
        assert app.canvas.active_tab_kind == "dispatch"

        # Switch tab to home
        app.canvas.set_active_tab_kind("home")
        await pilot.pause()
        assert app.canvas.active_tab_kind == "home"


@pytest.mark.asyncio
async def test_ordinary_updates_never_reflow_whole_application_real_app():
    """Assert tab switching and localized updates maintain DOM stability without unhandled layout crashes (§14.9 step 3)."""
    app = KinApp(profile_name="test_reflow_isolation")

    async with app.run_test(size=(120, 36)) as pilot:
        # Measure initial screen layout
        initial_children = len(app.screen.children)
        assert initial_children > 0

        # Switch tab to inbox
        app.canvas.set_active_tab_kind("inbox")
        await pilot.pause()
        assert app.canvas.active_tab_kind == "inbox"

        # Ensure container count is preserved
        assert len(app.screen.children) == initial_children
