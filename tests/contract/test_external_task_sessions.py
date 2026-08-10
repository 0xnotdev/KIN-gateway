"""Observer-only ExternalTaskSession records for the CP0 proxy seam."""

from dataclasses import fields
from uuid import UUID

import httpx
import pytest

from kin_gateway.app import create_gateway_app
from kin_gateway.config import GatewaySettings
from kin_gateway.sessions import ExternalTaskSession


class RecordingSessionObserver:
    """Collect completed records without participating in proxy decisions."""

    def __init__(self) -> None:
        self.sessions: list[ExternalTaskSession] = []

    async def record(self, session: ExternalTaskSession) -> None:
        self.sessions.append(session)


class FailingSessionObserver:
    """Prove an unavailable observer cannot alter A2A behavior."""

    async def record(self, session: ExternalTaskSession) -> None:
        raise RuntimeError("observer storage is unavailable")


def gateway_settings() -> GatewaySettings:
    return GatewaySettings(
        public_base_url="http://gateway",
        upstream_base_url="http://upstream",
    )


@pytest.mark.asyncio
async def test_jsonrpc_session_has_only_cp0_fields_and_preserves_response() -> None:
    """Observation records the task without changing the upstream response."""

    observer = RecordingSessionObserver()
    response_body = (
        b'{"jsonrpc":"2.0","id":"request-1","result":'
        b'{"task":{"id":"task-42","status":{"state":"TASK_STATE_COMPLETED"}}}}'
    )
    gateway = create_gateway_app(
        gateway_settings(),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                202,
                content=response_body,
                headers={
                    "Content-Type": "application/json",
                    "ETag": '"task-42"',
                },
            )
        ),
        session_observer=observer,
    )
    request_body = {
        "jsonrpc": "2.0",
        "id": "request-1",
        "method": "SendMessage",
        "params": {"message": {"messageId": "message-42"}},
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/a2a/jsonrpc",
            headers={"A2A-Version": "1.0"},
            json=request_body,
        )

    assert response.status_code == 202
    assert response.content == response_body
    assert response.headers["etag"] == '"task-42"'
    assert len(observer.sessions) == 1
    session = observer.sessions[0]
    assert [field.name for field in fields(session)] == [
        "session_id",
        "a2a_task_id",
        "transport",
        "request_method",
        "request_hash",
        "upstream",
        "started_at",
        "ended_at",
        "outcome",
    ]
    assert UUID(session.session_id).version == 4
    assert session.a2a_task_id == "task-42"
    assert session.transport == "JSONRPC"
    assert session.request_method == "SendMessage"
    assert len(session.request_hash) == 64
    assert int(session.request_hash, 16) >= 0
    assert session.upstream == "http://upstream"
    assert session.started_at.tzinfo is not None
    assert session.ended_at.tzinfo is not None
    assert session.ended_at >= session.started_at
    assert session.outcome == "forwarded"


@pytest.mark.asyncio
async def test_same_rest_request_has_stable_hash_and_unique_session_id() -> None:
    """Retries correlate by hash while remaining distinct task sessions."""

    observer = RecordingSessionObserver()
    gateway = create_gateway_app(
        gateway_settings(),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b'{"id":"task-rest","status":{"state":"COMPLETED"}}',
                headers={"Content-Type": "application/json"},
            )
        ),
        session_observer=observer,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="http://gateway",
    ) as client:
        first = await client.get(
            "/a2a/rest/tasks/task-rest?historyLength=3",
            headers={
                "A2A-Version": "1.0",
                "Authorization": "Bearer external-token-one",
            },
        )
        second = await client.get(
            "/a2a/rest/tasks/task-rest?historyLength=3",
            headers={
                "A2A-Version": "1.0",
                "Authorization": "Bearer external-token-two",
            },
        )

    assert first.content == second.content
    assert len(observer.sessions) == 2
    assert observer.sessions[0].request_hash == observer.sessions[1].request_hash
    assert observer.sessions[0].session_id != observer.sessions[1].session_id
    assert {session.transport for session in observer.sessions} == {"HTTP+JSON"}
    assert {session.request_method for session in observer.sessions} == {"GET"}
    assert {session.a2a_task_id for session in observer.sessions} == {"task-rest"}
    assert {session.outcome for session in observer.sessions} == {"forwarded"}


@pytest.mark.asyncio
async def test_observer_failure_cannot_change_buffered_a2a_response() -> None:
    """The proxy is fail-open for CP0 observation infrastructure."""

    expected = b'{"tasks":[],"nextPageToken":"opaque"}'
    gateway = create_gateway_app(
        gateway_settings(),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(206, content=expected)
        ),
        session_observer=FailingSessionObserver(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="http://gateway",
    ) as client:
        response = await client.get(
            "/a2a/rest/tasks?pageSize=1",
            headers={"A2A-Version": "1.0"},
        )

    assert response.status_code == 206
    assert response.content == expected


@pytest.mark.asyncio
async def test_upstream_failure_records_outcome_without_fabricating_task_id() -> None:
    """Transport failure is observed even though no A2A response exists."""

    observer = RecordingSessionObserver()

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("origin refused connection", request=request)

    gateway = create_gateway_app(
        gateway_settings(),
        upstream_transport=httpx.MockTransport(unavailable),
        session_observer=observer,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/a2a/jsonrpc",
            headers={"A2A-Version": "1.0"},
            json={
                "jsonrpc": "2.0",
                "id": "request-failure",
                "method": "SendMessage",
                "params": {},
            },
        )

    assert response.status_code == 502
    assert len(observer.sessions) == 1
    assert observer.sessions[0].a2a_task_id is None
    assert observer.sessions[0].outcome == "upstream_unavailable"
