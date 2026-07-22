"""Tests for kin.storage.vault — encryption at rest and raw file inspection."""

from __future__ import annotations

import json
from pathlib import Path

from kin.storage.db import get_connection, create_schema
from kin.storage.vault import encrypt_field, encrypt_bytes
from kin.identity.storage import get_or_create_vault_key


def test_at_rest_inspection(tmp_path: Path, monkeypatch) -> None:
    """Assert encrypted fields and artifacts do not appear as plaintext in raw SQLite bytes."""
    from kin.identity.storage import _assert_secure_backend
    monkeypatch.setattr("kin.identity.storage._assert_secure_backend", lambda: None)
    
    # Use fake keyring storage for vault key test
    vault_key = b"\x42" * 32

    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)

    secret_marker = "sk-test-should-not-appear"
    secret_objective = "Confidential Plan: sk-test-should-not-appear"
    secret_bytes = b"SECRET-BLOB-CONTENT-sk-test-should-not-appear"

    # Insert into sessions
    enc_obj = encrypt_field(vault_key, secret_objective)
    enc_snap = encrypt_field(vault_key, json.dumps({"note": secret_marker}))
    enc_term = encrypt_field(vault_key, json.dumps({"result": secret_marker}))

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, owner_username, peer_username, status, objective,
            participant_snapshot_json, turn_limit, created_at, updated_at, terminal_result_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("sess-1", "collaborative", "alice", "bob", "active", enc_obj, enc_snap, 12, "2026-07-22T12:00:00Z", "2026-07-22T12:00:00Z", enc_term),
    )

    # Insert into session_events
    enc_payload = encrypt_field(vault_key, json.dumps({"thought": secret_marker}))
    conn.execute(
        """\
        INSERT INTO session_events (
            event_id, session_id, event_order, sequence, actor_username,
            kind, visibility, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("ev-1", "sess-1", 0, 1, "alice", "message", "peer_visible", enc_payload, "2026-07-22T12:00:00Z"),
    )

    # Insert into artifacts
    enc_art_bytes = encrypt_bytes(vault_key, secret_bytes)
    enc_art_meta = encrypt_field(vault_key, json.dumps({"filename": secret_marker}))
    conn.execute(
        """\
        INSERT INTO artifacts (
            artifact_id, session_id, sha256, mime_type, bytes_encrypted,
            metadata_json, offered_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("art-1", "sess-1", "dummyhash", "text/plain", enc_art_bytes, enc_art_meta, "alice", "2026-07-22T12:00:00Z"),
    )

    # Insert into approvals
    enc_req = encrypt_field(vault_key, json.dumps({"command": secret_marker}))
    conn.execute(
        """\
        INSERT INTO approvals (
            approval_id, session_id, action_class, request_json, expires_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("app-1", "sess-1", "shell_execute", enc_req, "2026-07-22T13:00:00Z"),
    )

    conn.commit()
    conn.close()

    # Read raw database file bytes
    raw_bytes = db_path.read_bytes()

    assert secret_marker.encode("utf-8") not in raw_bytes
    assert secret_objective.encode("utf-8") not in raw_bytes
    assert secret_bytes not in raw_bytes
