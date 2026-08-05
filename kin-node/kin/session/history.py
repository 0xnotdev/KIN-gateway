"""Persistent M7 session checkpoints, decisions, outcomes, replay, and reruns."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from kin.audit.writer import append_session_event, write_audit_event
from kin.schemas import InternalEventKind
from kin.session.transition_matrix import TERMINAL_STATES
from kin.storage.vault import decrypt_field


def _utc_now(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class CheckpointRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    checkpoint_id: str
    session_id: str
    event_order: int = Field(ge=0)
    created_by: str
    label: str
    snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    decision_id: str
    session_id: str
    event_order: int = Field(ge=0)
    decided_by: str
    summary: str
    rationale: str = ""
    checkpoint_id: str | None = None
    created_at: str


class OutcomeCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    outcome_id: str
    session_id: str
    event_order: int = Field(ge=0)
    status: str
    summary: str
    evidence_event_count: int = Field(ge=0)
    replay_digest: str
    created_at: str


class ReplaySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    session_id: str
    through_event_order: int | None
    event_count: int = Field(ge=0)
    events: list[dict[str, Any]]
    digest: str


class FreshAuthorityRerun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    source_session_id: str
    rerun_session_id: str
    status: Literal["draft"] = "draft"
    created_by: str
    created_at: str
    carried_approval_count: Literal[0] = 0


def _require_session(conn: sqlite3.Connection, session_id: str) -> None:
    if conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone() is None:
        raise ValueError(f"Session '{session_id}' was not found.")


def _load_event(
    conn: sqlite3.Connection,
    vault_key: bytes,
    event_id: str,
) -> tuple[int, dict[str, Any], str]:
    row = conn.execute(
        "SELECT event_order, payload_json, created_at FROM session_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Persisted session event '{event_id}' disappeared.")
    payload = json.loads(decrypt_field(vault_key, row[1]) or "{}")
    return int(row[0]), payload, row[2]


def create_checkpoint(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    session_id: str,
    created_by: str,
    label: str,
    snapshot: dict[str, Any] | None = None,
) -> CheckpointRecord:
    """Persist an owner-local checkpoint in the append-only session record."""
    _require_session(conn, session_id)
    if not label.strip():
        raise ValueError("Checkpoint label cannot be empty.")
    result = append_session_event(
        conn,
        vault_key,
        session_id=session_id,
        actor_username=created_by,
        actor_agent_id=None,
        kind=InternalEventKind.CHECKPOINT.value,
        visibility="local_only",
        payload={"content": label.strip(), "label": label.strip(), "snapshot": snapshot or {}},
        signature=None,
        sequence=None,
    )
    order, payload, created_at = _load_event(conn, vault_key, result["event_id"])
    return CheckpointRecord(
        checkpoint_id=result["event_id"],
        session_id=session_id,
        event_order=order,
        created_by=created_by,
        label=payload["label"],
        snapshot=payload.get("snapshot") or {},
        created_at=created_at,
    )


def create_decision(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    session_id: str,
    decided_by: str,
    summary: str,
    rationale: str = "",
    checkpoint_id: str | None = None,
) -> DecisionRecord:
    """Persist an ordered owner decision tied optionally to a real checkpoint."""
    _require_session(conn, session_id)
    if not summary.strip():
        raise ValueError("Decision summary cannot be empty.")
    if checkpoint_id is not None:
        row = conn.execute(
            """SELECT 1 FROM session_events
               WHERE event_id = ? AND session_id = ? AND kind = ?""",
            (checkpoint_id, session_id, InternalEventKind.CHECKPOINT.value),
        ).fetchone()
        if row is None:
            raise ValueError("Decision checkpoint must belong to the same session.")
    result = append_session_event(
        conn,
        vault_key,
        session_id=session_id,
        actor_username=decided_by,
        actor_agent_id=None,
        kind=InternalEventKind.DECISION.value,
        visibility="local_only",
        payload={
            "content": summary.strip(),
            "summary": summary.strip(),
            "rationale": rationale.strip(),
            "checkpoint_id": checkpoint_id,
        },
        signature=None,
        sequence=None,
    )
    order, payload, created_at = _load_event(conn, vault_key, result["event_id"])
    return DecisionRecord(
        decision_id=result["event_id"],
        session_id=session_id,
        event_order=order,
        decided_by=decided_by,
        summary=payload["summary"],
        rationale=payload.get("rationale") or "",
        checkpoint_id=payload.get("checkpoint_id"),
        created_at=created_at,
    )


def replay_session(
    conn: sqlite3.Connection,
    vault_key: bytes,
    session_id: str,
    *,
    through_event_order: int | None = None,
) -> ReplaySnapshot:
    """Rebuild deterministic reviewed evidence from immutable stored events."""
    _require_session(conn, session_id)
    params: list[Any] = [session_id]
    order_clause = ""
    if through_event_order is not None:
        order_clause = "AND event_order <= ?"
        params.append(through_event_order)
    rows = conn.execute(
        f"""SELECT event_order, sequence, actor_username, actor_agent_id, kind,
                   visibility, payload_json, signature, created_at
            FROM session_events
            WHERE session_id = ? {order_clause}
              AND kind != ?
              AND (visibility != 'local_only' OR kind IN (?, ?, ?))
            ORDER BY event_order ASC""",
        [
            *params,
            InternalEventKind.PRIVATE_NOTE.value,
            InternalEventKind.CHECKPOINT.value,
            InternalEventKind.DECISION.value,
            InternalEventKind.OUTCOME.value,
        ],
    ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(decrypt_field(vault_key, row[6]) or "{}") if row[6] else {}
        events.append(
            {
                "event_order": row[0],
                "sequence": row[1],
                "actor_username": row[2],
                "actor_agent_id": row[3],
                "kind": row[4],
                "visibility": row[5],
                "payload": payload,
                "signature": row[7],
                "created_at": row[8],
            }
        )
    canonical = json.dumps(events, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ReplaySnapshot(
        session_id=session_id,
        through_event_order=through_event_order,
        event_count=len(events),
        events=events,
        digest=digest,
    )


def create_outcome_card(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    session_id: str,
    summary: str,
) -> OutcomeCard:
    """Persist one idempotent outcome linked to the pre-outcome replay digest."""
    existing = get_outcome_card(conn, vault_key, session_id)
    if existing is not None:
        return existing
    _require_session(conn, session_id)
    status = conn.execute(
        "SELECT status FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()[0]
    if status not in TERMINAL_STATES:
        raise ValueError(
            f"Outcome cards require a terminal session; '{session_id}' is '{status}'."
        )
    replay = replay_session(conn, vault_key, session_id)
    result = append_session_event(
        conn,
        vault_key,
        session_id=session_id,
        actor_username="system",
        actor_agent_id=None,
        kind=InternalEventKind.OUTCOME.value,
        visibility="local_only",
        payload={
            "content": summary.strip() or f"Session ended with status {status}.",
            "summary": summary.strip() or f"Session ended with status {status}.",
            "status": status,
            "evidence_event_count": replay.event_count,
            "replay_digest": replay.digest,
        },
        signature=None,
        sequence=None,
    )
    order, payload, created_at = _load_event(conn, vault_key, result["event_id"])
    return OutcomeCard(
        outcome_id=result["event_id"],
        session_id=session_id,
        event_order=order,
        status=payload["status"],
        summary=payload["summary"],
        evidence_event_count=payload["evidence_event_count"],
        replay_digest=payload["replay_digest"],
        created_at=created_at,
    )


def get_outcome_card(
    conn: sqlite3.Connection,
    vault_key: bytes,
    session_id: str,
) -> OutcomeCard | None:
    row = conn.execute(
        """SELECT event_id, event_order, payload_json, created_at
           FROM session_events
           WHERE session_id = ? AND kind = ?
           ORDER BY event_order DESC LIMIT 1""",
        (session_id, InternalEventKind.OUTCOME.value),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(decrypt_field(vault_key, row[2]) or "{}")
    return OutcomeCard(
        outcome_id=row[0],
        session_id=session_id,
        event_order=row[1],
        status=payload["status"],
        summary=payload["summary"],
        evidence_event_count=payload["evidence_event_count"],
        replay_digest=payload["replay_digest"],
        created_at=row[3],
    )


def create_fresh_authority_rerun(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    source_session_id: str,
    created_by: str,
    rerun_session_id: str | None = None,
    now: datetime | None = None,
) -> FreshAuthorityRerun:
    """Create a draft that copies shape/input but never approvals or decisions."""
    row = conn.execute(
        """SELECT type, initiator_username, receiver_username, objective,
                  sender_agent_id, receiver_agent_id, participant_snapshot_json,
                  turn_limit, runtime_budget_seconds, artifact_bytes_budget,
                  cost_budget_estimate
           FROM sessions WHERE session_id = ?""",
        (source_session_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Session '{source_session_id}' was not found.")
    new_id = rerun_session_id or f"sess_rerun_{uuid.uuid4().hex[:16]}"
    created_at = _utc_now(now)
    conn.execute(
        """INSERT INTO sessions (
               session_id, type, initiator_username, receiver_username, status,
               objective, sender_agent_id, receiver_agent_id, participant_snapshot_json,
               turn_limit, runtime_budget_seconds, artifact_bytes_budget,
               cumulative_artifact_bytes, cost_budget_estimate, cumulative_cost_estimate,
               created_at, updated_at
           ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, 0, ?, 0.0, ?, ?)""",
        (new_id, *row, created_at, created_at),
    )
    conn.commit()
    append_session_event(
        conn,
        vault_key,
        session_id=new_id,
        actor_username=created_by,
        actor_agent_id=None,
        kind=InternalEventKind.RERUN_CREATED.value,
        visibility="local_only",
        payload={"source_session_id": source_session_id, "fresh_authority": True},
        signature=None,
        sequence=None,
    )
    write_audit_event(
        conn,
        vault_key,
        category="fresh_authority_rerun",
        session_id=new_id,
        actor_username=created_by,
        summary=f"Fresh-authority rerun draft created from {source_session_id}",
        payload={"source_session_id": source_session_id, "carried_approval_count": 0},
        correlation_id=new_id,
    )
    return FreshAuthorityRerun(
        source_session_id=source_session_id,
        rerun_session_id=new_id,
        created_by=created_by,
        created_at=created_at,
    )
