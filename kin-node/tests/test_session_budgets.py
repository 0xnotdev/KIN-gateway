"""Tests for SessionType validation and aggregate session budget enforcement (§15.8 M5 Phase 6)."""

import datetime
import hashlib
import json
import sqlite3
import pytest
from unittest.mock import MagicMock

from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from kin.adapters import AdapterRequest, AdapterResponse
from kin.schemas import (
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    AutonomyLevel,
    LocalCommandAdapterConfig,
    MessageKind,
    SessionType,
    compute_content_hash,
    sign_envelope,
)
from kin.session.orchestrator import OrchestratorError, advance_session_turn
from kin.storage.migrations import run_migrations
from kin.transport.v11 import (
    DEFAULT_BUILD_ARTIFACT_BYTES_BUDGET,
    DEFAULT_BUILD_COST_BUDGET_ESTIMATE,
    DEFAULT_BUILD_MAX_TURNS,
    DEFAULT_BUILD_RUNTIME_BUDGET,
    dispatch_session,
    ingest_envelope,
)


def _gen_ed_keypair():
    priv = ed25519.Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def _gen_x255_keypair():
    priv = x25519.X25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    return priv.private_bytes_raw(), pub_bytes


@pytest.fixture
def profile_db():
    """Create an in-memory SQLite database initialized via run_migrations."""
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def identity_keys(profile_db):
    """Seed local identity and return Ed25519/X25519 keys."""
    ed_priv, ed_pub = _gen_ed_keypair()
    x255_priv, x255_pub = _gen_x255_keypair()

    ed_pub_hex = ed_pub.public_bytes_raw().hex()
    profile_db.execute(
        "INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES ('alice', ?, 'key_ref', '1.1')",
        (ed_pub_hex,),
    )
    profile_db.commit()
    return ed_priv, ed_pub, x255_priv, x255_pub


from kin.agent_registry.registry import register_card


@pytest.fixture
def mock_agent_card(profile_db, tmp_path):
    """Register a local agent card in registry."""
    card = AgentCard(
        schema_version="1.1",
        id="ag_budget_test",
        name="Budget Test Agent",
        description="Agent for testing session budgets",
        adapter=LocalCommandAdapterConfig(type="local_command", command="python", working_directory=str(tmp_path)),
        capabilities=AgentCapabilities(tags=["test"], accepts=["text/plain"], produces=["text/plain"]),
        boundaries=AgentBoundaries(
            network_access="allow",
            filesystem="workspace_read_write_with_approval",
            shell="approval_required",
            max_runtime_seconds=300,
            max_artifact_bytes=10000000,
        ),
        autonomy=AgentAutonomy(
            relay_information=AutonomyLevel.ALWAYS_ASK,
            propose_actions=AutonomyLevel.ALWAYS_ASK,
            execute_local_actions=AutonomyLevel.ALWAYS_ASK,
        ),
    )
    vault_key = b"01234567890123456789012345678901"
    register_card(profile_db, vault_key, card)
    return card


def _seed_contact(conn, username: str, ed_pub: ed25519.Ed25519PublicKey, x255_pub_bytes: bytes):
    """Helper to add verified contact to contacts table."""
    conn.execute(
        """\
        INSERT INTO contacts (
            username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at
        ) VALUES (?, ?, ?, ?, '', 'always_ask', '2026-07-30T10:00:00Z')
        """,
        (username, username.title(), ed_pub.public_bytes_raw().hex(), x255_pub_bytes.hex()),
    )
    conn.commit()


def test_session_type_rejection(profile_db, identity_keys):
    """1. SessionType rejection: dispatch_session rejects invalid mode string; raw envelope with bad mode is rejected by ingest_envelope."""
    ed_priv, ed_pub, x255_priv, x255_pub = identity_keys

    # A. dispatch_session with invalid collaboration_mode raises ValueError
    with pytest.raises(ValueError, match="Invalid collaboration_mode 'invalid_mode'"):
        dispatch_session(
            profile_db,
            b"01234567890123456789012345678901",
            ed_priv,
            x255_priv,
            sender_username="alice",
            peer_username="bob",
            sender_agent_id="ag_sender",
            receiver_agent_id="ag_receiver",
            collaboration_mode="invalid_mode",
            goal="Test invalid session type",
        )

    # B. Raw envelope with invalid collaboration_mode processed by ingest_envelope is rejected
    payload = {
        "collaboration_mode": "unrecognized_mode_xyz",
        "goal": "Malicious payload test",
        "requested_agent_id": "ag_receiver",
        "peer_username": "alice",
        "max_turns": 12,
    }
    now_str = "2026-07-30T10:00:00Z"
    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "sess_bad_type_1",
        "sequence": 1,
        "actor_username": "bob",
        "actor_agent_id": "ag_bob",
        "timestamp": now_str,
        "kind": MessageKind.TASK_REQUEST.value,
        "content_hash": compute_content_hash(payload),
        "payload": payload,
    }
    bob_ed_priv, bob_ed_pub = _gen_ed_keypair()
    env_dict["signature"] = sign_envelope(env_dict, bob_ed_priv)

    _seed_contact(profile_db, "bob", bob_ed_pub, b"\x00" * 32)

    def get_pubkey(un: str):
        return bob_ed_pub if un == "bob" else None

    ack = ingest_envelope(profile_db, b"01234567890123456789012345678901", env_dict, get_public_key_fn=get_pubkey)

    assert ack.status == "rejected"
    assert ack.error_code == "INVALID_SESSION_TYPE"

    # Confirm no session row was created
    cur = profile_db.cursor()
    cur.execute("SELECT COUNT(*) FROM sessions WHERE session_id = 'sess_bad_type_1'")
    assert cur.fetchone()[0] == 0


def test_default_budgets_for_build_and_delegate(profile_db, identity_keys):
    """2. build_pipeline / delegate_subtask get non-null default budgets; ask remains uncapped (NULL)."""
    ed_priv, ed_pub, x255_priv, x255_pub = identity_keys

    # Seed contact bob
    bob_ed_priv, bob_ed_pub = _gen_ed_keypair()
    _seed_contact(profile_db, "bob", bob_ed_pub, b"\x00" * 32)

    vault_key = b"01234567890123456789012345678901"

    # 1. Dispatch build_pipeline without explicit budgets
    res_build = dispatch_session(
        profile_db,
        vault_key,
        ed_priv,
        x255_priv,
        sender_username="alice",
        peer_username="bob",
        sender_agent_id="ag_sender",
        receiver_agent_id="ag_receiver",
        collaboration_mode=SessionType.BUILD_PIPELINE,
        goal="Build binary pipeline",
    )
    s_id_build = res_build["session_id"]

    cur = profile_db.cursor()
    cur.execute(
        """\
        SELECT turn_limit, runtime_budget_seconds, artifact_bytes_budget, cost_budget_estimate
        FROM sessions WHERE session_id = ?
        """,
        (s_id_build,),
    )
    b_row = cur.fetchone()
    assert b_row[0] == DEFAULT_BUILD_MAX_TURNS  # 50
    assert b_row[1] == DEFAULT_BUILD_RUNTIME_BUDGET  # 86400
    assert b_row[2] == DEFAULT_BUILD_ARTIFACT_BYTES_BUDGET  # 50_000_000
    assert b_row[3] == DEFAULT_BUILD_COST_BUDGET_ESTIMATE  # 100.0

    # 2. Dispatch ask without explicit budgets
    res_ask = dispatch_session(
        profile_db,
        vault_key,
        ed_priv,
        x255_priv,
        sender_username="alice",
        peer_username="bob",
        sender_agent_id="ag_sender",
        receiver_agent_id="ag_receiver",
        collaboration_mode=SessionType.ASK,
        goal="Quick question",
    )
    s_id_ask = res_ask["session_id"]

    cur.execute(
        """\
        SELECT turn_limit, runtime_budget_seconds, artifact_bytes_budget, cost_budget_estimate
        FROM sessions WHERE session_id = ?
        """,
        (s_id_ask,),
    )
    a_row = cur.fetchone()
    assert a_row[0] == 12  # default ask max turns
    assert a_row[1] is None  # uncapped
    assert a_row[2] is None  # uncapped
    assert a_row[3] is None  # uncapped


def test_runtime_budget_exhaustion(profile_db, identity_keys, mock_agent_card, monkeypatch):
    """4. Required test: runtime budget exhaustion pauses session BEFORE adapter invocation (0 adapter calls), writing audit event."""
    ed_priv, ed_pub, x255_priv, x255_pub = identity_keys
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_rt_budget"

    # Seed session with created_at 2 hours in past (7200s), runtime_budget_seconds=3600 (1 hour)
    created_at_past = "2026-07-30T08:00:00Z"
    now_current = datetime.datetime.fromisoformat("2026-07-30T10:00:00Z")  # 7200s elapsed
    now_str = "2026-07-30T10:00:00Z"

    profile_db.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, sender_agent_id, receiver_agent_id, turn_limit,
            runtime_budget_seconds, artifact_bytes_budget, cumulative_artifact_bytes,
            cost_budget_estimate, cumulative_cost_estimate,
            created_at, updated_at
        ) VALUES (?, 'build_pipeline', 'alice', 'bob', 'active', 'Build task', ?, 'ag_receiver', 50, 3600, NULL, 0, NULL, 0.0, ?, ?)
        """,
        (session_id, mock_agent_card.id, created_at_past, created_at_past),
    )
    profile_db.commit()

    # Mock adapter to verify zero calls
    mock_adapter = MagicMock()
    monkeypatch.setattr("kin.session.orchestrator.get_adapter", lambda card: mock_adapter)

    # Call advance_session_turn with controlled now_current
    res = advance_session_turn(
        profile_db,
        vault_key,
        ed_priv,
        "alice",
        session_id,
        now=now_current,
    )

    # 1. Session must be paused
    assert res["status"] == "paused"
    assert res["exhausted_dimension"] == "runtime_budget_seconds"

    # 2. Adapter MUST NEVER BE INVOKED (0 calls)
    assert mock_adapter.invoke.call_count == 0

    # 3. DB status updated to paused
    cur = profile_db.cursor()
    cur.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,))
    assert cur.fetchone()[0] == "paused"

    # 4. Audit trail contains budget_exhausted entry naming runtime_budget_seconds
    cur.execute("SELECT category, summary FROM audit_events WHERE session_id = ? AND category = 'budget_exhausted'", (session_id,))
    audit_rows = cur.fetchall()
    assert len(audit_rows) > 0
    assert "runtime_budget_seconds" in audit_rows[0][1]


def test_artifact_bytes_budget_exhaustion(profile_db, identity_keys, mock_agent_card, monkeypatch):
    """5. Artifact bytes budget exhaustion pauses session before adapter invocation (0 adapter calls)."""
    ed_priv, ed_pub, x255_priv, x255_pub = identity_keys
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_art_bytes_budget"
    now_str = "2026-07-30T10:00:00Z"

    # Seed session with artifact_bytes_budget=1000 and cumulative_artifact_bytes=1200
    profile_db.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, sender_agent_id, receiver_agent_id, turn_limit,
            runtime_budget_seconds, artifact_bytes_budget, cumulative_artifact_bytes,
            cost_budget_estimate, cumulative_cost_estimate,
            created_at, updated_at
        ) VALUES (?, 'build_pipeline', 'alice', 'bob', 'active', 'Build task', ?, 'ag_receiver', 50, NULL, 1000, 1200, NULL, 0.0, ?, ?)
        """,
        (session_id, mock_agent_card.id, now_str, now_str),
    )
    profile_db.commit()

    mock_adapter = MagicMock()
    monkeypatch.setattr("kin.session.orchestrator.get_adapter", lambda card: mock_adapter)

    res = advance_session_turn(
        profile_db,
        vault_key,
        ed_priv,
        "alice",
        session_id,
        now=datetime.datetime.fromisoformat(now_str),
    )

    assert res["status"] == "paused"
    assert res["exhausted_dimension"] == "artifact_bytes_budget"
    assert mock_adapter.invoke.call_count == 0


def test_cost_estimate_budget_exhaustion(profile_db, identity_keys, mock_agent_card, monkeypatch):
    """6. Cost estimate budget exhaustion pauses session before adapter invocation (0 adapter calls)."""
    ed_priv, ed_pub, x255_priv, x255_pub = identity_keys
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_cost_budget"
    now_str = "2026-07-30T10:00:00Z"

    # Seed session with cost_budget_estimate=5.0 and cumulative_cost_estimate=5.0
    profile_db.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, sender_agent_id, receiver_agent_id, turn_limit,
            runtime_budget_seconds, artifact_bytes_budget, cumulative_artifact_bytes,
            cost_budget_estimate, cumulative_cost_estimate,
            created_at, updated_at
        ) VALUES (?, 'build_pipeline', 'alice', 'bob', 'active', 'Build task', ?, 'ag_receiver', 50, NULL, NULL, 0, 5.0, 5.0, ?, ?)
        """,
        (session_id, mock_agent_card.id, now_str, now_str),
    )
    profile_db.commit()

    mock_adapter = MagicMock()
    monkeypatch.setattr("kin.session.orchestrator.get_adapter", lambda card: mock_adapter)

    res = advance_session_turn(
        profile_db,
        vault_key,
        ed_priv,
        "alice",
        session_id,
        now=datetime.datetime.fromisoformat(now_str),
    )

    assert res["status"] == "paused"
    assert res["exhausted_dimension"] == "cost_budget_estimate"
    assert mock_adapter.invoke.call_count == 0


def test_exhaustion_via_single_dimension(profile_db, identity_keys, mock_agent_card, monkeypatch):
    """7. Exhaustion via ANY ONE dimension is sufficient to pause even if others are unexhausted."""
    ed_priv, ed_pub, x255_priv, x255_pub = identity_keys
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_single_dim"

    # Seed session where ONLY runtime_budget_seconds is exceeded (elapsed 5000s > budget 3600s),
    # while artifact_bytes (100 < 500000) and cost_estimate (1.0 < 50.0) are well below limits.
    created_at_past = "2026-07-30T08:00:00Z"
    now_current = datetime.datetime.fromisoformat("2026-07-30T10:00:00Z")

    profile_db.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, sender_agent_id, receiver_agent_id, turn_limit,
            runtime_budget_seconds, artifact_bytes_budget, cumulative_artifact_bytes,
            cost_budget_estimate, cumulative_cost_estimate,
            created_at, updated_at
        ) VALUES (?, 'build_pipeline', 'alice', 'bob', 'active', 'Build task', ?, 'ag_receiver', 50, 3600, 500000, 100, 50.0, 1.0, ?, ?)
        """,
        (session_id, mock_agent_card.id, created_at_past, created_at_past),
    )
    profile_db.commit()

    mock_adapter = MagicMock()
    monkeypatch.setattr("kin.session.orchestrator.get_adapter", lambda card: mock_adapter)

    res = advance_session_turn(
        profile_db,
        vault_key,
        ed_priv,
        "alice",
        session_id,
        now=now_current,
    )

    assert res["status"] == "paused"
    assert res["exhausted_dimension"] == "runtime_budget_seconds"
    assert mock_adapter.invoke.call_count == 0


def test_peer_notification_on_budget_pause(profile_db, identity_keys, mock_agent_card, monkeypatch):
    """8. Confirm peer notification: after budget-triggered pause, peer STATUS_EVENT (owner_paused) is generated and ingested."""
    ed_priv, ed_pub, x255_priv, x255_pub = identity_keys
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_peer_notify"

    # Seed contact bob
    bob_ed_priv, bob_ed_pub = _gen_ed_keypair()
    _seed_contact(profile_db, "bob", bob_ed_pub, b"\x00" * 32)

    created_at_past = "2026-07-30T08:00:00Z"
    now_current = datetime.datetime.fromisoformat("2026-07-30T10:00:00Z")

    profile_db.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, sender_agent_id, receiver_agent_id, turn_limit,
            runtime_budget_seconds, artifact_bytes_budget, cumulative_artifact_bytes,
            cost_budget_estimate, cumulative_cost_estimate,
            created_at, updated_at
        ) VALUES (?, 'build_pipeline', 'alice', 'bob', 'active', 'Build task', ?, 'ag_receiver', 50, 3600, NULL, 0, NULL, 0.0, ?, ?)
        """,
        (session_id, mock_agent_card.id, created_at_past, created_at_past),
    )
    profile_db.commit()

    mock_adapter = MagicMock()
    monkeypatch.setattr("kin.session.orchestrator.get_adapter", lambda card: mock_adapter)

    advance_session_turn(
        profile_db,
        vault_key,
        ed_priv,
        "alice",
        session_id,
        now=now_current,
    )

    # Check session_events table for logged STATUS_EVENT with owner_paused
    from kin.storage.vault import decrypt_field
    cur = profile_db.cursor()
    cur.execute(
        "SELECT kind, payload_json FROM session_events WHERE session_id = ? AND kind = 'status_event'",
        (session_id,),
    )
    events = cur.fetchall()
    assert len(events) > 0
    dec_payload = decrypt_field(vault_key, events[0][1])
    payload_dict = json.loads(dec_payload)
    assert payload_dict.get("status_event") == "owner_paused"
    assert "runtime_budget_seconds" in payload_dict.get("reason", "")
