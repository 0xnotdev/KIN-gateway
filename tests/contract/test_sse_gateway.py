"""Transparent SSE behavior for both A2A HTTP bindings."""

import asyncio

from collections.abc import Awaitable, Callable

import httpx
import pytest

from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState

from kin_gateway.app import create_gateway_app
from kin_gateway.config import AgentCardMirrorSettings, GatewaySettings
from kin_gateway.sessions import ExternalTaskSession
from tests.contract.reference_agent import build_reference_agent


class RecordingStream(httpx.AsyncByteStream):
    """Expose when a synthetic upstream stream is read and closed."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.yielded: list[bytes] = []
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.yielded.append(chunk)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class RecordingSessionObserver:
    """Collect stream-lifecycle records without controlling proxy behavior."""

    def __init__(self) -> None:
        self.sessions: list[ExternalTaskSession] = []

    async def record(self, session: ExternalTaskSession) -> None:
        self.sessions.append(session)


async def invoke_stream_request(
    app,
    send: Callable[[dict[str, object]], Awaitable[None]],
    receive_after_request: Callable[[], Awaitable[dict[str, object]]],
) -> None:
    """Drive the public ASGI seam without a downstream buffering transport."""

    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {
                "type": "http.request",
                "body": b"{}",
                "more_body": False,
            }
        return await receive_after_request()

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/a2a/rest/message:stream",
            "raw_path": b"/a2a/rest/message:stream",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"gateway"),
                (b"a2a-version", b"1.0"),
                (b"content-type", b"application/json"),
                (b"accept", b"text/event-stream"),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("gateway", 80),
        },
        receive,
        send,
    )


@pytest.mark.parametrize("binding", ["JSONRPC", "HTTP+JSON"])
@pytest.mark.asyncio
async def test_official_streaming_client_preserves_event_sequence_through_gateway(
    binding: str,
) -> None:
    """Submitted, artifact, and terminal events cross KIN without synthesis."""

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
                streaming=True,
                supported_protocol_bindings=[binding],
            ),
        )
        request = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                message_id="44444444-4444-4444-8444-444444444444",
                parts=[Part(text="widget-44")],
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


@pytest.mark.asyncio
async def test_sse_bytes_ids_order_and_backpressure_are_preserved() -> None:
    """The adapter starts before reading and forwards every application byte once."""

    chunks = [
        f"id: {index}\r\nevent: update\r\ndata: value-{index}\r\n\r\n".encode()
        for index in range(100)
    ]
    chunks.insert(50, b"malformed-field-without-colon\r\n\r\n")
    chunks.append(b"id: large\r\ndata: " + (b"x" * 65_536) + b"\r\n\r\n")
    upstream_stream = RecordingStream(chunks)
    observer = RecordingSessionObserver()

    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache",
            },
            stream=upstream_stream,
        )

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
        ),
        upstream_transport=httpx.MockTransport(upstream),
        session_observer=observer,
    )
    messages: list[dict[str, object]] = []
    never = asyncio.Event()

    async def receive_after_request() -> dict[str, object]:
        await never.wait()
        raise AssertionError("unreachable")

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            assert upstream_stream.yielded == []
        elif message.get("body"):
            await asyncio.sleep(0.0001)
        messages.append(message)

    await invoke_stream_request(gateway, send, receive_after_request)

    start = messages[0]
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    response_headers = dict(start["headers"])
    assert start["status"] == 200
    assert response_headers[b"content-type"] == (
        b"text/event-stream; charset=utf-8"
    )
    assert body == b"".join(chunks)
    assert upstream_stream.yielded == chunks
    assert upstream_stream.closed is True
    assert len(observer.sessions) == 1
    assert observer.sessions[0].a2a_task_id is None
    assert observer.sessions[0].outcome == "forwarded"


@pytest.mark.asyncio
async def test_client_disconnect_closes_inflight_upstream_stream() -> None:
    """A downstream disconnect cancels the read and releases upstream resources."""

    disconnect = asyncio.Event()

    class InflightStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = False

        async def __aiter__(self):
            yield b"id: first\r\ndata: first\r\n\r\n"
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            self.closed = True

    upstream_stream = InflightStream()
    observer = RecordingSessionObserver()
    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
        ),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=upstream_stream,
            )
        ),
        session_observer=observer,
    )
    downstream_bodies: list[bytes] = []

    async def receive_after_request() -> dict[str, object]:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        body = message.get("body", b"")
        if body:
            downstream_bodies.append(body)
            disconnect.set()

    await asyncio.wait_for(
        invoke_stream_request(gateway, send, receive_after_request),
        timeout=1,
    )

    assert downstream_bodies == [b"id: first\r\ndata: first\r\n\r\n"]
    assert upstream_stream.closed is True
    assert len(observer.sessions) == 1
    assert observer.sessions[0].outcome == "client_disconnected"


@pytest.mark.asyncio
async def test_upstream_disconnect_is_propagated_without_completion_event() -> None:
    """An abrupt origin failure terminates downstream and never invents success."""

    class FailingStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = False

        async def __aiter__(self):
            yield b"id: partial\r\ndata: partial\r\n\r\n"
            raise httpx.ReadError("origin disconnected")

        async def aclose(self) -> None:
            self.closed = True

    upstream_stream = FailingStream()
    observer = RecordingSessionObserver()
    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
        ),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=upstream_stream,
            )
        ),
        session_observer=observer,
    )
    downstream_bodies: list[bytes] = []
    never = asyncio.Event()

    async def receive_after_request() -> dict[str, object]:
        await never.wait()
        raise AssertionError("unreachable")

    async def send(message: dict[str, object]) -> None:
        body = message.get("body", b"")
        if body:
            downstream_bodies.append(body)

    failure: BaseException | None = None
    try:
        await invoke_stream_request(gateway, send, receive_after_request)
    except BaseException as exc:  # the ASGI task group may wrap the read error
        failure = exc

    def contains_read_error(exc: BaseException) -> bool:
        if isinstance(exc, httpx.ReadError):
            return True
        if isinstance(exc, BaseExceptionGroup):
            return any(contains_read_error(item) for item in exc.exceptions)
        return False

    assert failure is not None
    assert contains_read_error(failure)
    assert downstream_bodies == [b"id: partial\r\ndata: partial\r\n\r\n"]
    assert upstream_stream.closed is True
    assert len(observer.sessions) == 1
    assert observer.sessions[0].outcome == "upstream_disconnected"


@pytest.mark.asyncio
async def test_upstream_pause_times_out_without_synthetic_event() -> None:
    """Read timeout starts between events and terminates without changing the stream."""

    class PausingStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = False

        async def __aiter__(self):
            yield b"id: first\r\ndata: first\r\n\r\n"
            await asyncio.sleep(0.1)
            yield b"id: late\r\ndata: late\r\n\r\n"

        async def aclose(self) -> None:
            self.closed = True

    upstream_stream = PausingStream()
    observer = RecordingSessionObserver()
    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
            stream_read_timeout_seconds=0.01,
        ),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=upstream_stream,
            )
        ),
        session_observer=observer,
    )
    downstream_bodies: list[bytes] = []
    never = asyncio.Event()

    async def receive_after_request() -> dict[str, object]:
        await never.wait()
        raise AssertionError("unreachable")

    async def send(message: dict[str, object]) -> None:
        body = message.get("body", b"")
        if body:
            downstream_bodies.append(body)

    failure: BaseException | None = None
    try:
        await invoke_stream_request(gateway, send, receive_after_request)
    except BaseException as exc:
        failure = exc

    def contains_timeout(exc: BaseException) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if isinstance(exc, BaseExceptionGroup):
            return any(contains_timeout(item) for item in exc.exceptions)
        return False

    assert failure is not None
    assert contains_timeout(failure)
    assert downstream_bodies == [b"id: first\r\ndata: first\r\n\r\n"]
    assert upstream_stream.closed is True
    assert len(observer.sessions) == 1
    assert observer.sessions[0].outcome == "upstream_timeout"


@pytest.mark.parametrize(
    ("public_method", "public_path", "request_body", "upstream_path"),
    [
        (
            "GET",
            "/a2a/rest/tasks/task-1:subscribe",
            None,
            "/a2a/rest/tasks/task-1:subscribe",
        ),
        (
            "POST",
            "/a2a/jsonrpc",
            {
                "jsonrpc": "2.0",
                "id": "subscribe-1",
                "method": "SubscribeToTask",
                "params": {"id": "task-1"},
            },
            "/a2a/jsonrpc",
        ),
    ],
)
@pytest.mark.asyncio
async def test_task_subscription_routes_remain_streaming(
    public_method: str,
    public_path: str,
    request_body: dict[str, object] | None,
    upstream_path: str,
) -> None:
    """REST and JSON-RPC task subscriptions use the same unbuffered path."""

    event_bytes = b"id: current\r\ndata: {\"task\":{\"id\":\"task-1\"}}\r\n\r\n"
    upstream_requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_requests.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=RecordingStream([event_bytes]),
        )

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
        ),
        upstream_transport=httpx.MockTransport(upstream),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="http://gateway",
    ) as client:
        response = await client.request(
            public_method,
            public_path,
            headers={"A2A-Version": "1.0", "Accept": "text/event-stream"},
            json=request_body,
        )

    assert response.status_code == 200
    assert response.content == event_bytes
    assert upstream_requests[0].method == public_method
    assert upstream_requests[0].url.path == upstream_path
