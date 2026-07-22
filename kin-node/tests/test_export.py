"""Tests for kin.audit.export — deterministic JSON/Markdown session transcripts."""

from __future__ import annotations

import json
from pathlib import Path

from kin.storage.db import get_connection, create_schema
from kin.storage.vault import encrypt_field
from kin.audit.writer import append_session_event
from kin.audit.export import export_session
from kin.audit.legacy import legacy_events_from_tasks


def test_golden_markdown_json_fixtures(tmp_path: Path) -> None:
    """Assert deterministic JSON and Markdown export outputs match expected golden structures."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)
    vault_key = b"\x07" * 32

    enc_obj = encrypt_field(vault_key, "Review code changes for security vulnerabilities")
    enc_snap = encrypt_field(vault_key, json.dumps({"agent_id": "code-scout", "version": "1.1"}))

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, owner_username, peer_username, status, objective,
            sender_agent_id, receiver_agent_id, participant_snapshot_json,
            turn_limit, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "sess-golden-1", "collaborative", "alice", "bob", "active", enc_obj,
            "code-scout", "patch-bot", enc_snap, 12, "2026-07-22T12:00:00Z", "2026-07-22T12:00:00Z"
        ),
    )
    conn.commit()

    append_session_event(
        conn,
        vault_key,
        session_id="sess-golden-1",
        actor_username="alice",
        actor_agent_id="code-scout",
        kind="proposal",
        visibility="peer_visible",
        payload={"proposal_id": "p-100", "diff": "--- file.py\n+++ file.py\n@@ -1 +1 @@\n-bug\n+fix"},
        sequence=1,
        signature="sig-alice-1",
    )

    json_output = export_session(conn, vault_key, "sess-golden-1", format="json")
    md_output = export_session(conn, vault_key, "sess-golden-1", format="markdown")

    parsed_json = json.loads(json_output)
    assert parsed_json["session"]["session_id"] == "sess-golden-1"
    assert parsed_json["session"]["objective"] == "Review code changes for security vulnerabilities"
    assert len(parsed_json["events"]) == 1
    assert parsed_json["events"][0]["kind"] == "proposal"
    assert parsed_json["events"][0]["payload"]["proposal_id"] == "p-100"

    assert "# Session Transcript: sess-golden-1" in md_output
    assert "Review code changes for security vulnerabilities" in md_output
    assert "Event #0 - proposal" in md_output

    conn.close()


def test_event_ordering(tmp_path: Path) -> None:
    """Assert export strictly orders by event_order, regardless of created_at timestamps."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)
    vault_key = b"\x07" * 32

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, owner_username, peer_username, status,
            turn_limit, created_at, updated_at
        ) VALUES ('sess-order', 'collaborative', 'alice', 'bob', 'active', 12, '2026-07-22T12:00:00Z', '2026-07-22T12:00:00Z')
        """
    )
    conn.commit()

    # Insert event_order 0 with a LATER timestamp
    conn.execute(
        """\
        INSERT INTO session_events (
            event_id, session_id, event_order, sequence, actor_username,
            kind, visibility, payload_json, created_at
        ) VALUES ('ev-first', 'sess-order', 0, 1, 'alice', 'init', 'peer_visible', ?, '2026-07-22T15:00:00Z')
        """,
        (encrypt_field(vault_key, json.dumps({"step": 1})),)
    )

    # Insert event_order 1 with an EARLIER timestamp
    conn.execute(
        """\
        INSERT INTO session_events (
            event_id, session_id, event_order, sequence, actor_username,
            kind, visibility, payload_json, created_at
        ) VALUES ('ev-second', 'sess-order', 1, 2, 'bob', 'reply', 'peer_visible', ?, '2026-07-22T10:00:00Z')
        """,
        (encrypt_field(vault_key, json.dumps({"step": 2})),)
    )
    conn.commit()

    json_output = export_session(conn, vault_key, "sess-order", format="json")
    parsed = json.loads(json_output)

    # Must be ordered strictly by event_order (0 then 1), not created_at (15:00 then 10:00)
    assert parsed["events"][0]["event_id"] == "ev-first"
    assert parsed["events"][0]["event_order"] == 0
    assert parsed["events"][1]["event_id"] == "ev-second"
    assert parsed["events"][1]["event_order"] == 1

    conn.close()


def test_redaction(tmp_path: Path) -> None:
    """Assert local_only events are excluded when include_private_notes=False."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)
    vault_key = b"\x07" * 32

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, owner_username, peer_username, status,
            turn_limit, created_at, updated_at
        ) VALUES ('sess-redact', 'collaborative', 'alice', 'bob', 'active', 12, '2026-07-22T12:00:00Z', '2026-07-22T12:00:00Z')
        """
    )
    conn.commit()

    append_session_event(
        conn, vault_key, session_id="sess-redact", actor_username="alice",
        actor_agent_id=None, kind="public_msg", visibility="peer_visible", payload={"text": "Hello Peer"}
    )
    append_session_event(
        conn, vault_key, session_id="sess-redact", actor_username="alice",
        actor_agent_id=None, kind="private_note", visibility="local_only", payload={"text": "Secret note to self"}
    )

    # Exclude private notes
    json_redacted = export_session(conn, vault_key, "sess-redact", format="json", include_private_notes=False)
    parsed_redacted = json.loads(json_redacted)
    assert len(parsed_redacted["events"]) == 1
    assert parsed_redacted["events"][0]["kind"] == "public_msg"

    # Include private notes
    json_full = export_session(conn, vault_key, "sess-redact", format="json", include_private_notes=True)
    parsed_full = json.loads(json_full)
    assert len(parsed_full["events"]) == 2
    assert parsed_full["events"][1]["kind"] == "private_note"

    conn.close()


def test_legacy_projection(tmp_path: Path) -> None:
    """Assert legacy V1 tasks and messages project into read-only event dicts with original IDs."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)

    conn.execute("INSERT INTO contacts (username, display_name) VALUES ('charlie', 'Charlie')")
    conn.execute(
        """\
        INSERT INTO tasks (task_id, contact_username, goal, status, created_at)
        VALUES ('task-v1-99', 'charlie', 'Legacy Goal', 'completed', '2026-07-20T10:00:00Z')
        """
    )
    conn.execute(
        """\
        INSERT INTO messages (message_id, task_id, from_username, content, message_type, created_at, signature)
        VALUES ('msg-v1-1', 'task-v1-99', 'charlie', 'Legacy text', 'user', '2026-07-20T10:01:00Z', 'sig-legacy')
        """
    )
    conn.commit()

    proj = legacy_events_from_tasks(conn, "task-v1-99")
    assert len(proj) == 2
    assert proj[0]["source"] == "legacy_v1"
    assert proj[0]["task_id"] == "task-v1-99"
    assert proj[0]["signature"] is None

    assert proj[1]["source"] == "legacy_v1"
    assert proj[1]["message_id"] == "msg-v1-1"
    assert proj[1]["signature"] == "sig-legacy"
    assert proj[1]["sequence"] is None
    assert proj[1]["session_id"] is None

    conn.close()
