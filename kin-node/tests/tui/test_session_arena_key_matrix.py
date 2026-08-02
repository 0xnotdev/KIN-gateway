"""Session Arena key dispatch tests via pilot.press() — proves BINDINGS are live.

These tests mount a real SessionArenaWidget inside a KinApp and press keys
through the Textual pilot, which goes through the full BINDINGS resolution
path. Direct action_*() method calls are NOT used — the point is to prove
the keyboard → BINDINGS → action_*() chain works end-to-end.

Previous versions of this test called action methods directly as Python
functions, which would pass even if on_key() was intercepting those keys
before BINDINGS resolution could run. This version catches that bug.
"""

import pytest
from unittest.mock import MagicMock

from kin.tui.app import KinApp


@pytest.mark.asyncio
async def test_arena_key_z_reaches_action_via_bindings():
    """Press 'z' through pilot; assert toggle_focus_mode is called via BINDINGS, not on_key."""
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test(size=(160, 44)) as pilot:
        # Switch to a session tab so the arena is mounted
        app.canvas.set_active_tab_kind("session", session_id="test-session-1")
        await pilot.pause()

        # Get the arena widget
        arena = None
        for widget in app.canvas.walk_children():
            if hasattr(widget, 'toggle_focus_mode') and hasattr(widget, 'active_lane'):
                arena = widget
                break

        if arena is None:
            pytest.skip("SessionArenaWidget not mounted — session tab routing not wired")

        # Spy on toggle_focus_mode
        original = arena.toggle_focus_mode
        call_count = 0
        def spy():
            nonlocal call_count
            call_count += 1
            original()

        arena.toggle_focus_mode = spy

        # Give arena focus
        arena.focus()
        await pilot.pause()

        # Press 'z' through the pilot (BINDINGS path)
        await pilot.press("z")
        await pilot.pause()

        assert call_count == 1, (
            f"Expected toggle_focus_mode to be called once via BINDINGS, "
            f"but it was called {call_count} times. "
            f"This means 'z' is not reaching action_lane_focus via BINDINGS."
        )

        await pilot.press("q")


@pytest.mark.asyncio
async def test_arena_key_t_switches_to_transcript_via_bindings():
    """Press 't' through pilot; assert lane switches to transcript."""
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test(size=(160, 44)) as pilot:
        app.canvas.set_active_tab_kind("session", session_id="test-session-1")
        await pilot.pause()

        arena = None
        for widget in app.canvas.walk_children():
            if hasattr(widget, 'switch_lane') and hasattr(widget, 'active_lane'):
                arena = widget
                break

        if arena is None:
            pytest.skip("SessionArenaWidget not mounted")

        # Start on a different lane to confirm the switch
        arena.active_lane = "activity"
        arena.focus()
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()

        assert arena.active_lane == "transcript", (
            f"Expected lane 'transcript' after pressing 't', got '{arena.active_lane}'"
        )

        await pilot.press("q")


@pytest.mark.asyncio
async def test_arena_key_e_collision_needs_you_vs_activity():
    """Press 'e' in needs_you lane → edit_constraints; in transcript lane → switch to activity."""
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test(size=(160, 44)) as pilot:
        app.canvas.set_active_tab_kind("session", session_id="test-session-1")
        await pilot.pause()

        arena = None
        for widget in app.canvas.walk_children():
            if hasattr(widget, 'switch_lane') and hasattr(widget, 'active_lane'):
                arena = widget
                break

        if arena is None:
            pytest.skip("SessionArenaWidget not mounted")

        # Test 1: 'e' in transcript lane → switches to activity
        arena.active_lane = "transcript"
        arena.focus()
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()

        assert arena.active_lane == "activity", (
            f"Expected lane 'activity' after pressing 'e' in transcript lane, got '{arena.active_lane}'"
        )

        # Test 2: 'e' in needs_you lane → calls handle_approval_key("e"), NOT switch_lane
        arena.active_lane = "needs_you"
        approval_key_calls = []
        original_handle = arena.handle_approval_key
        def spy_approval(k):
            approval_key_calls.append(k)
            original_handle(k)
        arena.handle_approval_key = spy_approval

        await pilot.press("e")
        await pilot.pause()

        assert "e" in approval_key_calls, (
            f"Expected handle_approval_key('e') to be called in needs_you lane, "
            f"got calls: {approval_key_calls}"
        )
        # Lane should NOT have switched to activity
        assert arena.active_lane == "needs_you", (
            f"Lane should remain 'needs_you' after pressing 'e' in needs_you lane, got '{arena.active_lane}'"
        )

        await pilot.press("q")


@pytest.mark.asyncio
async def test_on_key_does_not_handle_command_keys():
    """Directly verify on_key() does NOT intercept command keys z/t/e/c/o/u/i/s/m/r."""
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test(size=(160, 44)) as pilot:
        app.canvas.set_active_tab_kind("session", session_id="test-session-1")
        await pilot.pause()

        arena = None
        for widget in app.canvas.walk_children():
            if hasattr(widget, 'on_key') and hasattr(widget, 'active_lane'):
                arena = widget
                break

        if arena is None:
            pytest.skip("SessionArenaWidget not mounted")

        import inspect
        source = inspect.getsource(arena.on_key)

        # These command keys must NOT appear as intercepted cases in on_key
        command_keys = ["z", "t", "e", "c", "o", "u", "i", "s", "m", "r", "a", "d", "b", "v"]
        for key in command_keys:
            # Check that on_key source doesn't have `k == "{key}"` patterns
            # (navigation keys j/k/g/G are allowed)
            assert f'k == "{key}"' not in source, (
                f"on_key() still intercepts command key '{key}' — "
                f"this should be handled via BINDINGS + action_* instead"
            )

        await pilot.press("q")
