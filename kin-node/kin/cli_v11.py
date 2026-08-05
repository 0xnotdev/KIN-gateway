"""Shared V1.1 non-TTY projections used by scriptable CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kin.tui.redaction import redact_ui_text


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_ui_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


def list_sessions(profile_name: str, profile_dir: Path) -> list[dict[str, object]]:
    """Return the same durable session summaries that back the TUI Home/Arena."""
    from kin.tui.local_state import ensure_profile_db
    from kin.identity.storage import get_or_create_vault_key
    from kin.storage.vault import decrypt_field_or_plaintext

    db_path = profile_dir / "kin.db"
    if not db_path.is_file():
        return []
    conn = ensure_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)
    try:
        rows = conn.execute(
            """SELECT session_id, type, initiator_username, receiver_username,
                      status, objective, sender_agent_id, receiver_agent_id,
                      turn_limit, created_at, updated_at
               FROM sessions ORDER BY updated_at DESC, session_id ASC"""
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "session_id": row[0],
            "type": row[1],
            "initiator_username": row[2],
            "receiver_username": row[3],
            "status": row[4],
            "objective": redact_ui_text(decrypt_field_or_plaintext(vault_key, row[5]) or ""),
            "sender_agent_id": row[6],
            "receiver_agent_id": row[7],
            "turn_limit": row[8],
            "created_at": row[9],
            "updated_at": row[10],
        }
        for row in rows
    ]


def open_session(profile_name: str, profile_dir: Path, session_id: str) -> dict[str, object]:
    """Return a redacted, peer-visible session transcript projection."""
    from kin.audit.export import export_session
    from kin.identity.storage import get_or_create_vault_key
    from kin.tui.local_state import ensure_profile_db

    db_path = profile_dir / "kin.db"
    if not db_path.is_file():
        raise ValueError("Profile database is not initialized.")
    conn = ensure_profile_db(db_path)
    try:
        raw = export_session(
            conn,
            get_or_create_vault_key(profile_name),
            session_id,
            format="json",
            include_private_notes=False,
        )
    finally:
        conn.close()
    return _redact_value(json.loads(raw))


def export_session_content(
    profile_name: str,
    profile_dir: Path,
    session_id: str,
    *,
    export_format: str,
) -> str:
    """Produce the audited peer-visible export used by the TUI export action."""
    from kin.audit.export import export_session
    from kin.identity.storage import get_or_create_vault_key
    from kin.tui.local_state import ensure_profile_db

    if export_format not in {"markdown", "json"}:
        raise ValueError("Export format must be 'markdown' or 'json'.")
    db_path = profile_dir / "kin.db"
    if not db_path.is_file():
        raise ValueError("Profile database is not initialized.")
    conn = ensure_profile_db(db_path)
    try:
        raw = export_session(
            conn,
            get_or_create_vault_key(profile_name),
            session_id,
            format=export_format,
            include_private_notes=False,
        )
    finally:
        conn.close()
    if export_format == "json":
        return json.dumps(_redact_value(json.loads(raw)), indent=2, sort_keys=True)
    return redact_ui_text(raw)


def write_export_atomic(target: Path, content: str) -> None:
    """Write a CLI export atomically without exposing a partial transcript."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(target)


def list_inbox(profile_name: str, profile_dir: Path) -> list[dict[str, object]]:
    """Return the owner-attention queue that backs Inbox/Needs You."""
    from kin.tui.local_state import get_needs_you_items

    return [
        {
            "item_id": item.item_id,
            "session_id": item.session_id,
            "kind": item.kind,
            "reason": redact_ui_text(item.human_readable_reason),
            "urgency": item.urgency,
            "created_at": item.created_at,
        }
        for item in get_needs_you_items(profile_dir, profile_name)
    ]


def list_approvals(profile_name: str, profile_dir: Path) -> list[dict[str, object]]:
    """Return pending/expired approval cards from the shared persistence query."""
    from kin.tui.local_state import get_pending_approvals

    results: list[dict[str, object]] = []
    for view in get_pending_approvals(profile_dir, profile_name):
        request = view.request.model_dump(mode="json")
        results.append(_redact_value({"request": request, "decision": view.decision}))
    return results


def recover_session(profile_name: str, profile_dir: Path, session_id: str) -> dict[str, object]:
    """Reconstruct a session deterministically from durable events after restart."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.session.reducer import reconstruct_session_state
    from kin.tui.local_state import ensure_profile_db

    db_path = profile_dir / "kin.db"
    if not db_path.is_file():
        raise ValueError("Profile database is not initialized.")
    conn = ensure_profile_db(db_path)
    try:
        state = reconstruct_session_state(
            conn,
            get_or_create_vault_key(profile_name),
            session_id,
        )
    finally:
        conn.close()
    if state is None:
        raise ValueError(f"Session '{session_id}' was not found.")
    data = state.model_dump(mode="json")
    data["recovered_from_persistence"] = True
    return _redact_value(data)


def session_plain_lines(session: dict[str, object]) -> list[str]:
    """Render a deterministic semantic session transcript without terminal boxes."""
    meta = dict(session["session"])
    lines = [
        f"SESSION: {meta['session_id']}",
        f"STATUS: {meta['status']}",
        f"TYPE: {meta['type']}",
        f"PARTICIPANTS: {meta['initiator_username']} -> {meta['receiver_username']}",
        f"OBJECTIVE: {meta.get('objective') or ''}",
        "EVENTS:",
    ]
    for event in session.get("events", []):
        lines.append(
            f"{event['event_order']}. {event['created_at']} | {event['kind']} | @{event['actor_username']}"
        )
        lines.append(f"  {json.dumps(event.get('payload') or {}, sort_keys=True)}")
    lines.append("ARTIFACTS:")
    for artifact in session.get("artifacts", []):
        lines.append(
            f"- {artifact['artifact_id']} | {artifact['mime_type']} | sha256={artifact['sha256']}"
        )
    return lines
