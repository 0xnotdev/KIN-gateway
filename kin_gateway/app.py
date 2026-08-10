"""FastAPI data-plane application for the first transparent A2A slice."""

from collections.abc import Mapping

import httpx

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict, ParseDict
from packaging.version import InvalidVersion, Version

from a2a.types import AgentCard
from a2a.utils.proto_utils import validate_proto_required_fields

from kin_gateway.config import GatewaySettings
from kin_gateway.upstream.credentials import SecretProvider, resolve_upstream_headers


AGENT_CARD_PATH = "/.well-known/agent-card.json"
JSONRPC_PATH = "/a2a/jsonrpc"
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
) -> FastAPI:
    """Create a gateway data plane with an injectable upstream HTTP boundary."""

    app = FastAPI(title="KIN Gateway", version="0.1.0.dev0")

    def upstream_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=settings.upstream_base_url,
            transport=upstream_transport,
            headers=resolve_upstream_headers(
                settings.upstream_credential,
                secret_provider,
            ),
        )

    @app.get(AGENT_CARD_PATH)
    async def mirrored_agent_card() -> dict[str, object]:
        try:
            async with upstream_client() as client:
                response = await client.get(AGENT_CARD_PATH)
                response.raise_for_status()
                card = ParseDict(response.json(), AgentCard())
                validate_proto_required_fields(card)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail="Upstream Agent Card is unavailable or invalid",
            ) from exc

        public_interfaces = []
        for interface in card.supported_interfaces:
            if (
                interface.protocol_binding == "JSONRPC"
                and interface.protocol_version == "1.0"
            ):
                interface.url = f"{settings.public_base_url}{JSONRPC_PATH}"
                public_interfaces.append(interface)

        if not public_interfaces:
            raise HTTPException(
                status_code=502,
                detail="Upstream does not expose the A2A 1.0 JSON-RPC profile",
            )

        del card.supported_interfaces[:]
        card.supported_interfaces.extend(public_interfaces)
        return MessageToDict(card)

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
            async with upstream_client() as client:
                upstream_response = await client.post(
                    JSONRPC_PATH,
                    content=body,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
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
