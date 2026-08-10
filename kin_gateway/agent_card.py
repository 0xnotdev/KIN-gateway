"""Protected Agent Card acquisition and public-surface projection."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
import time

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from a2a.types import AgentCard
from a2a.utils.proto_utils import validate_proto_required_fields
from google.protobuf.json_format import MessageToDict, ParseDict

from kin_gateway.config import GatewaySettings
from kin_gateway.upstream.credentials import (
    RequestContext,
    UpstreamCredentialProvider,
)


AGENT_CARD_PATH = "/.well-known/agent-card.json"
JSONRPC_PATH = "/a2a/jsonrpc"
REST_PATH = "/a2a/rest"
_PUBLIC_INTERFACE_PATHS = {
    "JSONRPC": JSONRPC_PATH,
    "HTTP+JSON": REST_PATH,
}


class AgentCardMirrorError(Exception):
    """The private card could not safely become a public card."""


@dataclass(frozen=True)
class MirroredAgentCard:
    """A validated public representation and its eventual provenance metadata."""

    document: dict[str, object]
    source_sha256: str
    public_sha256: str


class TargetResolver(Protocol):
    """Resolve exactly once at the validation-to-connection seam."""

    async def resolve(
        self, host: str, port: int
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        """Return every address offered for a target host."""


class SystemTargetResolver:
    """Asynchronously resolve a host using the operating-system resolver."""

    async def resolve(
        self, host: str, port: int
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        loop = asyncio.get_running_loop()
        answers = await loop.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
        unique: dict[str, ipaddress.IPv4Address | ipaddress.IPv6Address] = {}
        for answer in answers:
            address = ipaddress.ip_address(answer[4][0])
            unique[str(address)] = address
        return tuple(unique.values())


class AgentCardMirror:
    """Own the complete private-card to public-card trust boundary."""

    def __init__(
        self,
        settings: GatewaySettings,
        *,
        transport: httpx.AsyncBaseTransport | None,
        credential_provider: UpstreamCredentialProvider,
        resolver: TargetResolver | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._credential_provider = credential_provider
        self._resolver = resolver or SystemTargetResolver()
        self._cached: MirroredAgentCard | None = None
        self._cache_expires_at = 0.0
        self._cache_lock = asyncio.Lock()

    async def public_card(self) -> MirroredAgentCard:
        """Return the current immutable snapshot, refreshing it once per TTL."""

        now = time.monotonic()
        if self._cached is not None and now < self._cache_expires_at:
            return self._cached
        async with self._cache_lock:
            now = time.monotonic()
            if self._cached is not None and now < self._cache_expires_at:
                return self._cached
            snapshot = await self._refresh()
            self._cached = snapshot
            self._cache_expires_at = (
                now + self._settings.agent_card.cache_ttl_seconds
            )
            return snapshot

    async def _refresh(self) -> MirroredAgentCard:
        """Fetch, validate, normalize, filter, rewrite, and hash one snapshot."""

        try:
            logical_url = str(
                httpx.URL(self._settings.upstream_base_url).join(AGENT_CARD_PATH)
            )
            async with asyncio.timeout(
                self._settings.agent_card.fetch_timeout_seconds
            ):
                document, credential_values = await self._fetch_document(logical_url)
            card = ParseDict(document, AgentCard())
            validate_proto_required_fields(card)
        except Exception as exc:
            if isinstance(exc, AgentCardMirrorError):
                raise
            raise AgentCardMirrorError("Upstream Agent Card is invalid") from exc

        public = AgentCard(
            name=card.name,
            description=card.description,
            version=card.version,
            default_input_modes=card.default_input_modes,
            default_output_modes=card.default_output_modes,
        )
        public.capabilities.SetInParent()
        public.capabilities.streaming = card.capabilities.streaming

        for interface in card.supported_interfaces:
            public_path = _PUBLIC_INTERFACE_PATHS.get(
                interface.protocol_binding
            )
            if public_path and interface.protocol_version == "1.0":
                public_interface = public.supported_interfaces.add()
                public_interface.CopyFrom(interface)
                public_interface.url = (
                    f"{self._settings.public_base_url}{public_path}"
                )

        if not public.supported_interfaces:
            raise AgentCardMirrorError(
                "Upstream does not expose an implemented A2A 1.0 profile"
            )

        approved_skills = self._settings.agent_card.approved_skill_ids
        for skill in card.skills:
            if skill.id in approved_skills:
                public.skills.add().CopyFrom(skill)
        if not public.skills:
            raise AgentCardMirrorError("No approved public Agent Card skills remain")

        source_document = MessageToDict(card)
        public_document = MessageToDict(public)
        self._ensure_no_private_reference(public_document, credential_values)
        return MirroredAgentCard(
            document=public_document,
            source_sha256=self._document_hash(source_document),
            public_sha256=self._document_hash(public_document),
        )

    def _ensure_no_private_reference(
        self,
        public_document: Mapping[str, object],
        credential_values: frozenset[str],
    ) -> None:
        """Fail closed if preserved text discloses an origin URL or credential."""

        serialized = json.dumps(public_document, ensure_ascii=False).casefold()
        upstream_url = urlsplit(self._settings.upstream_base_url)
        upstream_origin = f"{upstream_url.scheme}://{upstream_url.netloc}"
        forbidden = [self._settings.upstream_base_url, upstream_origin]
        forbidden.extend(credential_values)
        for value in forbidden:
            if value and value.casefold() in serialized:
                raise AgentCardMirrorError(
                    "Public Agent Card contains a private reference"
                )

    async def _fetch_document(
        self, logical_url: str
    ) -> tuple[object, frozenset[str]]:
        """Follow only same-origin redirects and read a bounded response body."""

        origin = self._origin(logical_url)
        credential_values: set[str] = set()
        async with httpx.AsyncClient(transport=self._transport) as client:
            for redirect_count in range(
                self._settings.agent_card.max_redirects + 1
            ):
                fetch_url, target_headers, extensions = (
                    await self._validated_target(logical_url)
                )
                credential_headers = await self._credential_provider.headers_for(
                    RequestContext(method="GET", url=logical_url)
                )
                for credential_value in credential_headers.values():
                    credential_values.add(credential_value)
                    _, separator, payload = credential_value.partition(" ")
                    if separator and payload:
                        credential_values.add(payload)
                async with client.stream(
                    "GET",
                    fetch_url,
                    headers={**credential_headers, **target_headers},
                    extensions=extensions,
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise AgentCardMirrorError(
                                "Agent Card redirect has no location"
                            )
                        if redirect_count >= self._settings.agent_card.max_redirects:
                            raise AgentCardMirrorError(
                                "Agent Card redirect limit exceeded"
                            )
                        redirected = urljoin(logical_url, location)
                        if self._origin(redirected) != origin:
                            raise AgentCardMirrorError(
                                "Agent Card redirect changed origin"
                            )
                        logical_url = redirected
                        continue

                    response.raise_for_status()
                    body = await self._bounded_body(response)
                    return json.loads(body), frozenset(credential_values)

        raise AgentCardMirrorError("Agent Card redirect limit exceeded")

    async def _bounded_body(self, response: httpx.Response) -> bytes:
        """Bound declared and actual decompressed response bytes."""

        content_length = response.headers.get("content-length")
        if (
            content_length is not None
            and int(content_length) > self._settings.agent_card.max_response_bytes
        ):
            raise AgentCardMirrorError("Agent Card exceeds size limit")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > self._settings.agent_card.max_response_bytes:
                raise AgentCardMirrorError("Agent Card exceeds size limit")
        return bytes(body)

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int]:
        """Normalize an HTTP origin for strict redirect comparison."""

        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AgentCardMirrorError("Agent Card target URL is invalid")
        if parsed.username is not None or parsed.password is not None:
            raise AgentCardMirrorError("Agent Card target contains credentials")
        default_port = 443 if parsed.scheme == "https" else 80
        return parsed.scheme, parsed.hostname.lower(), parsed.port or default_port

    @staticmethod
    def _document_hash(document: Mapping[str, object]) -> str:
        """Hash normalized protobuf JSON with a deterministic local encoding."""

        canonical = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    async def _validated_target(
        self, logical_url: str
    ) -> tuple[str, dict[str, str], dict[str, object]]:
        """Validate all answers and pin the request to one validated address."""

        parsed = urlsplit(logical_url)
        host = parsed.hostname or ""
        trusted = host.lower() in {
            item.lower() for item in self._settings.agent_card.trusted_private_hosts
        }
        if trusted:
            return logical_url, {}, {}
        if parsed.scheme != "https":
            raise AgentCardMirrorError("Untrusted Agent Card targets require HTTPS")
        port = parsed.port or 443
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            try:
                addresses = await self._resolver.resolve(host, port)
            except (OSError, ValueError) as exc:
                raise AgentCardMirrorError(
                    "Agent Card target cannot be resolved"
                ) from exc
        else:
            addresses = (literal,)
        if not addresses or any(not address.is_global for address in addresses):
            raise AgentCardMirrorError("Private upstream address is not trusted")

        pinned = httpx.URL(logical_url).copy_with(host=str(addresses[0]))
        authority = host
        if parsed.port is not None and parsed.port != 443:
            authority = f"{host}:{parsed.port}"
        return (
            str(pinned),
            {"Host": authority},
            {"sni_hostname": host},
        )
