"""Public JSON-RPC behavior with KIN inserted between official SDK peers."""

import httpx
import pytest

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from a2a.client import ClientConfig, create_client
from a2a.helpers import get_artifact_text
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState

from kin_gateway.app import create_gateway_app
from kin_gateway.config import AgentCardMirrorSettings, GatewaySettings
from tests.contract.reference_agent import build_reference_agent


@pytest.mark.asyncio
async def test_official_client_calls_reference_agent_through_gateway() -> None:
    upstream_app, _ = build_reference_agent(base_url="http://upstream")
    gateway_app = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
            agent_card=AgentCardMirrorSettings(
                approved_skill_ids=frozenset({"inventory.lookup"}),
                trusted_private_hosts=frozenset({"upstream"}),
            ),
        ),
        upstream_transport=httpx.ASGITransport(app=upstream_app),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app),
        base_url="http://gateway",
    ) as http_client:
        client = await create_client(
            "http://gateway",
            client_config=ClientConfig(
                httpx_client=http_client,
                streaming=False,
                supported_protocol_bindings=["JSONRPC"],
            ),
        )
        request = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                message_id="22222222-2222-4222-8222-222222222222",
                parts=[Part(text="widget-42")],
            )
        )

        responses = [event async for event in client.send_message(request)]

        assert len(responses) == 1
        assert responses[0].HasField("task")
        task = responses[0].task
        assert task.status.state == TaskState.TASK_STATE_COMPLETED
        assert get_artifact_text(task.artifacts[0]) == "inventory:widget-42:available"
        await client.close()


@pytest.mark.asyncio
async def test_unsupported_a2a_version_is_rejected_before_upstream() -> None:
    upstream_calls: list[str] = []
    upstream_app = FastAPI()

    @upstream_app.post("/a2a/jsonrpc")
    async def upstream_jsonrpc() -> JSONResponse:
        upstream_calls.append("called")
        return JSONResponse({"jsonrpc": "2.0", "id": "version-probe", "result": {}})

    gateway_app = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
        ),
        upstream_transport=httpx.ASGITransport(app=upstream_app),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app),
        base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/a2a/jsonrpc",
            headers={"A2A-Version": "99.0"},
            json={
                "jsonrpc": "2.0",
                "id": "version-probe",
                "method": "SendMessage",
                "params": {},
            },
        )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32009
    assert upstream_calls == []
