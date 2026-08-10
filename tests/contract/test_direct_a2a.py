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


@pytest.mark.parametrize("binding", ["JSONRPC", "HTTP+JSON"])
@pytest.mark.asyncio
async def test_official_streaming_client_calls_reference_agent_directly(
    binding: str,
) -> None:
    """Establish the three-event SDK baseline before KIN insertion."""

    app, _ = build_reference_agent()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://reference",
    ) as http_client:
        client = await create_client(
            "http://reference",
            client_config=ClientConfig(
                httpx_client=http_client,
                streaming=True,
                supported_protocol_bindings=[binding],
            ),
        )
        request = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                message_id="55555555-5555-4555-8555-555555555555",
                parts=[Part(text="widget-45")],
            )
        )

        events = [event async for event in client.send_message(request)]

        assert [event.WhichOneof("payload") for event in events] == [
            "task",
            "artifact_update",
            "status_update",
        ]
        assert events[-1].status_update.status.state == (
            TaskState.TASK_STATE_COMPLETED
        )
        await client.close()
