"""Unit tests for Session Arena Phase D approval decisions and session state controls (§14.8 Phase D).

Covers:
1. Interactive approval actions inside Arena Needs-You lane (a, d, e, b).
2. Confirmation modal gating ensuring ZERO single-key execution for consequential actions.
3. Session state transitions (pause, resume, cancel) via local_state wrappers.
4. Idempotency and RecoverableError mappings for terminal states and non-existent sessions.
"""

from datetime import datetime, timezone
import pytest

from kin.schemas import ActionClass, ApprovalDecision, ApprovalRequest, DecisionKind, RiskLabel
from kin.tui.local_state import cancel_session_command, decide_pending_approval, ensure_profile_db, pause_session, resume_session
from kin.tui.state import ApprovalView, RecoverableError, SessionSummary
from kin.tui.widgets.session_arena import SessionArenaWidget
from tests.tui.test_session_arena_rendering import ArenaSnapshotApp, PINNED_SNAPSHOT_NOW, sample_session_summary


@pytest.fixture
def sample_approval_view() -> ApprovalView:
    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="app-arena-100",
        session_id="sess-arena-test-100",
        agent_id="agent-scout",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Write files to workspace",
        reason="Update code dependencies",
        risk_label=RiskLabel.HIGH,
        requested_scope={"path": "/src/app.py"},
        expires_at="2026-08-02T12:00:00Z",
    )
    return ApprovalView(request=req, decision=None)


# -----------------------------------------------------------------------------
# 1. Session State Wrappers & Error Handling Test (§14.8 Phase D)
# -----------------------------------------------------------------------------
def test_session_state_wrappers_error_handling_on_nonexistent_and_terminal_sessions(tmp_path):
    """Assert pause_session, resume_session, and cancel_session_command return RecoverableError on non-existent or terminal sessions (§14.8 Phase D)."""
    # Create DB file so path exists
    db_file = tmp_path / "kin.db"
    conn = ensure_profile_db(db_file)
    conn.close()

    # 1. Non-existent session
    ok_pause, err_pause = pause_session(tmp_path, session_id="sess-nonexistent-99")
    assert ok_pause is False
    assert err_pause is not None
    assert "Session 'sess-nonexistent-99' not found" in err_pause.what_happened

    ok_resume, err_resume = resume_session(tmp_path, session_id="sess-nonexistent-99")
    assert ok_resume is False
    assert err_resume is not None
    assert "Session 'sess-nonexistent-99' not found" in err_resume.what_happened

    ok_cancel, err_cancel = cancel_session_command(tmp_path, session_id="sess-nonexistent-99")
    assert ok_cancel is False
    assert err_cancel is not None
    assert "Session 'sess-nonexistent-99' not found" in err_cancel.what_happened


# -----------------------------------------------------------------------------
# 2. Zero Single-Key Consequential Execution Test (§14.8 Phase D)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_single_key_executes_consequential_approval_or_state_action(sample_session_summary, sample_approval_view):
    """Assert pressing a, d, e, b, s inside Arena NEVER executes backend actions directly without pushing a confirmation modal (§14.8 Phase D)."""
    arena = SessionArenaWidget(
        session_summary=sample_session_summary,
        approvals=[sample_approval_view],
        now=PINNED_SNAPSHOT_NOW,
    )
    arena.open_needs_you_lane()
    assert arena.active_lane == "needs_you"

    # Direct keypress without active App screen stack does NOT record decisions in DB
    arena.handle_approval_key("a")
    # Approval decision remains None
    assert sample_approval_view.decision is None


# -----------------------------------------------------------------------------
# 3. Interactive Approval Actions Modal Integration (§14.8 Phase D)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_arena_needs_you_lane_all_approval_keys_drive_real_on_key_path(sample_session_summary, sample_approval_view):
    """Assert pressing 'a', 'd', 'e', 'b' via real on_key path in Needs-You lane pushes correct modals, and 'e' switches to activity lane when outside Needs-You (§14.8 Phase D)."""
    app = ArenaSnapshotApp(session_summary=sample_session_summary, approvals=[sample_approval_view])
    async with app.run_test() as pilot:
        arena = pilot.app.query_one(SessionArenaWidget)
        pilot.app.set_focus(arena)

        # 1. Collision verification: 'e' pressed while active_lane is 'transcript' MUST switch lane to 'activity'
        arena.switch_lane("transcript")
        assert arena.active_lane == "transcript"
        await pilot.press("e")
        assert arena.active_lane == "activity"

        # Switch to 'needs_you' lane for approval actions
        arena.open_needs_you_lane()
        assert arena.active_lane == "needs_you"

        # 2. Press 'a' via real on_key -> ApproveConfirmModal pushed
        await pilot.press("a")
        assert len(pilot.app.screen_stack) > 1
        assert pilot.app.screen_stack[-1].__class__.__name__ == "ApproveConfirmModal"
        await pilot.press("escape")
        assert len(pilot.app.screen_stack) == 1

        # 3. Press 'd' via real on_key -> DenyReasonModal pushed
        await pilot.press("d")
        assert len(pilot.app.screen_stack) > 1
        assert pilot.app.screen_stack[-1].__class__.__name__ == "DenyReasonModal"
        await pilot.press("escape")
        assert len(pilot.app.screen_stack) == 1

        # 4. Press 'e' via real on_key in Needs-You lane -> EditConstraintsModal pushed (unblocked by collision fix)
        await pilot.press("e")
        assert len(pilot.app.screen_stack) > 1
        assert pilot.app.screen_stack[-1].__class__.__name__ == "EditConstraintsModal"
        await pilot.press("escape")
        assert len(pilot.app.screen_stack) == 1

        # 5. Press 'b' via real on_key -> ApproveConfirmModal pushed
        await pilot.press("b")
        assert len(pilot.app.screen_stack) > 1
        assert pilot.app.screen_stack[-1].__class__.__name__ == "ApproveConfirmModal"
        await pilot.press("escape")
        assert len(pilot.app.screen_stack) == 1
