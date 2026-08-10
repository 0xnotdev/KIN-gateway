"""Official HTTP+JSON client behavior through the transparent gateway."""

import httpx
import pytest

from a2a.client import ClientConfig, create_client
from a2a.helpers import get_artifact_text
from a2a.server.context import ServerCallContext
from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
    Task,
    TaskState,
    TaskStatus,
)

from kin_gateway.app import create_gateway_app
from kin_gateway.config import AgentCardMirrorSettings, GatewaySettings
from tests.contract.reference_agent import build_reference_agent


@pytest.mark.asyncio
async def test_official_rest_client_sends_task_through_gateway() -> None:
    """Neither official endpoint is modified when KIN proxies HTTP+JSON."""

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
                supported_protocol_bindings=["HTTP+JSON"],
            ),
        )
        request = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                message_id="33333333-3333-4333-8333-333333333333",
                parts=[Part(text="widget-43")],
            )
        )

        responses = [event async for event in client.send_message(request)]

        assert len(responses) == 1
        task = responses[0].task
        assert task.status.state == TaskState.TASK_STATE_COMPLETED
        assert get_artifact_text(task.artifacts[0]) == "inventory:widget-43:available"
        await client.close()


@pytest.mark.asyncio
async def test_official_rest_client_gets_lists_and_cancels_through_gateway() -> None:
    """REST task resource paths and query semantics remain official A2A."""

    upstream_app, _ = build_reference_agent(base_url="http://upstream")
    task = Task(
        id="cancelable-task",
        context_id="rest-context",
        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
    )
    await upstream_app.state.a2a_handler.task_store.save(
        task,
        ServerCallContext(),
    )
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
                supported_protocol_bindings=["HTTP+JSON"],
            ),
        )

        fetched = await client.get_task(GetTaskRequest(id=task.id))
        listed = await client.list_tasks(ListTasksRequest(page_size=10))
        cancelled = await client.cancel_task(CancelTaskRequest(id=task.id))

        assert fetched.id == task.id
        assert [item.id for item in listed.tasks] == [task.id]
        assert cancelled.id == task.id
        assert cancelled.status.state == TaskState.TASK_STATE_CANCELED
        await client.close()


@pytest.mark.asyncio
async def test_rest_unsupported_version_stops_before_upstream() -> None:
    """REST uses the SDK-native version error and never probes the origin."""

    upstream_calls: list[str] = []
    gateway_app = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
        ),
        upstream_transport=httpx.MockTransport(
            lambda request: (
                upstream_calls.append(str(request.url))
                or httpx.Response(200, json={})
            )
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app),
        base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/a2a/rest/message:send",
            headers={"A2A-Version": "99.0"},
            json={},
        )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "FAILED_PRECONDITION"
    assert response.json()["error"]["details"][0]["reason"] == (
        "VERSION_NOT_SUPPORTED"
    )
    assert upstream_calls == []


@pytest.mark.asyncio
async def test_rest_query_status_body_and_protocol_headers_are_preserved() -> None:
    """The buffered REST adapter changes neither resource semantics nor bytes."""

    upstream_requests: list[httpx.Request] = []
    response_body = b'{"tasks":[],"nextPageToken":"a+b"}'

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_requests.append(request)
        return httpx.Response(
            200,
            content=response_body,
            headers={
                "Content-Type": "application/json",
                "ETag": '"task-list-v1"',
                "A2A-Version": "1.0",
            },
        )

    gateway_app = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
        ),
        upstream_transport=httpx.MockTransport(upstream),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app),
        base_url="http://gateway",
    ) as client:
        response = await client.get(
            "/a2a/rest/tasks?pageSize=7&pageToken=a%2Bb",
            headers={
                "A2A-Version": "1.0",
                "Authorization": "Bearer external-data-token",
            },
        )

    assert response.status_code == 200
    assert response.content == response_body
    assert response.headers["etag"] == '"task-list-v1"'
    assert response.headers["a2a-version"] == "1.0"
    assert upstream_requests[0].url.query == b"pageSize=7&pageToken=a%2Bb"
    assert upstream_requests[0].headers.get("authorization") is None
