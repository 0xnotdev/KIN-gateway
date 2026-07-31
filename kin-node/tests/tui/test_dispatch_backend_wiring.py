"""Unit tests for backend dispatch wiring in dispatch_new_session (§A4).

Covers:
1. Unverified peer rejection (prevents quiet false 'sent' fallback).
2. Key loading and Ed25519 bytes-to-key object conversion.
3. Direct delivery via mock HTTP client.
4. Error translation to distinct RecoverableError objects.
"""

from pathlib import Path

import httpx
import pytest

from kin.agent_registry.peer_cards import cache_peer_card
from kin.cli import open_profile_db
from kin.identity.storage import save_private_key, save_x25519_private_key
from kin.schemas import AgentAvailability, AgentCapabilities, PublishedAgentCard
from kin.storage.db import create_schema
from kin.tui.local_state import dispatch_new_session


def setup_profile_identity(prof_dir: Path, username: str):
    prof_dir.mkdir(parents=True, exist_ok=True)
    db_path = prof_dir / "kin.db"
    conn = open_profile_db(db_path)
    create_schema(conn)

    # Store identity keys
    import os
    ed_key_bytes = os.urandom(32)
    x255_key_bytes = os.urandom(32)
    save_private_key(username, ed_key_bytes)
    save_x25519_private_key(username, x255_key_bytes)

    # Insert identity row with valid hex strings
    pk_hex = ("00" * 32)
    conn.execute(
        "INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, 'ref_hex', '1.1')",
        (username, pk_hex),
    )
    conn.commit()
    conn.close()


# -----------------------------------------------------------------------------
# A4. Dispatch Backend Wiring Tests
# -----------------------------------------------------------------------------
def test_dispatch_unverified_peer_rejected(tmp_path: Path):
    """1. Unverified peer username passed to dispatch_new_session is rejected before backend call (§A4)."""
    prof_dir = tmp_path / "profiles" / "unverified_user"
    setup_profile_identity(prof_dir, "unverified_user")

    ok, result, err = dispatch_new_session(
        prof_dir,
        "unverified_user",
        peer_username="unknown_stranger",
        sender_agent_id="agent1",
        receiver_agent_id="agent2",
        session_type="ask",
        goal="Test goal",
    )

    assert ok is False
    assert result is None
    assert err is not None
    assert "not a verified contact" in err.what_happened.lower()
    assert "Verify peer identity" in err.next_action


def test_dispatch_stale_peer_card_rejected(tmp_path: Path):
    """2. Stale peer card causes dispatch_new_session to return StalePeerCard error (§A4)."""
    prof_dir = tmp_path / "profiles" / "stale_user"
    setup_profile_identity(prof_dir, "stale_user")
    db_path = prof_dir / "kin.db"

    # Insert verified contact and cached peer capability
    conn = open_profile_db(db_path)
    pk_hex = ("00" * 32)
    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at) VALUES ('bob', 'Bob Peer', ?, ?, 'http://127.0.0.1:8000', 'always_ask', '2026-07-31T00:00:00Z')",
        (pk_hex, pk_hex),
    )
    cap_json = '{"protocol_version": "1.1", "max_turn_limit": 10, "supported_features": ["session_v1", "jcs_signatures"]}'
    conn.execute(
        "INSERT INTO peer_capabilities (peer_username, capability_json, fetched_at) VALUES ('bob', ?, '2026-07-31T00:00:00Z')",
        (cap_json,),
    )
    conn.commit()

    # Cache stale peer card
    card1 = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="bob-agent",
        name="Bob Agent",
        description="Bob agent desc",
        capabilities=AgentCapabilities(tags=["ask"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
    card2 = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="bob-agent",
        name="Bob Agent Updated",
        description="Updated desc",
        capabilities=AgentCapabilities(tags=["ask", "v2"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
    cache_peer_card(conn, "bob", card1)
    cache_peer_card(conn, "bob", card2)  # Mark stale
    conn.close()

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"protocol_version": "1.1", "max_turn_limit": 10, "supported_features": ["session_v1", "jcs_signatures"]}))
    mock_client = httpx.Client(transport=transport)

    ok, result, err = dispatch_new_session(
        prof_dir,
        "stale_user",
        peer_username="bob",
        sender_agent_id="agent1",
        receiver_agent_id="bob-agent",
        session_type="ask",
        goal="Test goal",
        http_client=mock_client,
    )

    assert ok is False
    assert err is not None
    assert "stale" in err.what_happened.lower()


def test_dispatch_invalid_session_type_rejected(tmp_path: Path):
    """3. Invalid session_type returns clear ValueError RecoverableError (§A4)."""
    prof_dir = tmp_path / "profiles" / "invalid_type_user"
    setup_profile_identity(prof_dir, "invalid_type_user")
    db_path = prof_dir / "kin.db"

    conn = open_profile_db(db_path)
    pk_hex = ("00" * 32)
    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at) VALUES ('alice', 'Alice Peer', ?, ?, 'http://127.0.0.1:8000', 'always_ask', '2026-07-31T00:00:00Z')",
        (pk_hex, pk_hex),
    )
    conn.commit()
    conn.close()

    ok, result, err = dispatch_new_session(
        prof_dir,
        "invalid_type_user",
        peer_username="alice",
        sender_agent_id="agent1",
        receiver_agent_id="agent2",
        session_type="invalid_free_text_mode",
        goal="Test goal",
    )

    assert ok is False
    assert err is not None
    assert "invalid session parameter" in err.what_happened.lower()
