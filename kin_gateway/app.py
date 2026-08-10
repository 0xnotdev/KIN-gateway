"""FastAPI data-plane application for the first transparent A2A slice."""

from collections.abc import Mapping

import httpx

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from packaging.version import InvalidVersion, Version

from kin_gateway.agent_card import (
    AGENT_CARD_PATH,
    JSONRPC_PATH,
    AgentCardMirror,
    AgentCardMirrorError,
    TargetResolver,
)
from kin_gateway.config import GatewaySettings
from kin_gateway.upstream.credentials import (
    RequestContext,
    SecretProvider,
    UpstreamCredentialProvider,
    UpstreamCredentialError,
    build_upstream_credential_provider,
)


_FORWARDED_REQUEST_HEADERS = ("content-type", "a2a-version", "a2a-extensions")
_FORWARDED_RESPONSE_HEADERS = ("content-type", "cache-control")
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


def create_gateway_app(
    settings: GatewaySettings,
    *,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    secret_provider: SecretProvider | None = None,
    agent_card_resolver: TargetResolver | None = None,
    upstream_credential_provider: UpstreamCredentialProvider | None = None,
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
        if not _supports_a2a_version(request.headers.get("a2a-version")):
            try:
                request_id = (await request.json()).get("id")
            except (ValueError, AttributeError):
                request_id = None
            return _version_error(request_id)

        headers = _selected_headers(request.headers, _FORWARDED_REQUEST_HEADERS)

        try:
            credential_headers = await credential_provider.headers_for(
                RequestContext(
                    method="POST",
                    url=f"{settings.upstream_base_url}{JSONRPC_PATH}",
                )
            )
            async with upstream_client(credential_headers) as client:
                upstream_response = await client.post(
                    JSONRPC_PATH,
                    content=body,
                    headers=headers,
                )
        except (httpx.HTTPError, UpstreamCredentialError) as exc:
            raise HTTPException(
                status_code=502,
                detail="Protected A2A upstream is unavailable",
            ) from exc

        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=_selected_headers(
                upstream_response.headers,
                _FORWARDED_RESPONSE_HEADERS,
            ),
        )

    return app
