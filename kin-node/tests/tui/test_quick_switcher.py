"""Unit tests for Quick Switcher (Ctrl+P) navigation and fuzzy lookup.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.1, §5.4, §14.4
"""

import pytest

from kin.tui.app import KinApp
from kin.tui.palette import QuickSwitcherModal


@pytest.fixture
def mock_profile_dir(tmp_path, monkeypatch):
    profile_path = tmp_path / ".kin" / "profiles" / "test_profile"
    monkeypatch.setattr("kin.tui.persistence.get_profile_dir", lambda name="default": profile_path)
    monkeypatch.setattr("kin.tui.app.get_profile_dir", lambda name="default": profile_path)
    return profile_path


@pytest.mark.asyncio
async def test_quick_switcher_keyboard_navigation_and_filtering(mock_profile_dir):
    """Assert Ctrl+P opens Quick Switcher modal overlay and filters candidates (§5.1)."""
    app = KinApp()
    async with app.run_test(size=(160, 44)) as pilot:
        # Press Ctrl+P to launch Quick Switcher
        await pilot.press("ctrl+p")
        assert len(pilot.app.screen_stack) > 1
        switcher = pilot.app.screen
        assert isinstance(switcher, QuickSwitcherModal)

        # Type filter query 'home'
        await pilot.press("h", "o", "m", "e")
        assert len(switcher.filtered_items) >= 1
        assert switcher.filtered_items[0][0] == "tab_home"

        # Press Enter to select
        await pilot.press("enter")
        assert len(pilot.app.screen_stack) == 1
