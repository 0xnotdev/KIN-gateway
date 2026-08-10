"""Security and fidelity contract for the public Agent Card mirror."""

import asyncio
import ipaddress

import httpx
import pytest

from google.protobuf.json_format import MessageToDict
from pydantic import ValidationError

from kin_gateway.app import create_gateway_app
from kin_gateway.config import AgentCardMirrorSettings, GatewaySettings
from tests.contract.reference_agent import build_reference_agent


def test_upstream_url_rejects_embedded_credentials() -> None:
    """A configured fetch target must not smuggle authority in its URL."""

    with pytest.raises(ValidationError, match="must not contain credentials"):
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="https://operator:secret@agent.example",
        )


def test_upstream_url_rejects_unsupported_scheme() -> None:
    """Only HTTP transports can be used for the protected A2A upstream."""

    with pytest.raises(ValidationError, match="must use http or https"):
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="file:///etc/passwd",
        )


def test_upstream_url_rejects_malformed_port() -> None:
    """Malformed authority components fail during configuration validation."""

    with pytest.raises(ValidationError, match="valid numeric port"):
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="https://agent.example:not-a-port",
        )


@pytest.mark.asyncio
async def test_private_ip_agent_card_target_is_blocked_before_fetch() -> None:
    """Metadata, loopback, and private IP literals are not implicit upstreams."""

    _, card = build_reference_agent(base_url="http://169.254.169.254")
    upstream_calls: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(str(request.url))
        return httpx.Response(200, json={"name": card.name})

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="http://169.254.169.254",
        ),
        upstream_transport=httpx.MockTransport(upstream),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 502
    assert upstream_calls == []


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "[::1]",
        "[fe80::1]",
    ],
)
@pytest.mark.asyncio
async def test_nonpublic_address_classes_require_explicit_trust(host: str) -> None:
    """Loopback, RFC1918, and IPv6-local targets all use the same deny rule."""

    upstream_calls: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(str(request.url))
        return httpx.Response(200, json={})

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url=f"https://{host}",
        ),
        upstream_transport=httpx.MockTransport(upstream),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 502
    assert upstream_calls == []


@pytest.mark.asyncio
async def test_dns_answer_set_is_rejected_if_any_address_is_private() -> None:
    """A mixed DNS response cannot make address selection bypass validation."""

    upstream_calls: list[str] = []

    class Resolver:
        async def resolve(
            self, host: str, port: int
        ) -> tuple[ipaddress.IPv4Address, ...]:
            return (
                ipaddress.ip_address("93.184.216.34"),
                ipaddress.ip_address("10.0.0.4"),
            )

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(str(request.url))
        return httpx.Response(200, json={})

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="https://agent.example",
        ),
        upstream_transport=httpx.MockTransport(upstream),
        agent_card_resolver=Resolver(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 502
    assert upstream_calls == []


@pytest.mark.asyncio
async def test_agent_card_fetch_is_pinned_to_the_validated_dns_answer() -> None:
    """Validation and connection use one DNS answer, closing the rebinding gap."""

    _, card = build_reference_agent(base_url="https://agent.example")
    resolver_calls: list[str] = []
    upstream_requests: list[httpx.Request] = []

    class Resolver:
        async def resolve(self, host: str, port: int) -> tuple[ipaddress.IPv4Address]:
            resolver_calls.append(f"{host}:{port}")
            return (ipaddress.ip_address("93.184.216.34"),)

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_requests.append(request)
        return httpx.Response(200, json=MessageToDict(card))

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="https://agent.example",
            agent_card=AgentCardMirrorSettings(
                approved_skill_ids=frozenset({"inventory.lookup"})
            ),
        ),
        upstream_transport=httpx.MockTransport(upstream),
        agent_card_resolver=Resolver(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    assert resolver_calls == ["agent.example:443"]
    assert upstream_requests[0].url.host == "93.184.216.34"
    assert upstream_requests[0].headers["host"] == "agent.example"


@pytest.mark.asyncio
async def test_oversized_agent_card_is_rejected() -> None:
    """The mirror bounds decompressed bytes before parsing untrusted JSON."""

    _, card = build_reference_agent(base_url="http://upstream")
    card.description = "x" * 2_000

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="http://upstream",
            agent_card=AgentCardMirrorSettings(
                trusted_private_hosts=frozenset({"upstream"}),
                max_response_bytes=512,
            ),
        ),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=MessageToDict(card))
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_public_card_is_allowlisted_without_private_details() -> None:
    """Private URLs, upstream auth, signatures, and unapproved skills never leak."""

    _, card = build_reference_agent(base_url="http://private-agent.internal")
    card.documentation_url = "http://private-agent.internal/docs"
    card.icon_url = "http://private-agent.internal/icon.png"
    card.provider.organization = "Internal Operator"
    card.provider.url = "http://private-agent.internal"
    card.skills.add(
        id="finance.transfer",
        name="Internal transfer",
        description="Internal-only money movement.",
        tags=["finance"],
    )
    card.security_schemes[
        "upstreamBearer"
    ].http_auth_security_scheme.scheme = "bearer"
    card.security_requirements.add().schemes["upstreamBearer"].list.append(
        "internal"
    )
    card.signatures.add(protected="private", signature="private-signature")

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="http://private-agent.internal",
            agent_card=AgentCardMirrorSettings(
                trusted_private_hosts=frozenset({"private-agent.internal"}),
                approved_skill_ids=frozenset({"inventory.lookup"}),
            ),
        ),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=MessageToDict(card))
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    document = response.json()
    assert response.status_code == 200
    assert [skill["id"] for skill in document["skills"]] == ["inventory.lookup"]
    assert document["supportedInterfaces"] == [
        {
            "url": "https://gateway.example/a2a/jsonrpc",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        },
        {
            "url": "https://gateway.example/a2a/rest",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        },
    ]
    assert document["capabilities"] == {"streaming": True}
    assert "private-agent.internal" not in response.text
    assert "securitySchemes" not in document
    assert "securityRequirements" not in document
    assert "signatures" not in document


@pytest.mark.asyncio
async def test_agent_card_source_hash_and_cache_are_deterministic() -> None:
    """Repeated discovery is traceable to one normalized upstream snapshot."""

    _, card = build_reference_agent(base_url="http://upstream")
    upstream_calls: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(str(request.url))
        return httpx.Response(200, json=MessageToDict(card))

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="http://upstream",
            agent_card=AgentCardMirrorSettings(
                trusted_private_hosts=frozenset({"upstream"}),
                approved_skill_ids=frozenset({"inventory.lookup"}),
                cache_ttl_seconds=60,
            ),
        ),
        upstream_transport=httpx.MockTransport(upstream),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        first = await client.get("/.well-known/agent-card.json")
        second = await client.get("/.well-known/agent-card.json")

    source_hash = first.headers["x-kin-upstream-agent-card-sha256"]
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(source_hash) == 64
    assert int(source_hash, 16) >= 0
    assert second.headers["x-kin-upstream-agent-card-sha256"] == source_hash
    assert first.headers["etag"] == second.headers["etag"]
    assert upstream_calls == ["http://upstream/.well-known/agent-card.json"]


@pytest.mark.asyncio
async def test_same_origin_agent_card_redirect_is_revalidated_and_followed() -> None:
    """Legitimate redirects work without allowing authority or IP-policy changes."""

    _, card = build_reference_agent(base_url="https://agent.example")
    upstream_paths: list[str] = []

    class Resolver:
        async def resolve(self, host: str, port: int) -> tuple[ipaddress.IPv4Address]:
            return (ipaddress.ip_address("93.184.216.34"),)

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_paths.append(request.url.path)
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(302, headers={"Location": "/discovery/card.json"})
        return httpx.Response(200, json=MessageToDict(card))

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="https://agent.example",
            agent_card=AgentCardMirrorSettings(
                approved_skill_ids=frozenset({"inventory.lookup"})
            ),
        ),
        upstream_transport=httpx.MockTransport(upstream),
        agent_card_resolver=Resolver(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    assert upstream_paths == [
        "/.well-known/agent-card.json",
        "/discovery/card.json",
    ]


@pytest.mark.asyncio
async def test_agent_card_redirect_cannot_reach_metadata_service() -> None:
    """A public source cannot redirect discovery into a different trust zone."""

    upstream_hosts: list[str] = []

    class Resolver:
        async def resolve(self, host: str, port: int) -> tuple[ipaddress.IPv4Address]:
            return (ipaddress.ip_address("93.184.216.34"),)

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_hosts.append(request.url.host)
        return httpx.Response(
            302,
            headers={
                "Location": "http://169.254.169.254/latest/meta-data/iam/"
            },
        )

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="https://agent.example",
        ),
        upstream_transport=httpx.MockTransport(upstream),
        agent_card_resolver=Resolver(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 502
    assert upstream_hosts == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_agent_card_fetch_has_a_total_timeout() -> None:
    """A stalled private discovery endpoint cannot hold a public request forever."""

    completed: list[str] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        completed.append("completed")
        return httpx.Response(200, json={})

    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="http://upstream",
            agent_card=AgentCardMirrorSettings(
                trusted_private_hosts=frozenset({"upstream"}),
                fetch_timeout_seconds=0.01,
            ),
        ),
        upstream_transport=httpx.MockTransport(upstream),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 502
    assert completed == []


@pytest.mark.asyncio
async def test_private_url_inside_descriptive_text_fails_closed() -> None:
    """Allowlisted fields are still rejected if their content discloses the origin."""

    _, card = build_reference_agent(base_url="http://private-agent.internal")
    card.description = "Internal docs: http://private-agent.internal/runbook"
    gateway = create_gateway_app(
        GatewaySettings(
            public_base_url="https://gateway.example",
            upstream_base_url="http://private-agent.internal",
            agent_card=AgentCardMirrorSettings(
                trusted_private_hosts=frozenset({"private-agent.internal"}),
                approved_skill_ids=frozenset({"inventory.lookup"}),
            ),
        ),
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=MessageToDict(card))
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway),
        base_url="https://gateway.example",
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 502
    assert "private-agent.internal" not in response.text
