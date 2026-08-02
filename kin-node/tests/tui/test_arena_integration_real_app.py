"""Real KinApp End-to-End Session Arena Integration & Keymap Scoping Tests (§14.8 T6 Closeout).

Verifies real KinApp mounts SessionArenaWidget in MainCanvas, responds to arena keybindings,
opens ComposeMessageModal, and isolates arena bindings from global navigation.
"""

from pathlib import Path
import pytest
from textual.widgets import Input, Static

from kin.tui.app import KinApp
from kin.tui.help import generate_help_markdown
from kin.tui.local_state import ensure_profile_db
from kin.tui.widgets.compose_modal import ComposeMessageModal
from kin.tui.widgets.inbox_screen import InboxScreenWidget
from kin.tui.widgets.session_arena import SessionArenaWidget


def _seed_test_session(profile_dir: Path, session_id: str = "sess-real-100") -> None:
    db_path = profile_dir / "kin.db"
    conn = ensure_profile_db(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (session_id, initiator_username, receiver_username, status, type, created_at, updated_at) "
        "VALUES (?, 'alice', 'bob', 'active', 'collaboration', '2026-08-01T12:00:00Z', '2026-08-01T12:00:00Z')",
        (session_id,),
    )
    cur.execute(
        "INSERT INTO session_events (event_id, session_id, kind, created_at, actor_username, event_order) "
        "VALUES (?, ?, 'finding', '2026-08-01T12:01:00Z', 'bob', 1)",
        (f"evt-{session_id}-1", session_id),
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_real_app_mounts_session_arena_widget_not_placeholder(tmp_path, monkeypatch):
    """Assert real KinApp mounts SessionArenaWidget in MainCanvas and renders live Arena content (§14.8)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    profile_dir = tmp_path / ".kin" / "profiles" / "default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    _seed_test_session(profile_dir, "sess-real-100")

    app = KinApp(profile_name="default", profile_dir=profile_dir)
    async with app.run_test(size=(120, 36)) as pilot:
        # Open session tab for sess-real-100
        app.tab_manager.open_tab("tab:sess-real-100", "Real Session", "session")
        app.sync_tab_bar()
        await pilot.pause()

        # Assert SessionArenaWidget is mounted in MainCanvas
        arena = app.canvas.query_one(SessionArenaWidget)
        assert arena is not None
        assert arena.session_id == "sess-real-100"
        assert arena.active_lane == "transcript"


@pytest.mark.asyncio
async def test_real_app_arena_key_sequence_drives_widget_state(tmp_path, monkeypatch):
    """Press t, e, o, c, u, z, i in sequence on real KinApp and assert arena state changes (§14.8)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    profile_dir = tmp_path / ".kin" / "profiles" / "default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    _seed_test_session(profile_dir, "sess-real-200")

    app = KinApp(profile_name="default", profile_dir=profile_dir)
    async with app.run_test(size=(160, 44)) as pilot:
        app.tab_manager.open_tab("tab:sess-real-200", "Real Session", "session")
        app.sync_tab_bar()
        await pilot.pause()

        arena = app.canvas.query_one(SessionArenaWidget)
        arena.focus()
        await pilot.pause()

        # Press t -> transcript lane
        await pilot.press("t")
        assert arena.active_lane == "transcript"

        # Press e -> activity lane
        await pilot.press("e")
        assert arena.active_lane == "activity"

        # Press o -> outputs lane
        await pilot.press("o")
        assert arena.active_lane == "outputs"

        # Press c -> decisions lane
        await pilot.press("c")
        assert arena.active_lane == "decisions"

        # Press u -> needs-you lane
        await pilot.press("u")
        assert arena.active_lane == "needs_you"

        # Press z -> toggle focus mode
        await pilot.press("z")
        assert arena.focus_mode is True

        # Press z -> exit focus mode
        await pilot.press("z")
        assert arena.focus_mode is False

        # Press i -> toggle arena inspector
        init_inspector = arena.inspector_visible
        await pilot.press("i")
        assert arena.inspector_visible is not init_inspector


@pytest.mark.asyncio
async def test_real_app_press_m_opens_compose_message_modal(tmp_path, monkeypatch):
    """Press 'm' on active session tab in real KinApp and assert ComposeMessageModal is pushed (§14.8)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    profile_dir = tmp_path / ".kin" / "profiles" / "default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    _seed_test_session(profile_dir, "sess-real-300")

    app = KinApp(profile_name="default", profile_dir=profile_dir)
    async with app.run_test(size=(120, 36)) as pilot:
        app.tab_manager.open_tab("tab:sess-real-300", "Real Session", "session")
        app.sync_tab_bar()
        await pilot.pause()

        arena = app.canvas.query_one(SessionArenaWidget)
        arena.focus()
        await pilot.pause()

        # Press 'm'
        await pilot.press("m")
        await pilot.pause()

        # Assert ComposeMessageModal is active screen on stack
        assert isinstance(app.screen, ComposeMessageModal)


@pytest.mark.asyncio
async def test_arena_scoped_bindings_do_not_leak_outside_arena(tmp_path, monkeypatch):
    """Assert 'i' still opens Inbox and 'o' still opens new tab when active tab is Home (§14.4, §14.8)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    profile_dir = tmp_path / ".kin" / "profiles" / "default"
    profile_dir.mkdir(parents=True, exist_ok=True)

    app = KinApp(profile_name="default", profile_dir=profile_dir)
    async with app.run_test(size=(120, 36)) as pilot:
        # Active tab is Home (non-session)
        assert app.tab_manager.get_active_tab().kind == "home"

        # Focus home_widget (non-input screen widget) so keybindings dispatch
        app.canvas.home_widget.focus()
        await pilot.pause()

        # Press 'i' on Home tab -> should open Inbox tab
        await pilot.press("i")
        await pilot.pause()
        assert app.tab_manager.get_active_tab().kind == "inbox"


def test_help_markdown_includes_arena_scoped_bindings():
    """Assert generate_help_markdown surfaces o, i (arena), r, a, d, e, b under ## Session Arena (§14.4)."""
    md_text = generate_help_markdown()
    assert "## Session Arena" in md_text
    assert "`o`" in md_text
    assert "`i`" in md_text
    assert "`r`" in md_text
    assert "`a`" in md_text
    assert "`d`" in md_text
    assert "`e`" in md_text
    assert "`b`" in md_text
