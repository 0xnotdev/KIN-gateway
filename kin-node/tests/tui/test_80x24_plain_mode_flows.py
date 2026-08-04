"""Mounted 80x24/plain-mode completion matrix for T7 Build Step 5.

Every test runs a real Textual app at 80x24 with monochrome and ASCII fallback
enabled. Required flows are driven through keyboard actions or mounted modal
callbacks; direct, unmounted ``render()`` smoke tests are intentionally avoided.
"""

from __future__ import annotations

from textual.geometry import Size
from textual.events import Resize

import pytest

from kin.schemas import AgentAvailability
from kin.tui.state import (
    AgentCardView,
    ApprovalRequest,
    ApprovalView,
    RecoverableError,
    SessionSummary,
    UiEvent,
)
from kin.tui.widgets.agent_picker import AgentPickerWidget
from kin.tui.widgets.dispatch_wizard import DispatchStep, DispatchWizardWidget
from kin.tui.widgets.inbox_screen import InboxScreenWidget
from kin.tui.widgets.lifecycle import WidgetLifecycleState
from kin.tui.widgets.session_arena import SessionArenaWidget
from kin.tui.widgets.settings_screen import SettingsModal


async def _enable_plain_mode(app, pilot) -> None:
    app.prefs.ascii_fallback = True
    app.prefs.color_depth = "monochrome"
    app._refresh_theme_ui()
    await pilot.pause()
    assert app.current_breakpoint == "minimal"
    assert app.is_plain_mode_active is True
    assert app.is_ascii_fallback_active is True
    assert app.is_colorless_active is True


def _assert_semantic_ascii(text: str, *ordered_headings: str) -> None:
    assert text.isascii(), text
    assert not any(glyph in text for glyph in ("┌", "┐", "└", "┘", "│", "─", "▶", "●"))
    positions = [text.index(heading) for heading in ordered_headings]
    assert positions == sorted(positions)


def _approval() -> ApprovalView:
    request = ApprovalRequest(
        schema_version="1.1",
        session_id="sess-minimal",
        approval_id="approval-minimal-001",
        agent_id="security-agent",
        action_class="workspace_write",
        requested_scope={"paths": ["workspace/config.toml"]},
        summary="Modify the complete production configuration for the workspace",
        risk_label="high",
        reason="Apply reviewed configuration changes after owner confirmation",
        expires_at="2026-08-05T18:00:00Z",
    )
    return ApprovalView(request=request, time_remaining=120.0)


def _summary() -> SessionSummary:
    return SessionSummary(
        session_id="sess-minimal",
        status="active",
        type="research",
        initiator_username="alice",
        receiver_username="bob",
        objective="Review the complete production configuration without truncating meaning",
        participant_display_names=["alice", "bob"],
        current_turn=2,
        max_turns=10,
    )


def _events() -> list[UiEvent]:
    return [
        UiEvent(
            event_id="event-001",
            session_id="sess-minimal",
            kind="task_request",
            created_at="2026-08-05T10:00:00Z",
            actor_username="alice",
            presentation_class="message",
            content="Please inspect the full configuration and preserve every decision.",
        ),
        UiEvent(
            event_id="event-002",
            session_id="sess-minimal",
            kind="checkpoint",
            created_at="2026-08-05T10:01:00Z",
            actor_username="bob",
            presentation_class="checkpoint",
            content="Configuration review checkpoint completed.",
        ),
    ]


async def _mount_arena(app, pilot, tmp_path, *, approvals=None) -> SessionArenaWidget:
    arena = SessionArenaWidget(
        session_id="sess-minimal",
        profile_name=app.profile_name,
        profile_dir=tmp_path,
        session_summary=_summary(),
        events=_events(),
        approvals=approvals or [],
    )
    app.canvas.session_arena_widgets["sess-minimal"] = arena
    app.tab_manager.open_tab("sess-minimal", "Session: Complete Configuration Review", "session")
    app.sync_tab_bar()
    await pilot.pause()
    mounted = app.query_one(SessionArenaWidget)
    mounted.focus()
    return mounted


@pytest.mark.asyncio
async def test_flow_1_home_and_settings_are_keyboard_reachable_at_80x24_plain_mode(
    build_tui_app,
    tmp_path,
):
    app = build_tui_app(profile_name="minimal-home", profile_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await _enable_plain_mode(app, pilot)
        home_text = str(app.canvas.home_widget.render())
        _assert_semantic_ascii(home_text, "HOME", "1. STATUS", "3. NEEDS YOU", "4. AGENTS", "5. NETWORK", "ACTIONS")
        assert app.sidebar.styles.display == "none"
        assert app.inspector.styles.display == "none"
        assert app.minimal_breadcrumb.styles.display == "block"

        await pilot.press("f2")
        assert isinstance(app.screen, SettingsModal)
        await pilot.press("escape")
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_flow_2_dispatch_preserves_draft_and_focus_across_resize_and_breadcrumb_back(
    build_tui_app,
    tmp_path,
):
    app = build_tui_app(profile_name="minimal-dispatch", profile_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await _enable_plain_mode(app, pilot)
        app.set_focus(None)
        await pilot.press("d")
        wizard = app.query_one(DispatchWizardWidget)
        wizard.controller.select_peer("bob")
        wizard.controller.select_sender_agent("local-builder")
        wizard.controller.select_receiver_agent("peer-reviewer")
        wizard.controller.current_step = DispatchStep.GOAL_INPUT
        wizard.step_index = DispatchStep.GOAL_INPUT.value
        wizard.focus()
        await pilot.pause()
        for character in "Audit production policy without losing the long objective":
            await pilot.press(character)

        focused_before = app.focused
        app.post_message(Resize(Size(120, 36), Size(80, 24)))
        await pilot.pause()
        app.post_message(Resize(Size(80, 24), Size(120, 36)))
        await pilot.pause()
        assert wizard.prompt == "Audit production policy without losing the long objective"
        assert app.focused is focused_before is wizard

        wizard.controller.current_step = DispatchStep.REVIEW_DISPATCH
        wizard.step_index = DispatchStep.REVIEW_DISPATCH.value
        review_text = str(wizard.render())
        _assert_semantic_ascii(review_text, "DISPATCH", "STEP", "PEER", "GOAL", "REVIEW")
        assert "Audit production policy without losing the long objective" in review_text

        await pilot.press("escape")
        assert app.tab_manager.get_active_tab().kind == "home"
        assert wizard.prompt == "Audit production policy without losing the long objective"


@pytest.mark.asyncio
async def test_flow_3_picker_exposes_long_details_and_selects_without_mouse(
    build_tui_app,
    tmp_path,
):
    app = build_tui_app(profile_name="minimal-picker", profile_dir=tmp_path)
    selected: list[str] = []
    agent = AgentCardView(
        agent_id="planner-with-a-very-long-stable-identifier",
        name="Production Configuration Planning and Verification Agent",
        description="Explains every boundary and capability without relying on hover content.",
        availability=AgentAvailability.READY,
        readiness_reason="Operational",
        boundary_summary="Read-only review of configuration with explicit owner approval for writes",
        is_peer=False,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await _enable_plain_mode(app, pilot)
        app.push_screen(AgentPickerWidget(agents=[agent]), lambda result: selected.append(result.agent_id) if result else None)
        await pilot.pause()
        picker = app.screen
        text = str(picker.render())
        _assert_semantic_ascii(text, "AGENT PICKER", "DESCRIPTION", "CAPABILITIES", "BOUNDARY", "ACTIONS")
        assert agent.name in text
        assert agent.description in text
        assert agent.boundary_summary in text
        await pilot.press("enter")
        assert selected == [agent.agent_id]


@pytest.mark.asyncio
async def test_flow_4_inbox_is_ordered_and_keyboard_navigable_at_80x24(
    build_tui_app,
    tmp_path,
):
    app = build_tui_app(profile_name="minimal-inbox", profile_dir=tmp_path)
    app.canvas.inbox_widget._approvals_override = [_approval()]
    async with app.run_test(size=(80, 24)) as pilot:
        await _enable_plain_mode(app, pilot)
        app.set_focus(None)
        await pilot.press("p")
        inbox = app.query_one(InboxScreenWidget)
        inbox.focus()
        text = str(inbox.render())
        _assert_semantic_ascii(text, "INBOX / NEEDS YOU", "1. NEEDS YOU ITEMS", "2. APPROVALS", "ACTIONS")
        assert "Modify the complete production configuration for the workspace" in text
        await pilot.press("tab", "tab")
        assert inbox.active_lane == "approvals"


@pytest.mark.asyncio
async def test_flow_5_approval_review_and_confirm_are_keyboard_complete_at_80x24(
    build_tui_app,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "kin.tui.widgets.inbox_screen.decide_pending_approval",
        lambda *args, **kwargs: (True, None),
    )
    app = build_tui_app(profile_name="minimal-approval", profile_dir=tmp_path)
    app.canvas.inbox_widget._approvals_override = [_approval()]
    async with app.run_test(size=(80, 24)) as pilot:
        await _enable_plain_mode(app, pilot)
        app.action_open_approvals()
        await pilot.pause()
        inbox = app.query_one(InboxScreenWidget)
        inbox.focus()
        await pilot.press("a")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.press("y")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert inbox.last_action_message == "Approved once: approval"
        assert app.notification_toast.styles.visibility == "visible"


@pytest.mark.asyncio
async def test_flow_6_arena_lanes_and_action_required_state_work_at_80x24_plain_mode(
    build_tui_app,
    tmp_path,
):
    app = build_tui_app(profile_name="minimal-arena", profile_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await _enable_plain_mode(app, pilot)
        arena = await _mount_arena(app, pilot, tmp_path, approvals=[_approval()])
        transcript = str(arena.render())
        _assert_semantic_ascii(transcript, "SESSION ARENA", "SESSION", "PARTICIPANTS", "ACTIVE LANE", "EVENTS", "ACTIONS")
        assert "Review the complete production configuration without truncating meaning" in transcript

        await pilot.press("u")
        assert arena.active_lane == "needs_you"
        needs_you = str(arena.render())
        assert "APPROVALS: 1" in needs_you
        assert "Modify the complete production configuration for the workspace" in needs_you


@pytest.mark.asyncio
async def test_flow_7_replay_and_plain_export_are_keyboard_accessible_at_80x24(
    build_tui_app,
    tmp_path,
):
    app = build_tui_app(profile_name="minimal-replay", profile_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await _enable_plain_mode(app, pilot)
        arena = await _mount_arena(app, pilot, tmp_path)
        await pilot.press("r")
        assert arena.is_replay_mode is True
        assert "REPLAY: ON" in str(arena.render())

        await pilot.press("ctrl+e")
        export_path = tmp_path / "exports" / "latest-view.txt"
        assert export_path.exists()
        exported = export_path.read_text(encoding="utf-8")
        _assert_semantic_ascii(exported, "SESSION ARENA", "SESSION", "EVENTS", "ACTIONS")
        assert "event-001" not in exported  # semantic export uses ordered content, not opaque IDs
        assert "Please inspect" in exported
        assert "full configuration and preserve every decision." in exported


@pytest.mark.asyncio
async def test_flow_8_recovery_output_is_ordered_complete_and_box_free_at_80x24(
    build_tui_app,
    tmp_path,
):
    app = build_tui_app(profile_name="minimal-recovery", profile_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await _enable_plain_mode(app, pilot)
        arena = await _mount_arena(app, pilot, tmp_path)
        arena.last_arena_error = RecoverableError(
            what_happened="Session event stream became unavailable.",
            impact="New events cannot be displayed yet.",
            preserved="Draft text, event history, and current selection remain intact.",
            next_action="Press Retry after checking the local node.",
        )
        arena.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)
        recovery = str(arena.render())
        _assert_semantic_ascii(
            recovery,
            "RECOVERY",
            "1. WHAT HAPPENED",
            "2. IMPACT",
            "3. PRESERVED",
            "4. NEXT ACTION",
            "ACTIONS",
        )
        assert "Draft text, event history, and current selection remain intact." in recovery
