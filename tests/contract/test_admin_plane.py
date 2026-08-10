"""Network and authentication boundary for bootstrap administration."""

import httpx
import pytest

from kin_gateway.admin import create_admin_app
from kin_gateway.app import create_gateway_app
from kin_gateway.config import AdminPlaneSettings, GatewaySettings
from kin_gateway.upstream.credentials import MappingSecretProvider


@pytest.mark.asyncio
async def test_admin_routes_exist_only_on_authenticated_private_application() -> None:
    """The public listener cannot route to admin, and admin fails closed."""

    secrets = MappingSecretProvider(
        {
            "bootstrap-admin-token": "admin-control-canary",
        }
    )
    gateway_settings = GatewaySettings(
        public_base_url="http://gateway",
        upstream_base_url="http://upstream",
    )
    admin_settings = AdminPlaneSettings(
        token_secret_ref="bootstrap-admin-token"
    )
    public_app = create_gateway_app(
        gateway_settings,
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(500)
        ),
    )
    admin_app = create_admin_app(
        admin_settings,
        secret_provider=secrets,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=public_app),
        base_url="http://gateway",
    ) as public_client:
        public_response = await public_client.get(
            "/admin/health",
            headers={"Authorization": "Bearer admin-control-canary"},
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app),
        base_url="http://admin",
    ) as admin_client:
        missing = await admin_client.get("/admin/health")
        wrong = await admin_client.get(
            "/admin/health",
            headers={"Authorization": "Bearer external-data-token"},
        )
        allowed = await admin_client.get(
            "/admin/health",
            headers={"Authorization": "Bearer admin-control-canary"},
        )

    assert public_response.status_code == 404
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json() == {"status": "ok"}
    assert gateway_settings.port == 8080
    assert admin_settings.bind_host == "127.0.0.1"
    assert admin_settings.port == 9090


@pytest.mark.asyncio
async def test_admin_credential_is_never_forwarded_or_logged(caplog) -> None:
    """Possessing admin authority does not create data-plane upstream authority."""

    admin_token = "admin-do-not-forward-or-log-canary"
    upstream_authorization: list[str | None] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        upstream_authorization.append(request.headers.get("authorization"))
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "admin-canary", "result": {}},
        )

    public_app = create_gateway_app(
        GatewaySettings(
            public_base_url="http://gateway",
            upstream_base_url="http://upstream",
        ),
        upstream_transport=httpx.MockTransport(upstream),
    )
    admin_app = create_admin_app(
        AdminPlaneSettings(token_secret_ref="bootstrap-admin-token"),
        secret_provider=MappingSecretProvider(
            {"bootstrap-admin-token": admin_token}
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app),
        base_url="http://admin",
    ) as client:
        assert (
            await client.get(
                "/admin/health",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        ).status_code == 200

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=public_app),
        base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/a2a/jsonrpc",
            headers={
                "A2A-Version": "1.0",
                "Authorization": f"Bearer {admin_token}",
            },
            json={
                "jsonrpc": "2.0",
                "id": "admin-canary",
                "method": "SendMessage",
                "params": {},
            },
        )

    assert response.status_code == 200
    assert upstream_authorization == [None]
    assert admin_token not in caplog.text


@pytest.mark.asyncio
async def test_mtls_mode_requires_a_verified_peer_certificate() -> None:
    """mTLS mode fails closed unless the serving stack supplies a peer cert."""

    admin_app = create_admin_app(
        AdminPlaneSettings(authentication="mtls"),
    )

    class VerifiedTls:
        def getpeercert(self) -> dict[str, object]:
            return {"subject": (("commonName", "gateway-operator"),)}

    async def verified_app(scope, receive, send) -> None:
        verified_scope = dict(scope)
        verified_scope["ssl_object"] = VerifiedTls()
        await admin_app(verified_scope, receive, send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app),
        base_url="https://admin",
    ) as client:
        missing = await client.get("/admin/health")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=verified_app),
        base_url="https://admin",
    ) as client:
        verified = await client.get("/admin/health")

    assert missing.status_code == 401
    assert verified.status_code == 200
