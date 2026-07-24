"""Tests for kin.audit — immutability triggers and duplicate envelope delivery."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import pytest

from kin.storage.db import get_connection, create_schema
from kin.audit.writer import append_session_event, write_audit_event


def test_immutability(tmp_path: Path) -> None:
    """Assert session_events and audit_events reject UPDATE and DELETE operations."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)
    vault_key = b"\x01" * 32

    # Insert a dummy session first to satisfy foreign key
    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            turn_limit, created_at, updated_at
        ) VALUES ('sess-imm', 'collaborative', 'alice', 'bob', 'active', 12, '2026-07-22T12:00:00Z', '2026-07-22T12:00:00Z')
        """
    )
    conn.commit()

    # Append session event
    res = append_session_event(
        conn,
        vault_key,
        session_id="sess-imm",
        actor_username="alice",
        actor_agent_id=None,
        kind="message",
        payload={"msg": "hello"},
    )
    event_id = res["event_id"]

    # Write audit event directly
    audit_id = write_audit_event(
        conn,
        vault_key,
        category="state_transition",
        summary="Test state transition",
        session_id="sess-imm",
    )

    # Attempt UPDATE on session_events -> MUST FAIL
    with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError), match="session_events is append-only"):
        conn.execute("UPDATE session_events SET kind = 'hacked' WHERE event_id = ?", (event_id,))

    # Attempt DELETE on session_events -> MUST FAIL
    with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError), match="session_events is append-only"):
        conn.execute("DELETE FROM session_events WHERE event_id = ?", (event_id,))

    # Attempt UPDATE on audit_events -> MUST FAIL
    with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError), match="audit_events is append-only"):
        conn.execute("UPDATE audit_events SET summary = 'hacked' WHERE audit_id = ?", (audit_id,))

    # Attempt DELETE on audit_events -> MUST FAIL
    with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError), match="audit_events is append-only"):
        conn.execute("DELETE FROM audit_events WHERE audit_id = ?", (audit_id,))

    conn.close()


def test_duplicate_delivery(tmp_path: Path) -> None:
    """Assert duplicate sequence envelope delivery is correctly categorized and handled."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)
    vault_key = b"\x01" * 32

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            turn_limit, created_at, updated_at
        ) VALUES ('sess-dup', 'collaborative', 'alice', 'bob', 'active', 12, '2026-07-22T12:00:00Z', '2026-07-22T12:00:00Z')
        """
    )
    conn.commit()

    payload_1 = {"text": "Original message body"}

    # First delivery
    res1 = append_session_event(
        conn,
        vault_key,
        session_id="sess-dup",
        actor_username="alice",
        actor_agent_id="code-agent",
        kind="envelope_received",
        payload=payload_1,
        sequence=1,
    )
    assert res1["status"] == "appended"
    orig_event_id = res1["event_id"]

    # Duplicate delivery with identical payload -> duplicate_delivery
    res2 = append_session_event(
        conn,
        vault_key,
        session_id="sess-dup",
        actor_username="alice",
        actor_agent_id="code-agent",
        kind="envelope_received",
        payload=payload_1,
        sequence=1,
    )
    assert res2["status"] == "duplicate"
    assert res2["event_id"] == orig_event_id

    # Verify audit_events recorded duplicate_delivery
    cur = conn.cursor()
    cur.execute("SELECT category, summary FROM audit_events WHERE category = 'duplicate_delivery'")
    dup_audit = cur.fetchone()
    assert dup_audit is not None
    assert "Duplicate envelope sequence 1" in dup_audit[1]

    # Duplicate sequence with DIFFERENT payload -> security_rejection
    payload_modified = {"text": "TAMPERED / MISMATCHED message body"}
    res3 = append_session_event(
        conn,
        vault_key,
        session_id="sess-dup",
        actor_username="alice",
        actor_agent_id="code-agent",
        kind="envelope_received",
        payload=payload_modified,
        sequence=1,
    )
    assert res3["status"] == "rejected"
    assert res3["error_code"] == "SEQUENCE_REUSE_MISMATCH"

    # Verify audit_events recorded security_rejection
    cur.execute("SELECT category, summary FROM audit_events WHERE category = 'security_rejection'")
    sec_audit = cur.fetchone()
    assert sec_audit is not None
    assert "Sequence reuse mismatch" in sec_audit[1]

    # Assert exactly 1 row in session_events
    cur.execute("SELECT COUNT(*) FROM session_events WHERE session_id = 'sess-dup'")
    assert cur.fetchone()[0] == 1

    conn.close()
