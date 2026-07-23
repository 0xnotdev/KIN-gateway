"""Tests for kin.storage.db — schema creation and table structure."""

from __future__ import annotations

import tempfile
from pathlib import Path

from kin.storage.db import create_schema, get_connection

# Expected columns per table, including local operational state for reliable relay delivery.
EXPECTED_SCHEMA: dict[str, set[str]] = {
    "identity": {
        "username",
        "public_key",
        "keychain_ref",
        "protocol_version",
    },
    "contacts": {
        "username",
        "display_name",
        "public_key",
        "x25519_public_key",
        "endpoint",
        "autonomy_level",
        "fingerprint_verified_at",
    },
    "tasks": {
        "task_id",
        "contact_username",
        "goal",
        "context_json",
        "status",
        "created_at",
        "updated_at",
        "result_json",
        "draft_content",
        "draft_message_type",
        "agent_name",
        "peer_agent_name",
        "peer_task_id",
        "origin_ref_id",
    },
    "messages": {
        "message_id",
        "task_id",
        "from_username",
        "content",
        "message_type",
        "created_at",
        "signature",
    },
    "settings": {"key", "value"},
    "processed_relay_messages": {"message_id", "processed_at"},
    "schema_migrations": {"version", "name", "applied_at", "checksum"},
    "agents": {"agent_id", "name", "adapter_type", "local_card_json", "published_card_json", "enabled", "availability", "created_at", "updated_at", "card_version"},
    "peer_agent_cards": {"peer_username", "agent_id", "card_json", "content_hash", "status", "first_seen_at", "last_seen_at"},
    "sessions": {"session_id", "type", "owner_username", "peer_username", "status", "objective", "sender_agent_id", "receiver_agent_id", "participant_snapshot_json", "turn_limit", "created_at", "updated_at", "terminal_result_json"},
    "session_events": {"event_id", "session_id", "event_order", "sequence", "actor_username", "actor_agent_id", "kind", "visibility", "payload_json", "signature", "created_at"},
    "artifacts": {"artifact_id", "session_id", "sha256", "mime_type", "bytes_encrypted", "metadata_json", "offered_by", "created_at"},
    "approvals": {"approval_id", "session_id", "agent_id", "action_class", "request_json", "decision", "decided_at", "expires_at"},
    "audit_events": {"audit_id", "correlation_id", "session_id", "category", "actor_username", "summary", "payload_json", "created_at"},
}


def test_schema_creates_all_tables_with_expected_columns() -> None:
    """Create the schema in a temp DB and verify every local table and column."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test_kin.db"
        conn = get_connection(db_path)
        try:
            create_schema(conn)

            # Verify all four tables exist
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = {row[0] for row in cursor.fetchall()}
            assert tables == set(EXPECTED_SCHEMA.keys()), (
                f"Expected tables {set(EXPECTED_SCHEMA.keys())}, got {tables}"
            )

            # Verify each table has exactly the expected columns
            for table, expected_cols in EXPECTED_SCHEMA.items():
                cursor = conn.execute(f"PRAGMA table_info({table})")
                actual_cols = {row[1] for row in cursor.fetchall()}
                assert actual_cols == expected_cols, (
                    f"Table '{table}': expected columns {expected_cols}, got {actual_cols}"
                )
        finally:
            conn.close()
