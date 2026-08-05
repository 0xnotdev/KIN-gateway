"""T8 Phase B: real-node restart with Arena polling and reopen recovery."""

from __future__ import annotations

import keyring
import pytest

from kin.testing.insecure_memory_keyring import InMemoryTestKeyring
from kin.tui.widgets.session_arena import SessionArenaWidget
from scripts.smoke_two_node_harness import TwoNodeSmokeHarness


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_sigterm_restart_arena_polling_reopens_without_gap_or_duplicate(
    build_tui_app, monkeypatch
) -> None:
    harness = TwoNodeSmokeHarness()
    try:
        harness.start()
        dispatch = harness.run_worker(
            "alice",
            "dispatch",
            "--peer",
            "bob",
            "--sender-agent",
            "alice_agent",
            "--receiver-agent",
            "bob_agent",
            "--goal",
            "Keep the live Arena exact across a real Alice node crash",
        )
        session_id = str(dispatch["session_id"])
        harness.run_worker(
            "bob",
            "respond",
            "--session",
            session_id,
            "--decision",
            "accept",
            "--agent",
            "bob_agent",
            "--text",
            "Accepted before Alice crashes",
        )
        harness.run_worker(
            "alice",
            "message",
            "--session",
            session_id,
            "--kind",
            "question",
            "--actor-agent",
            "alice_agent",
            "--text",
            "Will the reopened Arena preserve this event?",
        )
        before_crash = harness.run_worker("alice", "inspect", "--session", session_id)
        assert before_crash["status"] == "active"
        assert before_crash["event_count"] == 3

        sigterm_returncode = harness.stop_node("alice", crash=True)
        harness.restart_node("alice")
        reconstructed = harness.run_worker("alice", "reconstruct", "--session", session_id)
        assert reconstructed["found"] is True
        assert reconstructed["status"] == "active"
        assert reconstructed["event_count"] == 3

        monkeypatch.setenv("HOME", str(harness.alice_home))
        monkeypatch.setenv("USERPROFILE", str(harness.alice_home))
        monkeypatch.setenv("KIN_UNSAFE_TEST_KEYRING", "1")
        monkeypatch.setenv("KIN_TEST_KEYRING_PATH", str(harness.alice_home / "keyring.json"))
        keyring.set_keyring(InMemoryTestKeyring())
        app = build_tui_app(profile_name="alice", profile_dir=harness.alice_profile_dir)

        async with app.run_test(size=(120, 36)) as pilot:
            app.tab_manager.open_tab(f"tab:{session_id}", "Restart resilience", "session")
            app.sync_tab_bar()
            await pilot.pause(0.5)

            arena = app.canvas.query_one(SessionArenaWidget)
            assert arena.is_mounted is True
            assert arena.is_polling_active is True
            initial_session_events = [
                event for event in arena.events if event.event_id in set(before_crash["event_ids"])
            ]
            assert [event.kind for event in initial_session_events] == [
                "task_request",
                "acceptance",
                "question",
            ]

            harness.run_worker(
                "bob",
                "message",
                "--session",
                session_id,
                "--kind",
                "answer",
                "--actor-agent",
                "bob_agent",
                "--text",
                "The remounted worker will deduplicate by event ID.",
            )
            after_answer = harness.run_worker("alice", "inspect", "--session", session_id)
            for _ in range(30):
                visible_session_ids = {
                    event.event_id for event in arena.events if event.event_id in set(after_answer["event_ids"])
                }
                if visible_session_ids == set(after_answer["event_ids"]):
                    break
                await pilot.pause(0.1)
            assert [
                event.event_id for event in arena.events if event.event_id in set(after_answer["event_ids"])
            ] == after_answer["event_ids"]
            assert len({event.event_id for event in arena.events}) == len(arena.events)
            arena_ids_before_close = [event.event_id for event in arena.events]

            app.action_close_tab()
            await app.canvas.recompose()
            await pilot.pause(0.2)
            assert app.tab_manager.active_tab_id == "home"
            assert list(app.canvas.query(SessionArenaWidget)) == []
            assert arena.is_polling_active is False

            app.action_reopen_tab()
            await app.canvas.recompose()
            await pilot.pause(0.2)
            assert app.tab_manager.active_tab_id == f"tab:{session_id}"
            reopened = app.canvas.query_one(SessionArenaWidget)
            assert reopened.is_mounted is True
            assert reopened.is_polling_active is True
            assert [event.event_id for event in reopened.events] == arena_ids_before_close
            assert len({event.event_id for event in reopened.events}) == len(reopened.events)

            harness.run_worker(
                "bob",
                "message",
                "--session",
                session_id,
                "--kind",
                "final_result",
                "--actor-agent",
                "bob_agent",
                "--text",
                "Arena restart and reopen proof completed.",
            )
            persisted = harness.run_worker("alice", "inspect", "--session", session_id)
            for _ in range(30):
                visible_session_ids = {
                    event.event_id for event in reopened.events if event.event_id in set(persisted["event_ids"])
                }
                if visible_session_ids == set(persisted["event_ids"]):
                    break
                await pilot.pause(0.1)
            assert len({event.event_id for event in reopened.events}) == len(reopened.events)

            assert persisted["status"] == "completed"
            assert persisted["event_count"] == 5
            visible_session_events = [
                event for event in reopened.events if event.event_id in set(persisted["event_ids"])
            ]
            assert [event.event_id for event in visible_session_events] == persisted["event_ids"]
            assert [event.kind for event in visible_session_events] == persisted["event_kinds"]

        print(
            "TUI PHASE B RESTART: "
            f"session_id={session_id}, sigterm_returncode={sigterm_returncode}, "
            f"reconstructed_status={reconstructed['status']}, "
            f"reconstructed_events={reconstructed['event_count']}"
        )
        print(
            "TUI PHASE B ARENA: on_mount restarted polling after reopen; "
            f"status={persisted['status']}, event_count={persisted['event_count']}, "
            f"unique_event_ids={len(set(persisted['event_ids']))}, "
            f"kinds={persisted['event_kinds']}"
        )
        print("PASS: real-node SIGTERM/restart and Arena reopen preserved exact history")
    finally:
        harness.cleanup()
