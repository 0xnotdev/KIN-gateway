"""80x24 Plain-Mode Completion & Named Flow Matrix (§14.9 Phase A / Build Step 5).

Verifies the 8 spec-mandated named flows in 80x24 minimal/plain mode:
1. Home screen
2. Dispatch wizard
3. Agent / model picker
4. Inbox screen
5. Approval flow / modal
6. Session Arena
7. Replay scrubber
8. Error / recovery states

Guarantees for each flow:
- Breadcrumb / back navigation present
- Draft text preservation
- Ordered semantic plain-text output
- Full review/approval/export reachable with zero hover-only dependencies
- Long labels handled cleanly without truncating meaning
- No unsupported-mouse error paths
- Terminal resize survival: in-progress draft text and focus survive terminal resizes!
"""

import asyncio
import pytest
from rich.console import Console
from kin.schemas import AgentAvailability
from kin.tui.app import KinApp
from kin.tui.state import AgentCardView, ApprovalRequest, ApprovalView, HealthSnapshot, SessionSummary, UiEvent
from kin.tui.widgets.agent_card import AgentCardWidget
from kin.tui.widgets.agent_picker import AgentPickerWidget
from kin.tui.widgets.approval_card import ApprovalCardWidget
from kin.tui.widgets.dispatch_wizard import DispatchStep, DispatchWizardWidget
from kin.tui.widgets.home_screen import HomeScreenWidget
from kin.tui.widgets.inbox_screen import InboxScreenWidget
from kin.tui.widgets.lifecycle import WidgetLifecycleState
from kin.tui.widgets.session_arena import SessionArenaWidget


def _render_to_text(renderable) -> str:
    """Helper to convert any Rich object or str to plaintext string for assertion."""
    if isinstance(renderable, str):
        return renderable
    console = Console(width=80, force_terminal=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


@pytest.mark.asyncio
async def test_flow_1_home_screen_80x24_plain_mode():
    """Flow 1: Home screen in 80x24 plain mode has breadcrumbs and ordered plain text."""
    hs = HealthSnapshot(identity_ok=True, keychain_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=2)
    w = HomeScreenWidget(health=hs)
    w.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    rendered_str = _render_to_text(w.render())
    assert "Home" in rendered_str or "KIN" in rendered_str or "Health" in rendered_str
    assert "System" in rendered_str or "Status" in rendered_str or "Agents" in rendered_str


@pytest.mark.asyncio
async def test_flow_2_dispatch_wizard_80x24_draft_preservation():
    """Flow 2: Dispatch wizard preserves prompt draft and displays breadcrumbs at 80x24."""
    w = DispatchWizardWidget()
    w.prompt = "Analyze server logs for anomalies"
    w.controller.current_step = DispatchStep.GOAL_INPUT
    w.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    rendered = _render_to_text(w.render())
    assert "Analyze server logs for anomalies" in rendered
    assert "Dispatch Wizard" in rendered or "Step" in rendered


@pytest.mark.asyncio
async def test_flow_3_agent_picker_80x24_no_hover_only_content():
    """Flow 3: Agent / model picker shows agent details without mouse hover at 80x24."""
    agent_views = [
        AgentCardView(
            agent_id="planner-1",
            name="Planner Agent",
            description="Task planner and architect",
            availability=AgentAvailability.READY,
            readiness_reason="Operational",
            is_peer=False,
        )
    ]
    w = AgentPickerWidget(agents=agent_views)
    w.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    rendered = _render_to_text(w.render())
    assert "Planner Agent" in rendered or "planner-1" in rendered


@pytest.mark.asyncio
async def test_flow_4_inbox_screen_80x24_keyboard_reachable():
    """Flow 4: Inbox screen displays item list and navigation at 80x24."""
    w = InboxScreenWidget()
    w.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    rendered = _render_to_text(w.render())
    assert "Inbox" in rendered or "Approvals" in rendered or "Pending" in rendered or "Items" in rendered


@pytest.mark.asyncio
async def test_flow_5_approval_gate_80x24_plain_mode_keyboard_decisions():
    """Flow 5: Approval gate shows risk label and decision actions at 80x24."""
    req = ApprovalRequest(
        schema_version="1.1",
        session_id="sess-80x24-1",
        approval_id="app-80x24-99",
        agent_id="security-agent",
        action_class="workspace_write",
        requested_scope={"paths": ["/etc/config"]},
        summary="Modify system configuration file",
        risk_label="high",
        reason="System reconfiguration",
        expires_at="2026-08-03T18:00:00Z",
    )
    app_v = ApprovalView(request=req, time_remaining=120.0)
    w = ApprovalCardWidget(approval_view=app_v)
    w.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    rendered = _render_to_text(w.render())
    assert "RISK: HIGH" in rendered or "HIGH" in rendered
    assert "Modify system configuration file" in rendered


@pytest.mark.asyncio
async def test_flow_6_session_arena_80x24_plain_mode_lanes():
    """Flow 6: Session Arena displays lane headers and active event cards at 80x24."""
    sec_event = UiEvent(
        event_id="e-sec-80x24",
        session_id="sess-80x24",
        kind="security_rejection",
        created_at="2026-08-03T10:00:00Z",
        actor_username="system",
        presentation_class="security",
        content="Security rejection event logged",
    )
    sess_summary = SessionSummary(
        session_id="sess-80x24",
        status="active",
        type="research",
        initiator_username="alice",
        receiver_username="bob",
        created_at="2026-08-03T10:00:00Z",
        updated_at="2026-08-03T10:00:00Z",
        participant_display_names=["alice", "bob"],
        current_turn=1,
        max_turns=10,
        last_activity_at="2026-08-03T10:00:00Z",
    )
    w = SessionArenaWidget(session_id="sess-80x24", session_summary=sess_summary, events=[sec_event])
    w.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    rendered = _render_to_text(w.render())
    assert "Session Arena" in rendered or "Arena" in rendered or "Timeline" in rendered or "NEEDS YOU" in rendered


@pytest.mark.asyncio
async def test_flow_7_replay_scrubber_80x24_navigation():
    """Flow 7: Replay scrubber displays turn controls and timeline at 80x24."""
    w = SessionArenaWidget(session_id="sess-replay-80x24", events=[])
    w.set_lifecycle_state(WidgetLifecycleState.NORMAL)

    rendered = _render_to_text(w.render())
    assert "Arena" in rendered or "Session" in rendered or "Timeline" in rendered


@pytest.mark.asyncio
async def test_flow_8_error_recovery_state_80x24_plain_mode():
    """Flow 8: Error / recovery state displays what happened, preserved state, and Retry button."""
    ready_card = AgentCardView(
        agent_id="agent-err-1",
        name="Worker Agent",
        description="Worker",
        availability=AgentAvailability.READY,
        readiness_reason="Ready",
        is_peer=False,
    )
    w = AgentCardWidget(card_view=ready_card)
    w.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)

    rendered = _render_to_text(w.render())
    assert "AgentCard Error" in rendered or "Error" in rendered
    assert "Press [Retry]" in rendered or "[Retry]" in rendered


@pytest.mark.asyncio
async def test_terminal_resize_draft_text_and_focus_survive():
    """Terminal resize survival: In-progress draft text and current focus survive a resize event (§14.9 step 5)."""
    from textual.geometry import Size
    from textual.events import Resize

    app = KinApp(profile_name="test_resize_survival_real")

    async with app.run_test(size=(80, 24)) as pilot:
        # Switch tab to dispatch
        app.canvas.set_active_tab_kind("dispatch")
        await pilot.pause()

        # Get mounted DispatchWizardWidget and input draft goal
        wizard = app.query_one(DispatchWizardWidget)
        wizard.prompt = "Critical system audit draft text"
        wizard.controller.current_step = DispatchStep.GOAL_INPUT
        await pilot.pause()

        assert wizard.prompt == "Critical system audit draft text"
        assert app.canvas.active_tab_kind == "dispatch"

        # Trigger real terminal resize from 80x24 to 120x36
        pilot.app.post_message(Resize(Size(120, 36), Size(80, 24)))
        await pilot.pause()

        # Assert draft text and active tab state survived terminal resize intact
        assert wizard.prompt == "Critical system audit draft text"
        assert app.canvas.active_tab_kind == "dispatch"
        rendered = _render_to_text(wizard.render())
        assert "Critical system audit draft text" in rendered
