"""Unit and integration tests for kin.transport.v11 artifact_offer / artifact_accept wire exchange (§15.8 M5 Phase 2)."""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.agent_registry.peer_cards import cache_peer_card
from kin.agent_registry.registry import register_card
from kin.artifacts.vault import (
    ArtifactIdConflictError,
    ArtifactMetadata,
    ArtifactNotFoundError,
    get_artifact_metadata,
    load_artifact_bytes,
    store_artifact,
)
from kin.identity.keys import derive_key_pair, derive_x25519_key_pair, generate_recovery_phrase, encrypt_for_recipient
from kin.schemas import (
    AgentAutonomy,
    AgentAvailability,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    AutonomyLevel,
    CapabilityAdvertisement,
    EmbeddedAdapterConfig,
    MessageKind,
    PublishedAgentCard,
    compute_content_hash,
    sign_envelope,
)
from kin.storage.migrations import run_migrations
from kin.transport.v11 import (
    TransportError,
    dispatch_session,
    ingest_envelope,
    respond_to_session,
    send_artifact_offer,
)


def _setup_node_db(username: str, pubkey_hex: str, x25519_pub_hex: str) -> tuple[sqlite3.Connection, bytes]:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    run_migrations(conn)
    vault_key = b"test-vault-key-32bytes-long!!!!!"
    conn.execute("INSERT INTO identity VALUES (?, ?, ?, ?)", (username, pubkey_hex, "ref", "1.1"))
    conn.commit()
    return conn, vault_key


def _add_verified_contact(
    conn: sqlite3.Connection,
    username: str,
    pubkey_hex: str,
    x25519_pub_hex: str,
    endpoint: str | None = None,
) -> None:
    conn.execute(
        """\
        INSERT OR REPLACE INTO contacts (username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at)
        VALUES (?, ?, ?, ?, ?, 'always_ask', '2026-07-22T12:00:00Z')
        """,
        (username, username.title(), pubkey_hex, x25519_pub_hex, endpoint),
    )
    conn.commit()


@pytest.fixture
def alice_node(alice_keys):
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


def _make_agent_card(agent_id: str, name: str, max_artifact_bytes: int = 10_000_000) -> AgentCard:
    return AgentCard(
        schema_version="1.1",
        id=agent_id,
        name=name,
        description=name,
        adapter=EmbeddedAdapterConfig(type="embedded", provider="openai", model="gpt-4o"),
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        boundaries=AgentBoundaries(
            network_access="deny",
            filesystem="none",
            shell="deny",
            max_runtime_seconds=900,
            max_artifact_bytes=max_artifact_bytes,
        ),
        autonomy=AgentAutonomy(
            relay_information=AutonomyLevel.ALWAYS_ASK,
            propose_actions=AutonomyLevel.ALWAYS_ASK,
            execute_local_actions=AutonomyLevel.ALWAYS_ASK,
        ),
    )


def make_mock_client(alice_node, bob_node):
    """Construct a mock HTTP client that routes envelopes directly to the peer's ingest_envelope pipeline."""
    def mock_post(url, json=None, **kwargs):
        if "capabilities" in url:
            return MagicMock(
                status_code=200,
                json=lambda: {"protocol_version": "1.1", "supported_features": ["session_v1", "jcs_signatures"], "max_turn_limit": 12},
            )
        def get_pubkey(un):
            return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]

        actor = json.get("actor_username") if json else ""
        if actor == "alice":
            target_conn = bob_node["conn"]
            target_vault = bob_node["vault_key"]
            target_x255 = bob_node["x255_priv"]
            target_ed = bob_node["ed_priv"]
        else:
            target_conn = alice_node["conn"]
            target_vault = alice_node["vault_key"]
            target_x255 = alice_node["x255_priv"]
            target_ed = alice_node["ed_priv"]

        ack = ingest_envelope(
            target_conn,
            target_vault,
            json,
            get_public_key_fn=get_pubkey,
            recipient_x25519_privkey=target_x255,
            owner_identity_key=target_ed,
        )
        return MagicMock(status_code=200, json=lambda: ack.model_dump(mode="json"))

    def mock_get(url, **kwargs):
        return MagicMock(
            status_code=200,
            json=lambda: {"protocol_version": "1.1", "supported_features": ["session_v1", "jcs_signatures"], "max_turn_limit": 12},
        )

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = mock_get
    mock_client.post.side_effect = mock_post
    return mock_client


def _setup_active_session(
    alice_node,
    bob_node,
    bob_agent_id: str = "bob_agent",
    bob_max_artifact_bytes: int = 10_000_000,
):
    """Wire contacts, register cards, cache capabilities, and create an active session between Alice and Bob."""
    _add_verified_contact(
        alice_node["conn"],
        "bob",
        bob_node["ed_pub"].public_bytes_raw().hex(),
        bob_node["x255_pub"].hex(),
        endpoint="http://bob-node",
    )
    _add_verified_contact(
        bob_node["conn"],
        "alice",
        alice_node["ed_pub"].public_bytes_raw().hex(),
        alice_node["x255_pub"].hex(),
        endpoint="http://alice-node",
    )

    alice_card = _make_agent_card("alice_agent", "Alice Agent")
    bob_card = _make_agent_card(bob_agent_id, "Bob Agent", max_artifact_bytes=bob_max_artifact_bytes)
    register_card(alice_node["conn"], alice_node["vault_key"], alice_card)
    register_card(bob_node["conn"], bob_node["vault_key"], bob_card)

    alice_node["conn"].execute("UPDATE agents SET enabled = 1")
    bob_node["conn"].execute("UPDATE agents SET enabled = 1")

    card_b = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id=bob_agent_id,
        name="Bob Agent",
        description="Bob Agent",
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
    card_a = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="alice_agent",
        name="Alice Agent",
        description="Alice Agent",
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
    cache_peer_card(alice_node["conn"], "bob", card_b)
    cache_peer_card(bob_node["conn"], "alice", card_a)

    cap_ad = CapabilityAdvertisement(
        protocol_version="1.1",
        supported_features=["session_v1", "jcs_signatures"],
        max_turn_limit=12,
    )
    from kin.transport.v11 import cache_peer_capabilities
    cache_peer_capabilities(alice_node["conn"], "bob", cap_ad)
    cache_peer_capabilities(bob_node["conn"], "alice", cap_ad)

    mock_client = make_mock_client(alice_node, bob_node)

    res = dispatch_session(
        alice_node["conn"],
        alice_node["vault_key"],
        alice_node["ed_priv"],
        alice_node["x255_priv"],
        "alice",
        "bob",
        "alice_agent",
        bob_agent_id,
        "ask",
        "Analyze data artifact",
        peer_endpoint="http://bob-node",
        recipient_x25519_pubkey=bob_node["x255_pub"],
        http_client=mock_client,
    )
    session_id = res["session_id"]

    # Bob responds with ACCEPTANCE
    respond_to_session(
        bob_node["conn"],
        bob_node["vault_key"],
        owner_identity_key=bob_node["ed_priv"],
        owner_x25519_privkey=bob_node["x255_priv"],
        owner_username="bob",
        session_id=session_id,
        decision="accept",
        accepting_agent_id=bob_agent_id,
        reason_or_question="Ready to assist",
        peer_endpoint="http://alice-node",
        http_client=mock_client,
    )
    return session_id, mock_client


def test_artifact_offer_accept_full_roundtrip(alice_node, bob_node):
    """Requirement 1: Full end-to-end roundtrip: Alice stores artifact locally, offers to Bob. Bob verifies, stores in vault, sends artifact_accept back."""
    session_id, mock_client = _setup_active_session(alice_node, bob_node)
    raw_payload = b"Hello Bob! Here is the analysis report."

    # 1. Alice stores artifact locally
    alice_meta = store_artifact(
        alice_node["conn"],
        alice_node["vault_key"],
        session_id=session_id,
        raw_bytes=raw_payload,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=1_000_000,
    )

    # 2. Alice sends artifact_offer to Bob
    res = send_artifact_offer(
        alice_node["conn"],
        alice_node["vault_key"],
        alice_node["ed_priv"],
        alice_node["x255_priv"],
        "alice",
        session_id,
        alice_meta.artifact_id,
        http_client=mock_client,
    )
    assert res["status"] == "offered"

    # 3. Assert Bob's vault has stored the exact artifact under the same artifact_id
    bob_meta = get_artifact_metadata(bob_node["conn"], alice_meta.artifact_id)
    assert bob_meta.artifact_id == alice_meta.artifact_id
    assert bob_meta.session_id == session_id
    assert bob_meta.sha256 == alice_meta.sha256
    assert bob_meta.offered_by == "alice"
    assert bob_meta.source == "peer_received"

    # 4. Assert Bob's decrypted vault bytes match Alice's raw bytes byte-for-byte
    bob_bytes = load_artifact_bytes(bob_node["conn"], bob_node["vault_key"], alice_meta.artifact_id)
    assert bob_bytes == raw_payload


def test_artifact_offer_hash_mismatch_rejected(alice_node, bob_node):
    """Requirement 2: Buggy/malicious sender sends artifact_offer with mismatched SHA-256. Bob logs security_rejection, omits artifact_accept, creates no vault row."""
    session_id, mock_client = _setup_active_session(alice_node, bob_node)
    raw_payload = b"Real content bytes"
    fake_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"

    enc_bytes = encrypt_for_recipient(alice_node["x255_priv"], bob_node["x255_pub"], raw_payload)
    enc_b64 = base64.b64encode(enc_bytes).decode("ascii")

    art_id = "art_mismatch_999"
    payload = {
        "schema_version": "1.1",
        "artifact_id": art_id,
        "session_id": session_id,
        "sha256": fake_sha256,
        "mime_type": "text/plain",
        "size_bytes": len(raw_payload),
        "offered_by": "alice",
        "preview_policy": "auto",
        "encrypted_bytes_b64": enc_b64,
    }

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": 2,
        "actor_username": "alice",
        "actor_agent_id": "alice_agent",
        "timestamp": "2026-07-27T10:00:00Z",
        "kind": MessageKind.ARTIFACT_OFFER.value,
        "content_hash": compute_content_hash(payload),
        "payload": payload,
    }
    env_dict["signature"] = sign_envelope(env_dict, alice_node["ed_priv"])

    def get_pubkey(un: str):
        return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]

    ack = ingest_envelope(
        bob_node["conn"],
        bob_node["vault_key"],
        env_dict,
        get_public_key_fn=get_pubkey,
        recipient_x25519_privkey=bob_node["x255_priv"],
        owner_identity_key=bob_node["ed_priv"],
    )
    assert ack.status == "delivered"

    # Assert no vault row created on Bob's side
    with pytest.raises(ArtifactNotFoundError):
        get_artifact_metadata(bob_node["conn"], art_id)

    # Assert security rejection audit event was logged on Bob's side
    cur = bob_node["conn"].cursor()
    cur.execute("SELECT category, summary FROM audit_events WHERE session_id = ?", (session_id,))
    events = cur.fetchall()
    rejection = [e for e in events if e[0] == "security_rejection"]
    assert len(rejection) >= 1
    assert "does not match computed payload hash" in rejection[0][1]


def test_artifact_offer_receiver_boundary_overshoot(alice_node, bob_node):
    """Requirement 3 & Directive 2: Bob has 2 registered cards with different max_artifact_bytes. Verify size check specifically enforces receiving agent's card limit."""
    _add_verified_contact(alice_node["conn"], "bob", bob_node["ed_pub"].public_bytes_raw().hex(), bob_node["x255_pub"].hex())
    _add_verified_contact(bob_node["conn"], "alice", alice_node["ed_pub"].public_bytes_raw().hex(), alice_node["x255_pub"].hex())

    alice_card = _make_agent_card("alice_agent", "Alice Agent")
    bob_card_small = _make_agent_card("bob_small", "Bob Small Agent", max_artifact_bytes=50)
    bob_card_large = _make_agent_card("bob_large", "Bob Large Agent", max_artifact_bytes=100_000)

    register_card(alice_node["conn"], alice_node["vault_key"], alice_card)
    register_card(bob_node["conn"], bob_node["vault_key"], bob_card_small)
    register_card(bob_node["conn"], bob_node["vault_key"], bob_card_large)

    alice_node["conn"].execute("UPDATE agents SET enabled = 1")
    bob_node["conn"].execute("UPDATE agents SET enabled = 1")

    # Session created with receiver_agent_id = "bob_small" (max_artifact_bytes = 50)
    session_id, mock_client = _setup_active_session(
        alice_node, bob_node, bob_agent_id="bob_small", bob_max_artifact_bytes=50
    )

    # Alice offers artifact of 200 bytes (> bob_small's 50 bytes, but < bob_large's 100,000 bytes)
    raw_payload = b"A" * 200
    alice_meta = store_artifact(
        alice_node["conn"],
        alice_node["vault_key"],
        session_id=session_id,
        raw_bytes=raw_payload,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=1_000_000,
    )

    send_artifact_offer(
        alice_node["conn"],
        alice_node["vault_key"],
        alice_node["ed_priv"],
        alice_node["x255_priv"],
        "alice",
        session_id,
        alice_meta.artifact_id,
        http_client=mock_client,
    )

    # Assert Bob rejected it specifically because receiver_agent_id is bob_small (50 bytes)
    with pytest.raises(ArtifactNotFoundError):
        get_artifact_metadata(bob_node["conn"], alice_meta.artifact_id)

    cur = bob_node["conn"].cursor()
    cur.execute("SELECT category, summary FROM audit_events WHERE session_id = ?", (session_id,))
    events = cur.fetchall()
    rejection = [e for e in events if e[0] == "security_rejection"]
    assert len(rejection) >= 1
    assert "exceeds receiving card max_artifact_bytes (50)" in rejection[0][1]


def test_artifact_offer_duplicate_offer_exact_replay(alice_node, bob_node):
    """Requirement 4: Duplicate offer with exact same sequence number is caught by sequence replay guard."""
    session_id, mock_client = _setup_active_session(alice_node, bob_node)
    raw_payload = b"Replay test artifact payload"

    alice_meta = store_artifact(
        alice_node["conn"],
        alice_node["vault_key"],
        session_id=session_id,
        raw_bytes=raw_payload,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=1_000_000,
    )

    enc_bytes = encrypt_for_recipient(alice_node["x255_priv"], bob_node["x255_pub"], raw_payload)
    enc_b64 = base64.b64encode(enc_bytes).decode("ascii")

    payload = {
        "schema_version": "1.1",
        "artifact_id": alice_meta.artifact_id,
        "session_id": session_id,
        "sha256": alice_meta.sha256,
        "mime_type": "text/plain",
        "size_bytes": len(raw_payload),
        "offered_by": "alice",
        "preview_policy": "auto",
        "encrypted_bytes_b64": enc_b64,
    }

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": 2,
        "actor_username": "alice",
        "actor_agent_id": "alice_agent",
        "timestamp": "2026-07-27T10:00:00Z",
        "kind": MessageKind.ARTIFACT_OFFER.value,
        "content_hash": compute_content_hash(payload),
        "payload": payload,
    }
    env_dict["signature"] = sign_envelope(env_dict, alice_node["ed_priv"])

    def get_pubkey(un: str):
        return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]

    ack1 = ingest_envelope(
        bob_node["conn"],
        bob_node["vault_key"],
        env_dict,
        get_public_key_fn=get_pubkey,
        recipient_x25519_privkey=bob_node["x255_priv"],
        owner_identity_key=bob_node["ed_priv"],
    )
    assert ack1.status == "delivered"

    # Second ingestion of exact same envelope (duplicate sequence)
    ack2 = ingest_envelope(
        bob_node["conn"],
        bob_node["vault_key"],
        env_dict,
        get_public_key_fn=get_pubkey,
        recipient_x25519_privkey=bob_node["x255_priv"],
        owner_identity_key=bob_node["ed_priv"],
    )
    assert ack2.status == "delivered"


def test_artifact_offer_duplicate_offer_new_sequence_same_content(alice_node, bob_node):
    """Requirement 5: Duplicate offer under a new sequence number with matching content is handled idempotently without duplicate vault rows."""
    session_id, mock_client = _setup_active_session(alice_node, bob_node)
    raw_payload = b"Idempotent re-offer content"

    alice_meta = store_artifact(
        alice_node["conn"],
        alice_node["vault_key"],
        session_id=session_id,
        raw_bytes=raw_payload,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=1_000_000,
    )

    send_artifact_offer(
        alice_node["conn"],
        alice_node["vault_key"],
        alice_node["ed_priv"],
        alice_node["x255_priv"],
        "alice",
        session_id,
        alice_meta.artifact_id,
        http_client=mock_client,
    )

    # Send second offer for same artifact under new sequence number
    send_artifact_offer(
        alice_node["conn"],
        alice_node["vault_key"],
        alice_node["ed_priv"],
        alice_node["x255_priv"],
        "alice",
        session_id,
        alice_meta.artifact_id,
        http_client=mock_client,
    )

    # Assert exactly 1 row exists in Bob's artifacts table
    cur = bob_node["conn"].cursor()
    cur.execute("SELECT COUNT(*) FROM artifacts WHERE artifact_id = ?", (alice_meta.artifact_id,))
    assert cur.fetchone()[0] == 1


def test_artifact_offer_conflicting_artifact_id_rejected(alice_node, bob_node):
    """Requirement 6: Offer claiming an artifact_id that already exists in Bob's vault with different content triggers ArtifactIdConflictError and leaves original content intact."""
    session_id, mock_client = _setup_active_session(alice_node, bob_node)
    original_bob_content = b"Bob's original artifact content"
    conflict_id = "art_conflict_777"

    # Pre-populate Bob's vault with conflict_id
    store_artifact(
        bob_node["conn"],
        bob_node["vault_key"],
        session_id=session_id,
        raw_bytes=original_bob_content,
        mime_type="text/plain",
        offered_by="bob",
        preview_policy="auto",
        max_bytes=1_000_000,
        artifact_id=conflict_id,
    )

    # Alice stores a DIFFERENT payload under conflict_id
    differing_alice_content = b"Alice's conflicting payload content"
    alice_meta = store_artifact(
        alice_node["conn"],
        alice_node["vault_key"],
        session_id=session_id,
        raw_bytes=differing_alice_content,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=1_000_000,
        artifact_id=conflict_id,
    )

    # Alice attempts to offer conflicting artifact to Bob
    send_artifact_offer(
        alice_node["conn"],
        alice_node["vault_key"],
        alice_node["ed_priv"],
        alice_node["x255_priv"],
        "alice",
        session_id,
        alice_meta.artifact_id,
        http_client=mock_client,
    )

    # Assert Bob's original vault content remains untouched and unmodified
    bob_bytes = load_artifact_bytes(bob_node["conn"], bob_node["vault_key"], conflict_id)
    assert bob_bytes == original_bob_content

    # Assert security_rejection logged on Bob's side
    cur = bob_node["conn"].cursor()
    cur.execute("SELECT category, summary FROM audit_events WHERE session_id = ?", (session_id,))
    events = cur.fetchall()
    rejection = [e for e in events if e[0] == "security_rejection"]
    assert len(rejection) >= 1
    assert "Vault storage of offered artifact rejected" in rejection[0][1]


def test_artifact_offer_tampered_envelope_signature_failed(alice_node, bob_node):
    """Requirement 7: Tampered envelope fails Ed25519 signature verification prior to artifact handling."""
    session_id, mock_client = _setup_active_session(alice_node, bob_node)
    raw_payload = b"Tampered envelope payload"

    alice_meta = store_artifact(
        alice_node["conn"],
        alice_node["vault_key"],
        session_id=session_id,
        raw_bytes=raw_payload,
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=1_000_000,
    )

    enc_bytes = encrypt_for_recipient(alice_node["x255_priv"], bob_node["x255_pub"], raw_payload)
    enc_b64 = base64.b64encode(enc_bytes).decode("ascii")

    payload = {
        "schema_version": "1.1",
        "artifact_id": alice_meta.artifact_id,
        "session_id": session_id,
        "sha256": alice_meta.sha256,
        "mime_type": "text/plain",
        "size_bytes": len(raw_payload),
        "offered_by": "alice",
        "preview_policy": "auto",
        "encrypted_bytes_b64": enc_b64,
    }

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": 2,
        "actor_username": "alice",
        "actor_agent_id": "alice_agent",
        "timestamp": "2026-07-27T10:00:00Z",
        "kind": MessageKind.ARTIFACT_OFFER.value,
        "content_hash": compute_content_hash(payload),
        "payload": payload,
    }
    # Create valid signature
    env_dict["signature"] = sign_envelope(env_dict, alice_node["ed_priv"])

    # Tamper payload after signing
    env_dict["payload"]["mime_type"] = "application/x-malicious"

    def get_pubkey(un: str):
        return alice_node["ed_pub"] if un == "alice" else bob_node["ed_pub"]

    ack = ingest_envelope(
        bob_node["conn"],
        bob_node["vault_key"],
        env_dict,
        get_public_key_fn=get_pubkey,
        recipient_x25519_privkey=bob_node["x255_priv"],
        owner_identity_key=bob_node["ed_priv"],
    )
    assert ack.status == "rejected"
    assert ack.error_code in ("INVALID_SIGNATURE", "CONTENT_HASH_MISMATCH")


def test_artifact_offer_multimegabyte_payload_roundtrip(alice_node, bob_node):
    """Directive 1 Limit Audit Proxy Test: 2 MB artifact transfers end-to-end without body size truncation or rejection."""
    session_id, mock_client = _setup_active_session(alice_node, bob_node)
    # 2 MB binary payload
    large_payload = b"\x01\x02\x03\x04\xff" * (400 * 1024)
    assert len(large_payload) == 2_048_000

    alice_meta = store_artifact(
        alice_node["conn"],
        alice_node["vault_key"],
        session_id=session_id,
        raw_bytes=large_payload,
        mime_type="application/octet-stream",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=10_000_000,
    )

    res = send_artifact_offer(
        alice_node["conn"],
        alice_node["vault_key"],
        alice_node["ed_priv"],
        alice_node["x255_priv"],
        "alice",
        session_id,
        alice_meta.artifact_id,
        http_client=mock_client,
    )
    assert res["status"] == "offered"

    bob_bytes = load_artifact_bytes(bob_node["conn"], bob_node["vault_key"], alice_meta.artifact_id)
    assert len(bob_bytes) == len(large_payload)
    assert bob_bytes == large_payload


def test_send_artifact_offer_validation_errors(alice_node, bob_node):
    """Directive 4 Validation Tests: Non-existent artifact_id and session_id mismatch raise explicit domain exceptions."""
    session_id, mock_client = _setup_active_session(alice_node, bob_node)

    # 1. Offering non-existent artifact_id raises ArtifactNotFoundError
    with pytest.raises(ArtifactNotFoundError):
        send_artifact_offer(
            alice_node["conn"],
            alice_node["vault_key"],
            alice_node["ed_priv"],
            alice_node["x255_priv"],
            "alice",
            session_id,
            "art_nonexistent_000",
            http_client=mock_client,
        )

    # 2. Offering artifact belonging to session_1 when calling send_artifact_offer for session_2 raises ValueError
    alice_meta_sess1 = store_artifact(
        alice_node["conn"],
        alice_node["vault_key"],
        session_id=session_id,
        raw_bytes=b"Session 1 payload",
        mime_type="text/plain",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=100_000,
    )

    session_id_2, mock_client_2 = _setup_active_session(alice_node, bob_node)

    with pytest.raises(ValueError, match="belongs to session"):
        send_artifact_offer(
            alice_node["conn"],
            alice_node["vault_key"],
            alice_node["ed_priv"],
            alice_node["x255_priv"],
            "alice",
            session_id_2,
            alice_meta_sess1.artifact_id,
            http_client=mock_client_2,
        )
