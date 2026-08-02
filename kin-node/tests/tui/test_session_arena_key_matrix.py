"""Full key matrix and lane-dependent action dispatch tests for SessionArenaWidget (§14.9 Phase E)."""

import pytest
from kin.tui.widgets.session_arena import SessionArenaWidget


def test_session_arena_full_key_matrix():
    """Assert key 'a' delegates to handle_approval_key in needs_you lane and handle_artifact_key in outputs lane."""
    arena = SessionArenaWidget(session_id="test-key-matrix-sess")

    approval_calls = []
    artifact_calls = []

    arena.handle_approval_key = lambda key: approval_calls.append(key)
    arena.handle_artifact_key = lambda key: artifact_calls.append(key)

    # 1. Needs-You Lane
    arena.active_lane = "needs_you"
    arena.action_approve_item()
    assert approval_calls == ["a"]
    assert artifact_calls == []

    # 2. Outputs Lane
    arena.active_lane = "outputs"
    arena.action_approve_item()
    assert approval_calls == ["a"]
    assert artifact_calls == ["a"]

    # 3. Import artifact action 'v'
    arena.action_import_artifact()
    assert artifact_calls == ["a", "v"]


def test_session_arena_lane_switching_matrix():
    """Assert lane switching actions update active_lane cleanly."""
    arena = SessionArenaWidget(session_id="test-lane-switch-sess")

    arena.switch_lane("transcript")
    assert arena.active_lane == "transcript"

    arena.switch_lane("outputs")
    assert arena.active_lane == "outputs"

    arena.switch_lane("needs_you")
    assert arena.active_lane == "needs_you"

    arena.switch_lane("activity")
    assert arena.active_lane == "activity"

    arena.switch_lane("decisions")
    assert arena.active_lane == "decisions"
