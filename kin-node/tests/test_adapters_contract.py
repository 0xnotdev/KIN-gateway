"""Unit tests for adapter contract, schemas, and factory (§15.7)."""

from __future__ import annotations

import sys
import types

import httpx
import pytest
from pydantic import ValidationError

from kin.adapters import (
    AdapterActivityEvent,
    AdapterApprovalEvent,
    AdapterErrorEvent,
    AdapterRequest,
    AdapterResponse,
    get_adapter,
)
from kin.adapters.embedded import EmbeddedAdapter
from kin.adapters.local_command import LocalCommandAdapter
from kin.adapters.sdk import SdkAdapter
from kin.adapters.webhook import WebhookAdapter
from kin.schemas import (
    ActionClass,
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    ApprovalRequest,
    AutonomyLevel,
    EmbeddedAdapterConfig,
    LocalCommandAdapterConfig,
    SdkAdapterConfig,
    WebhookAdapterConfig,
)


def _make_card(adapter_type: str) -> AgentCard:
    if adapter_type == "embedded":
        adapter_cfg = EmbeddedAdapterConfig(type="embedded", provider="openai", model="gpt-4o")
    elif adapter_type == "webhook":
        adapter_cfg = WebhookAdapterConfig(type="webhook", webhook_url="https://agent.example.com/webhook", credential_ref="cred_1")
    elif adapter_type == "local_command":
        adapter_cfg = LocalCommandAdapterConfig(type="local_command", command="echo test", working_directory="/tmp")
    elif adapter_type == "sdk":
        adapter_cfg = SdkAdapterConfig(type="sdk", entry_point="pkg.module:Agent")

    return AgentCard(
        schema_version="1.1",
        id="test_ag",
        name="Test Agent",
        description="Test Agent Description",
        adapter=adapter_cfg,
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="none", shell="deny", max_runtime_seconds=30, max_artifact_bytes=1048576),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ALLOW, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )


def test_adapter_factory_dispatch():
    c_emb = _make_card("embedded")
    a_emb = get_adapter(c_emb)
    assert isinstance(a_emb, EmbeddedAdapter)

    c_web = _make_card("webhook")
    a_web = get_adapter(c_web)
    assert isinstance(a_web, WebhookAdapter)

    c_cmd = _make_card("local_command")
    a_cmd = get_adapter(c_cmd)
    assert isinstance(a_cmd, LocalCommandAdapter)

    c_sdk = _make_card("sdk")
    assert isinstance(get_adapter(c_sdk), SdkAdapter)


def test_adapter_request_schema_validation():
    req = AdapterRequest(
        schema_version="1.1",
        protocol_version="1.1",
        session={"id": "s1", "type": "ask", "turn": 1},
        self_participant={"agent_id": "a1", "card_snapshot": {}},
        peer={"person": "bob", "agent_id": "b1", "card_snapshot": {}},
        objective="Test objective",
    )
    assert req.schema_version == "1.1"

    with pytest.raises(ValidationError):
        AdapterRequest(
            session={"id": "s1"},
            self_participant={},
            peer={},
            objective="test",
            extra_field="forbidden",
        )


def test_sdk_adapter_invokes_owner_entry_point_through_normalized_contract():
    module = types.ModuleType("pkg.module")

    def agent(request):
        assert isinstance(request, AdapterRequest)
        return {
            "schema_version": "1.1",
            "protocol_version": "1.1",
            "events": [{"event_kind": "activity", "label": "SDK work complete"}],
            "message": {"kind": "proposal", "content": request.objective},
        }

    module.Agent = agent
    sys.modules["pkg"] = types.ModuleType("pkg")
    sys.modules["pkg.module"] = module
    try:
        adapter = get_adapter(_make_card("sdk"))
        response = adapter.invoke(
            AdapterRequest(
                session={"id": "s1", "type": "ask", "turn": 1},
                self_participant={"agent_id": "test_ag", "card_snapshot": {}},
                peer={"person": "bob", "agent_id": "bob_agent", "card_snapshot": {}},
                objective="bounded SDK objective",
            )
        )
    finally:
        sys.modules.pop("pkg.module", None)
        sys.modules.pop("pkg", None)

    assert response.message is not None
    assert response.message.content == "bounded SDK objective"
    assert response.events[0].label == "SDK work complete"


def test_webhook_adapter_uses_validated_webhook_url(monkeypatch):
    observed = {}

    def post(self, url, **kwargs):
        observed["url"] = url
        return httpx.Response(
            200,
            json={
                "schema_version": "1.1",
                "protocol_version": "1.1",
                "message": {"kind": "proposal", "content": "webhook result"},
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    response = get_adapter(_make_card("webhook")).invoke(
        AdapterRequest(
            session={"id": "s1", "type": "ask", "turn": 1},
            self_participant={"agent_id": "test_ag", "card_snapshot": {}},
            peer={"person": "bob", "agent_id": "bob_agent", "card_snapshot": {}},
            objective="call the configured webhook",
        )
    )

    assert observed["url"] == "https://agent.example.com/webhook"
    assert response.message is not None and response.message.content == "webhook result"


from kin.schemas import RiskLabel

def test_adapter_event_discriminated_union():
    act = AdapterActivityEvent(label="Doing work")
    assert act.event_kind == "activity"

    req_ev = AdapterApprovalEvent(
        approval_request=ApprovalRequest(
            schema_version="1.1",
            approval_id="app_1",
            session_id="s1",
            agent_id="test_ag",
            action_class=ActionClass.WORKSPACE_WRITE,
            summary="Writing file",
            reason="Writing file to workspace",
            risk_label=RiskLabel.MEDIUM,
            requested_scope={"path": "/path/to/file"},
            expires_at="2026-07-22T12:00:00Z",
        )
    )
    assert req_ev.event_kind == "approval_request"

    err = AdapterErrorEvent(code="ERR", message="Failed")
    assert err.event_kind == "error"
