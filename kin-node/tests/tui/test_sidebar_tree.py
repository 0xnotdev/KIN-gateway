"""Unit tests for sidebar tree navigation, section collapse persistence, and sticky selection.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §4.3, §14.4
"""

import pytest

from kin.tui.app import KinApp
from kin.tui.persistence import UiStatePreferences, load_ui_preferences, save_ui_preferences
from kin.tui.shell import Sidebar, SidebarNode
from kin.tui.widgets import WidgetLifecycleState


@pytest.fixture
def mock_profile_dir(tmp_path, monkeypatch):
    profile_path = tmp_path / ".kin" / "profiles" / "test_profile"
    monkeypatch.setattr("kin.tui.persistence.get_profile_dir", lambda name="default": profile_path)
    monkeypatch.setattr("kin.tui.app.get_profile_dir", lambda name="default": profile_path)
    return profile_path


def test_sidebar_keyboard_navigation_and_collapse():
    """Assert j/k moves selection, h/l collapses sections, space previews (§4.3)."""
    sidebar = Sidebar()

    # Initial selected node is Home (index 1)
    sel1 = sidebar.get_selected_node()
    assert sel1.node_id == "space_home"

    # j moves down to Inbox
    sel2 = sidebar.move_selection(+1)
    assert sel2.node_id == "space_inbox"

    # k moves up to Home
    sel3 = sidebar.move_selection(-1)
    assert sel3.node_id == "space_home"

    # Move to top section (SPACES) and collapse with h
    sidebar.move_to_boundary(first=True)
    sel_sec = sidebar.get_selected_node()
    assert sel_sec.kind == "section"

    is_collapsed = sidebar.toggle_section_collapse("SPACES")
    assert is_collapsed
    assert "SPACES" in sidebar.section_collapse
    assert sidebar.section_collapse["SPACES"] is True


def test_section_collapse_persistence(mock_profile_dir):
    """Assert section collapse state persists to ui-state.json and reloads cleanly (§4.3)."""
    prefs = UiStatePreferences(sidebar_section_collapse={"SPACES": True, "AGENTS": False})
    save_ui_preferences(prefs)

    loaded, status_msg = load_ui_preferences()
    assert status_msg is None
    assert loaded.sidebar_section_collapse == {"SPACES": True, "AGENTS": False}


def test_disappearing_row_sticky_selection_fallback():
    """SPEC REQUIRED TEST (§4.3, §14.4).

    Assert when selected row disappears, selection moves to nearest sibling and surfaces status message.
    """
    sidebar = Sidebar()
    # Select Inbox (index 2 in visible nodes)
    sidebar.move_selection(+1)
    assert sidebar.get_selected_node().node_id == "space_inbox"

    # Remove Inbox node (simulating disappearing row)
    ok, msg = sidebar.remove_node("space_inbox")
    assert ok
    assert "Selection moved to nearest sibling" in msg

    # Assert selection moved to nearest sibling (Recent Sessions or Home)
    new_sel = sidebar.get_selected_node()
    assert new_sel is not None
    assert new_sel.node_id != "space_inbox"
    assert new_sel.node_id in ("space_home", "space_recents")


@pytest.mark.asyncio
async def test_space_key_previews_in_inspector(mock_profile_dir):
    """Assert Space key previews selected sidebar item in Inspector (§4.3)."""
    app = KinApp()
    async with app.run_test(size=(160, 44)) as pilot:
        pilot.app.set_focus(None)
        await pilot.press("space")
        assert pilot.app.inspector.preview_title.startswith("INSPECTOR:")


@pytest.mark.asyncio
async def test_sidebar_search_field_interactive_filtering(mock_profile_dir):
    """SPEC REQUIRED TEST (§14.5).

    Assert SearchField accepts real interactive character entry via pilot.press() character-by-character
    in a mounted KinApp and narrows visible nodes. Zero direct set_query() or action_action_focus_filter() calls.
    """
    app = KinApp()
    async with app.run_test(size=(160, 44)) as pilot:
        initial_count = len(pilot.app.sidebar.get_visible_nodes())
        assert initial_count >= 5

        # Unfocus command input so non-priority slash shortcut is dispatched (§5.1)
        pilot.app.set_focus(None)

        # Press '/' key to focus SearchFieldWidget via app keymap handler
        await pilot.press("slash")

        # Type character-by-character into mounted SearchFieldWidget via pilot.press()
        await pilot.press("i", "n", "b", "o", "x")

        # Assert query was typed character-by-character into SearchFieldWidget
        assert pilot.app.sidebar.search_field.query == "inbox"

        # Assert real narrowing
        vis_narrow = pilot.app.sidebar.get_visible_nodes()
        assert len(vis_narrow) < initial_count
        assert any(n.node_id == "space_inbox" for n in vis_narrow)

        # Clear query via Escape keypress
        await pilot.press("escape")
        assert pilot.app.sidebar.search_field.query == ""
        assert len(pilot.app.sidebar.get_visible_nodes()) == initial_count
