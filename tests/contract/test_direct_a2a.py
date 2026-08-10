"""Prove the official client and reference agent work before KIN insertion."""

import httpx
import pytest

from a2a.client import ClientConfig, create_client
from a2a.helpers import get_artifact_text
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState

from tests.contract.reference_agent import build_reference_agent


@pytest.mark.asyncio
async def test_official_client_calls_reference_agent_directly() -> None:
    app, _ = build_reference_agent()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://reference",
    ) as http_client:
        client = await create_client(
            "http://reference",
            client_config=ClientConfig(
                httpx_client=http_client,
                streaming=False,
                supported_protocol_bindings=["JSONRPC"],
            ),
        )
        request = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                message_id="11111111-1111-4111-8111-111111111111",
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
