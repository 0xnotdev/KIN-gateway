"""Read-time projection helper for legacy V1 tasks and messages."""

from __future__ import annotations

import sqlite3
from typing import Any


def legacy_events_from_tasks(conn: sqlite3.Connection, task_id_or_contact: str) -> list[dict[str, Any]]:
    """Project V1 tasks and messages as legacy event records without mutating V11 audit tables."""
    cur = conn.cursor()
    
    # Check if task_id_or_contact matches a specific task_id or contact_username
    cur.execute(
        """\
        SELECT task_id, contact_username, goal, context_json, status, created_at, updated_at, result_json
        FROM tasks
        WHERE task_id = ? OR contact_username = ?
        ORDER BY created_at ASC
        """,
        (task_id_or_contact, task_id_or_contact),
    )
    task_rows = cur.fetchall()

    events: list[dict[str, Any]] = []

    for t in task_rows:
        t_id, contact_user, goal, context_json, status, created_at, updated_at, result_json = t
        
        events.append({
            "source": "legacy_v1",
            "type": "task_summary",
            "task_id": t_id,
            "message_id": None,
            "contact_username": contact_user,
            "goal": goal,
            "context_json": context_json,
            "status": status,
            "created_at": created_at,
            "updated_at": updated_at,
            "result_json": result_json,
            "signature": None,
            "sequence": None,
            "session_id": None,
        })

        cur.execute(
            """\
            SELECT message_id, from_username, content, message_type, created_at, signature
            FROM messages
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (t_id,),
        )
        msg_rows = cur.fetchall()
        for m in msg_rows:
            m_id, from_user, content, msg_type, msg_created, msg_sig = m
            events.append({
                "source": "legacy_v1",
                "type": "message",
                "task_id": t_id,
                "message_id": m_id,
                "from_username": from_user,
                "content": content,
                "message_type": msg_type,
                "created_at": msg_created,
                "signature": msg_sig,
                "sequence": None,
                "session_id": None,
            })

    return events
