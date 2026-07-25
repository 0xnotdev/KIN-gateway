"""Unit tests for validate_adapter_output security redaction (§15.7 and §2.1)."""

from __future__ import annotations

from kin.adapters.base import (
    AdapterActivityEvent,
    AdapterApprovalEvent,
    AdapterMessage,
    AdapterResponse,
    validate_adapter_output,
)
from kin.schemas import (
    ActionClass,
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    ApprovalRequest,
    AutonomyLevel,
    EmbeddedAdapterConfig,
)


def _make_embedded_card() -> AgentCard:
    return AgentCard(
        schema_version="1.1",
        id="emb_ag",
        name="Embedded Agent",
        description="Embedded Agent Description",
        adapter=EmbeddedAdapterConfig(type="embedded", provider="openai", model="gpt-4o"),
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="none", shell="deny", max_runtime_seconds=30, max_artifact_bytes=1048576),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ALLOW, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )


def test_validate_output_clean_response():
    card = _make_embedded_card()
    resp = AdapterResponse(
        events=[AdapterActivityEvent(label="Inference complete")],
        message=AdapterMessage(kind="proposal", content="Here is my proposal."),
    )
    outcome = validate_adapter_output(resp, card)
    assert outcome.valid is True
    assert outcome.rejection_reason is None


from kin.schemas import RiskLabel

def test_validate_output_disallowed_capability():
    card = _make_embedded_card()
    # Embedded adapter attempting a WORKSPACE_WRITE approval request (not allowed by embedded capability declaration)
    resp = AdapterResponse(
        events=[
            AdapterApprovalEvent(
                approval_request=ApprovalRequest(
                    schema_version="1.1",
                    approval_id="app_1",
                    session_id="s1",
                    agent_id="emb_ag",
                    action_class=ActionClass.WORKSPACE_WRITE,
                    summary="Writing file",
                    reason="Writing file to workspace",
                    risk_label=RiskLabel.MEDIUM,
                    requested_scope={"path": "/path/to/file"},
                    expires_at="2026-07-22T12:00:00Z",
                )
            )
        ]
    )
    outcome = validate_adapter_output(resp, card)
    assert outcome.valid is False
    assert "disallowed action class 'workspace_write'" in outcome.rejection_reason


def test_validate_output_secret_pattern_rejection():
    card = _make_embedded_card()
    # Output containing an API key pattern
    resp = AdapterResponse(
        message=AdapterMessage(kind="proposal", content="Here is my key: sk-live-abc123def456ghi789jkl0123")
    )
    outcome = validate_adapter_output(resp, card)
    assert outcome.valid is False
    assert "API key or secret token pattern" in outcome.rejection_reason


def test_validate_output_owner_only_kind_rejection():
    from kin.schemas import MessageKind
    card = _make_embedded_card()
    resp = AdapterResponse(
        message=AdapterMessage(kind=MessageKind.CANCEL, content="Unauthorized cancel attempt")
    )
    outcome = validate_adapter_output(resp, card)
    assert outcome.valid is False
    assert "owner-only message kind 'cancel'" in outcome.rejection_reason
