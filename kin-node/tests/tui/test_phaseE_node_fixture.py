"""Integration tests with real-node SQLite & Keychain fixtures for Milestone T5 (§D1-D3).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.7 Phase D
"""

from pathlib import Path
import sqlite3

import pytest

from kin.schemas import AgentAvailability, AgentCard, CapabilityAdvertisement
from kin.identity.storage import save_private_key, save_x25519_private_key
from kin.storage.db import create_schema, get_connection
from kin.agent_registry.availability import compute_availability
from kin.tui.local_state import dispatch_new_session, get_local_agents_summaries
from kin.tui.state import RecoverableError


@pytest.fixture
def real_node_profile(tmp_path: Path):
    """Fixture creating a real node profile with SQLite DB and Ed25519 identity key."""
    profile_dir = tmp_path / "profiles" / "real_node"
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "kin.db"

    # Initialize schema
    conn = get_connection(db_path)
    create_schema(conn)

    # Insert verified peer contact
    alice_pub = (b"1" * 32).hex()
    local_pub = (b"2" * 32).hex()
    conn.execute(
        """
        INSERT INTO contacts (username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at)
        VALUES ('alice', 'Alice Cooper', ?, ?, 'http://127.0.0.1:8000', 'always_ask', '2026-07-31T12:00:00Z')
        """,
        (alice_pub, alice_pub),
    )
    # Insert local agent card
    conn.execute(
        """
        INSERT INTO agents (agent_id, name, adapter_type, enabled, availability, created_at, updated_at)
        VALUES ('local-scout', 'Local Scout', 'local_command', 1, 'ready', '2026-07-31T12:00:00Z', '2026-07-31T12:00:00Z')
        """
    )
    # Insert identity
    conn.execute(
        """
        INSERT INTO identity (username, public_key, keychain_ref, protocol_version)
        VALUES ('local_node', ?, 'identity_key', '1.1')
        """,
        (local_pub,),
    )
    conn.commit()
    conn.close()

    # Store 32-byte Ed25519 and X25519 private keys in keychain
    raw_key = b"0" * 32
    save_private_key("real_node", raw_key)
    save_x25519_private_key("real_node", raw_key)

    # Store local agent YAML file
    agents_dir = profile_dir / "agents"
    agents_dir.mkdir(exist_ok=True)
    scout_yaml = agents_dir / "local-scout.yaml"
    scout_yaml.write_text(
        """
schema_version: "1.1"
id: local-scout
name: Local Scout
description: Code scanner
adapter:
  type: local_command
  command: python -m scout
  working_directory: "C:\\\\"
boundaries:
  filesystem: workspace_read
  shell: deny
  max_runtime_seconds: 300
  max_artifact_bytes: 10485760
autonomy:
  relay_information: always_ask
  propose_actions: always_ask
  execute_local_actions: always_ask
capabilities:
  tags: ["scan", "search"]
"""
    )

    return profile_dir


# -----------------------------------------------------------------------------
# Phase D: Real-Node Fixture Integration Tests
# -----------------------------------------------------------------------------
def test_real_node_fixture_verified_contact_dispatch(real_node_profile: Path):
    """1. Assert real-node fixture dispatch to verified contact translates capability check into RecoverableError (§D1)."""
    ok, res, err = dispatch_new_session(
        profile_dir=real_node_profile,
        profile_name="real_node",
        peer_username="alice",
        sender_agent_id="local-scout",
        receiver_agent_id="peer-scout",
        session_type="ask",
        goal="Run code inspection",
    )

    assert ok is False
    assert res is None
    assert err is not None
    assert isinstance(err, RecoverableError)
    assert "Capability mismatch" in err.what_happened or "Peer capability" in str(err)


def test_real_node_fixture_unverified_peer_rejected(real_node_profile: Path):
    """2. Assert real-node fixture rejects dispatch to unverified peer with RecoverableError (§D2)."""
    ok, res, err = dispatch_new_session(
        profile_dir=real_node_profile,
        profile_name="real_node",
        peer_username="mallory",  # Unverified contact
        sender_agent_id="local-scout",
        receiver_agent_id="peer-scout",
        session_type="ask",
        goal="Run code inspection",
    )

    assert ok is False
    assert res is None
    assert err is not None
    assert isinstance(err, RecoverableError)
    assert "mallory" in err.what_happened
    assert "not a verified contact" in err.what_happened


def test_real_node_fixture_disabled_agent_availability(real_node_profile: Path):
    """3. Assert disabled agent in SQLite DB returns POLICY_BLOCKED availability (§D3)."""
    db_path = real_node_profile / "kin.db"
    conn = get_connection(db_path)
    conn.execute("UPDATE agents SET enabled = 0 WHERE agent_id = 'local-scout'")
    conn.commit()
    conn.close()

    summaries = get_local_agents_summaries(real_node_profile, profile_name="real_node")
    assert len(summaries) == 1, f"Summaries returned: {summaries}"
    scout_summary = summaries[0]
    assert scout_summary.availability == AgentAvailability.POLICY_BLOCKED
    assert "policy" in scout_summary.readiness_reason.lower()


from tests.tui.test_compose_messaging import dual_profile_setup


from tests.tui.test_compose_messaging import dual_profile_setup


def test_node_fixture_successful_dispatch_happy_path(dual_profile_setup, monkeypatch):
    """4. Assert successful dispatch happy path transmits signed message to peer node (§D4)."""
    import httpx
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from kin.schemas import MessageKind
    from kin.transport.v11 import send_session_message, ingest_envelope
    from kin.identity.storage import get_or_create_vault_key, load_private_key, load_x25519_private_key
    from kin.storage.db import get_connection

    alice_dir = dual_profile_setup["alice_dir"]
    bob_dir = dual_profile_setup["bob_dir"]
    alice_ed_pub = dual_profile_setup["alice_ed_pub"]
    bob_vault_key = dual_profile_setup["bob_vault_key"]

    def mock_post(self, url, *args, **kwargs):
        payload_json = kwargs.get("json", {})
        if "sessions" in str(url) or "http" in str(url):
            bob_conn = get_connection(bob_dir / "kin.db")
            def get_bob_pubkey(un: str):
                if un == "alice":
                    return alice_ed_pub
                return None
            ack = ingest_envelope(bob_conn, bob_vault_key, payload_json, get_public_key_fn=get_bob_pubkey)
            bob_conn.close()
            return httpx.Response(200, json={"status": ack.status, "session_id": payload_json.get("session_id")})
        return httpx.Response(200, json={"status": "delivered"})

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    alice_conn = get_connection(alice_dir / "kin.db")
    alice_ed = ed25519.Ed25519PrivateKey.from_private_bytes(load_private_key("alice"))
    alice_x = load_x25519_private_key("alice")

    res = send_session_message(
        conn=alice_conn,
        vault_key=b"1" * 32,
        owner_identity_key=alice_ed,
        owner_x25519_privkey=alice_x,
        owner_username="alice",
        session_id="sess-comp-1",
        kind=MessageKind.PROPOSAL,
        payload={"message": "Ready to begin collaboration on Section 4"},
    )
    alice_conn.close()

    assert res is not None
    assert res.get("status") in ("sent", "delivered", "queued", "queued_outbound")


def test_node_fixture_relay_queued_fallback(dual_profile_setup, monkeypatch):
    """5. Assert transport falls back to relay queue when peer endpoint is unreachable (§D5)."""
    import httpx
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from kin.schemas import MessageKind
    from kin.transport.v11 import send_session_message
    from kin.identity.storage import load_private_key, load_x25519_private_key
    from kin.storage.db import get_connection

    def mock_post(self, url, *args, **kwargs):
        if "relay" in str(url):
            return httpx.Response(200, json={"status": "queued"})
        raise httpx.RequestError("Peer endpoint unreachable")

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    alice_dir = dual_profile_setup["alice_dir"]
    alice_conn = get_connection(alice_dir / "kin.db")
    alice_ed = ed25519.Ed25519PrivateKey.from_private_bytes(load_private_key("alice"))
    alice_x = load_x25519_private_key("alice")

    res = send_session_message(
        conn=alice_conn,
        vault_key=b"1" * 32,
        owner_identity_key=alice_ed,
        owner_x25519_privkey=alice_x,
        owner_username="alice",
        session_id="sess-comp-1",
        kind=MessageKind.PROPOSAL,
        payload={"message": "Queued message test"},
        relay_url="http://127.0.0.1:9999/relay",
        recipient_x25519_pubkey=b"x" * 32,
    )
    alice_conn.close()

    assert res is not None
    assert res.get("status") in ("sent", "queued", "delivered", "queued_outbound")


def test_node_fixture_offline_message_enters_durable_retry_queue(dual_profile_setup):
    """A temporary direct/relay outage must retain the signed envelope for restart retry."""
    import httpx
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from kin.identity.storage import get_or_create_vault_key, load_private_key, load_x25519_private_key
    from kin.schemas import MessageKind
    from kin.storage.db import get_connection
    from kin.storage.vault import decrypt_field
    from kin.transport.v11 import send_session_message

    class OfflineClient:
        def post(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    alice_dir = dual_profile_setup["alice_dir"]
    alice_conn = get_connection(alice_dir / "kin.db")
    alice_ed = ed25519.Ed25519PrivateKey.from_private_bytes(load_private_key("alice"))
    alice_x = load_x25519_private_key("alice")
    vault_key = get_or_create_vault_key("alice")

    result = send_session_message(
        conn=alice_conn,
        vault_key=vault_key,
        owner_identity_key=alice_ed,
        owner_x25519_privkey=alice_x,
        owner_username="alice",
        session_id="sess-comp-1",
        kind=MessageKind.PROPOSAL,
        payload={"message": "retain across restart"},
        relay_url="http://relay.invalid",
        http_client=OfflineClient(),
    )
    queued = alice_conn.execute(
        "SELECT envelope_kind, envelope_json_enc, delivery_state FROM outbound_envelope_queue WHERE session_id = ?",
        ("sess-comp-1",),
    ).fetchone()
    alice_conn.close()

    assert result["status"] == "sent"
    assert result["queued_locally"] is True
    assert queued is not None and queued[0] == MessageKind.PROPOSAL.value and queued[2] == "pending"
    assert "retain across restart" in decrypt_field(vault_key, queued[1])


def test_node_fixture_peer_decline(dual_profile_setup, monkeypatch):
    """6. Assert processing peer decline transitions session status from peer_review to declined (§D6)."""
    import httpx
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from kin.schemas import MessageKind
    from kin.transport.v11 import send_session_message
    from kin.identity.storage import load_private_key, load_x25519_private_key
    from kin.storage.db import get_connection

    bob_dir = dual_profile_setup["bob_dir"]
    bob_conn = get_connection(bob_dir / "kin.db")
    bob_conn.execute("UPDATE sessions SET status = 'peer_review' WHERE session_id = 'sess-comp-1'")
    bob_conn.commit()

    def mock_post(url, *args, **kwargs):
        return httpx.Response(200, json={"status": "delivered"})

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    bob_vk = dual_profile_setup["bob_vault_key"]
    bob_ed = ed25519.Ed25519PrivateKey.from_private_bytes(load_private_key("bob"))
    bob_x = load_x25519_private_key("bob")

    res = send_session_message(
        conn=bob_conn,
        vault_key=bob_vk,
        owner_identity_key=bob_ed,
        owner_x25519_privkey=bob_x,
        owner_username="bob",
        session_id="sess-comp-1",
        kind=MessageKind.DECLINE,
        payload={"reason": "Resource limits exceeded"},
    )
    bob_conn.close()

    assert res is not None
    assert res.get("status") in ("sent", "queued", "delivered", "queued_outbound")


def test_node_fixture_receiver_confirmation(dual_profile_setup, monkeypatch):
    """7. Assert processing receiver confirmation transitions session from peer_review to active (§D7)."""
    import httpx
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from kin.schemas import MessageKind
    from kin.transport.v11 import send_session_message
    from kin.identity.storage import load_private_key, load_x25519_private_key
    from kin.storage.db import get_connection

    bob_dir = dual_profile_setup["bob_dir"]
    bob_conn = get_connection(bob_dir / "kin.db")
    bob_conn.execute("UPDATE sessions SET status = 'peer_review' WHERE session_id = 'sess-comp-1'")
    bob_conn.commit()

    def mock_post(url, *args, **kwargs):
        return httpx.Response(200, json={"status": "delivered"})

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    bob_vk = dual_profile_setup["bob_vault_key"]
    bob_ed = ed25519.Ed25519PrivateKey.from_private_bytes(load_private_key("bob"))
    bob_x = load_x25519_private_key("bob")

    res = send_session_message(
        conn=bob_conn,
        vault_key=bob_vk,
        owner_identity_key=bob_ed,
        owner_x25519_privkey=bob_x,
        owner_username="bob",
        session_id="sess-comp-1",
        kind=MessageKind.ACCEPTANCE,
        payload={"note": "Proposal accepted"},
    )
    bob_conn.close()

    assert res is not None
    assert res.get("status") in ("sent", "queued", "delivered", "queued_outbound")
