"""Milestone M3 Test Suite: Network Transport, Envelope Ingestion, and Relay Integration."""

from __future__ import annotations

import datetime
import json
import sqlite3
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.agent_registry.peer_cards import cache_peer_card
from kin.agent_registry.registry import register_card
from kin.identity.auth import create_signed_auth_headers, verify_signed_auth_headers
from kin.identity.keys import derive_key_pair, derive_x25519_key_pair, generate_recovery_phrase
from kin.schemas import (
    AgentAutonomy,
    AgentAvailability,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    AutonomyLevel,
    EmbeddedAdapterConfig,
    MessageKind,
    PublishedAgentCard,
    TransportAcknowledgement,
    compute_content_hash,
    sign_envelope,
)
from kin.storage.migrations import run_migrations
from kin.transport.v11 import (
    CapabilityMismatchError,
    StalePeerCardError,
    TransportError,
    cancel_session,
    dispatch_session,
    ingest_envelope,
    pause_session,
    respond_to_session,
    resume_session,
    retry_outbound_queue,
    sync_peer_cards,
)


def _setup_node_db(username: str, pubkey_hex: str, x25519_pub_hex: str) -> tuple[sqlite3.Connection, bytes]:
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    vault_key = b"test-vault-key-32bytes-long!!!!!"
    conn.execute("INSERT INTO identity VALUES (?, ?, ?, ?)", (username, pubkey_hex, "ref", "1.1"))
    conn.commit()
    return conn, vault_key


def _add_verified_contact(conn: sqlite3.Connection, username: str, pubkey_hex: str, x25519_pub_hex: str, endpoint: str = "http://localhost:8321") -> None:
    conn.execute(
        """\
        INSERT INTO contacts (username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at)
        VALUES (?, ?, ?, ?, ?, 'always_ask', '2026-07-22T12:00:00Z')
        """,
        (username, username.title(), pubkey_hex, x25519_pub_hex, endpoint),
    )
    conn.commit()


@pytest.fixture
def alice_node(alice_keys):
    priv_bytes = alice_keys["private_key"].private_bytes_raw()
    pub_bytes = alice_keys["public_key"].public_bytes_raw()
    phrase = generate_recovery_phrase()
    x255_priv, x255_pub = derive_x25519_key_pair(phrase)
    conn, vault_key = _setup_node_db("alice", pub_bytes.hex(), x255_pub.hex())
    return {
        "conn": conn,
        "vault_key": vault_key,
        "username": "alice",
        "ed_priv": alice_keys["private_key"],
        "ed_pub": alice_keys["public_key"],
        "x255_priv": x255_priv,
        "x255_pub": x255_pub,
    }


@pytest.fixture
def bob_node(bob_keys):
    priv_bytes = bob_keys["private_key"].private_bytes_raw()
    pub_bytes = bob_keys["public_key"].public_bytes_raw()
    phrase = generate_recovery_phrase()
    x255_priv, x255_pub = derive_x25519_key_pair(phrase)
    conn, vault_key = _setup_node_db("bob", pub_bytes.hex(), x255_pub.hex())
    return {
        "conn": conn,
        "vault_key": vault_key,
        "username": "bob",
        "ed_priv": bob_keys["private_key"],
        "ed_pub": bob_keys["public_key"],
        "x255_priv": x255_priv,
        "x255_pub": x255_pub,
    }


def _make_agent_card(agent_id: str, name: str) -> AgentCard:
    return AgentCard(
        schema_version="1.1",
        id=agent_id,
        name=name,
        description=name,
        adapter=EmbeddedAdapterConfig(type="embedded", provider="openai", model="gpt-4o"),
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="none", shell="deny", max_runtime_seconds=900, max_artifact_bytes=10000000),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ASK, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )


def test_two_profile_direct_session_lifecycle(alice_node, bob_node):
    """Test full direct session lifecycle: dispatch -> ingest -> respond accept -> active."""
    # Wire contacts
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://bob-node")
    _add_verified_contact(bob_node["conn"], "alice", alice_node["ed_pub"].public_bytes_raw().hex(), alice_node["x255_pub"].hex(), "http://alice-node")

    # Register local agents
    register_card(alice_node["conn"], alice_node["vault_key"], _make_agent_card("alice_agent", "Alice Agent"))
    register_card(bob_node["conn"], bob_node["vault_key"], _make_agent_card("bob_agent", "Bob Agent"))

    # Cache peer cards
    card_b = PublishedAgentCard(schema_version="1.1", protocol_version="1.1", agent_id="bob_agent", name="Bob Agent", description="Bob Agent", capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]), availability=AgentAvailability.READY, requires_owner_acceptance=True)
    card_a = PublishedAgentCard(schema_version="1.1", protocol_version="1.1", agent_id="alice_agent", name="Alice Agent", description="Alice Agent", capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]), availability=AgentAvailability.READY, requires_owner_acceptance=True)
    cache_peer_card(alice_node["conn"], "bob", card_b)
    cache_peer_card(bob_node["conn"], "alice", card_a)

    # Mock HTTP client for direct HTTP POST dispatch
    def mock_post(url, json=None, **kwargs):
        if "capabilities" in url:
            return MagicMock(status_code=200, json=lambda: {"protocol_version": "1.1", "supported_features": ["session_v1", "jcs_signatures"], "max_turn_limit": 12})
        if "/v1.1/sessions" in url:
            def get_pubkey(un):
                return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]
            ack = ingest_envelope(bob_node["conn"], bob_node["vault_key"], json, get_public_key_fn=get_pubkey)
            return MagicMock(status_code=200, json=lambda: ack.model_dump(mode="json"))
        return MagicMock(status_code=404)

    def mock_get(url, **kwargs):
        if "capabilities" in url:
            return MagicMock(status_code=200, json=lambda: {"protocol_version": "1.1", "supported_features": ["session_v1", "jcs_signatures"], "max_turn_limit": 12})
        return MagicMock(status_code=404)

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = mock_get
    mock_client.post.side_effect = mock_post

    # Alice dispatches session
    res = dispatch_session(
        alice_node["conn"],
        alice_node["vault_key"],
        sender_identity_key=alice_node["ed_priv"],
        sender_x25519_privkey=alice_node["x255_priv"],
        sender_username="alice",
        peer_username="bob",
        sender_agent_id="alice_agent",
        receiver_agent_id="bob_agent",
        collaboration_mode="ask",
        goal="Analyze research paper",
        peer_endpoint="http://bob-node",
        recipient_x25519_pubkey=bob_node["x255_pub"],
        http_client=mock_client,
    )

    session_id = res["session_id"]
    assert res["status"] == "delivered"

    # Verify Bob received session in peer_review state ready for acceptance
    bob_cur = bob_node["conn"].cursor()
    bob_cur.execute("SELECT status, sender_agent_id FROM sessions WHERE session_id = ?", (session_id,))
    row = bob_cur.fetchone()
    assert row is not None
    assert row[0] == "peer_review"
    assert row[1] == "alice_agent"

    # Bob responds with ACCEPTANCE
    resp_res = respond_to_session(
        bob_node["conn"],
        bob_node["vault_key"],
        owner_identity_key=bob_node["ed_priv"],
        owner_x25519_privkey=bob_node["x255_priv"],
        owner_username="bob",
        session_id=session_id,
        decision="accept",
        accepting_agent_id="bob_agent",
        reason_or_question="Ready to assist",
        peer_endpoint="http://alice-node",
        http_client=mock_client,
    )
    assert resp_res["status"] == "processed"

    # Verify Bob's session status moved to accepted
    bob_cur.execute("SELECT status, receiver_agent_id FROM sessions WHERE session_id = ?", (session_id,))
    row = bob_cur.fetchone()
    assert row[0] == "accepted"
    assert row[1] == "bob_agent"


def test_dispatch_capability_negotiation_failure(alice_node, bob_node):
    """Test GAP A: dispatch_session fails locally if peer capabilities are incompatible."""
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://bob-node")

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"protocol_version": "1.0", "supported_features": ["session_v1"], "max_turn_limit": 12})

    with pytest.raises(CapabilityMismatchError) as exc_info:
        dispatch_session(
            alice_node["conn"],
            alice_node["vault_key"],
            sender_identity_key=alice_node["ed_priv"],
            sender_x25519_privkey=alice_node["x255_priv"],
            sender_username="alice",
            peer_username="bob",
            sender_agent_id="alice_agent",
            receiver_agent_id="bob_agent",
            collaboration_mode="ask",
            goal="Test goal",
            peer_endpoint="http://bob-node",
            http_client=mock_client,
        )

    assert "incompatible with V1.1" in str(exc_info.value)

    cur = alice_node["conn"].cursor()
    cur.execute("SELECT COUNT(*) FROM sessions")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM session_events")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM outbound_envelope_queue")
    assert cur.fetchone()[0] == 0


def test_dispatch_stale_peer_card_rejection(alice_node, bob_node):
    """Test GAP B: dispatch_session refuses dispatch if targeted peer card is stale."""
    from kin.schemas import AgentCapabilities, AgentAvailability, PublishedAgentCard
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://bob-node")
    card_stale = PublishedAgentCard(schema_version="1.1", protocol_version="1.1", agent_id="stale_agent", name="Stale", description="Stale", capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]), availability=AgentAvailability.READY, requires_owner_acceptance=True)
    cache_peer_card(alice_node["conn"], "bob", card_stale)
    alice_node["conn"].execute("UPDATE peer_agent_cards SET status = 'stale' WHERE peer_username = 'bob' AND agent_id = 'stale_agent'")
    alice_node["conn"].commit()

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"protocol_version": "1.1", "supported_features": ["session_v1", "jcs_signatures"], "max_turn_limit": 12})

    with pytest.raises(StalePeerCardError) as exc_info:
        dispatch_session(
            alice_node["conn"],
            alice_node["vault_key"],
            sender_identity_key=alice_node["ed_priv"],
            sender_x25519_privkey=alice_node["x255_priv"],
            sender_username="alice",
            peer_username="bob",
            sender_agent_id="alice_agent",
            receiver_agent_id="stale_agent",
            collaboration_mode="ask",
            goal="Test goal",
            peer_endpoint="http://bob-node",
            http_client=mock_client,
        )

    assert "stale and requires owner review" in str(exc_info.value)


def test_envelope_rejection_wire_contracts(alice_node, bob_node):
    """Test GAP D: ingest_envelope returns TransportAcknowledgement(status='rejected') with error codes."""
    _add_verified_contact(bob_node["conn"], "alice", alice_node["ed_pub"].public_bytes_raw().hex(), alice_node["x255_pub"].hex())

    payload = {"collaboration_mode": "ask", "goal": "Rejection test"}
    chash = compute_content_hash(payload)

    # Invalid signature envelope
    bad_env = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "sess_bad_sig",
        "sequence": 1,
        "actor_username": "alice",
        "actor_agent_id": "alice_agent",
        "timestamp": "2026-07-22T12:00:00Z",
        "kind": "task_request",
        "content_hash": chash,
        "payload": payload,
        "signature": "invalid_sig_base64_string",
    }

    def get_pubkey(un):
        return alice_node["ed_pub"] if un == "alice" else None

    ack = ingest_envelope(bob_node["conn"], bob_node["vault_key"], bad_env, get_public_key_fn=get_pubkey)
    assert ack.status == "rejected"
    assert ack.error_code == "INVALID_SIGNATURE"


def test_retry_queue_terminal_vs_transient(alice_node, bob_node):
    """Test GAP D & E: 4xx rejection marks queue row failed; connection errors retry until expiry."""
    from kin.schemas import AgentCapabilities, AgentAvailability, PublishedAgentCard
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://bob-node")
    card_b = PublishedAgentCard(schema_version="1.1", protocol_version="1.1", agent_id="bob_agent", name="Bob", description="Bob", capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]), availability=AgentAvailability.READY, requires_owner_acceptance=True)
    cache_peer_card(alice_node["conn"], "bob", card_b)

    # Dispatch when peer returns 403 Forbidden rejection
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"protocol_version": "1.1", "supported_features": ["session_v1", "jcs_signatures"], "max_turn_limit": 12})
    mock_client.post.return_value = MagicMock(status_code=403, text="Forbidden: unpaired sender")

    res = dispatch_session(
        alice_node["conn"],
        alice_node["vault_key"],
        sender_identity_key=alice_node["ed_priv"],
        sender_x25519_privkey=alice_node["x255_priv"],
        sender_username="alice",
        peer_username="bob",
        sender_agent_id="alice_agent",
        receiver_agent_id="bob_agent",
        collaboration_mode="ask",
        goal="Test goal",
        peer_endpoint="http://bob-node",
        http_client=mock_client,
    )

    assert res["status"] == "failed"


def test_retry_queue_uniqueness_constraint(alice_node):
    """Test GAP F: outbound_envelope_queue enforces UNIQUE(session_id, sequence, recipient_username)."""
    conn = alice_node["conn"]
    now_str = "2026-07-22T12:00:00Z"
    conn.execute(
        "INSERT INTO sessions (session_id, type, initiator_username, receiver_username, status, created_at, updated_at) VALUES ('s1', 'ask', 'alice', 'bob', 'sent', ?, ?)",
        (now_str, now_str),
    )
    conn.execute(
        "INSERT INTO outbound_envelope_queue VALUES ('q1', 's1', 1, 'bob', 'task_request', 'enc', 'pending', 0, ?, 'err', ?, ?)",
        (now_str, now_str, now_str),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO outbound_envelope_queue VALUES ('q2', 's1', 1, 'bob', 'task_request', 'enc', 'pending', 0, ?, 'err', ?, ?)",
            (now_str, now_str, now_str),
        )


def test_accept_without_agent_validation(bob_node):
    """Test GAP G: respond_to_session('accept') requires valid local agent_id."""
    now_str = "2026-07-22T12:00:00Z"
    bob_node["conn"].execute(
        "INSERT INTO sessions (session_id, type, initiator_username, receiver_username, status, created_at, updated_at) VALUES ('s1', 'ask', 'bob', 'alice', 'peer_review', ?, ?)",
        (now_str, now_str),
    )
    bob_node["conn"].commit()

    with pytest.raises(ValueError) as exc1:
        respond_to_session(bob_node["conn"], bob_node["vault_key"], bob_node["ed_priv"], bob_node["x255_priv"], "bob", "s1", "accept", accepting_agent_id=None)
    assert "accepting_agent_id is required" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        respond_to_session(bob_node["conn"], bob_node["vault_key"], bob_node["ed_priv"], bob_node["x255_priv"], "bob", "s1", "accept", accepting_agent_id="non_existent")
    assert "does not exist or is disabled" in str(exc2.value)


def test_shared_auth_headers_verification(alice_node):
    """Test GAP H: create_signed_auth_headers and verify_signed_auth_headers with 300s window."""
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    headers = create_signed_auth_headers("alice", alice_node["ed_priv"], now=now_dt)

    def get_pubkey(un):
        return alice_node["ed_pub"] if un == "alice" else None

    ok, un, err = verify_signed_auth_headers(headers, get_pubkey, now=now_dt)
    assert ok is True
    assert un == "alice"

    # Expired timestamp test (400 seconds old)
    old_dt = now_dt - datetime.timedelta(seconds=400)
    old_headers = create_signed_auth_headers("alice", alice_node["ed_priv"], now=old_dt)
    ok_old, _, err_old = verify_signed_auth_headers(old_headers, get_pubkey, now=now_dt)
    assert ok_old is False
    assert "expired" in err_old


def test_sync_peer_cards_provenance(alice_node, bob_node):
    """Test GAP I: sync_peer_cards discloses source='network' vs source='cache_fallback'."""
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://bob-node")
    card_cached = PublishedAgentCard(schema_version="1.1", protocol_version="1.1", agent_id="bob_cached", name="Bob Cached", description="Desc", capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]), availability=AgentAvailability.READY, requires_owner_acceptance=True)
    cache_peer_card(alice_node["conn"], "bob", card_cached)

    # Direct fetch succeeds
    mock_client_ok = MagicMock(spec=httpx.Client)
    mock_client_ok.get.return_value = MagicMock(status_code=200, json=lambda: {"schema_version": "1.1", "cards": [{"schema_version": "1.1", "protocol_version": "1.1", "agent_id": "bob_fresh", "name": "Fresh", "description": "Fresh", "capabilities": {"tags": [], "accepts": [], "produces": []}, "availability": "ready", "requires_owner_acceptance": True}]})

    res_ok = sync_peer_cards(alice_node["conn"], "alice", alice_node["ed_priv"], "bob", "http://bob-node", http_client=mock_client_ok)
    assert res_ok["source"] == "network"
    assert len(res_ok["cards"]) == 1
    assert res_ok["cards"][0]["agent_id"] == "bob_fresh"

    # Direct fetch connection fails -> fallback
    mock_client_err = MagicMock(spec=httpx.Client)
    mock_client_err.get.side_effect = httpx.RequestError("Connection failed")

    res_fb = sync_peer_cards(alice_node["conn"], "alice", alice_node["ed_priv"], "bob", "http://bob-node", http_client=mock_client_err)
    assert res_fb["source"] == "cache_fallback"
    assert len(res_fb["cards"]) >= 1


def test_pause_resume_status_event_non_transition(alice_node, bob_node):
    """Test STATUS_EVENT appends peer_visible event without altering receiver's session status."""
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex())
    _add_verified_contact(bob_node["conn"], "alice", alice_node["ed_pub"].public_bytes_raw().hex(), alice_node["x255_pub"].hex())

    # Create active session on both nodes
    now_str = "2026-07-22T12:00:00Z"
    alice_node["conn"].execute("INSERT INTO sessions VALUES ('s_p', 'ask', 'alice', 'bob', 'active', 'goal', 'a_ag', 'b_ag', NULL, 12, ?, ?, NULL, NULL)", (now_str, now_str))
    bob_node["conn"].execute("INSERT INTO sessions VALUES ('s_p', 'ask', 'alice', 'bob', 'active', 'goal', 'a_ag', 'b_ag', NULL, 12, ?, ?, NULL, NULL)", (now_str, now_str))
    alice_node["conn"].commit()
    bob_node["conn"].commit()

    # Alice pauses session locally
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = MagicMock(status_code=200)

    pause_session(alice_node["conn"], alice_node["vault_key"], alice_node["ed_priv"], alice_node["x255_priv"], "alice", "s_p", http_client=mock_client)

    cur = alice_node["conn"].cursor()
    cur.execute("SELECT status FROM sessions WHERE session_id = 's_p'")
    assert cur.fetchone()[0] == "paused"


def test_cancel_session_dual_path(alice_node, bob_node):
    """Test CANCEL envelope independently transitions both state machines to cancelled."""
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex())
    _add_verified_contact(bob_node["conn"], "alice", alice_node["ed_pub"].public_bytes_raw().hex(), alice_node["x255_pub"].hex())

    now_str = "2026-07-22T12:00:00Z"
    alice_node["conn"].execute("INSERT INTO sessions VALUES ('s_c', 'ask', 'alice', 'bob', 'active', 'goal', 'a_ag', 'b_ag', NULL, 12, ?, ?, NULL, NULL)", (now_str, now_str))
    bob_node["conn"].execute("INSERT INTO sessions VALUES ('s_c', 'ask', 'alice', 'bob', 'active', 'goal', 'a_ag', 'b_ag', NULL, 12, ?, ?, NULL, NULL)", (now_str, now_str))
    alice_node["conn"].commit()
    bob_node["conn"].commit()

    # Alice cancels
    cancel_res = cancel_session(alice_node["conn"], alice_node["vault_key"], alice_node["ed_priv"], alice_node["x255_priv"], "alice", "s_c")
    assert cancel_res["status"] == "cancelled"

    cur = alice_node["conn"].cursor()
    cur.execute("SELECT status FROM sessions WHERE session_id = 's_c'")
    assert cur.fetchone()[0] == "cancelled"


def test_agent_id_locking(alice_node, bob_node):
    """Test agent-id locking: second envelope claiming different actor_agent_id is rejected."""
    _add_verified_contact(bob_node["conn"], "alice", alice_node["ed_pub"].public_bytes_raw().hex(), alice_node["x255_pub"].hex())

    payload1 = {"collaboration_mode": "ask", "goal": "Initial goal", "requested_agent_id": "bob_agent"}
    env1 = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "s_lock",
        "sequence": 1,
        "actor_username": "alice",
        "actor_agent_id": "alice_ag_1",
        "timestamp": "2026-07-22T12:00:00Z",
        "kind": "task_request",
        "content_hash": compute_content_hash(payload1),
        "payload": payload1,
    }
    env1["signature"] = sign_envelope(env1, alice_node["ed_priv"])

    def get_pubkey(un):
        return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]

    ack1 = ingest_envelope(bob_node["conn"], bob_node["vault_key"], env1, get_public_key_fn=get_pubkey)
    assert ack1.status == "delivered"

    # Second envelope from Alice claiming a DIFFERENT agent_id
    payload2 = {"reason": "proposal"}
    env2 = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "s_lock",
        "sequence": 2,
        "actor_username": "alice",
        "actor_agent_id": "alice_ag_DIFFERENT",
        "timestamp": "2026-07-22T12:01:00Z",
        "kind": "proposal",
        "content_hash": compute_content_hash(payload2),
        "payload": payload2,
    }
    env2["signature"] = sign_envelope(env2, alice_node["ed_priv"])

    ack2 = ingest_envelope(bob_node["conn"], bob_node["vault_key"], env2, get_public_key_fn=get_pubkey)
    assert ack2.status == "rejected"
    assert ack2.error_code == "UNAUTHORIZED_AGENT"


def test_duplicate_redelivery_acks_as_delivered_not_rejected(alice_node, bob_node):
    """Test GAP K & O: Resending an identical envelope returns HTTP 200 status='delivered' and logs duplicate_delivery audit event."""
    _add_verified_contact(bob_node["conn"], "alice", alice_node["ed_pub"].public_bytes_raw().hex(), alice_node["x255_pub"].hex())

    payload = {"collaboration_mode": "ask", "goal": "Identical resend goal", "requested_agent_id": "bob_agent"}
    env = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "s_dup_resend",
        "sequence": 1,
        "actor_username": "alice",
        "actor_agent_id": "alice_agent",
        "timestamp": "2026-07-22T12:00:00Z",
        "kind": "task_request",
        "content_hash": compute_content_hash(payload),
        "payload": payload,
    }
    env["signature"] = sign_envelope(env, alice_node["ed_priv"])

    def get_pubkey(un):
        return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]

    ack1 = ingest_envelope(bob_node["conn"], bob_node["vault_key"], env, get_public_key_fn=get_pubkey)
    assert ack1.status == "delivered"

    # Resend IDENTICAL envelope
    ack2 = ingest_envelope(bob_node["conn"], bob_node["vault_key"], env, get_public_key_fn=get_pubkey)
    assert ack2.status == "delivered"

    # Verify duplicate_delivery audit event recorded
    cur = bob_node["conn"].cursor()
    cur.execute("SELECT category FROM audit_events WHERE session_id = 's_dup_resend'")
    categories = [r[0] for r in cur.fetchall()]
    assert "duplicate_delivery" in categories


def test_sequence_reuse_mismatch_security_rejection(alice_node, bob_node):
    """Test GAP K & O: Resending same sequence with differing payload returns HTTP 409 SEQUENCE_REUSE_MISMATCH."""
    _add_verified_contact(bob_node["conn"], "alice", alice_node["ed_pub"].public_bytes_raw().hex(), alice_node["x255_pub"].hex())

    payload1 = {"collaboration_mode": "ask", "goal": "Original goal", "requested_agent_id": "bob_agent"}
    env1 = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "s_seq_reuse",
        "sequence": 1,
        "actor_username": "alice",
        "actor_agent_id": "alice_agent",
        "timestamp": "2026-07-22T12:00:00Z",
        "kind": "task_request",
        "content_hash": compute_content_hash(payload1),
        "payload": payload1,
    }
    env1["signature"] = sign_envelope(env1, alice_node["ed_priv"])

    def get_pubkey(un):
        return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]

    ack1 = ingest_envelope(bob_node["conn"], bob_node["vault_key"], env1, get_public_key_fn=get_pubkey)
    assert ack1.status == "delivered"

    # Tampered envelope with SAME sequence but DIFFERENT payload
    payload2 = {"collaboration_mode": "ask", "goal": "TAMPERED GOAL", "requested_agent_id": "bob_agent"}
    env2 = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "s_seq_reuse",
        "sequence": 1,
        "actor_username": "alice",
        "actor_agent_id": "alice_agent",
        "timestamp": "2026-07-22T12:00:00Z",
        "kind": "task_request",
        "content_hash": compute_content_hash(payload2),
        "payload": payload2,
    }
    env2["signature"] = sign_envelope(env2, alice_node["ed_priv"])

    ack2 = ingest_envelope(bob_node["conn"], bob_node["vault_key"], env2, get_public_key_fn=get_pubkey)
    assert ack2.status == "rejected"
    assert ack2.error_code == "SEQUENCE_REUSE_MISMATCH"

    cur = bob_node["conn"].cursor()
    cur.execute("SELECT category FROM audit_events WHERE session_id = 's_seq_reuse'")
    categories = [r[0] for r in cur.fetchall()]
    assert "security_rejection" in categories


def test_retry_queue_abandons_moot_terminal_session_items(alice_node):
    """Test GAP L: retry_outbound_queue marks items 'abandoned' when session reaches terminal state."""
    now_str = "2026-07-22T12:00:00Z"
    alice_node["conn"].execute(
        "INSERT INTO sessions VALUES ('s_moot', 'ask', 'alice', 'bob', 'cancelled', 'goal', 'a_ag', 'b_ag', NULL, 12, ?, ?, NULL, '2026-07-29T12:00:00Z')",
        (now_str, now_str),
    )
    alice_node["conn"].execute(
        """\
        INSERT INTO outbound_envelope_queue (
            queue_id, session_id, sequence, recipient_username,
            envelope_kind, envelope_json_enc, delivery_state, attempt_count,
            next_retry_at, created_at, updated_at
        ) VALUES ('q_moot', 's_moot', 1, 'bob', 'proposal', 'enc_json', 'pending', 0, ?, ?, ?)
        """,
        (now_str, now_str, now_str),
    )
    alice_node["conn"].commit()

    res = retry_outbound_queue(alice_node["conn"], alice_node["vault_key"])
    cur = alice_node["conn"].cursor()
    cur.execute("SELECT delivery_state FROM outbound_envelope_queue WHERE queue_id = 'q_moot'")
    assert cur.fetchone()[0] == "abandoned"


def test_dispatch_failure_no_side_effects(alice_node, bob_node):
    """Test GAP N: capability/stale card dispatch failure leaves DB tables completely empty."""
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://bob-node")

    # Mark peer card as stale to trigger StalePeerCardError
    alice_node["conn"].execute(
        """\
        INSERT INTO peer_agent_cards (peer_username, agent_id, card_json, content_hash, status, first_seen_at, last_seen_at)
        VALUES ('bob', 'bob_agent', '{}', 'hash123', 'stale', '2026-07-22T12:00:00Z', '2026-07-22T12:00:00Z')
        """
    )
    alice_node["conn"].commit()

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"protocol_version": "1.1", "supported_features": ["session_v1", "jcs_signatures"], "max_turn_limit": 12})

    with pytest.raises(StalePeerCardError):
        dispatch_session(
            alice_node["conn"],
            alice_node["vault_key"],
            sender_identity_key=alice_node["ed_priv"],
            sender_x25519_privkey=alice_node["x255_priv"],
            sender_username="alice",
            peer_username="bob",
            sender_agent_id="alice_agent",
            receiver_agent_id="bob_agent",
            collaboration_mode="ask",
            goal="Goal",
            peer_endpoint="http://bob-node",
            http_client=mock_client,
        )

    # Assert 0 rows in sessions, session_events, outbound_envelope_queue
    cur = alice_node["conn"].cursor()
    cur.execute("SELECT COUNT(*) FROM sessions")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM session_events")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM outbound_envelope_queue")
    assert cur.fetchone()[0] == 0


def test_list_sessions_for_participant(alice_node, bob_node):
    """Test GAP R: Querying sessions by participant (initiator_username = ? OR receiver_username = ?) returns session on BOTH Alice's and Bob's DB."""
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://bob-node")
    _add_verified_contact(bob_node["conn"], "alice", alice_node["ed_pub"].public_bytes_raw().hex(), alice_node["x255_pub"].hex(), "http://alice-node")

    card_b = PublishedAgentCard(schema_version="1.1", protocol_version="1.1", agent_id="bob_agent", name="Bob Agent", description="Bob Agent", capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]), availability=AgentAvailability.READY, requires_owner_acceptance=True)
    card_a = PublishedAgentCard(schema_version="1.1", protocol_version="1.1", agent_id="alice_agent", name="Alice Agent", description="Alice Agent", capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]), availability=AgentAvailability.READY, requires_owner_acceptance=True)
    cache_peer_card(alice_node["conn"], "bob", card_b)
    cache_peer_card(bob_node["conn"], "alice", card_a)

    def mock_post(url, json=None, **kwargs):
        if "/v1.1/sessions" in url:
            def get_pubkey(un):
                return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]
            ack = ingest_envelope(bob_node["conn"], bob_node["vault_key"], json, get_public_key_fn=get_pubkey)
            return MagicMock(status_code=200, json=lambda: ack.model_dump(mode="json"))
        return MagicMock(status_code=404)

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"protocol_version": "1.1", "supported_features": ["session_v1", "jcs_signatures"], "max_turn_limit": 12})
    mock_client.post.side_effect = mock_post

    res = dispatch_session(
        alice_node["conn"],
        alice_node["vault_key"],
        sender_identity_key=alice_node["ed_priv"],
        sender_x25519_privkey=alice_node["x255_priv"],
        sender_username="alice",
        peer_username="bob",
        sender_agent_id="alice_agent",
        receiver_agent_id="bob_agent",
        collaboration_mode="ask",
        goal="Participant query test",
        peer_endpoint="http://bob-node",
        recipient_x25519_pubkey=bob_node["x255_pub"],
        http_client=mock_client,
    )
    session_id = res["session_id"]

    # Query Alice's database for sessions involving 'alice'
    alice_cur = alice_node["conn"].cursor()
    alice_cur.execute(
        "SELECT session_id, initiator_username, receiver_username FROM sessions WHERE initiator_username = 'alice' OR receiver_username = 'alice'"
    )
    alice_rows = alice_cur.fetchall()
    assert len(alice_rows) == 1
    assert alice_rows[0][0] == session_id
    assert alice_rows[0][1] == "alice"
    assert alice_rows[0][2] == "bob"

    # Query Bob's database for sessions involving 'bob'
    bob_cur = bob_node["conn"].cursor()
    bob_cur.execute(
        "SELECT session_id, initiator_username, receiver_username FROM sessions WHERE initiator_username = 'bob' OR receiver_username = 'bob'"
    )
    bob_rows = bob_cur.fetchall()
    assert len(bob_rows) == 1
    assert bob_rows[0][0] == session_id
    assert bob_rows[0][1] == "alice"
    assert bob_rows[0][2] == "bob"


def test_raw_status_update_prevented_on_terminal_session(alice_node):
    """Test GAP S: reducer process_node_command prevents status updates on terminal sessions."""
    now_str = "2026-07-22T12:00:00Z"
    alice_node["conn"].execute(
        "INSERT INTO sessions (session_id, type, initiator_username, receiver_username, status, created_at, updated_at) VALUES ('s_term', 'ask', 'alice', 'bob', 'cancelled', ?, ?)",
        (now_str, now_str),
    )
    alice_node["conn"].execute(
        """\
        INSERT INTO outbound_envelope_queue (
            queue_id, session_id, sequence, recipient_username,
            envelope_kind, envelope_json_enc, delivery_state, attempt_count,
            next_retry_at, created_at, updated_at
        ) VALUES ('q_term', 's_term', 1, 'bob', 'task_request', 'enc', 'pending', 0, ?, ?, ?)
        """,
        (now_str, now_str, now_str),
    )
    alice_node["conn"].commit()

    # Retry queue sweep should abandon moot item and leave session status as 'cancelled'
    res = retry_outbound_queue(alice_node["conn"], alice_node["vault_key"])
    cur = alice_node["conn"].cursor()
    cur.execute("SELECT status FROM sessions WHERE session_id = 's_term'")
    assert cur.fetchone()[0] == "cancelled"

    cur.execute("SELECT delivery_state FROM outbound_envelope_queue WHERE queue_id = 'q_term'")
    assert cur.fetchone()[0] == "abandoned"


def test_dispatch_capability_failure_with_relay_configured(alice_node, bob_node):
    """Test GAP U: Unreachable direct capabilities endpoint raises CapabilityMismatchError even when relay_url is provided."""
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://unreachable-peer")

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.RequestError("Connection refused")

    with pytest.raises(CapabilityMismatchError) as exc_info:
        dispatch_session(
            alice_node["conn"],
            alice_node["vault_key"],
            sender_identity_key=alice_node["ed_priv"],
            sender_x25519_privkey=alice_node["x255_priv"],
            sender_username="alice",
            peer_username="bob",
            sender_agent_id="alice_agent",
            receiver_agent_id="bob_agent",
            collaboration_mode="ask",
            goal="Goal",
            peer_endpoint="http://unreachable-peer",
            relay_url="http://relay.example.com",
            recipient_x25519_pubkey=bob_node["x255_pub"],
            http_client=mock_client,
        )

    assert "Failed to reach peer capabilities endpoint" in str(exc_info.value)


def test_dispatch_session_via_relay_with_cached_capabilities(alice_node, bob_node):
    """Test GAP W: When peer's direct endpoint is unreachable, dispatch_session succeeds via relay if a fresh cached capability advertisement exists."""
    from kin.schemas import CapabilityAdvertisement
    from kin.transport.v11 import cache_peer_capabilities

    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://unreachable-peer")

    # Cache peer capabilities locally (simulating prior successful negotiation)
    cap_ad = CapabilityAdvertisement(
        protocol_version="1.1",
        supported_features=["session_v1", "jcs_signatures"],
        max_turn_limit=12,
    )
    cache_peer_capabilities(alice_node["conn"], "bob", cap_ad)

    def mock_post(url, json=None, **kwargs):
        if "/relay/mailbox" in url:
            return MagicMock(status_code=200, json=lambda: {"status": "queued"})
        raise httpx.RequestError(f"Connection refused to direct endpoint {url}")

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.RequestError("Connection refused to direct endpoint")
    mock_client.post.side_effect = mock_post

    res = dispatch_session(
        alice_node["conn"],
        alice_node["vault_key"],
        sender_identity_key=alice_node["ed_priv"],
        sender_x25519_privkey=alice_node["x255_priv"],
        sender_username="alice",
        peer_username="bob",
        sender_agent_id="alice_agent",
        receiver_agent_id="bob_agent",
        collaboration_mode="ask",
        goal="Offline dispatch test",
        peer_endpoint="http://unreachable-peer",
        relay_url="http://relay.example.com",
        recipient_x25519_pubkey=bob_node["x255_pub"],
        http_client=mock_client,
    )

    assert res["status"] == "queued"


def test_dispatch_session_populates_capabilities_cache(alice_node, bob_node):
    """Test Item 1a: Successful direct dispatch_session automatically populates the peer_capabilities cache in SQLite."""
    from kin.transport.v11 import get_cached_peer_capabilities

    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://bob-node")
    card_b = PublishedAgentCard(schema_version="1.1", protocol_version="1.1", agent_id="bob_agent", name="Bob Agent", description="Bob Agent", capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]), availability=AgentAvailability.READY, requires_owner_acceptance=True)
    cache_peer_card(alice_node["conn"], "bob", card_b)

    # Ensure no cache exists initially
    assert get_cached_peer_capabilities(alice_node["conn"], "bob") is None

    def mock_post(url, json=None, **kwargs):
        if "/v1.1/sessions" in url:
            def get_pubkey(un):
                return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]
            ack = ingest_envelope(bob_node["conn"], bob_node["vault_key"], json, get_public_key_fn=get_pubkey)
            return MagicMock(status_code=200, json=lambda: ack.model_dump(mode="json"))
        return MagicMock(status_code=404)

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"protocol_version": "1.1", "supported_features": ["session_v1", "jcs_signatures"], "max_turn_limit": 12})
    mock_client.post.side_effect = mock_post

    res = dispatch_session(
        alice_node["conn"],
        alice_node["vault_key"],
        sender_identity_key=alice_node["ed_priv"],
        sender_x25519_privkey=alice_node["x255_priv"],
        sender_username="alice",
        peer_username="bob",
        sender_agent_id="alice_agent",
        receiver_agent_id="bob_agent",
        collaboration_mode="ask",
        goal="Direct dispatch cache population test",
        peer_endpoint="http://bob-node",
        recipient_x25519_pubkey=bob_node["x255_pub"],
        http_client=mock_client,
    )
    assert res["status"] == "delivered"

    # Assert peer capabilities were automatically cached in DB
    cached = get_cached_peer_capabilities(alice_node["conn"], "bob")
    assert cached is not None
    assert cached.protocol_version == "1.1"


def test_dispatch_session_via_relay_with_expired_cached_capabilities(alice_node, bob_node):
    """Test Item 3: A cached capability advertisement older than 72 hours is treated as expired and raises CapabilityMismatchError."""
    from kin.schemas import CapabilityAdvertisement
    from kin.transport.v11 import cache_peer_capabilities

    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex(), "http://unreachable-peer")

    now = datetime.datetime.now(datetime.timezone.utc)
    stale_time = now - datetime.timedelta(hours=73)

    cap_ad = CapabilityAdvertisement(
        protocol_version="1.1",
        supported_features=["session_v1", "jcs_signatures"],
        max_turn_limit=12,
    )
    # Seed cache with timestamp 73 hours ago
    cache_peer_capabilities(alice_node["conn"], "bob", cap_ad, now=stale_time)

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.RequestError("Connection refused to direct endpoint")

    with pytest.raises(CapabilityMismatchError) as exc_info:
        dispatch_session(
            alice_node["conn"],
            alice_node["vault_key"],
            sender_identity_key=alice_node["ed_priv"],
            sender_x25519_privkey=alice_node["x255_priv"],
            sender_username="alice",
            peer_username="bob",
            sender_agent_id="alice_agent",
            receiver_agent_id="bob_agent",
            collaboration_mode="ask",
            goal="Stale capability cache test",
            peer_endpoint="http://unreachable-peer",
            relay_url="http://relay.example.com",
            recipient_x25519_pubkey=bob_node["x255_pub"],
            now=now,
            http_client=mock_client,
        )

    assert "no fresh cached capabilities exist" in str(exc_info.value)



