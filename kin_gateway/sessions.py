"""Observer-only CP0 records for A2A requests crossing the gateway."""

import hashlib
import json

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ExternalTaskSession:
    """One completed A2A proxy attempt, limited to facts known in CP0."""

    session_id: str
    a2a_task_id: str | None
    transport: str
    request_method: str
    request_hash: str
    upstream: str
    started_at: datetime
    ended_at: datetime
    outcome: str


class ExternalTaskSessionObserver(Protocol):
    """Receive completed session facts without participating in proxy control."""

    async def record(self, session: ExternalTaskSession) -> None:
        """Observe a completed session."""


def deterministic_request_hash(
    *,
    transport: str,
    request_method: str,
    target: str,
    headers: Mapping[str, str],
    body: bytes,
) -> str:
    """Hash stable protocol inputs while excluding caller credentials."""

    normalized_headers = {
        name.lower(): value for name, value in headers.items()
    }
    protocol_headers = {
        name: normalized_headers[name]
        for name in (
            "a2a-version",
            "a2a-extensions",
            "accept",
            "content-type",
            "last-event-id",
        )
        if name in normalized_headers
    }
    envelope = {
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "headers": protocol_headers,
        "request_method": request_method,
        "target": target,
        "transport": transport,
    }
    canonical = json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _task_id_from_response(response_body: bytes | None) -> str | None:
    """Best-effort task ID observation for buffered JSON; never alter the body."""

    if not response_body:
        return None
    try:
        document = json.loads(response_body)
    except (TypeError, ValueError):
        return None
    if not isinstance(document, dict):
        return None

    candidate = document.get("result", document)
    if not isinstance(candidate, dict):
        return None
    task = candidate.get("task", candidate)
    if not isinstance(task, dict):
        return None
    task_id = task.get("id")
    return task_id if isinstance(task_id, str) and task_id else None


class ExternalTaskSessionTracker:
    """Build exactly one immutable completion record for a proxy attempt."""

    def __init__(
        self,
        *,
        observer: ExternalTaskSessionObserver | None,
        transport: str,
        request_method: str,
        target: str,
        upstream: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        self._observer = observer
        self._session_id = str(uuid4())
        self._transport = transport
        self._request_method = request_method
        self._upstream = upstream
        self._started_at = datetime.now(timezone.utc)
        self._request_hash = deterministic_request_hash(
            transport=transport,
            request_method=request_method,
            target=target,
            headers=headers,
            body=body,
        )
        self._completed = False

    async def complete(
        self,
        outcome: str,
        *,
        response_body: bytes | None = None,
    ) -> None:
        """Notify once; observer failures are never proxy failures in CP0."""

        if self._completed:
            return
        self._completed = True
        session = ExternalTaskSession(
            session_id=self._session_id,
            a2a_task_id=_task_id_from_response(response_body),
            transport=self._transport,
            request_method=self._request_method,
            request_hash=self._request_hash,
            upstream=self._upstream,
            started_at=self._started_at,
            ended_at=datetime.now(timezone.utc),
            outcome=outcome,
        )
        if self._observer is None:
            return
        try:
            await self._observer.record(session)
        except Exception:
            return
