"""Credential separation at the external-to-customer trust boundary."""

import httpx
import pytest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict

from kin_gateway.app import create_gateway_app
from kin_gateway.config import (
    AgentCardMirrorSettings,
    GatewaySettings,
    UpstreamCredentialSettings,
)
from kin_gateway.upstream.credentials import (
    MappingSecretProvider,
    StaticHeaderCredentialProvider,
)
from tests.contract.reference_agent import build_reference_agent


@pytest.mark.asyncio
async def test_external_bearer_is_replaced_by_customer_upstream_credential() -> None:
    upstream_authorization: list[str | None] = []
    upstream_app = FastAPI()

    @upstream_app.post("/a2a/jsonrpc")
    async def upstream_jsonrpc(request: Request) -> JSONResponse:
        upstream_authorization.append(request.headers.get("authorization"))
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": "credential-probe",
                "result": {"message": {}},
            }
        )

    gateway_app = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
            upstream_credential=UpstreamCredentialSettings(
                mode="header",
                header_name="Authorization",
                secret_ref="protected-agent-token",
                value_prefix="Bearer ",
            ),
        ),
        upstream_transport=httpx.ASGITransport(app=upstream_app),
        secret_provider=MappingSecretProvider(
            {"protected-agent-token": "customer-local-token"}
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app),
        base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/a2a/jsonrpc",
            headers={
                "A2A-Version": "1.0",
                "Authorization": "Bearer external-caller-token",
            },
            json={
                "jsonrpc": "2.0",
                "id": "credential-probe",
                "method": "SendMessage",
                "params": {},
            },
        )

    assert response.status_code == 200
    assert upstream_authorization == ["Bearer customer-local-token"]


@pytest.mark.asyncio
async def test_static_provider_supplies_authority_per_upstream_request() -> None:
    """An injected static provider follows the same async request-time contract."""

    upstream_authorization: list[str | None] = []
    upstream_app = FastAPI()

    @upstream_app.post("/a2a/jsonrpc")
    async def upstream_jsonrpc(request: Request) -> JSONResponse:
        upstream_authorization.append(request.headers.get("authorization"))
        return JSONResponse(
            {"jsonrpc": "2.0", "id": "static-probe", "result": {}}
        )

    gateway_app = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
        ),
        upstream_transport=httpx.ASGITransport(app=upstream_app),
        upstream_credential_provider=StaticHeaderCredentialProvider(
            header_name="Authorization",
            header_value="Bearer customer-static-token",
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app),
        base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/a2a/jsonrpc",
            headers={
                "A2A-Version": "1.0",
                "Authorization": "Bearer external-caller-token",
            },
            json={
                "jsonrpc": "2.0",
                "id": "static-probe",
                "method": "SendMessage",
                "params": {},
            },
        )

    assert response.status_code == 200
    assert upstream_authorization == ["Bearer customer-static-token"]


@pytest.mark.asyncio
async def test_upstream_secret_canary_cannot_appear_in_public_agent_card() -> None:
    """Even malicious upstream content cannot reflect customer authority publicly."""

    _, card = build_reference_agent(base_url="http://upstream")
    card.description = "debug credential: Bearer customer-secret-canary"
    gateway_app = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
            upstream_credential=UpstreamCredentialSettings(
                mode="header",
                header_name="Authorization",
                secret_ref="protected-agent-token",
                value_prefix="Bearer ",
            ),
            agent_card=AgentCardMirrorSettings(
                approved_skill_ids=frozenset({"inventory.lookup"}),
                trusted_private_hosts=frozenset({"upstream"}),
            ),
        ),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=MessageToDict(card))
        ),
        secret_provider=MappingSecretProvider(
            {"protected-agent-token": "customer-secret-canary"}
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app),
        base_url="http://gateway",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 502
    assert "customer-secret-canary" not in response.text


@pytest.mark.asyncio
async def test_unavailable_upstream_secret_fails_closed_before_upstream() -> None:
    """Credential resolution failure is a gateway error, never a bare upstream call."""

    upstream_calls: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(str(request.url))
        return httpx.Response(200, json={})

    gateway_app = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
            upstream_credential=UpstreamCredentialSettings(
                mode="header",
                header_name="Authorization",
                secret_ref="missing-token",
                value_prefix="Bearer ",
            ),
        ),
        upstream_transport=httpx.MockTransport(upstream),
        secret_provider=MappingSecretProvider({}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app),
        base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/a2a/jsonrpc",
            headers={"A2A-Version": "1.0"},
            json={
                "jsonrpc": "2.0",
                "id": "missing-secret-probe",
                "method": "SendMessage",
                "params": {},
            },
        )

    assert response.status_code == 502
    assert upstream_calls == []
