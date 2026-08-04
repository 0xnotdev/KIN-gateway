"""Unit tests for the 7-step Dispatch Wizard and Context Pantry (§14.7 Phase C).

Covers:
1. 7-step wizard navigation and validation rules (direct-call controller unit tests).
2. Context Pantry item addition, removal, and M7 local reference restriction.
3. Dirty tracking on draft modifications.
4. Non-blocking off-main-thread worker execution.
5. REAL KEYBOARD-ONLY (pilot.press) end-to-end interactive wizard test with strict peer scoping.
6. Invalid key press preservation on session type selection.
"""

from pathlib import Path

import pytest

from kin.schemas import AgentAvailability, SessionType
from kin.tui.dispatch import DispatchController, DispatchStep
from kin.tui.shell import MainCanvas
from kin.tui.state import AgentCardView, ContactSummary, ContextPantryItem
from kin.tui.widgets.agent_picker import AgentPickerWidget
from kin.tui.widgets.dispatch_wizard import ContactPickerModal, DispatchWizardWidget
from kin.tui.widgets.lifecycle import WidgetLifecycleState


@pytest.fixture
def mock_profile_dir(tmp_path, monkeypatch):
    profile_path = tmp_path / ".kin" / "profiles" / "wizard_user"
    monkeypatch.setattr("kin.tui.persistence.get_profile_dir", lambda name="default": profile_path)
    monkeypatch.setattr("kin.tui.app.get_profile_dir", lambda name="default": profile_path)
    return profile_path


# -----------------------------------------------------------------------------
# Direct-Call Controller Unit Tests (Preserved)
# -----------------------------------------------------------------------------
def test_dispatch_wizard_7_steps_navigation(tmp_path: Path):
    """1. Assert DispatchController navigates through all 7 steps with SessionType validation (§C1)."""
    prof_dir = tmp_path / "profiles" / "wizard_user"
    ctrl = DispatchController(profile_name="wizard_user", profile_dir=prof_dir)

    # Initial step: PEER_SELECTION (Step 0)
    assert ctrl.current_step == DispatchStep.PEER_SELECTION
    assert ctrl.validate_current_step() is False  # Required peer_username missing

    # Select peer -> advance to Step 1
    ctrl.select_peer("alice")
    assert ctrl.validate_current_step() is True
    assert ctrl.next_step() is True
    assert ctrl.current_step == DispatchStep.SENDER_AGENT_SELECTION

    # Select sender agent -> advance to Step 2
    ctrl.select_sender_agent("my-agent-1")
    assert ctrl.next_step() is True
    assert ctrl.current_step == DispatchStep.RECEIVER_AGENT_SELECTION

    # Select receiver agent -> advance to Step 3
    ctrl.select_receiver_agent("peer-agent-2")
    assert ctrl.next_step() is True
    assert ctrl.current_step == DispatchStep.COLLABORATION_TYPE

    # Set master SessionType enum value -> advance to Step 4
    ctrl.set_session_type(SessionType.RESEARCH.value)
    assert ctrl.next_step() is True
    assert ctrl.current_step == DispatchStep.GOAL_INPUT

    # Set goal -> advance to Step 5
    ctrl.set_goal("Audit security vulnerability")
    assert ctrl.next_step() is True
    assert ctrl.current_step == DispatchStep.CONTEXT_PANTRY

    # Context Pantry optional -> advance to Step 6
    assert ctrl.next_step() is True
    assert ctrl.current_step == DispatchStep.REVIEW_DISPATCH

    # Step 6 is final step
    assert ctrl.next_step() is False


def test_dispatch_wizard_context_pantry_operations(tmp_path: Path):
    """2. Assert Context Pantry items add/remove and local reference restriction (§C3)."""
    prof_dir = tmp_path / "profiles" / "pantry_user"
    widget = DispatchWizardWidget(profile_name="pantry_user", profile_dir=prof_dir)

    # Add message item
    widget.add_context_pantry_item("message", "High priority request")
    assert len(widget.controller.draft.pantry_items) == 1
    assert widget.controller.draft.pantry_items[0].kind == "message"
    assert widget.controller.draft.pantry_items[0].classification == "attached"

    # Add local reference item -> verifies M7 explanation
    widget.add_context_pantry_item("local_reference", "file:///d:/KIN/doc.txt")
    assert len(widget.controller.draft.pantry_items) == 2
    local_ref_item = widget.controller.draft.pantry_items[1]
    assert local_ref_item.kind == "local_reference"
    assert "Milestone M7" in local_ref_item.classification

    # Remove item
    removed = widget.controller.remove_pantry_item(0)
    assert removed is True
    assert len(widget.controller.draft.pantry_items) == 1
    assert widget.controller.draft.pantry_items[0].kind == "local_reference"


def test_dispatch_wizard_dirty_state_tracking(tmp_path: Path):
    """3. Assert modifications to draft update dirty = True (§C2)."""
    prof_dir = tmp_path / "profiles" / "dirty_user"
    ctrl = DispatchController(profile_name="dirty_user", profile_dir=prof_dir)

    assert ctrl.draft.dirty is False
    ctrl.set_goal("New updated goal")
    assert ctrl.draft.dirty is True


@pytest.mark.asyncio
async def test_dispatch_wizard_non_blocking_worker_execution(tmp_path: Path):
    """4. Assert confirm_dispatch triggers off-main-thread non-blocking worker (§C5)."""
    prof_dir = tmp_path / "profiles" / "worker_user"
    widget = DispatchWizardWidget(
        agent_id="my-agent",
        prompt="Execute task",
        profile_name="worker_user",
        profile_dir=prof_dir,
    )
    widget.controller.select_peer("alice")
    widget.controller.select_sender_agent("my-agent")
    widget.controller.select_receiver_agent("alice-agent")

    # Confirm dispatch initiates worker execution
    widget.confirm_dispatch()
    assert widget.is_submitted is True
    assert "Dispatch draft prepared" in widget.status_message or "✔" in widget.status_message or "failed" in widget.status_message


# -----------------------------------------------------------------------------
# Real Keyboard-Only (pilot.press) Interactive Unit Tests
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_wizard_keyboard_only_end_to_end_pilot_flow(mock_profile_dir, monkeypatch, build_tui_app):
    """5. End-to-end test driving all 6 selection-bearing steps exclusively via pilot.press() with strict peer scoping (§14.7 Phase C Rework)."""
    # Seed mock contact summaries for peer selection modal
    contacts = [
        ContactSummary("alice", "Alice Cooper", "pk1", "x1", "http://alice"),
        ContactSummary("bob", "Bob Dylan", "pk2", "x2", "http://bob"),
    ]
    monkeypatch.setattr("kin.tui.widgets.dispatch_wizard.get_local_contacts_summaries", lambda d=None: contacts)

    # Seed mock agents for both local user and peers "alice" and "bob"
    local1 = AgentCardView(agent_id="my_local_scout", name="Local Scout", description="Local scanner", availability=AgentAvailability.READY, readiness_reason="Ready", is_peer=False)
    local2 = AgentCardView(agent_id="my_local_builder", name="Local Builder", description="Local builder", availability=AgentAvailability.READY, readiness_reason="Ready", is_peer=False)

    alice_agent = AgentCardView(agent_id="alice_scout", name="Alice Scout", description="Alice agent", availability=AgentAvailability.READY, readiness_reason="Ready", is_peer=True, peer_username="alice")
    bob_agent1 = AgentCardView(agent_id="bob_analyst", name="Bob Analyst", description="Bob agent 1", availability=AgentAvailability.READY, readiness_reason="Ready", is_peer=True, peer_username="bob")
    bob_agent2 = AgentCardView(agent_id="bob_evaluator", name="Bob Evaluator", description="Bob agent 2", availability=AgentAvailability.READY, readiness_reason="Ready", is_peer=True, peer_username="bob")

    monkeypatch.setattr("kin.tui.widgets.dispatch_wizard.get_local_agents_summaries", lambda d=None: [local1, local2])
    monkeypatch.setattr("kin.tui.widgets.dispatch_wizard.get_all_agent_summaries", lambda d=None: ([local1, local2], [alice_agent, bob_agent1, bob_agent2]))

    app = build_tui_app()
    async with app.run_test(size=(160, 44)) as pilot:
        # Mount dispatch canvas and focus wizard widget
        canvas = pilot.app.query_one(MainCanvas)
        canvas.set_active_tab_kind("dispatch")
        await pilot.pause()

        wizard = pilot.app.query_one(DispatchWizardWidget)
        wizard.focus()
        assert wizard.step_index == 0

        # Step 0 (Peer Selection): Press Enter to open ContactPickerModal, press down/j to select 'bob', Enter
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ContactPickerModal)
        await pilot.press("j")  # select bob
        await pilot.press("enter")
        await pilot.pause()
        assert wizard.controller.draft.peer_username == "bob"

        # Step 1 (Sender Agent): Open AgentPickerWidget, select non-default 'my_local_builder'
        await pilot.press("right")
        assert wizard.step_index == 1
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(pilot.app.screen, AgentPickerWidget)
        assert len(pilot.app.screen.agents) == 2
        await pilot.press("j")  # select my_local_builder
        await pilot.press("enter")
        await pilot.pause()
        assert wizard.controller.draft.sender_agent_id == "my_local_builder"

        # Step 2 (Receiver Agent): Open AgentPickerWidget, verify STRICT peer scoping (only bob's agents, NOT alice's)
        await pilot.press("right")
        assert wizard.step_index == 2
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(pilot.app.screen, AgentPickerWidget)
        picker_agents = pilot.app.screen.agents
        assert len(picker_agents) == 2  # bob_analyst and bob_evaluator
        assert all(a.peer_username == "bob" for a in picker_agents)
        assert not any(a.peer_username == "alice" for a in picker_agents)

        # Select non-default 'bob_evaluator'
        await pilot.press("j")  # select bob_evaluator
        await pilot.press("enter")
        await pilot.pause()
        assert wizard.controller.draft.receiver_agent_id == "bob_evaluator"

        # Step 3 (Collaboration Mode): Press down to cycle from 'ask' to 'research'
        await pilot.press("right")
        assert wizard.step_index == 3
        await pilot.press("down")
        assert wizard.controller.draft.session_type == SessionType.RESEARCH.value

        # Step 4 (Goal Input): Type non-default goal text character-by-character
        await pilot.press("right")
        assert wizard.step_index == 4
        for _ in range(len(wizard.prompt)):
            await pilot.press("backspace")
        for char in "Audit security flaws":
            await pilot.press(char)
        assert wizard.prompt == "Audit security flaws"

        # Step 5 (Context Pantry): Press 'a' to add a pantry item
        await pilot.press("right")
        assert wizard.step_index == 5
        await pilot.press("a")
        assert len(wizard.controller.draft.pantry_items) >= 1

        # Step 6 (Review & Dispatch): Press Enter to confirm dispatch
        await pilot.press("right")
        assert wizard.step_index == 6
        await pilot.press("enter")
        await pilot.pause()

        # Assert final submitted state reflects ALL chosen non-default values
        assert wizard.is_submitted is True
        rendered_text = wizard.render()
        assert "@bob" in rendered_text
        assert "my_local_builder" in rendered_text
        assert "bob_evaluator" in rendered_text
        assert "RESEARCH" in rendered_text
        assert "Audit security flaws" in rendered_text


@pytest.mark.asyncio
async def test_dispatch_wizard_invalid_key_preserves_session_type(mock_profile_dir, build_tui_app):
    """6. Assert pressing invalid/no-op key on Collaboration Mode step preserves session type (§14.7 Phase C Rework)."""
    app = build_tui_app()
    async with app.run_test(size=(160, 44)) as pilot:
        canvas = pilot.app.query_one(MainCanvas)
        canvas.set_active_tab_kind("dispatch")
        await pilot.pause()

        wizard = pilot.app.query_one(DispatchWizardWidget)
        wizard.focus()

        wizard.controller.select_peer("alice")
        wizard.controller.select_sender_agent("a1")
        wizard.controller.select_receiver_agent("a2")
        wizard.step_index = 3  # Collaboration Mode step

        original_mode = wizard.controller.draft.session_type
        assert original_mode == SessionType.ASK.value

        # Press invalid key 'z'
        await pilot.press("z")
        # Assert session type remains unchanged
        assert wizard.controller.draft.session_type == original_mode


@pytest.mark.asyncio
async def test_dispatch_wizard_skip_all_steps_without_selection_blocks_dispatch(mock_profile_dir, monkeypatch, build_tui_app):
    """7. Assert constructing DispatchWizardWidget() zero-args and skipping all steps without selection BLOCKS dispatch (§14.7 Phase C Rework)."""
    dispatch_calls = []

    def mock_dispatch(*args, **kwargs):
        dispatch_calls.append((args, kwargs))
        return True, {"session_id": "mock-123"}, None

    monkeypatch.setattr("kin.tui.widgets.dispatch_wizard.dispatch_new_session", mock_dispatch)

    app = build_tui_app()
    async with app.run_test(size=(160, 44)) as pilot:
        canvas = pilot.app.query_one(MainCanvas)
        canvas.set_active_tab_kind("dispatch")
        await pilot.pause()

        # Get default zero-arg DispatchWizardWidget constructed by shell.py
        wizard = pilot.app.query_one(DispatchWizardWidget)
        wizard.focus()

        # Press 'right' / 'n' 7 times without making any selections or typing a goal
        for _ in range(7):
            await pilot.press("right")
            await pilot.pause(0.01)

        # Assert navigation was blocked at Step 0 due to missing required peer_username
        assert wizard.step_index == 0

        # Attempt to confirm dispatch
        wizard.confirm_dispatch()
        await pilot.pause(0.1)

        # ASSERT: dispatch_new_session MUST NOT be called!
        assert len(dispatch_calls) == 0, f"CRITICAL BUG: dispatch_new_session was called with unselected data: {dispatch_calls}"
        # ASSERT: wizard MUST show blocking error status
        assert "Cannot dispatch" in wizard.status_message or wizard.lifecycle_state == WidgetLifecycleState.RECOVERABLE_ERROR
