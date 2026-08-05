"""T8 Phase A: keyboard-driven KinApp dispatch to a separate real node."""

from __future__ import annotations

import keyring
import pytest

from kin.testing.insecure_memory_keyring import InMemoryTestKeyring
from kin.tui.widgets.dispatch_wizard import DispatchWizardWidget
from scripts.smoke_two_node_harness import TwoNodeSmokeHarness


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_keyboard_dispatch_reaches_separate_real_bob_node(
    build_tui_app, monkeypatch
) -> None:
    harness = TwoNodeSmokeHarness()
    try:
        harness.start()
        monkeypatch.setenv("HOME", str(harness.alice_home))
        monkeypatch.setenv("USERPROFILE", str(harness.alice_home))
        monkeypatch.setenv("KIN_UNSAFE_TEST_KEYRING", "1")
        monkeypatch.setenv("KIN_TEST_KEYRING_PATH", str(harness.alice_home / "keyring.json"))
        keyring.set_keyring(InMemoryTestKeyring())

        app = build_tui_app(
            profile_name="alice",
            profile_dir=harness.alice_profile_dir,
        )
        goal = "prove keyboard dispatch over a real node boundary"

        async with app.run_test(size=(120, 36)) as pilot:
            app.canvas.home_widget.focus()
            await pilot.press("d")
            await pilot.pause()
            wizard = app.canvas.query_one(DispatchWizardWidget)
            wizard.focus()

            # Step 1: peer contact. Open and confirm the real paired Bob row.
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert wizard.controller.draft.peer_username == "bob"
            await pilot.press("right")
            assert wizard.step_index == 1

            # Step 2: Alice's imported local agent.
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert wizard.controller.draft.sender_agent_id == "alice_agent"
            await pilot.press("right")
            assert wizard.step_index == 2

            # Step 3: Bob's card, synced over Bob's authenticated HTTP endpoint.
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert wizard.controller.draft.receiver_agent_id == "bob_agent"
            await pilot.press("right")
            assert wizard.step_index == 3

            # Step 4 retains the default collaboration mode: ask.
            await pilot.press("right")
            assert wizard.step_index == 4

            # Step 5 enters the real goal through keyboard events only.
            for character in goal:
                await pilot.press(character)
            assert wizard.prompt == goal
            await pilot.press("right")
            assert wizard.step_index == 5

            # Step 6 optional pantry -> Step 7 review -> keyboard confirmation.
            await pilot.press("right")
            assert wizard.step_index == 6
            await pilot.press("enter")

            for _ in range(100):
                if wizard.last_dispatch_result is not None or wizard.last_dispatch_error is not None:
                    break
                await pilot.pause(0.1)

            assert wizard.last_dispatch_error is None
            assert wizard.last_dispatch_result is not None
            assert wizard.last_dispatch_result["status"] == "delivered"
            session_id = wizard.last_dispatch_result["session_id"]

        bob_evidence = harness.run_worker("bob", "inspect", "--session", session_id)
        assert bob_evidence["found"] is True
        assert bob_evidence["status"] == "peer_review"
        assert bob_evidence["goal"] == goal
        assert bob_evidence["event_count"] == 1
        assert bob_evidence["event_kinds"] == ["task_request"]

        print(
            "TUI REAL-NODE: "
            f"alice_profile={harness.alice_profile_dir}, bob_port={harness.bob_port}"
        )
        print(
            "TUI REAL-NODE: keyboard dispatch -> "
            f"session_id={session_id}, transport_status=delivered"
        )
        print(
            "TUI REAL-NODE: Bob subprocess storage proof -> "
            f"status={bob_evidence['status']}, event_count={bob_evidence['event_count']}, "
            f"kinds={bob_evidence['event_kinds']}, goal={bob_evidence['goal']!r}"
        )
        print("PASS: KinApp pilot keyboard dispatch reached the separate real Bob node")
    finally:
        harness.cleanup()
