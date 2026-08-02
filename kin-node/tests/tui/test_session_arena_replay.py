"""Unit and integration tests for Session Arena Replay Timeline Scrubber (§14.8 Step 5)."""

import pytest
from kin.tui.state import UiEvent
from kin.tui.widgets.session_arena import SessionArenaWidget


@pytest.fixture
def sample_events() -> list[UiEvent]:
    return [
        UiEvent("e-1", "sess-rep-1", "task_request", "2026-08-01T12:00:00Z", "alice", "message"),
        UiEvent("e-2", "sess-rep-1", "finding", "2026-08-01T12:00:05Z", "bob", "activity"),
        UiEvent("e-3", "sess-rep-1", "finding", "2026-08-01T12:00:10Z", "bob", "activity"),
        UiEvent("e-4", "sess-rep-1", "final_result", "2026-08-01T12:00:15Z", "bob", "state_transition"),
    ]


@pytest.fixture
def dummy_summary():
    from kin.tui.state import SessionSummary
    return SessionSummary(
        session_id="sess-rep-1",
        status="active",
        type="research",
        initiator_username="alice",
        receiver_username="bob",
        objective="Replay test",
        turn_limit=12,
        created_at="2026-08-01T12:00:00Z",
        updated_at="2026-08-01T12:00:00Z",
    )


@pytest.mark.asyncio
async def test_replay_mode_keyboard_toggle_and_event_slicing(sample_events, dummy_summary):
    """Assert pressing 'r' toggles read-only replay mode, slices timeline, and 'G' returns to live tail (§14.8 Step 5)."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield SessionArenaWidget(session_id="sess-rep-1", session_summary=dummy_summary, events=sample_events)

    app = TestApp()
    async with app.run_test() as pilot:
        arena = pilot.app.query_one(SessionArenaWidget)
        assert arena.is_replay_mode is False
        assert len(arena.events) == 4
        assert len(arena.exchange_timeline_widget.events) == 4

        # 1. Select second event and press 'r' to enter replay mode
        arena.exchange_timeline_widget.selected_index = 1
        await pilot.press("r")
        await pilot.pause()

        assert arena.is_replay_mode is True
        assert arena.replay_index == 1
        # Timeline view is sliced to first 2 events
        assert len(arena.exchange_timeline_widget.events) == 2
        assert arena.exchange_timeline_widget.events[-1].event_id == "e-2"
        # Master list remains complete
        assert len(arena.events) == 4

        # 2. Press 'G' to exit replay mode and return to live tail-follow
        await pilot.press("G")
        await pilot.pause()

        assert arena.is_replay_mode is False
        assert arena.replay_index is None
        assert len(arena.exchange_timeline_widget.events) == 4


@pytest.mark.asyncio
async def test_live_polling_background_appends_without_disturbing_active_replay(sample_events, dummy_summary):
    """Assert background polling appends to master events without mutating active replay view (§14.8 Step 5)."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield SessionArenaWidget(session_id="sess-rep-1", session_summary=dummy_summary, events=sample_events)

    app = TestApp()
    async with app.run_test() as pilot:
        arena = pilot.app.query_one(SessionArenaWidget)

        # Enter replay mode at index 0
        arena.enter_replay_mode(target_index=0)
        assert arena.is_replay_mode is True
        assert len(arena.exchange_timeline_widget.events) == 1

        # Simulate background polling worker appending 2 new live events
        new_events = [
            UiEvent("e-5", "sess-rep-1", "finding", "2026-08-01T12:00:20Z", "bob", "activity"),
            UiEvent("e-6", "sess-rep-1", "finding", "2026-08-01T12:00:25Z", "bob", "activity"),
        ]
        arena.append_events(new_events)

        # Master list grew to 6 events, but active replay view remains sliced to 1 event
        assert len(arena.events) == 6
        assert len(arena.exchange_timeline_widget.events) == 1

        # Exit replay mode
        arena.exit_replay_mode()
        assert arena.is_replay_mode is False
        assert len(arena.exchange_timeline_widget.events) == 6
