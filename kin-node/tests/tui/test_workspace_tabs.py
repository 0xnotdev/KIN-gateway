"""Unit tests for workspace tab lifecycle, singleton rules, and background stability.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §4.1, §4.2, §14.4
"""

import pytest

from kin.tui.app import KinApp
from kin.tui.workspace import WorkspaceTabManager


@pytest.fixture
def mock_profile_dir(tmp_path, monkeypatch):
    profile_path = tmp_path / ".kin" / "profiles" / "test_profile"
    monkeypatch.setattr("kin.tui.persistence.get_profile_dir", lambda name="default": profile_path)
    monkeypatch.setattr("kin.tui.app.get_profile_dir", lambda name="default": profile_path)
    return profile_path


def test_home_tab_cannot_close():
    """Assert Home tab is always present and Ctrl+W on Home is a no-op (§4.1)."""
    mgr = WorkspaceTabManager()
    assert mgr.tabs[0].kind == "home"
    assert not mgr.tabs[0].closeable

    ok, msg = mgr.close_tab("home")
    assert not ok
    assert "Home tab cannot be closed" in msg
    assert len(mgr.tabs) == 1
    assert mgr.active_tab_id == "home"


def test_singleton_tab_rules():
    """Assert Agents, Network, and Inbox tabs are singletons (§4.1)."""
    mgr = WorkspaceTabManager()

    # Open Agents first time
    ok1, msg1 = mgr.open_tab("agents", "Agents", "agents", singleton=True)
    assert ok1
    assert len(mgr.tabs) == 2
    assert mgr.active_tab_id == "agents"

    # Open Agents second time -> focuses existing tab without duplicating
    ok2, msg2 = mgr.open_tab("agents", "Agents", "agents", singleton=True)
    assert ok2
    assert "Focused existing singleton" in msg2
    assert len(mgr.tabs) == 2
    assert mgr.active_tab_id == "agents"


def test_dispatch_dirty_draft_warning():
    """Assert Dispatch is a single reusable draft tab that warns when dirty (§4.1)."""
    mgr = WorkspaceTabManager()

    # Open Dispatch
    ok1, msg1 = mgr.open_tab("dispatch:draft", "Dispatch", "dispatch")
    assert ok1

    # Mark dispatch draft dirty
    dispatch_tab = mgr.get_tab("dispatch:draft")
    dispatch_tab.dirty = True

    # Attempt to open second dispatch tab -> warns unsaved changes
    ok2, msg2 = mgr.open_tab("dispatch:new", "Dispatch New", "dispatch")
    assert not ok2
    assert "Unsaved changes in active Dispatch draft" in msg2

    # Attempt to close dirty tab without force -> warns unsaved changes
    ok3, msg3 = mgr.close_tab("dispatch:draft")
    assert not ok3
    assert "unsaved draft changes" in msg3


def test_close_and_reopen_last_tab():
    """Assert closing closeable tab and Ctrl+Shift+T reopens last closed tab (§4.2)."""
    mgr = WorkspaceTabManager()
    mgr.open_tab("session:s1", "Session S1", "session")
    mgr.open_tab("session:s2", "Session S2", "session")
    assert len(mgr.tabs) == 3

    # Close S2
    ok_close, _ = mgr.close_tab("session:s2")
    assert ok_close
    assert len(mgr.tabs) == 2
    assert mgr.active_tab_id == "session:s1"

    # Reopen last tab (Ctrl+Shift+T)
    ok_reopen, msg_reopen = mgr.reopen_last_tab()
    assert ok_reopen
    assert "Reopened tab 'Session S2'" in msg_reopen
    assert len(mgr.tabs) == 3
    assert mgr.active_tab_id == "session:s2"


def test_tab_stable_ordering_and_background_events():
    """Assert background event update updates tab badge in-place without reordering or stealing focus (§4.2)."""
    mgr = WorkspaceTabManager()
    mgr.open_tab("session:s1", "Session S1", "session")
    mgr.open_tab("inbox", "Inbox", "inbox", singleton=True)

    mgr.active_tab_id = "session:s1"
    initial_tab_order = [t.tab_id for t in mgr.tabs]

    # Background fixture event updates inbox badge
    updated = mgr.update_tab_badge("inbox", "3")
    assert updated

    # Assert tabs order is 100% unchanged and active focus is untouched
    assert [t.tab_id for t in mgr.tabs] == initial_tab_order
    assert mgr.active_tab_id == "session:s1"
    assert mgr.get_tab("inbox").badge == "3"


@pytest.mark.asyncio
async def test_alt_number_tab_jumping_and_cycling(mock_profile_dir):
    """Assert Alt+1..9 jumps to visible tabs and Ctrl+Tab / Ctrl+Shift+Tab cycles (§4.2)."""
    app = KinApp()
    async with app.run_test(size=(160, 44)) as pilot:
        tm = pilot.app.tab_manager
        tm.open_tab("agents", "Agents", "agents", singleton=True)
        tm.open_tab("network", "Network", "network", singleton=True)
        pilot.app.sync_tab_bar()

        # Cycle tab forward (Ctrl+Tab)
        await pilot.press("ctrl+tab")
        assert tm.active_tab_id == "home"

        # Jump to Tab 2 (Alt+2) -> Agents
        await pilot.press("alt+2")
        assert tm.active_tab_id == "agents"

        # Jump to Tab 1 (Alt+1) -> Home
        await pilot.press("alt+1")
        assert tm.active_tab_id == "home"
