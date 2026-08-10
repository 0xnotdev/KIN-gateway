"""Credential separation at the external-to-customer trust boundary."""

import httpx
import pytest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kin_gateway.app import create_gateway_app
from kin_gateway.config import GatewaySettings, UpstreamCredentialSettings
from kin_gateway.upstream.credentials import MappingSecretProvider


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
