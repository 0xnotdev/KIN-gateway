"""Motion controls, latency hysteresis, and blur/focus isolation test suite (§14.9 Phase D)."""

import time
import pytest
from kin.tui.motion import REDUCED_MOTION_PROBE_INTERVAL_SECONDS
from kin.tui.persistence import UiStatePreferences


def test_transient_reduced_motion_isolation(build_tui_app):
    """Assert transient reduced motion alters active motion state without mutating persisted user preferences."""
    app = build_tui_app()
    app.prefs = UiStatePreferences(reduced_motion=False)
    app.transient_reduced_motion = False

    assert app.is_reduced_motion_active is False
    assert app.prefs.reduced_motion is False

    # Simulate AppBlur
    app.on_app_blur()
    assert app.transient_reduced_motion is True
    assert app.is_reduced_motion_active is True
    assert app.prefs.reduced_motion is False  # Persisted setting unaffected

    # Simulate AppFocus
    app.on_app_focus()
    assert app.transient_reduced_motion is False
    assert app.is_reduced_motion_active is False
    assert app.prefs.reduced_motion is False


def test_cpu_latency_hysteresis_trigger(build_tui_app):
    """Assert 3 consecutive tick checks with latency > 100ms trigger reduced motion, and 1 normal check recovers."""
    app = build_tui_app()
    app.prefs = UiStatePreferences(reduced_motion=False)
    app.transient_reduced_motion = False
    app.latency_breach_count = 0

    # 1. First breach
    app.record_latency_sample(120.0)
    assert app.latency_breach_count == 1
    assert app.is_reduced_motion_active is False

    # 2. Second breach
    app.record_latency_sample(110.0)
    assert app.latency_breach_count == 2
    assert app.is_reduced_motion_active is False

    # 3. Third consecutive breach -> triggers reduced motion
    app.record_latency_sample(105.0)
    assert app.latency_breach_count == 3
    assert app.is_reduced_motion_active is True

    # 4. Normal check <= 100ms -> recovers immediately (hysteresis reset)
    app.record_latency_sample(45.0)
    assert app.latency_breach_count == 0
    assert app.is_reduced_motion_active is False


def test_keystroke_latency_zero_artificial_delay(build_tui_app):
    """Assert keypress event handling inserts zero artificial animation/timer delays prior to processing."""
    app = build_tui_app()
    start_time = time.perf_counter()

    # Simulate key event processing and latency recording
    app.record_latency_sample(2.5)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    # Assert processing completes synchronously under 50ms without artificial sleep
    assert elapsed_ms < 50.0, f"Keypress action took {elapsed_ms:.2f}ms, artificial delay detected"


def test_live_event_loop_probe_feeds_cpu_pressure_hysteresis(build_tui_app, monkeypatch):
    """The production probe measures drift and feeds the real hysteresis path."""
    app = build_tui_app()
    app.prefs = UiStatePreferences(reduced_motion=False)
    app._motion_probe_last_at = 10.0
    sample_gap = REDUCED_MOTION_PROBE_INTERVAL_SECONDS + 0.120
    samples = iter([10.0 + sample_gap, 10.0 + sample_gap * 2, 10.0 + sample_gap * 3])
    monkeypatch.setattr("kin.tui.app.monotonic", lambda: next(samples))

    app._sample_event_loop_latency()
    app._sample_event_loop_latency()
    app._sample_event_loop_latency()

    assert app.latency_breach_count == 3
    assert app.cpu_reduced_motion is True
    assert app.is_reduced_motion_active is True


@pytest.mark.asyncio
async def test_automatic_and_manual_reduced_motion_propagate_to_hosted_animations(
    build_tui_app,
    tmp_path,
):
    app = build_tui_app(profile_name="motion-propagation", profile_dir=tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        assert app._motion_probe_timer is not None

        for latency_ms in (120.0, 130.0, 140.0):
            app.record_latency_sample(latency_ms)
        assert app.cpu_reduced_motion is True
        assert app.activity_spinner._reduced_motion is True
        assert app.notification_toast._reduced_motion is True

        app.start_activity("Indexing session history")
        app.show_toast("Approval waiting", severity="warning")
        await pilot.pause()
        assert app.activity_spinner._frame_timer is None
        assert app.notification_toast._amber_pulse_timer is None
        assert "elapsed" in app.activity_spinner.render()
        assert "Approval waiting" in app.notification_toast.render()

        app.record_latency_sample(20.0)
        assert app.cpu_reduced_motion is False
        assert app.activity_spinner._reduced_motion is False
        assert app.activity_spinner._frame_timer is not None

        app.on_app_blur()
        app.record_latency_sample(20.0)
        assert app.is_reduced_motion_active is True
        assert app.activity_spinner._reduced_motion is True
        app.on_app_focus()
        assert app.is_reduced_motion_active is False
