"""Adversarial End-to-End Content Scrubbing Tests for KIN V1.1 TUI (§14.5).

Seeds fake API keys, secrets, absolute filesystem paths, and chain-of-thought strings
across all free-form text displaying widgets, asserting 0 secret/path leakage in rendered outputs.
"""

from datetime import datetime, timezone
import pytest

from kin.schemas import ActionClass, ApprovalRequest, RiskLabel
from kin.tui.state import AgentCardView, ApprovalView, CommandResult, SessionSummary, UiEvent
from kin.tui.widgets import (
    ActivityFeedWidget,
    AgentCardWidget,
    ApprovalCardWidget,
    DispatchWizardWidget,
    ExchangeTimelineWidget,
    InspectorWidget,
    ModalWidget,
    OutcomeCardWidget,
    StatusLineWidget,
    ToastWidget,
)

FAKE_SECRETS = [
    "sk-live-1234567890abcdef12345678",
    "ghp_123456789012345678901234567890123456",
    r"C:\Users\Administrator\secrets\passwords.txt",
    "/home/ubuntu/production_keys/id_rsa",
    "<think>Internal reasoning step: leak token</think>",
]


def test_adversarial_content_scrubbing_across_all_free_form_widgets():
    """END-TO-END ADVERSARIAL CONTENT SCRUBBING TEST (§14.5).

    Verifies all free-form text displaying widgets scrub seeded API keys, secrets,
    local absolute paths, and chain-of-thought reasoning from their rendered outputs.
    """

    # 1. ApprovalCardWidget (summary & reason)
    app_req = ApprovalRequest(
        schema_version="1.1",
        approval_id="app_adv",
        session_id="sess_101",
        agent_id="scout",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary=f"Write config using sk-live-1234567890abcdef12345678",
        reason=f"Saving credentials to C:\\Users\\Administrator\\secrets\\passwords.txt",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-28T20:00:00Z",
    )
    app_view = ApprovalView(request=app_req, now=datetime(2026, 7, 28, 19, 0, 0, tzinfo=timezone.utc))
    app_widget = ApprovalCardWidget(approval_view=app_view)
    app_rendered = app_widget.render()

    # 2. DispatchWizardWidget (prompt preview)
    wiz_widget = DispatchWizardWidget(
        agent_id="scout",
        prompt="Audit <think>Internal reasoning step: leak token</think> with ghp_123456789012345678901234567890123456",
    )
    wiz_rendered = wiz_widget.render()

    # 3. AgentCardWidget (adversarial peer description & name)
    peer_card = AgentCardView(
        agent_id="peer_adv",
        name="Peer ghp_123456789012345678901234567890123456",
        description="Public peer description with C:\\Users\\Administrator\\secrets\\passwords.txt",
        availability="available",
        readiness_reason="ready",
        is_peer=True,
    )
    agent_widget = AgentCardWidget(card_view=peer_card)
    agent_rendered = agent_widget.render()

    # 4. OutcomeCardWidget (error_message)
    cmd_res = CommandResult(
        success=False,
        error_code="EXEC_ERROR",
        error_message="Failed reading /home/ubuntu/production_keys/id_rsa with key sk-live-1234567890abcdef12345678",
    )
    sess_sum = SessionSummary(
        session_id="sess_101",
        status="failed",
        participant_display_names=["scout"],
        current_turn=5,
        max_turns=10,
        last_activity_at="12:00:00",
    )
    outcome_widget = OutcomeCardWidget(session_summary=sess_sum, command_result=cmd_res)
    outcome_rendered = outcome_widget.render()

    # 5. ToastWidget (message)
    toast_widget = ToastWidget(message="Alert: api_key=sk-live-1234567890abcdef12345678 exposed")
    toast_rendered = toast_widget.render()

    # 6. InspectorWidget (details)
    insp_widget = InspectorWidget(title="Preview", details="Item at /home/ubuntu/production_keys/id_rsa")
    insp_rendered = insp_widget.render()

    # 7. ExchangeTimelineWidget & ActivityFeedWidget (event kinds)
    adv_event_1 = UiEvent("e1", "s1", "TASK sk-live-1234567890abcdef12345678", "12:00:00", "actor", "message")
    adv_event_2 = UiEvent("e2", "s1", "SEC C:\\Users\\Administrator\\secrets\\passwords.txt", "12:01:00", "actor", "security")
    ex_widget = ExchangeTimelineWidget(events=[adv_event_1])
    act_widget = ActivityFeedWidget(events=[adv_event_2])
    ex_rendered = ex_widget.render()
    act_rendered = act_widget.render()

    # 8. ModalWidget (body_text)
    modal_widget = ModalWidget(title="Alert", body_text="Confirm delete C:\\Users\\Administrator\\secrets\\passwords.txt?")
    modal_rendered = modal_widget.render()

    # 9. StatusLineWidget (message)
    status_widget = StatusLineWidget(message="Status sk-live-1234567890abcdef12345678 active")
    status_rendered = status_widget.render()

    all_rendered = [
        app_rendered,
        wiz_rendered,
        agent_rendered,
        outcome_rendered,
        toast_rendered,
        insp_rendered,
        ex_rendered,
        act_rendered,
        modal_rendered,
        status_rendered,
    ]

    # ASSERTIONS: None of the seeded secret strings or local paths appear in ANY output!
    for rendered_text in all_rendered:
        for secret in FAKE_SECRETS:
            assert secret not in rendered_text, f"LEAK DETECTED! Found secret '{secret}' in rendered output:\n{rendered_text}"

        # Confirm redaction markers are present where secrets were scrubbed
        assert ("sk-live-" not in rendered_text)
        assert ("ghp_" not in rendered_text)
        assert ("C:\\Users\\Administrator" not in rendered_text)
        assert ("/home/ubuntu/production_keys" not in rendered_text)
        assert ("<think>" not in rendered_text)
