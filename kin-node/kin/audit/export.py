"""Deterministic export module for session transcripts in Markdown and JSON formats."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Literal

from kin.storage.vault import decrypt_field


def export_session(
    conn: sqlite3.Connection,
    vault_key: bytes,
    session_id: str,
    format: Literal["markdown", "json"] = "json",
    include_private_notes: bool = False,
) -> str:
    """Export a session transcript ordered strictly by session_events.event_order."""
    cur = conn.cursor()
    cur.execute(
        """\
        SELECT session_id, type, owner_username, peer_username, status, objective,
               sender_agent_id, receiver_agent_id, participant_snapshot_json,
               turn_limit, created_at, updated_at, terminal_result_json
        FROM sessions WHERE session_id = ?
        """,
        (session_id,),
    )
    session_row = cur.fetchone()
    if session_row is None:
        raise ValueError(f"Session not found: {session_id}")

    (
        s_id, s_type, owner, peer, status, enc_obj,
        sender_agent, receiver_agent, enc_part_snap,
        turn_limit, created_at, updated_at, enc_term_res
    ) = session_row

    dec_obj = decrypt_field(vault_key, enc_obj)
    dec_part_snap = decrypt_field(vault_key, enc_part_snap)
    dec_term_res = decrypt_field(vault_key, enc_term_res)

    try:
        parsed_part_snap = json.loads(dec_part_snap) if dec_part_snap else None
    except Exception:
        parsed_part_snap = dec_part_snap

    try:
        parsed_term_res = json.loads(dec_term_res) if dec_term_res else None
    except Exception:
        parsed_term_res = dec_term_res

    session_meta = {
        "session_id": s_id,
        "type": s_type,
        "owner_username": owner,
        "peer_username": peer,
        "status": status,
        "objective": dec_obj,
        "sender_agent_id": sender_agent,
        "receiver_agent_id": receiver_agent,
        "participant_snapshot": parsed_part_snap,
        "turn_limit": turn_limit,
        "created_at": created_at,
        "updated_at": updated_at,
        "terminal_result": parsed_term_res,
    }

    cur.execute(
        """\
        SELECT event_id, event_order, sequence, actor_username, actor_agent_id,
               kind, visibility, payload_json, signature, created_at
        FROM session_events
        WHERE session_id = ?
        ORDER BY event_order ASC
        """,
        (session_id,),
    )
    event_rows = cur.fetchall()

    exported_events = []
    for r in event_rows:
        (
            ev_id, ev_order, seq, actor_user, actor_agent,
            kind, vis, enc_payload, sig, ev_created
        ) = r

        if vis == "local_only" and not include_private_notes:
            continue

        dec_payload = decrypt_field(vault_key, enc_payload)
        parsed_payload: Any = None
        if dec_payload is not None:
            try:
                parsed_payload = json.loads(dec_payload)
            except Exception:
                parsed_payload = dec_payload

        # Check if payload itself marks private note
        if isinstance(parsed_payload, dict) and parsed_payload.get("visibility") == "local_only" and not include_private_notes:
            continue

        if isinstance(parsed_payload, dict):
            from kin.schemas import compute_content_hash
            content_hash = compute_content_hash(parsed_payload)
        elif parsed_payload is not None:
            from kin.schemas import compute_content_hash
            content_hash = compute_content_hash({"value": str(parsed_payload)})
        else:
            content_hash = ""

        exported_events.append({
            "event_id": ev_id,
            "event_order": ev_order,
            "sequence": seq,
            "actor_username": actor_user,
            "actor_agent_id": actor_agent,
            "kind": kind,
            "visibility": vis,
            "payload": parsed_payload,
            "content_hash": content_hash,
            "signature": sig,
            "created_at": ev_created,
        })

    if format == "json":
        export_data = {
            "session": session_meta,
            "events": exported_events,
        }
        return json.dumps(export_data, indent=2)

    elif format == "markdown":
        lines = [
            f"# Session Transcript: {session_id}",
            f"- **Type**: {s_type}",
            f"- **Owner**: {owner}",
            f"- **Peer**: {peer}",
            f"- **Status**: {status}",
            f"- **Objective**: {dec_obj or 'N/A'}",
            f"- **Created At**: {created_at}",
            "",
            "## Events Sequence",
            "",
        ]

        if not exported_events:
            lines.append("*(No events recorded)*")
        else:
            for ev in exported_events:
                lines.append(f"### Event #{ev['event_order']} - {ev['kind']}")
                lines.append(f"- **Event ID**: {ev['event_id']}")
                lines.append(f"- **Actor**: {ev['actor_username']} ({ev['actor_agent_id'] or 'system'})")
                lines.append(f"- **Sequence**: {ev['sequence'] if ev['sequence'] is not None else 'N/A'}")
                lines.append(f"- **Visibility**: {ev['visibility']}")
                lines.append(f"- **Content Hash**: {ev['content_hash']}")
                lines.append(f"- **Signature**: {ev['signature'] or 'N/A'}")
                lines.append(f"- **Timestamp**: {ev['created_at']}")
                lines.append("```json")
                lines.append(json.dumps(ev['payload'], indent=2) if isinstance(ev['payload'], (dict, list)) else str(ev['payload']))
                lines.append("```")
                lines.append("")

        return "\n".join(lines)

    else:
        raise ValueError(f"Unsupported format: {format}")
