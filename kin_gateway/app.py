"""FastAPI data-plane application for the first transparent A2A slice."""

import asyncio
import json
import re

from collections.abc import Mapping

import httpx

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from packaging.version import InvalidVersion, Version

from a2a.utils.error_handlers import build_rest_error_payload
from a2a.utils.errors import VersionNotSupportedError

from kin_gateway.agent_card import (
    AGENT_CARD_PATH,
    JSONRPC_PATH,
    REST_PATH,
    AgentCardMirror,
    AgentCardMirrorError,
    TargetResolver,
)
from kin_gateway.config import GatewaySettings
from kin_gateway.sessions import (
    ExternalTaskSessionObserver,
    ExternalTaskSessionTracker,
)
from kin_gateway.upstream.credentials import (
    RequestContext,
    SecretProvider,
    UpstreamCredentialProvider,
    UpstreamCredentialError,
    build_upstream_credential_provider,
)


_FORWARDED_REQUEST_HEADERS = (
    "content-type",
    "accept",
    "a2a-version",
    "a2a-extensions",
    "last-event-id",
)
_FORWARDED_RESPONSE_HEADERS = (
    "content-type",
    "cache-control",
    "a2a-version",
    "etag",
    "content-location",
    "retry-after",
    "content-encoding",
)
_SUPPORTED_A2A_VERSION = Version("1.0")


def _selected_headers(
    headers: Mapping[str, str], allowed: tuple[str, ...]
) -> dict[str, str]:
    """Copy only protocol headers explicitly allowed across the trust boundary."""

    return {name: headers[name] for name in allowed if name in headers}


def _supports_a2a_version(value: str | None) -> bool:
    """Accept the pinned major/minor profile while ignoring patch versions."""

    if not value:
        return False
    try:
        actual = Version(value)
    except InvalidVersion:
        return False
    return actual.release[:2] == _SUPPORTED_A2A_VERSION.release[:2]


def _version_error(request_id: object) -> JSONResponse:
    """Return the A2A 1.0 JSON-RPC version error without calling upstream."""

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32009,
                "message": "Version not supported",
            },
        }
    )


def _rest_version_error() -> JSONResponse:
    """Return the SDK's native HTTP+JSON version error representation."""

    return JSONResponse(
        build_rest_error_payload(VersionNotSupportedError()),
        status_code=400,
    )


def _is_nonstreaming_rest_operation(method: str, path: str) -> bool:
    """Expose only the CP0 REST operations implemented by this slice."""

    if (method, path) in {("POST", "message:send"), ("GET", "tasks")}:
        return True
    if method == "GET" and re.fullmatch(r"tasks/[^/]+", path):
        return True
    return bool(
        method == "POST" and re.fullmatch(r"tasks/[^/]+:cancel", path)
    )


def _is_streaming_rest_operation(method: str, path: str) -> bool:
    """Recognize only A2A 1.0 stream and task-subscription resources."""

    if method == "POST" and path == "message:stream":
        return True
    return bool(
        method in {"GET", "POST"}
        and re.fullmatch(r"tasks/[^/]+:subscribe", path)
    )


def create_gateway_app(
    settings: GatewaySettings,
    *,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    secret_provider: SecretProvider | None = None,
    agent_card_resolver: TargetResolver | None = None,
    upstream_credential_provider: UpstreamCredentialProvider | None = None,
    session_observer: ExternalTaskSessionObserver | None = None,
) -> FastAPI:
    """Create a gateway data plane with an injectable upstream HTTP boundary."""

    app = FastAPI(title="KIN Gateway", version="0.1.0.dev0")

    if upstream_credential_provider is not None and (
        secret_provider is not None
        or settings.upstream_credential.mode != "private"
    ):
        raise ValueError(
            "Explicit credential provider cannot be combined with credential settings"
        )
    credential_provider = upstream_credential_provider or (
        build_upstream_credential_provider(
            settings.upstream_credential,
            secret_provider,
        )
    )
    agent_card_mirror = AgentCardMirror(
        settings,
        transport=upstream_transport,
        credential_provider=credential_provider,
        resolver=agent_card_resolver,
    )

    def upstream_client(headers: Mapping[str, str]) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=settings.upstream_base_url,
            transport=upstream_transport,
            headers=headers,
        )

    async def streaming_upstream_response(
        *,
        method: str,
        url: str | httpx.URL,
        body: bytes,
        headers: Mapping[str, str],
        session: ExternalTaskSessionTracker,
    ) -> Response:
        """Keep the upstream client open exactly as long as the downstream stream."""

        client: httpx.AsyncClient | None = None
        try:
            credential_headers = await credential_provider.headers_for(
                RequestContext(method=method, url=str(url))
            )
            client = upstream_client(credential_headers)
            upstream_request = client.build_request(
                method,
                url,
                content=body,
                headers=headers,
            )
            upstream_response = await client.send(
                upstream_request,
                stream=True,
            )
        except (httpx.HTTPError, UpstreamCredentialError) as exc:
            if client is not None:
                await client.aclose()
            await session.complete("upstream_unavailable")
            raise HTTPException(
                status_code=502,
                detail="Protected A2A upstream is unavailable",
            ) from exc

        async def forward_body():
            outcome = "forwarded"
            try:
                iterator = upstream_response.aiter_raw().__aiter__()
                while True:
                    try:
                        async with asyncio.timeout(
                            settings.stream_read_timeout_seconds
                        ):
                            chunk = await anext(iterator)
                    except StopAsyncIteration:
                        break
                    yield chunk
            except TimeoutError:
                outcome = "upstream_timeout"
                raise
            except asyncio.CancelledError:
                outcome = "client_disconnected"
                raise
            except httpx.HTTPError:
                outcome = "upstream_disconnected"
                raise
            finally:
                try:
                    await upstream_response.aclose()
                    await client.aclose()
                finally:
                    await session.complete(outcome)

        return StreamingResponse(
            forward_body(),
            status_code=upstream_response.status_code,
            headers=_selected_headers(
                upstream_response.headers,
                _FORWARDED_RESPONSE_HEADERS,
            ),
        )

    @app.get(AGENT_CARD_PATH)
    async def mirrored_agent_card(response: Response) -> dict[str, object]:
        try:
            snapshot = await agent_card_mirror.public_card()
        except AgentCardMirrorError as exc:
            raise HTTPException(
                status_code=502,
                detail="Upstream Agent Card is unavailable or invalid",
            ) from exc
        response.headers["ETag"] = f'"sha256-{snapshot.public_sha256}"'
        response.headers[
            "X-KIN-Upstream-Agent-Card-SHA256"
        ] = snapshot.source_sha256
        response.headers["Cache-Control"] = (
            f"public, max-age={int(settings.agent_card.cache_ttl_seconds)}"
        )
        return snapshot.document

    @app.post(JSONRPC_PATH)
    async def proxy_jsonrpc(request: Request) -> Response:
        body = await request.body()
        try:
            jsonrpc_request = json.loads(body)
        except (ValueError, TypeError):
            jsonrpc_request = {}
        request_method = "POST"
        if isinstance(jsonrpc_request, dict) and isinstance(
            jsonrpc_request.get("method"), str
        ):
            request_method = jsonrpc_request["method"]
        upstream_url = f"{settings.upstream_base_url}{JSONRPC_PATH}"
        session = ExternalTaskSessionTracker(
            observer=session_observer,
            transport="JSONRPC",
            request_method=request_method,
            target=JSONRPC_PATH,
            upstream=settings.upstream_base_url,
            headers=request.headers,
            body=body,
        )
        if not _supports_a2a_version(request.headers.get("a2a-version")):
            request_id = (
                jsonrpc_request.get("id")
                if isinstance(jsonrpc_request, dict)
                else None
            )
            response = _version_error(request_id)
            await session.complete("unsupported_version")
            return response

        headers = _selected_headers(request.headers, _FORWARDED_REQUEST_HEADERS)
        if isinstance(jsonrpc_request, dict) and jsonrpc_request.get("method") in {
            "SendStreamingMessage",
            "SubscribeToTask",
        }:
            return await streaming_upstream_response(
                method="POST",
                url=upstream_url,
                body=body,
                headers=headers,
                session=session,
            )

        try:
            credential_headers = await credential_provider.headers_for(
                RequestContext(
                    method="POST",
                    url=upstream_url,
                )
            )
            async with upstream_client(credential_headers) as client:
                upstream_response = await client.post(
                    JSONRPC_PATH,
                    content=body,
                    headers=headers,
                )
        except (httpx.HTTPError, UpstreamCredentialError) as exc:
            await session.complete("upstream_unavailable")
            raise HTTPException(
                status_code=502,
                detail="Protected A2A upstream is unavailable",
            ) from exc

        await session.complete(
            "forwarded",
            response_body=upstream_response.content,
        )
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=_selected_headers(
                upstream_response.headers,
                _FORWARDED_RESPONSE_HEADERS,
            ),
        )

    @app.api_route(
        f"{REST_PATH}/{{rest_path:path}}",
        methods=["GET", "POST"],
    )
    async def proxy_rest(rest_path: str, request: Request) -> Response:
        raw_path = request.scope.get("raw_path", request.url.path.encode("ascii"))
        query_string = request.scope.get("query_string", b"")
        target = raw_path.decode("ascii")
        if query_string:
            target = f"{target}?{query_string.decode('ascii')}"
        upstream_url = httpx.URL(settings.upstream_base_url).join(
            raw_path.decode("ascii")
        )
        upstream_url = upstream_url.copy_with(query=query_string)
        body = await request.body()
        session = ExternalTaskSessionTracker(
            observer=session_observer,
            transport="HTTP+JSON",
            request_method=request.method,
            target=target,
            upstream=settings.upstream_base_url,
            headers=request.headers,
            body=body,
        )
        is_streaming = _is_streaming_rest_operation(request.method, rest_path)
        if not (
            is_streaming
            or _is_nonstreaming_rest_operation(request.method, rest_path)
        ):
            await session.complete("unsupported_operation")
            raise HTTPException(status_code=404, detail="A2A operation is unsupported")
        if not _supports_a2a_version(request.headers.get("a2a-version")):
            response = _rest_version_error()
            await session.complete("unsupported_version")
            return response

        headers = _selected_headers(request.headers, _FORWARDED_REQUEST_HEADERS)

        if is_streaming:
            return await streaming_upstream_response(
                method=request.method,
                url=upstream_url,
                body=body,
                headers=headers,
                session=session,
            )

        try:
            credential_headers = await credential_provider.headers_for(
                RequestContext(method=request.method, url=str(upstream_url))
            )
            async with upstream_client(credential_headers) as client:
                upstream_response = await client.request(
                    request.method,
                    upstream_url,
                    content=body,
                    headers=headers,
                )
        except (httpx.HTTPError, UpstreamCredentialError) as exc:
            await session.complete("upstream_unavailable")
            raise HTTPException(
                status_code=502,
                detail="Protected A2A upstream is unavailable",
            ) from exc

        await session.complete(
            "forwarded",
            response_body=upstream_response.content,
        )
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=_selected_headers(
                upstream_response.headers,
                _FORWARDED_RESPONSE_HEADERS,
            ),
        )

    return app
