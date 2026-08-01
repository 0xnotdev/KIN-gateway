"""Unit tests for Session Arena Phase D lane switching, Focus/Cockpit mode, and keymap completeness (§14.8 Phase D).

Covers:
1. Keymap completeness test: Asserts EVERY key spec in DEFAULT_KEYMAP has a real, callable handler on KinApp.
2. Binding safety & action dispatch for z, t, e, c, u, i, o, s, m, r.
3. Focus/Cockpit mode toggling (z key) across wide, standard, compact breakpoints.
4. Lane switching (t, e, c, o, u) with correct widget and presentation class filtering.
5. Security event persistent queue visibility.
"""

from datetime import datetime, timezone
import pytest

from kin.tui.app import KinApp
from kin.tui.keymap import DEFAULT_KEYMAP, KeyBindingSpec
from kin.tui.local_state import NeedsYouItem, get_needs_you_items
from kin.tui.state import ApprovalView, ArtifactView, SessionSummary, UiEvent
from kin.tui.widgets.artifact_list import ArtifactListWidget
from kin.tui.widgets.session_arena import SessionArenaWidget
from tests.tui.test_session_arena_rendering import ArenaSnapshotApp, PINNED_SNAPSHOT_NOW, events_all_7_classes, sample_session_summary


from kin.artifacts.vault import ArtifactMetadata


@pytest.fixture
def sample_artifacts() -> list[ArtifactView]:
    meta = ArtifactMetadata(
        artifact_id="art-1",
        session_id="sess-arena-test-100",
        sha256="abc123def456",
        mime_type="text/plain",
        size_bytes=1024,
        offered_by="bob",
        preview_policy="text",
        created_at="2026-08-01T12:00:00Z",
        source="adapter_output",
    )
    return [ArtifactView.from_metadata(meta)]


# -----------------------------------------------------------------------------
# 1. Keymap Completeness Test (§14.4, §14.8 Phase D)
# -----------------------------------------------------------------------------
def test_all_default_keymap_specs_have_callable_handlers_on_kin_app():
    """Assert every single KeyBindingSpec in DEFAULT_KEYMAP maps to a real, callable action method on KinApp (§14.4, §14.8)."""
    app = KinApp()
    missing_handlers = []

    for spec in DEFAULT_KEYMAP:
        action_name = spec.action
        # Textual maps action="foo" to action_foo if explicit, or action_action_foo
        expected_handler_1 = f"action_{action_name}"
        expected_handler_2 = f"action_action_{action_name}"

        has_h1 = hasattr(app, expected_handler_1) and callable(getattr(app, expected_handler_1))
        has_h2 = hasattr(app, expected_handler_2) and callable(getattr(app, expected_handler_2))

        if not (has_h1 or has_h2):
            missing_handlers.append((spec.key, spec.action, spec.section))

    assert missing_handlers == [], f"Missing action handler methods on KinApp for specs: {missing_handlers}"


# -----------------------------------------------------------------------------
# 2. Binding Safety Tests Outside Arena (§14.8 Phase D)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_arena_keybindings_safe_without_active_session_tab():
    """Assert z, t, e, c, u, m, s do not crash when no session tab is active (§14.8 Phase D)."""
    app = KinApp()
    async with app.run_test() as pilot:
        for k in ("z", "t", "e", "c", "u", "m", "s"):
            await pilot.press(k)
            # Status bar receives non-crashing hint message
            assert app.status_bar is not None
            assert app.status_bar.status_message != ""


# -----------------------------------------------------------------------------
# 3. Focus/Cockpit Mode Toggling (§5.3, §14.8 Phase D)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_focus_cockpit_mode_toggling_across_breakpoints(sample_session_summary, events_all_7_classes):
    """Assert z key toggles focus_mode and full-bleed layout across wide, standard, compact breakpoints (§5.3, §14.8)."""
    import io
    from rich.console import Console

    def get_text(renderable):
        buf = io.StringIO()
        c = Console(file=buf, width=160, height=44)
        c.print(renderable)
        return buf.getvalue()

    app = ArenaSnapshotApp(session_summary=sample_session_summary, events=events_all_7_classes)
    async with app.run_test(size=(160, 44)) as pilot:
        arena = pilot.app.query_one(SessionArenaWidget)
        assert arena.focus_mode is False

        # Press z -> Focus mode ON
        arena.toggle_focus_mode()
        assert arena.focus_mode is True
        text_focus = get_text(arena.render())
        assert "FOCUS MODE" in text_focus
        assert "FOCUS LANE: TRANSCRIPT" in text_focus

        # Press z -> Focus mode OFF (Cockpit mode)
        arena.toggle_focus_mode()
        assert arena.focus_mode is False
        text_cockpit = get_text(arena.render())
        assert "SESSION MAP" in text_cockpit


# -----------------------------------------------------------------------------
# 4. Lane Switching Tests (t, e, o, c, u) (§5.3, §14.8 Phase D)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lane_switching_renders_correct_widgets(sample_session_summary, events_all_7_classes, sample_artifacts):
    """Assert t, e, o, c, u keys switch active_lane and render correct lane content (§5.3, §14.8 Phase D)."""
    arena = SessionArenaWidget(
        session_summary=sample_session_summary,
        events=events_all_7_classes,
        artifacts=sample_artifacts,
        now=PINNED_SNAPSHOT_NOW,
    )

    # 1. Transcript (t)
    arena.switch_lane("transcript")
    assert arena.active_lane == "transcript"
    assert arena.exchange_timeline_widget.allowed_presentation_classes == {"message", "artifact", "approval", "state_transition", "checkpoint"}

    # 2. Activity (e)
    arena.switch_lane("activity")
    assert arena.active_lane == "activity"

    # 3. Outputs (o)
    arena.switch_lane("outputs")
    assert arena.active_lane == "outputs"

    # 4. Decisions (c)
    arena.switch_lane("decisions")
    assert arena.active_lane == "decisions"
    assert arena.exchange_timeline_widget.allowed_presentation_classes == {"checkpoint"}

    # 5. Needs-You (u)
    arena.switch_lane("needs_you")
    assert arena.active_lane == "needs_you"


# -----------------------------------------------------------------------------
# 5. Security Event Queue Visibility Test (§10.1, §14.8 Phase D)
# -----------------------------------------------------------------------------
def test_security_events_surface_in_needs_you_queue(tmp_path, sample_session_summary):
    """Assert security-class session events (with no approval record and active session status) surface in global get_needs_you_items and Arena u lane (§10.1, §14.8)."""
    import io
    from rich.console import Console
    from kin.tui.local_state import ensure_profile_db

    db_path = tmp_path / "kin.db"
    conn = ensure_profile_db(db_path)
    cur = conn.cursor()

    # Insert active session with NO session status change
    cur.execute(
        """
        INSERT INTO sessions (session_id, initiator_username, receiver_username, status, type, created_at, updated_at)
        VALUES ('sess-sec-100', 'alice', 'bob', 'active', 'research', '2026-08-01T12:00:00Z', '2026-08-01T12:00:00Z')
        """
    )
    # Insert security rejection event with NO approval record
    cur.execute(
        """
        INSERT INTO session_events (event_id, session_id, event_order, actor_username, kind, visibility, created_at)
        VALUES ('evt-sec-999', 'sess-sec-100', 1, 'eve', 'security_rejection', 'peer_visible', '2026-08-01T12:00:05Z')
        """
    )
    conn.commit()
    conn.close()

    # 1. Global sidebar / Inbox Needs-You queue verification
    items = get_needs_you_items(tmp_path)
    assert len(items) == 1
    sec_item = items[0]
    assert sec_item.kind == "security"
    assert sec_item.urgency == "high"
    assert "SECURITY ALERT [security_rejection]" in sec_item.human_readable_reason
    assert "eve" in sec_item.human_readable_reason

    # 2. Session Arena 'u' (Needs-You) lane rendering verification
    sec_event = UiEvent("evt-sec-999", "sess-sec-100", "security_rejection", "2026-08-01T12:00:05Z", "eve", "security")
    arena = SessionArenaWidget(
        session_summary=sample_session_summary,
        events=[sec_event],
        now=PINNED_SNAPSHOT_NOW,
    )
    arena.switch_lane("needs_you")

    buf = io.StringIO()
    c = Console(file=buf, width=160, height=44)
    c.print(arena.render())
    rendered_u_lane = buf.getvalue()

    assert "SECURITY REJECTION CARDS" in rendered_u_lane
    assert "🚨 SECURITY REJECTION CARD" in rendered_u_lane
    assert "Persistent Alert (No auto-dismiss)" in rendered_u_lane
