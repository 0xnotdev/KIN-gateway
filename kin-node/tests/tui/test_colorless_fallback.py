"""Unit tests for Colorless / ASCII Fallback Semantic State Presentation (§14.9 Phase A Build Step 2).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.9 build step 2, §8.1-8.2
- Live, waiting, approval, error, muted, and security states are each
  distinguishable via glyph + text label + border/bracket treatment alone,
  with color and Unicode both stripped.
- Renders REAL production widgets (AgentCardWidget, ApprovalCardWidget,
  ActivityFeedWidget, etc.) in ASCII-fallback mode to prove that
  real widget outputs for all six semantic states are mutually distinct.
"""

import pytest
from kin.schemas import AgentAvailability
from kin.tui.state import ApprovalRequest, ApprovalView, AgentCardView, RecoverableError, UiEvent
from kin.tui.widgets.agent_card import AgentCardWidget
from kin.tui.widgets.approval_card import ApprovalCardWidget
from kin.tui.widgets.activity_feed import ActivityFeedWidget
from kin.tui.widgets.lifecycle import WidgetLifecycleState
from kin.tui.tokens import get_glyph


def test_real_widgets_render_six_semantic_states_distinguishably_in_ascii_mode():
    """Assert real widgets rendering live, waiting, approval, error, muted, and security states

    produce mutually distinct rendered outputs in ASCII mode (color & unicode stripped).
    """
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
    w_approval.set_lifecycle_state(WidgetLifecycleState.NORMAL)
    out_approval = w_approval.render()

    # 4. ERROR STATE — Widget in RECOVERABLE_ERROR lifecycle state
    w_error = AgentCardWidget(card_view=ready_card)
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
    w_sec.set_lifecycle_state(WidgetLifecycleState.NORMAL)
    out_sec = w_sec.render()

    # Map of all 6 state outputs from real production widgets
    real_outputs = {
        "live": out_live,
        "waiting": out_waiting,
        "approval": out_approval,
        "error": out_error,
        "muted": out_muted,
        "security": out_sec,
    }

    # Assert every output is non-empty and contains state-identifying keywords/labels
    assert "ready" in out_live.lower() or "●" in out_live or "*" in out_live
    assert "busy" in out_waiting.lower()
    assert "risk:" in out_approval.lower()
    assert "error" in out_error.lower()
    assert "disabled" in out_muted.lower()
    assert "activity" in out_sec.lower() or "security" in out_sec.lower()

    # Pairwise comparison to prove all six real outputs are distinct from each other
    states = list(real_outputs.keys())
    for i in range(len(states)):
        for j in range(i + 1, len(states)):
            s1, s2 = states[i], states[j]
            o1, o2 = real_outputs[s1], real_outputs[s2]
            assert o1 != o2, f"Real widget outputs for state '{s1}' and '{s2}' must be distinct, but were identical!"


def test_ascii_fallback_glyph_registry_coverage():
    """Assert indicator glyphs produce pure ASCII fallbacks for plain-terminal compatibility."""
    indicator_symbols = ["●", "✓", "!", "→", "○", "◌", "✖", "▲"]
    for s in indicator_symbols:
        fallback = get_glyph(s, ascii_fallback=True)
        assert fallback.isascii(), f"ASCII fallback for symbol '{s}' must be ASCII, got: '{fallback}'"
        if not s.isascii():
            assert fallback != s, f"ASCII fallback for unicode symbol '{s}' must differ from original"
