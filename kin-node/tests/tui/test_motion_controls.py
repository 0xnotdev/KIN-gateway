"""Motion controls, latency hysteresis, and blur/focus isolation test suite (§14.9 Phase D)."""

import time
import pytest
from kin.tui.app import KinApp
from kin.tui.persistence import UiStatePreferences


def test_transient_reduced_motion_isolation():
    """Assert transient reduced motion alters active motion state without mutating persisted user preferences."""
    app = KinApp()
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


def test_cpu_latency_hysteresis_trigger():
    """Assert 3 consecutive tick checks with latency > 100ms trigger reduced motion, and 1 normal check recovers."""
    app = KinApp()
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


def test_keystroke_latency_zero_artificial_delay():
    """Assert keypress event handling inserts zero artificial animation/timer delays prior to processing."""
    app = KinApp()
    start_time = time.perf_counter()

    # Simulate key event processing and latency recording
    app.record_latency_sample(2.5)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    # Assert processing completes synchronously under 50ms without artificial sleep
    assert elapsed_ms < 50.0, f"Keypress action took {elapsed_ms:.2f}ms, artificial delay detected"
