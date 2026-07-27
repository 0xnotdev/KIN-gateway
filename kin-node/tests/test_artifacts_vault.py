"""Unit tests for kin.artifacts.vault module (§15.8 M5 Phase 1)."""

from __future__ import annotations

import hashlib
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.agent_registry.registry import register_card
from kin.artifacts.vault import (
    ArtifactCorruptedError,
    ArtifactIdConflictError,
    ArtifactMetadata,
    ArtifactNotFoundError,
    ArtifactTooLargeError,
    get_artifact_metadata,
    load_artifact_bytes,
    store_artifact,
)
from kin.schemas import (
    TIMESTAMP_REGEX,
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    AutonomyLevel,
    EmbeddedAdapterConfig,
)
from kin.session.orchestrator import OrchestratorError, advance_session_turn
from kin.session.reducer import reconstruct_session_state
from kin.storage.migrations import run_migrations


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    run_migrations(conn)
    vault_key = b"test-vault-key-32bytes-long!!!!!"
    now_str = "2026-07-25T12:00:00Z"
    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES ('sess_test_1', 'ask', 'alice', 'bob', 'active', 'alice_agent', 'bob_agent', 12, ?, ?)
        """,
        (now_str, now_str),
    )
    conn.commit()
    return conn, vault_key


def test_store_and_load_roundtrip(db_conn):
    """Requirement 1 & 2: Round-trip empty bytes, text, and binary with null bytes. Verify SHA-256 accuracy."""
    conn, vault_key = db_conn
    test_cases = [
        (b"", "application/octet-stream"),
        (b"Hello world artifact content", "text/plain"),
        (b"\x00\x01\x02\xff\x00\x00\xfe\x42", "application/x-binary"),
    ]

    for raw_bytes, mime_type in test_cases:
        meta = store_artifact(
            conn,
            vault_key,
            session_id="sess_test_1",
            raw_bytes=raw_bytes,
            mime_type=mime_type,
            offered_by="alice",
            preview_policy="auto",
            max_bytes=100_000,
        )

        assert isinstance(meta, ArtifactMetadata)
        expected_sha = hashlib.sha256(raw_bytes).hexdigest()
        assert meta.sha256 == expected_sha
        assert meta.size_bytes == len(raw_bytes)
        assert meta.mime_type == mime_type
        assert meta.offered_by == "alice"
        assert meta.preview_policy == "auto"

        loaded_bytes = load_artifact_bytes(conn, vault_key, meta.artifact_id)
        assert loaded_bytes == raw_bytes


def test_oversized_artifact_rejected_no_side_effects(db_conn):
    """Requirement 3: Oversized artifact raises ArtifactTooLargeError and zero rows inserted."""
    conn, vault_key = db_conn
    raw_bytes = b"X" * 1005
    max_bytes = 1000

    with pytest.raises(ArtifactTooLargeError, match="exceeds limit"):
        store_artifact(
            conn,
            vault_key,
            session_id="sess_test_1",
            raw_bytes=raw_bytes,
            mime_type="text/plain",
            offered_by="alice",
            preview_policy="auto",
            max_bytes=max_bytes,
        )

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM artifacts WHERE session_id = 'sess_test_1'")
    assert cur.fetchone()[0] == 0


def test_corruption_detection_ciphertext_and_hash_drift(db_conn):
    """Requirement 4: Tampered ciphertext or stored SHA-256 mismatch raises ArtifactCorruptedError."""
    conn, vault_key = db_conn
    raw_bytes = b"Secret artifact payload"
    meta = store_artifact(
        conn,
        vault_key,
        session_id="sess_test_1",
        raw_bytes=raw_bytes,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=100_000,
    )

    # 1. Corrupt encrypted ciphertext bytes in DB
    cur = conn.cursor()
    cur.execute(
        "SELECT bytes_encrypted FROM artifacts WHERE artifact_id = ?",
        (meta.artifact_id,),
    )
    enc_bytes = bytearray(cur.fetchone()[0])
    enc_bytes[-1] ^= 0xFF  # Flip bit in AEAD tag
    cur.execute(
        "UPDATE artifacts SET bytes_encrypted = ? WHERE artifact_id = ?",
        (bytes(enc_bytes), meta.artifact_id),
    )
    conn.commit()

    with pytest.raises(ArtifactCorruptedError, match="decryption failed"):
        load_artifact_bytes(conn, vault_key, meta.artifact_id)

    # 2. Restore encrypted bytes, but tamper stored sha256 column
    valid_enc = store_artifact(
        conn,
        vault_key,
        session_id="sess_test_1",
        raw_bytes=b"Payload 2",
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=100_000,
    )
    cur.execute(
        "UPDATE artifacts SET sha256 = 'bad_tampered_hash_00000000000000000000000000' WHERE artifact_id = ?",
        (valid_enc.artifact_id,),
    )
    conn.commit()

    with pytest.raises(ArtifactCorruptedError, match="SHA-256 hash mismatch"):
        load_artifact_bytes(conn, vault_key, valid_enc.artifact_id)


def test_get_artifact_metadata_without_vault_key(db_conn):
    """Requirement 5: get_artifact_metadata requires no vault_key and returns correct fields."""
    conn, vault_key = db_conn
    raw_bytes = b"Metadata test artifact"
    meta_stored = store_artifact(
        conn,
        vault_key,
        session_id="sess_test_1",
        raw_bytes=raw_bytes,
        mime_type="application/json",
        offered_by="alice",
        preview_policy="deny",
        max_bytes=100_000,
        source="peer_received",
    )

    # Call get_artifact_metadata WITHOUT vault_key
    meta_fetched = get_artifact_metadata(conn, meta_stored.artifact_id)

    assert meta_fetched.artifact_id == meta_stored.artifact_id
    assert meta_fetched.session_id == "sess_test_1"
    assert meta_fetched.sha256 == hashlib.sha256(raw_bytes).hexdigest()
    assert meta_fetched.mime_type == "application/json"
    assert meta_fetched.size_bytes == len(raw_bytes)
    assert meta_fetched.offered_by == "alice"
    assert meta_fetched.preview_policy == "deny"
    assert meta_fetched.source == "peer_received"
    assert meta_fetched.created_at == meta_stored.created_at


def test_artifact_not_found(db_conn):
    """Requirement 6: get_artifact_metadata and load_artifact_bytes raise ArtifactNotFoundError for missing ID."""
    conn, vault_key = db_conn
    missing_id = "art_nonexistent_9999"

    with pytest.raises(ArtifactNotFoundError, match="not found"):
        load_artifact_bytes(conn, vault_key, missing_id)

    with pytest.raises(ArtifactNotFoundError, match="not found"):
        get_artifact_metadata(conn, missing_id)


def test_identical_content_distinct_artifact_ids(db_conn):
    """Requirement 7: Identical content stored twice produces identical SHA-256 but distinct artifact_ids."""
    conn, vault_key = db_conn
    raw_bytes = b"Identical artifact content"

    art1 = store_artifact(
        conn,
        vault_key,
        session_id="sess_test_1",
        raw_bytes=raw_bytes,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=100_000,
    )

    art2 = store_artifact(
        conn,
        vault_key,
        session_id="sess_test_1",
        raw_bytes=raw_bytes,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=100_000,
    )

    assert art1.sha256 == art2.sha256
    assert art1.artifact_id != art2.artifact_id


def test_orchestrator_artifact_too_large_refactored():
    """Requirement 8 & Confirmation: Orchestrator catches ArtifactTooLargeError, writes security audit, marks failed."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    run_migrations(conn)
    vault_key = b"test-vault-key-32bytes-long!!!!!"
    alice_priv = ed25519.Ed25519PrivateKey.generate()
    now_str = "2026-07-25T12:00:00Z"
    sess_id = "s_art_too_large"

    # Register card with max_artifact_bytes = 100
    card = AgentCard(
        schema_version="1.1",
        id="alice_agent",
        name="Alice Agent",
        description="Alice Agent",
        adapter=EmbeddedAdapterConfig(type="embedded", provider="openai", model="gpt-4o"),
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="none", shell="deny", max_runtime_seconds=30, max_artifact_bytes=100),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ALLOW, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )
    register_card(conn, vault_key, card)
    conn.execute("UPDATE agents SET enabled = 1")

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES (?, 'ask', 'alice', 'bob', 'active', 'alice_agent', 'bob_agent', 12, ?, ?)
        """,
        (sess_id, now_str, now_str),
    )
    conn.commit()

    # Mock adapter response returning artifact of 500 bytes (> max_artifact_bytes=100)
    mock_artifact = MagicMock()
    mock_artifact.mime_type = "text/plain"
    mock_artifact.path_or_bytes = b"A" * 500

    with patch("kin.session.orchestrator.get_adapter") as mock_get_adapter, \
         patch("kin.session.orchestrator.validate_adapter_output") as mock_val:

        mock_adapter = MagicMock()
        mock_adapter.invoke.return_value = MagicMock(
            error=None,
            events=[],
            message=None,
            artifacts=[mock_artifact],
            terminal=False,
        )
        mock_get_adapter.return_value = mock_adapter

        mock_val_out = MagicMock()
        mock_val_out.valid = True
        mock_val.return_value = mock_val_out

        with pytest.raises(OrchestratorError) as exc_info:
            advance_session_turn(conn, vault_key, alice_priv, "alice", sess_id)

        assert exc_info.value.code == "ARTIFACT_TOO_LARGE"
        assert "exceeds card max_artifact_bytes (100)" in str(exc_info.value)

        # Assert session state moved to 'failed'
        state = reconstruct_session_state(conn, vault_key, sess_id)
        assert state.status == "failed"

        # Assert security audit event was written
        cur = conn.cursor()
        cur.execute(
            "SELECT category, summary FROM audit_events WHERE session_id = ?",
            (sess_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "security_rejection"
        assert "exceeds card max_artifact_bytes" in row[1]


def test_created_at_timestamp_format_matches_schema_regex(db_conn):
    """Requirement 2 regression test: created_at must match TIMESTAMP_REGEX (ending in 'Z', not '+00:00') for both now=None and explicit tz-aware datetime."""
    import datetime

    conn, vault_key = db_conn

    # 1. Test now=None default path (which calls datetime.now(timezone.utc))
    meta_default = store_artifact(
        conn,
        vault_key,
        session_id="sess_test_1",
        raw_bytes=b"Default now timestamp test",
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=100_000,
        now=None,
    )
    assert TIMESTAMP_REGEX.match(meta_default.created_at) is not None
    assert meta_default.created_at.endswith("Z")
    assert "+00:00" not in meta_default.created_at

    # 2. Test explicit timezone-aware datetime path (e.g. datetime.now(timezone.utc))
    explicit_dt = datetime.datetime.now(datetime.timezone.utc)
    meta_explicit = store_artifact(
        conn,
        vault_key,
        session_id="sess_test_1",
        raw_bytes=b"Explicit now timestamp test",
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=100_000,
        now=explicit_dt,
    )
    assert TIMESTAMP_REGEX.match(meta_explicit.created_at) is not None
    assert meta_explicit.created_at.endswith("Z")
    assert "+00:00" not in meta_explicit.created_at


def test_store_artifact_explicit_id_and_conflict_branches(db_conn):
    """Test all 3 artifact_id branches: auto-generation, explicit artifact_id, idempotent re-storage, and sha256 conflict rejection."""
    conn, vault_key = db_conn
    raw_bytes = b"Explicit ID test payload"
    explicit_id = "art_custom_id_123"

    # Branch 1 & 2: Store with explicit artifact_id
    meta1 = store_artifact(
        conn,
        vault_key,
        session_id="sess_test_1",
        raw_bytes=raw_bytes,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=100_000,
        artifact_id=explicit_id,
    )
    assert meta1.artifact_id == explicit_id

    # Branch 3: Store identical payload with same explicit artifact_id (idempotent no-op)
    meta2 = store_artifact(
        conn,
        vault_key,
        session_id="sess_test_1",
        raw_bytes=raw_bytes,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=100_000,
        artifact_id=explicit_id,
    )
    assert meta2.artifact_id == explicit_id
    assert meta2.sha256 == meta1.sha256

    # Branch 4: Store differing payload with same explicit artifact_id (raises ArtifactIdConflictError)
    differing_bytes = b"COMPLETELY DIFFERENT PAYLOAD"
    with pytest.raises(ArtifactIdConflictError, match="already exists with different sha256"):
        store_artifact(
            conn,
            vault_key,
            session_id="sess_test_1",
            raw_bytes=differing_bytes,
            mime_type="text/plain",
            offered_by="alice",
            preview_policy="auto",
            max_bytes=100_000,
            artifact_id=explicit_id,
        )


