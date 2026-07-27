"""Unit tests for consequential action confirmation gate and Esc priority chain.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.3, §14.4
"""

import pytest

from kin.tui.app import KinApp
from kin.tui.shell import ConfirmationModal


@pytest.fixture
def mock_profile_dir(tmp_path, monkeypatch):
    profile_path = tmp_path / ".kin" / "profiles" / "test_profile"
    monkeypatch.setattr("kin.tui.persistence.get_profile_dir", lambda name="default": profile_path)
    monkeypatch.setattr("kin.tui.app.get_profile_dir", lambda name="default": profile_path)
    return profile_path


@pytest.mark.asyncio
async def test_no_single_key_executes_consequential_action(mock_profile_dir):
    """SPEC REQUIRED ARCHITECTURAL GATE TEST (§5.3, §14.4).

    Assert pressing 'x' (cancel/archive) opens ConfirmationModal stub and takes NO
    effect when user declines ('n').
    """
    app = KinApp()
    async with app.run_test(size=(160, 44)) as pilot:
        pilot.app.set_focus(None)
        await pilot.pause()

        # Press 'x' to trigger cancel/archive action
        await pilot.press("x")
        await pilot.pause()

        # Assert confirmation modal is open
        assert len(pilot.app.screen_stack) > 1
        modal = pilot.app.screen
        assert isinstance(modal, ConfirmationModal)

        # Pressing 'n' cancels without taking effect
        await pilot.press("n")
        await pilot.pause()
        assert len(pilot.app.screen_stack) == 1
        assert "Cancelled" in pilot.app.status_bar.render()


@pytest.mark.asyncio
async def test_consequential_action_confirm_path_executes_action(mock_profile_dir):
    """SPEC REQUIRED CONFIRMATION PATH TEST (§5.3, §14.4).

    Assert pressing 'x' and confirming via 'y' fires the underlying action callback
    and updates the status bar cleanly.
    """
    app = KinApp()
    action_fired = False

    def on_confirm_callback():
        nonlocal action_fired
        action_fired = True

    async with app.run_test(size=(160, 44)) as pilot:
        pilot.app.set_focus(None)
        await pilot.pause()

        # Trigger consequential action gate with callback
        pilot.app.gate_consequential_action("Cancel / Archive", "Home Workspace", on_confirm=on_confirm_callback)
        await pilot.pause()

        # Assert confirmation modal is open
        assert len(pilot.app.screen_stack) > 1
        modal = pilot.app.screen
        assert isinstance(modal, ConfirmationModal)

        # Press 'y' to confirm
        await pilot.press("y")
        await pilot.pause()

        # Assert modal is closed, callback fired, and status bar updated
        assert len(pilot.app.screen_stack) == 1
        assert action_fired is True, "Underlying action callback failed to fire on confirm!"
        assert "Confirmed and executed" in pilot.app.status_bar.render()


@pytest.mark.asyncio
async def test_esc_priority_chain_exhaustive(mock_profile_dir):
    """EXHAUSTIVE 3-STAGE ESC PRIORITY CHAIN TEST (§4, §14.4).

    Stage 1: Clear active search/filter if present.
    Stage 2: Close open modal/overlay if active.
    Stage 3: Return focus to main canvas input.
    """
    app = KinApp()
    async with app.run_test(size=(160, 44)) as pilot:
        # Combined setup: BOTH active filter query AND open modal overlay active simultaneously
        pilot.app.sidebar.filter_query = "scout"
        pilot.app.sidebar.refresh()

        # Open help modal screen with focus cleared
        pilot.app.set_focus(None)
        await pilot.press("question_mark")
        assert len(pilot.app.screen_stack) > 1
        assert pilot.app.sidebar.filter_query == "scout", "Filter query should remain active when modal opens."

        # Press Escape #1 -> Stage 1: clears active filter query FIRST while modal screen remains OPEN
        await pilot.press("escape")
        assert pilot.app.sidebar.filter_query == ""
        assert len(pilot.app.screen_stack) > 1, "Screen closed prematurely during Stage 1!"

        # Press Escape #2 -> Stage 2: closes open modal screen
        await pilot.press("escape")
        assert len(pilot.app.screen_stack) == 1

        # Press Escape #3 -> Stage 3: returns focus to main canvas input
        pilot.app.set_focus(None)
        await pilot.press("escape")
        assert pilot.app.focused == pilot.app.query_one("#command-input")
