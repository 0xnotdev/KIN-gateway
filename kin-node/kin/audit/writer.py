"""Centralized audit log and session event writer with sequence deduplication."""

from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from kin.storage.vault import decrypt_field, encrypt_field


def _canonical_payload_hash(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        try:
            val = json.loads(payload)
            return hashlib.sha256(json.dumps(val, sort_keys=True).encode("utf-8")).hexdigest()
        except Exception:
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def write_audit_event(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    category: str,
    summary: str,
    session_id: str | None = None,
    actor_username: str | None = None,
    payload: Any = None,
    correlation_id: str | None = None,
) -> str:
    """Write an encrypted audit event to audit_events. Single entry point for audit records."""
    audit_id = str(uuid.uuid4())
    cid = correlation_id or session_id or audit_id
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    payload_str: str | None = None
    if payload is not None:
        if isinstance(payload, str):
            payload_str = payload
        else:
            payload_str = json.dumps(payload, sort_keys=True)

    encrypted_payload = encrypt_field(vault_key, payload_str)

    conn.execute(
        """\
        INSERT INTO audit_events (
            audit_id, correlation_id, session_id, category,
            actor_username, summary, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (audit_id, cid, session_id, category, actor_username, summary, encrypted_payload, now_str),
    )
    conn.commit()
    return audit_id


def check_sequence_conflict(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    session_id: str,
    actor_username: str,
    sequence: int,
    payload: Any,
) -> tuple[str, str | None]:
    """Evaluate incoming sequence against stored session_events.

    Returns:
        ("new", None) if sequence is not yet stored.
        ("duplicate", existing_event_id) if sequence is stored and content hash matches. Audit event recorded.
        ("conflict", existing_event_id) if sequence is stored and content hash differs. Audit event recorded.
    """
    cur = conn.cursor()
    cur.execute(
        """\
        SELECT event_id, payload_json FROM session_events
        WHERE session_id = ? AND actor_username = ? AND sequence = ?
        """,
        (session_id, actor_username, sequence),
    )
    row = cur.fetchone()
    if row is None:
        return ("new", None)

    existing_event_id, existing_enc_payload = row
    existing_dec_payload = decrypt_field(vault_key, existing_enc_payload)

    incoming_hash = _canonical_payload_hash(payload)
    existing_hash = _canonical_payload_hash(existing_dec_payload)

    if incoming_hash == existing_hash:
        write_audit_event(
            conn,
            vault_key,
            category="duplicate_delivery",
            session_id=session_id,
            actor_username=actor_username,
            summary=f"Duplicate envelope sequence {sequence} received for session {session_id}",
            payload={"sequence": sequence, "existing_event_id": existing_event_id},
            correlation_id=session_id,
        )
        return ("duplicate", existing_event_id)
    else:
        write_audit_event(
            conn,
            vault_key,
            category="security_rejection",
            session_id=session_id,
            actor_username=actor_username,
            summary=f"Sequence reuse mismatch: sequence {sequence} received with different content for session {session_id}",
            payload={"sequence": sequence, "existing_event_id": existing_event_id},
            correlation_id=session_id,
        )
        return ("conflict", existing_event_id)


def append_session_event(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    session_id: str,
    actor_username: str,
    actor_agent_id: str | None,
    kind: str,
    visibility: str = "peer_visible",
    payload: Any = None,
    signature: str | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    """Append a session event assigned a deterministic event_order and record an audit log.

    Handles duplicate envelope detection:
    - Same sequence & matching content -> category="duplicate_delivery", returns {"status": "duplicate", "event_id": ...}
    - Same sequence & differing content -> category="security_rejection", returns {"status": "rejected", "error_code": "SEQUENCE_REUSE_MISMATCH"}
    """
    cur = conn.cursor()

    if sequence is not None:
        status_kind, existing_id = check_sequence_conflict(
            conn,
            vault_key,
            session_id=session_id,
            actor_username=actor_username,
            sequence=sequence,
            payload=payload,
        )
        if status_kind == "duplicate":
            return {"status": "duplicate", "event_id": existing_id}
        elif status_kind == "conflict":
            return {"status": "rejected", "error_code": "SEQUENCE_REUSE_MISMATCH"}

    # Assign next monotonic event_order
    cur.execute(
        "SELECT COALESCE(MAX(event_order), -1) + 1 FROM session_events WHERE session_id = ?",
        (session_id,),
    )
    next_order = cur.fetchone()[0]

    event_id = str(uuid.uuid4())
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    payload_str: str | None = None
    payload_dict: dict[str, Any]
    if payload is None:
        payload_dict = {}
    elif isinstance(payload, str):
        payload_str = payload
        try:
            parsed = json.loads(payload)
            payload_dict = parsed if isinstance(parsed, dict) else {"content": payload}
        except Exception:
            payload_dict = {"content": payload}
    elif isinstance(payload, dict):
        payload_str = json.dumps(payload, sort_keys=True)
        payload_dict = payload
    else:
        payload_str = json.dumps(payload, sort_keys=True)
        payload_dict = {"content": str(payload)}

    from kin.schemas import SessionEvent
    event_data = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "event_id": event_id,
        "session_id": session_id,
        "event_order": next_order,
        "sequence": sequence,
        "actor_username": actor_username,
        "actor_agent_id": actor_agent_id,
        "kind": kind,
        "visibility": visibility,
        "payload": payload_dict,
        "signature": signature,
        "created_at": now_str,
    }
    SessionEvent.model_validate(event_data)

    enc_payload = encrypt_field(vault_key, payload_str)

    conn.execute(
        """\
        INSERT INTO session_events (
            event_id, session_id, event_order, sequence,
            actor_username, actor_agent_id, kind, visibility,
            payload_json, signature, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            session_id,
            next_order,
            sequence,
            actor_username,
            actor_agent_id,
            kind,
            visibility,
            enc_payload,
            signature,
            now_str,
        ),
    )

    write_audit_event(
        conn,
        vault_key,
        category=f"session_event_{kind}",
        session_id=session_id,
        actor_username=actor_username,
        summary=f"Session event {kind} appended (order {next_order})",
        payload=payload,
        correlation_id=session_id,
    )

    conn.commit()
    return {"status": "appended", "event_id": event_id, "event_order": next_order}
