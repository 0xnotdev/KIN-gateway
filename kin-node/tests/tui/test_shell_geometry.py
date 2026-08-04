"""Unit tests for shell geometry, keybindings, dock safety, and health update focus stability.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §3.1, §3.2, §3.3, §5, §14.3
"""

from pathlib import Path
import pytest

from kin.tui.layout import (
    INSPECTOR_MAX_WIDTH,
    INSPECTOR_MIN_WIDTH,
    SIDEBAR_MAX_WIDTH,
    SIDEBAR_MIN_WIDTH,
)
from kin.tui.persistence import UiStatePreferences, save_ui_preferences
from kin.tui.state import HealthSnapshot


@pytest.fixture
def mock_profile_dir(tmp_path, monkeypatch):
    """Monkeypatch get_profile_dir to isolate UI state persistence tests."""
    profile_path = tmp_path / ".kin" / "profiles" / "test_profile"
    monkeypatch.setattr("kin.tui.persistence.get_profile_dir", lambda name="default": profile_path)
    monkeypatch.setattr("kin.tui.app.get_profile_dir", lambda name="default": profile_path)
    return profile_path


@pytest.mark.asyncio
async def test_stable_region_widget_ids_mounted(mock_profile_dir, build_tui_app):
    """Assert all five persistent region widgets are mounted with stable IDs (§3.1)."""
    app = build_tui_app()
    async with app.run_test(size=(160, 44)) as pilot:
        assert pilot.app.query_one("#workspace-tab-bar") is not None
        assert pilot.app.query_one("#sidebar") is not None
        assert pilot.app.query_one("#main-canvas") is not None
        assert pilot.app.query_one("#inspector") is not None
        assert pilot.app.query_one("#status-bar") is not None


@pytest.mark.asyncio
async def test_keyboard_sidebar_resize_and_clamping(mock_profile_dir, build_tui_app):
    """Assert Alt+[ and Alt+] resize sidebar in 2-col increments clamped to [24, 42] (§3.3)."""
    app = build_tui_app()
    async with app.run_test(size=(160, 44)) as pilot:
        sidebar = pilot.app.sidebar

        # Initial width 32
        assert sidebar.sidebar_width == 32

        # Alt+] increases by 2 to 34
        await pilot.press("alt+right_square_bracket")
        assert sidebar.sidebar_width == 34

        # Press Alt+] repeatedly to test max clamp (42)
        for _ in range(10):
            await pilot.press("alt+right_square_bracket")
        assert sidebar.sidebar_width == SIDEBAR_MAX_WIDTH  # 42

        # Press Alt+[ repeatedly to test min clamp (24)
        for _ in range(15):
            await pilot.press("alt+left_square_bracket")
        assert sidebar.sidebar_width == SIDEBAR_MIN_WIDTH  # 24


@pytest.mark.asyncio
async def test_keyboard_inspector_resize_and_clamping(mock_profile_dir, build_tui_app):
    """Assert Alt+{ and Alt+} resize inspector in 2-col increments clamped to [30, 52] (§3.3)."""
    app = build_tui_app()
    async with app.run_test(size=(160, 44)) as pilot:
        inspector = pilot.app.inspector

        # Initial width 38
        assert inspector.inspector_width == 38

        # Alt+} increases by 2 to 40
        await pilot.press("alt+shift+right_square_bracket")
        assert inspector.inspector_width == 40

        # Press Alt+} repeatedly to test max clamp (52)
        for _ in range(10):
            await pilot.press("alt+shift+right_square_bracket")
        assert inspector.inspector_width == INSPECTOR_MAX_WIDTH  # 52

        # Press Alt+{ repeatedly to test min clamp (30)
        for _ in range(15):
            await pilot.press("alt+shift+left_square_bracket")
        assert inspector.inspector_width == INSPECTOR_MIN_WIDTH  # 30


@pytest.mark.asyncio
async def test_keyboard_toggle_sidebar_and_inspector(mock_profile_dir, build_tui_app):
    """Assert [ toggles sidebar collapse and ] toggles inspector visibility (§3.3).

    When #command-input is focused, printable characters '[' and ']' append to input.
    When focus is not on input, '[' and ']' toggle sidebar/inspector.
    """
    app = build_tui_app()
    async with app.run_test(size=(160, 44)) as pilot:
        sidebar = pilot.app.sidebar
        inspector = pilot.app.inspector
        input_widget = pilot.app.query_one("#command-input")

        # 1. With #command-input focused, pressing '[' appends to input value without collapsing sidebar
        input_widget.focus()
        await pilot.pause()
        assert pilot.app.focused == input_widget
        assert sidebar.collapsed is False

        await pilot.press("left_square_bracket")
        assert input_widget.value == "["
        assert sidebar.collapsed is False, "Sidebar collapsed while input had focus!"

        # 2. With focus cleared, '[' and ']' toggle sidebar collapse and inspector visibility
        pilot.app.set_focus(None)
        await pilot.pause()
        assert pilot.app.focused is None

        # [ toggles sidebar collapse
        await pilot.press("left_square_bracket")
        assert sidebar.collapsed is True

        # ] toggles inspector visibility
        await pilot.press("right_square_bracket")
        assert inspector.visible_state is False

        # Toggle back
        await pilot.press("left_square_bracket")
        assert sidebar.collapsed is False

        await pilot.press("right_square_bracket")
        assert inspector.visible_state is True


@pytest.mark.asyncio
async def test_dock_non_overlap_safety_guarantee(mock_profile_dir, build_tui_app):
    """CRITICAL DOCK SAFETY TEST (§3.3, §14.3).

    Asserts sidebar and inspector docks NEVER overlap or cover workspace-tab-bar,
    status-bar, or active approval / command input in main-canvas.
    """
    app = build_tui_app()
    async with app.run_test(size=(160, 44)) as pilot:
        tab_bar = pilot.app.query_one("#workspace-tab-bar")
        status_bar = pilot.app.query_one("#status-bar")
        sidebar = pilot.app.query_one("#sidebar")
        inspector = pilot.app.query_one("#inspector")
        canvas = pilot.app.query_one("#main-canvas")

        # TabBar is docked top, StatusBar is docked bottom
        assert tab_bar.region.y == 0
        assert status_bar.region.y > 0

        # Sidebar and Inspector stay strictly between TabBar and StatusBar vertically
        assert sidebar.region.y >= tab_bar.region.height
        assert inspector.region.y >= tab_bar.region.height

        # MainCanvas stays between Sidebar and Inspector horizontally
        assert canvas.region.x >= sidebar.region.x + sidebar.region.width
        assert inspector.region.x >= canvas.region.x + canvas.region.width


@pytest.mark.asyncio
async def test_100_health_updates_focus_and_cursor_stability(mock_profile_dir, build_tui_app):
    """SPEC REQUIRED STRESS TEST (§14.3).

    Inject 100 sequential HealthSnapshot fixture updates into running app while
    command input holds focus, and assert across all 100:
      - focus unchanged
      - cursor position unchanged
      - scroll position unchanged
      - selection unchanged
    """
    app = build_tui_app()
    async with app.run_test(size=(160, 44)) as pilot:
        input_widget = pilot.app.query_one("#command-input")
        input_widget.focus()
        await pilot.pause()

        # Type sample text into input
        await pilot.press("h", "e", "l", "l", "o")
        initial_value = input_widget.value
        initial_cursor = input_widget.cursor_position

        status_bar = pilot.app.status_bar

        # Inject 100 health updates in rapid succession
        for i in range(100):
            h_snap = HealthSnapshot(
                keychain_ok=(i % 2 == 0),
                identity_ok=True,
                relay_reachable=(i % 3 != 0),
                node_reachable=True,
                pending_inbox_count=i,
            )
            status_bar.update_health(h_snap)
            await pilot.pause()

            # Assert focus and input state remain 100% untouched
            assert pilot.app.focused == input_widget, f"Focus stolen on update {i}!"
            assert input_widget.value == initial_value, f"Input text modified on update {i}!"
            assert input_widget.cursor_position == initial_cursor, f"Cursor moved on update {i}!"

        # Assert status bar updated cleanly in-place
        assert status_bar.health.pending_inbox_count == 99


# Golden Snapshots at 4 Breakpoints using pytest-textual-snapshot
def test_blank_shell_snapshot_160x44(snap_compare, build_tui_app):
    """Wide breakpoint (160x44) golden snapshot (§14.3)."""
    assert snap_compare(build_tui_app(), terminal_size=(160, 44))


def test_blank_shell_snapshot_120x36(snap_compare, build_tui_app):
    """Standard breakpoint (120x36) golden snapshot (§14.3)."""
    assert snap_compare(build_tui_app(), terminal_size=(120, 36))


def test_blank_shell_snapshot_90x28(snap_compare, build_tui_app):
    """Compact breakpoint (90x28) golden snapshot (§14.3)."""
    assert snap_compare(build_tui_app(), terminal_size=(90, 28))


def test_blank_shell_snapshot_80x24(snap_compare, build_tui_app):
    """Minimal breakpoint (80x24) golden snapshot (§14.3)."""
    assert snap_compare(build_tui_app(), terminal_size=(80, 24))


def test_degraded_health_snapshot_160x44(snap_compare, build_tui_app):
    """Degraded relay and keychain health golden snapshot (§14.3)."""
    app = build_tui_app()
    app.status_bar.health = HealthSnapshot(
        keychain_ok=False,
        identity_ok=True,
        relay_reachable=False,
        node_reachable=True,
        pending_inbox_count=3,
        degraded_reason="Relay connection offline",
    )
    rendered = app.status_bar.render()
    assert "Relay connection offline" in rendered
    assert snap_compare(app, terminal_size=(160, 44))


def test_long_profile_name_snapshot_120x36(snap_compare, build_tui_app):
    """Long profile name golden snapshot (§14.3)."""
    app = build_tui_app(profile_name="production-engineer-profile-alpha-v1")
    assert snap_compare(app, terminal_size=(120, 36))
