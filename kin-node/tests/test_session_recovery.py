"""Tests for session state recovery directly from SQLite database."""

from __future__ import annotations

import json
from pathlib import Path

from kin.storage.db import get_connection, create_schema
from kin.storage.vault import encrypt_field, decrypt_field
from kin.audit.writer import append_session_event


def test_session_recovery_from_db(tmp_path: Path) -> None:
    """Persist session state records and reconstruct them purely from DB connection."""
    db_path = tmp_path / "kin.db"
    vault_key = b"\x09" * 32

    # Step 1: Initialize DB and write session, approval, and session event
    conn1 = get_connection(db_path)
    create_schema(conn1)

    session_id = "sess-recov-123"
    enc_obj = encrypt_field(vault_key, "Perform isolated data cleanup")
    enc_part = encrypt_field(vault_key, json.dumps({"owner": "alice", "peer": "bob"}))

    conn1.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status, objective,
            sender_agent_id, receiver_agent_id, participant_snapshot_json,
            turn_limit, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id, "collaborative", "alice", "bob", "awaiting_approval", enc_obj,
            "agent-alpha", "agent-beta", enc_part, 12, "2026-07-22T12:00:00Z", "2026-07-22T12:00:00Z"
        ),
    )

    enc_req = encrypt_field(vault_key, json.dumps({"action": "delete_tmp_files", "path": "/tmp/clean"}))
    conn1.execute(
        """\
        INSERT INTO approvals (
            approval_id, session_id, agent_id, action_class, request_json, decision, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("app-recov-1", session_id, "agent-alpha", "file_system_write", enc_req, None, "2026-07-22T14:00:00Z"),
    )

    append_session_event(
        conn1,
        vault_key,
        session_id=session_id,
        actor_username="alice",
        actor_agent_id="agent-alpha",
        kind="outbound_envelope_queued",
        visibility="peer_visible",
        payload={"action": "queued_delivery", "payload_hash": "abc123hash"},
        sequence=1,
    )

    conn1.commit()
    conn1.close()

    # Step 2: Open a fresh connection (no in-memory state) and reconstruct SessionState picture
    conn2 = get_connection(db_path)

    cur = conn2.cursor()
    cur.execute(
        """\
        SELECT session_id, type, initiator_username, receiver_username, status, objective,
               sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        FROM sessions WHERE session_id = ?
        """,
        (session_id,),
    )
    s_row = cur.fetchone()
    assert s_row is not None
    assert s_row[0] == session_id
    assert s_row[4] == "awaiting_approval"
    assert decrypt_field(vault_key, enc_obj) == "Perform isolated data cleanup"

    # Recover pending approval
    cur.execute(
        """\
        SELECT approval_id, agent_id, action_class, request_json, decision, expires_at
        FROM approvals WHERE session_id = ? AND decision IS NULL
        """,
        (session_id,),
    )
    app_row = cur.fetchone()
    assert app_row is not None
    assert app_row[0] == "app-recov-1"
    assert app_row[2] == "file_system_write"
    dec_req = decrypt_field(vault_key, app_row[3])
    assert json.loads(dec_req)["action"] == "delete_tmp_files"

    # Recover queued session event
    cur.execute(
        """\
        SELECT event_id, event_order, sequence, kind, payload_json
        FROM session_events WHERE session_id = ?
        ORDER BY event_order ASC
        """,
        (session_id,),
    )
    ev_rows = cur.fetchall()
    assert len(ev_rows) == 1
    assert ev_rows[0][3] == "outbound_envelope_queued"
    dec_ev_payload = decrypt_field(vault_key, ev_rows[0][4])
    assert json.loads(dec_ev_payload)["action"] == "queued_delivery"

    conn2.close()


def test_session_state_reconstruction_from_db(tmp_path: Path) -> None:
    """Assert reconstruct_session_state restores full SessionState matching in-memory execution."""
    from kin.session.reducer import reconstruct_session_state, process_peer_envelope, SessionState, ParticipantInfo

    db_path = tmp_path / "kin_recov.db"
    vault_key = b"\x07" * 32
    conn = get_connection(db_path)
    create_schema(conn)

    session_id = "sess-full-recov"
    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-07-24T00:00:00Z', '2026-07-24T00:00:00Z')
        """,
        (session_id, "ask", "alice", "bob", "active", "alice_ag", "bob_ag", 12),
    )

    append_session_event(
        conn,
        vault_key,
        session_id=session_id,
        actor_username="alice",
        actor_agent_id="alice_ag",
        kind="task_request",
        payload={"goal": "Test goal"},
        sequence=1,
    )
    append_session_event(
        conn,
        vault_key,
        session_id=session_id,
        actor_username="bob",
        actor_agent_id="bob_ag",
        kind="acceptance",
        payload={"reason": "Accepted"},
        sequence=1,
    )
    conn.commit()

    # Reconstruct from fresh query
    state = reconstruct_session_state(conn, vault_key, session_id)
    assert state is not None
    assert state.session_id == session_id
    assert state.initiator_username == "alice"
    assert state.receiver_username == "bob"
    assert state.status == "active"
    assert state.current_turn == 1  # TASK_REQUEST is turn-consuming
    assert state.actor_sequences == {"alice": 1, "bob": 1}
    assert state.participants["alice"].agent_id == "alice_ag"
    assert state.participants["bob"].agent_id == "bob_ag"
    conn.close()
