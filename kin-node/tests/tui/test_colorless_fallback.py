"""Unit tests for Colorless / ASCII Fallback Semantic State Presentation (§14.9 Phase A2).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.9 build step 2, §8.1-8.2
- Renders REAL production widgets (AgentCardWidget, ApprovalCardWidget,
  ActivityFeedWidget, etc.) with ascii_fallback=True and color_depth="monochrome"
  active on KinApp.
- Asserts that rendered string outputs:
  1. Contain ZERO hex color tags (#[0-9a-fA-F]{6}).
  2. Contain ZERO non-ASCII unicode characters (pure ASCII string output).
  3. Are mutually distinct across all six semantic states (live, waiting, approval, error, muted, security).
"""

import pytest
import re
from kin.schemas import AgentAvailability
from kin.tui.app import KinApp
from kin.tui.state import ApprovalRequest, ApprovalView, AgentCardView, RecoverableError, UiEvent
from kin.tui.widgets.agent_card import AgentCardWidget
from kin.tui.widgets.approval_card import ApprovalCardWidget
from kin.tui.widgets.activity_feed import ActivityFeedWidget
from kin.tui.widgets.lifecycle import WidgetLifecycleState
from kin.tui.tokens import get_glyph

HEX_COLOR_TAG_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


@pytest.mark.asyncio
async def test_real_widgets_in_active_colorless_ascii_mode():
    """Mount KinApp with ascii_fallback=True and color_depth='monochrome', render 6 real widgets,

    and verify zero hex colors, pure ASCII text, and mutual distinctness across all six states.
    """
    app = KinApp(theme_name="kin-graphite", profile_name="test_profile_colorless")
    async with app.run_test(size=(160, 44)) as pilot:
        # Activate ASCII fallback & colorless monochrome mode via real app preferences
        app.prefs.ascii_fallback = True
        app.prefs.color_depth = "monochrome"
        await pilot.pause()

        assert app.is_ascii_fallback_active is True
        assert app.is_colorless_active is True

        # 1. LIVE STATE — AgentCardWidget with READY availability
        ready_card = AgentCardView(
            agent_id="agent-ready-1",
            name="Planner Agent",
            description="Task planner",
            availability=AgentAvailability.READY,
            readiness_reason="Operational",
            is_peer=False,
        )
        w_live = AgentCardWidget(card_view=ready_card)
        w_live._app = app
        w_live.set_lifecycle_state(WidgetLifecycleState.NORMAL)
        out_live = w_live.render()

        # 2. WAITING STATE — AgentCardWidget with BUSY availability
        busy_card = AgentCardView(
            agent_id="agent-busy-1",
            name="Planner Agent",
            description="Task planner",
            availability=AgentAvailability.BUSY,
            readiness_reason="In collaboration",
            is_peer=False,
        )
        w_waiting = AgentCardWidget(card_view=busy_card)
        w_waiting._app = app
        w_waiting.set_lifecycle_state(WidgetLifecycleState.NORMAL)
        out_waiting = w_waiting.render()

        # 3. APPROVAL STATE — ApprovalCardWidget with pending request
        req = ApprovalRequest(
            schema_version="1.1",
            session_id="sess-1",
            approval_id="app-12345678",
            agent_id="agent-1",
            action_class="workspace_write",
            requested_scope={"paths": ["/tmp/out"]},
            summary="Write file to /tmp/out",
            risk_label="high",
            reason="Modification of external file",
            expires_at="2026-08-03T12:00:00Z",
        )
        app_v = ApprovalView(request=req, time_remaining=45.0)
        w_approval = ApprovalCardWidget(approval_view=app_v)
        w_approval._app = app
        w_approval.set_lifecycle_state(WidgetLifecycleState.NORMAL)
        out_approval = w_approval.render()

        # 4. ERROR STATE — Widget in RECOVERABLE_ERROR lifecycle state
        w_error = AgentCardWidget(card_view=ready_card)
        w_error._app = app
        w_error.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)
        w_error.recoverable_error = RecoverableError(
            what_happened="Agent metadata corrupted",
            impact="Unable to inspect agent",
            preserved="Card state safe",
            next_action="Press [Retry]",
        )
        out_error = w_error.render()

        # 5. MUTED / DISABLED STATE — Widget in DISABLED lifecycle state
        w_muted = AgentCardWidget(card_view=ready_card)
        w_muted._app = app
        w_muted.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Agent offline")
        out_muted = w_muted.render()

        # 6. SECURITY STATE — ActivityFeedWidget with security event item
        sec_event = UiEvent(
            event_id="sec-1",
            session_id="sess-sec",
            kind="security_rejection",
            created_at="2026-08-03T00:00:00Z",
            actor_username="system",
            presentation_class="security",
            content="Security Event: Unauthorized write attempt blocked",
        )
        w_sec = ActivityFeedWidget(events=[sec_event])
        w_sec._app = app
        w_sec.timeline._app = app
        w_sec.set_lifecycle_state(WidgetLifecycleState.NORMAL)
        out_sec = w_sec.render()

        real_outputs = {
            "live": out_live,
            "waiting": out_waiting,
            "approval": out_approval,
            "error": out_error,
            "muted": out_muted,
            "security": out_sec,
        }

        # Verification 1 & 2: Zero hex color tags and 100% pure ASCII strings
        for state_name, text_out in real_outputs.items():
            assert not HEX_COLOR_TAG_PATTERN.search(text_out), (
                f"State '{state_name}' output contains hex color tags in colorless mode: {text_out}"
            )
            assert text_out.isascii(), (
                f"State '{state_name}' output contains non-ASCII unicode characters in ASCII mode: {text_out}"
            )

        # Verification 3: Pairwise distinctness across all six real outputs
        states = list(real_outputs.keys())
        for i in range(len(states)):
            for j in range(i + 1, len(states)):
                s1, s2 = states[i], states[j]
                o1, o2 = real_outputs[s1], real_outputs[s2]
                assert o1 != o2, f"Real widget outputs for state '{s1}' and '{s2}' must be distinct, but were identical!"

        await pilot.press("q")


@pytest.mark.asyncio
async def test_no_color_environment_variable_activates_colorless_only(monkeypatch):
    """Assert NO_COLOR env var activates is_colorless_active, but NOT is_ascii_fallback_active (Correction 1)."""
    monkeypatch.setenv("NO_COLOR", "1")
    app = KinApp(theme_name="kin-graphite", profile_name="test_profile_nocolor")
    async with app.run_test(size=(160, 44)) as pilot:
        app.prefs.ascii_fallback = False
        assert app.is_colorless_active is True
        assert app.is_ascii_fallback_active is False
        await pilot.press("q")
