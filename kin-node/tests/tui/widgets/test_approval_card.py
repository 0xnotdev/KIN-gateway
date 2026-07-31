"""Unit tests for ApprovalCardWidget risk levels and dynamic time-remaining.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime, timezone
import pytest

from kin.schemas import ActionClass, ApprovalRequest, RiskLabel
from kin.tui.state import ApprovalView
from kin.tui.widgets import ApprovalCardWidget


def test_approval_card_time_remaining_progression_with_injectable_clock():
    """DYNAMIC TIME-REMAINING CLOCK TEST (§14.5).

    Verifies ApprovalCardWidget dynamically updates time_remaining as an injectable `now` clock advances.
    """
    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="app_99",
        session_id="sess_101",
        agent_id="agent_scout",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Delete Temp Files",
        reason="Cleanup workspace",
        risk_label=RiskLabel.HIGH,
        requested_scope={"path": "tmp/*"},
        expires_at="2026-07-28T15:00:00Z",
    )
    t0 = datetime(2026, 7, 28, 14, 50, 0, tzinfo=timezone.utc)
    app_view = ApprovalView(request=req, now=t0)
    widget = ApprovalCardWidget(approval_view=app_view, now=t0)

    # Initial time_remaining: 10 minutes = 600.0s
    assert widget.approval_view.time_remaining == 600.0
    assert "600.0s remaining" in widget.render()

    # Advance clock by 5 minutes (300 seconds)
    t1 = datetime(2026, 7, 28, 14, 55, 0, tzinfo=timezone.utc)
    widget.update_clock(now=t1)
    assert widget.approval_view.time_remaining == 300.0
    assert "300.0s remaining" in widget.render()

    # Advance past expiration time
    t2 = datetime(2026, 7, 28, 15, 0, 5, tzinfo=timezone.utc)
    widget.update_clock(now=t2)
    assert widget.approval_view.time_remaining == 0.0
    assert "0.0s remaining" in widget.render()


def test_approval_card_risk_levels_distinct_rendering():
    """DISTINCT RISK LEVEL RENDER TEST (§14.5).

    Verifies LOW, MEDIUM, HIGH, and CRITICAL risk levels produce visibly distinct outputs.
    """
    risk_labels = [RiskLabel.LOW, RiskLabel.MEDIUM, RiskLabel.HIGH, RiskLabel.CRITICAL]
    outputs = {}

    for risk in risk_labels:
        req = ApprovalRequest(
            schema_version="1.1",
            approval_id=f"app_{risk.value}",
            session_id="sess_101",
            agent_id="scout",
            action_class=ActionClass.SHELL_NETWORK_EXTERNAL,
            summary="Action Test",
            reason="testing",
            risk_label=risk,
            requested_scope={"cmd": "curl"},
            expires_at="2026-07-28T15:00:00Z",
        )
        view = ApprovalView(request=req, now=datetime(2026, 7, 28, 14, 0, 0, tzinfo=timezone.utc))
        widget = ApprovalCardWidget(approval_view=view)
        rendered = widget.render()
        outputs[risk.value] = rendered

        assert f"RISK: {risk.value.upper()}" in rendered

    # Assert outputs for all 4 risk levels are unique and distinct
    distinct_outputs = set(outputs.values())
    assert len(distinct_outputs) == 4, "Risk level outputs were not visually distinct!"
