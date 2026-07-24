"""Tests for the kin-relay service endpoints and business logic."""

from __future__ import annotations

import sqlite3
import tempfile
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from kin_relay.app import app
from kin_relay.db import get_connection, create_schema


@pytest.fixture
def temp_db() -> Path:
    """Fixture that creates a temporary database and configures the app to use it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_relay.db"
        # Pre-initialize schema
        conn = get_connection(db_path)
        create_schema(conn)
        conn.close()

        # Configure app state
        app.state.db_path = str(db_path)
        yield db_path


@pytest.fixture
def client(temp_db) -> TestClient:
    """Fixture providing a test client configured with the temporary database."""
    # TestClient calls lifespan events
    with TestClient(app) as c:
        yield c


def test_registration_idempotency_and_update(client) -> None:
    """Test that registering a new contact works, re-registering is idempotent, and endpoint can be updated."""
    # 1. First-time registration
    payload = {
        "username": "alice",
        "public_key": "pubkey-alice-123",
        "x25519_public_key": "x25519-alice-123",
        "endpoint": "https://alice.kin.dev",
    }
    r = client.post("/directory/register", json=payload)
    assert r.status_code == 200
    assert r.json() == {"status": "registered"}

    # 2. Idempotent re-registration with same username & key (updating the endpoint)
    updated_payload = {
        "username": "alice",
        "public_key": "pubkey-alice-123",
        "x25519_public_key": "x25519-alice-123",
        "endpoint": "https://new-alice.kin.dev",
    }
    r = client.post("/directory/register", json=updated_payload)
    assert r.status_code == 200

    # 3. Lookup must reflect updated endpoint
    r = client.get("/directory/lookup/alice")
    assert r.status_code == 200
    data = r.json()
    assert data["public_key"] == "pubkey-alice-123"
    assert data["x25519_public_key"] == "x25519-alice-123"
    assert data["endpoint"] == "https://new-alice.kin.dev"


def test_registration_conflict_different_keys(client) -> None:
    """Test that attempting to register an existing username with a different key fails."""
    # Register alice first
    payload = {
        "username": "alice",
        "public_key": "pubkey-alice-123",
        "x25519_public_key": "x25519-alice-123",
        "endpoint": "https://alice.kin.dev",
    }
    r = client.post("/directory/register", json=payload)
    assert r.status_code == 200

    # Register alice again with a different public key (conflict)
    conflict_payload = {
        "username": "alice",
        "public_key": "pubkey-alice-different",
        "x25519_public_key": "x25519-alice-123",
        "endpoint": "https://alice.kin.dev",
    }
    r = client.post("/directory/register", json=conflict_payload)
    assert r.status_code == 409
    assert "already registered to a different key" in r.json()["detail"]


def test_lookup_not_found(client) -> None:
    """Test that looking up a non-existent username returns 404."""
    r = client.get("/directory/lookup/nonexistent")
    assert r.status_code == 404
    assert "not found in directory" in r.json()["detail"]


def test_mailbox_delivery_unregistered_recipient(client) -> None:
    """Test that sending a message to a recipient not in the directory fails with 404."""
    payload = {"sender_username": "alice", "encrypted_blob": "some-encrypted-content"}
    r = client.post("/relay/mailbox/unregistered-user", json=payload)
    assert r.status_code == 404
    assert "is not registered" in r.json()["detail"]


def test_mailbox_delivery_and_inbox_fetch_roundtrip(client) -> None:
    """Test successful delivery, durable fetch, and explicit acknowledgement."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    # 1. Register sender and recipient
    keys = {}
    for user in ["alice", "bob"]:
        priv = ed25519.Ed25519PrivateKey.generate()
        pub = priv.public_key().public_bytes_raw().hex()
        keys[user] = (priv, pub)
        client.post(
            "/directory/register",
            json={
                "username": user,
                "public_key": pub,
                "x25519_public_key": f"x25519-{user}",
                "endpoint": f"https://{user}.kin.dev",
            },
        )

    # 2. Deliver message to Bob's mailbox
    payload = {"sender_username": "alice", "encrypted_blob": "encrypted-msg-for-bob"}
    r = client.post("/relay/mailbox/bob", json=payload)
    assert r.status_code == 200
    assert r.json() == {"status": "queued"}

    # 3. Fetch Bob's inbox (must succeed and return the message)
    bob_priv, bob_pub = keys["bob"]
    ts = datetime.now(timezone.utc).isoformat()
    msg = f"bob:{ts}".encode("utf-8")
    sig = bob_priv.sign(msg).hex()

    r = client.get(
        "/relay/inbox",
        headers={
            "X-Username": "bob",
            "X-Timestamp": ts,
            "X-Signature": sig,
        }
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["messages"]) == 1
    assert data["messages"][0]["sender_username"] == "alice"
    assert data["messages"][0]["encrypted_blob"] == "encrypted-msg-for-bob"
    message_id = data["messages"][0]["message_id"]

    # 4. Acknowledge only after local processing has succeeded.
    ack_payload = {"message_ids": [message_id]}
    ack_body = json.dumps(ack_payload, separators=(",", ":"))
    ack_timestamp = datetime.now(timezone.utc).isoformat()
    ack_signature = bob_priv.sign(f"bob:{ack_timestamp}:{ack_body}".encode("utf-8")).hex()
    r = client.post(
        "/relay/inbox/ack",
        content=ack_body,
        headers={"Content-Type": "application/json", "X-Username": "bob", "X-Timestamp": ack_timestamp, "X-Signature": ack_signature},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "acknowledged", "count": 1}

    # 5. Fetch Bob's inbox again (now it is empty).
    ts2 = datetime.now(timezone.utc).isoformat()
    msg2 = f"bob:{ts2}".encode("utf-8")
    sig2 = bob_priv.sign(msg2).hex()

    r = client.get(
        "/relay/inbox",
        headers={
            "X-Username": "bob",
            "X-Timestamp": ts2,
            "X-Signature": sig2,
        }
    )
    assert r.status_code == 200
    assert r.json()["messages"] == []


def test_inbox_missing_auth_header(client) -> None:
    """Test that fetching inbox without proper auth headers returns 400."""
    r = client.get("/relay/inbox")
    assert r.status_code == 400
    assert "Missing X-Username header" in r.json()["detail"]

    r = client.get("/relay/inbox", headers={"X-Username": "bob"})
    assert r.status_code == 400
    assert "Missing X-Signature header" in r.json()["detail"]

    r = client.get("/relay/inbox", headers={"X-Username": "bob", "X-Signature": "abc"})
    assert r.status_code == 400
    assert "Missing X-Timestamp header" in r.json()["detail"]


def test_ack_signature_is_bound_to_message_ids(client) -> None:
    """An inbox-read signature cannot be replayed as a destructive acknowledgement."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private_key = ed25519.Ed25519PrivateKey.generate()
    client.post(
        "/directory/register",
        json={
            "username": "bob",
            "public_key": private_key.public_key().public_bytes_raw().hex(),
            "x25519_public_key": "x25519-bob",
            "endpoint": "https://bob.kin.dev",
        },
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    inbox_signature = private_key.sign(f"bob:{timestamp}".encode("utf-8")).hex()
    response = client.post(
        "/relay/inbox/ack",
        json={"message_ids": [1]},
        headers={"X-Username": "bob", "X-Timestamp": timestamp, "X-Signature": inbox_signature},
    )
    assert response.status_code == 401


def test_expired_messages_not_returned(client, temp_db) -> None:
    """Test that expired messages are cleaned up and never returned to the client."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    # 1. Register Bob
    bob_priv = ed25519.Ed25519PrivateKey.generate()
    bob_pub = bob_priv.public_key().public_bytes_raw().hex()
    client.post(
        "/directory/register",
        json={
            "username": "bob",
            "public_key": bob_pub,
            "x25519_public_key": "x25519-bob",
            "endpoint": "https://bob.kin.dev",
        },
    )

    # 2. Manually insert one expired message and one active message into the DB
    conn = get_connection(temp_db)
    cursor = conn.cursor()

    now = datetime.now(timezone.utc)
    expired_time = (now - timedelta(days=1)).isoformat()
    active_time = (now + timedelta(days=5)).isoformat()
    received_time = now.isoformat()

    # Expired message
    cursor.execute(
        "INSERT INTO mailbox (username, sender_username, encrypted_blob, received_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        ("bob", "alice", "expired-message-blob", received_time, expired_time),
    )
    # Active message
    cursor.execute(
        "INSERT INTO mailbox (username, sender_username, encrypted_blob, received_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        ("bob", "alice", "active-message-blob", received_time, active_time),
    )
    conn.commit()
    conn.close()

    # 3. Fetch Bob's inbox
    ts = datetime.now(timezone.utc).isoformat()
    msg = f"bob:{ts}".encode("utf-8")
    sig = bob_priv.sign(msg).hex()

    r = client.get(
        "/relay/inbox",
        headers={
            "X-Username": "bob",
            "X-Timestamp": ts,
            "X-Signature": sig,
        }
    )
    assert r.status_code == 200
    data = r.json()

    # Must only return the active message, and the expired message must be deleted.
    assert len(data["messages"]) == 1
    assert data["messages"][0]["sender_username"] == "alice"
    assert data["messages"][0]["encrypted_blob"] == "active-message-blob"

    # The active message remains until the recipient explicitly acknowledges it.
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM mailbox WHERE username = 'bob'")
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 1


def test_inbox_auth_invalid_signature(client) -> None:
    """Test that fetching inbox with an invalid signature is rejected with 401."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    # Register Bob
    bob_priv = ed25519.Ed25519PrivateKey.generate()
    bob_pub = bob_priv.public_key().public_bytes_raw().hex()
    client.post(
        "/directory/register",
        json={
            "username": "bob",
            "public_key": bob_pub,
            "x25519_public_key": "x25519-bob",
            "endpoint": "https://bob.kin.dev",
        },
    )

    ts = datetime.now(timezone.utc).isoformat()
    bad_sig = "ff" * 64

    r = client.get(
        "/relay/inbox",
        headers={
            "X-Username": "bob",
            "X-Timestamp": ts,
            "X-Signature": bad_sig,
        }
    )
    assert r.status_code == 401
    assert "Invalid signature" in r.json()["detail"]


def test_inbox_auth_stale_timestamp(client) -> None:
    """Test that fetching inbox with a timestamp > 5 minutes in the past is rejected."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    # Register Bob
    bob_priv = ed25519.Ed25519PrivateKey.generate()
    bob_pub = bob_priv.public_key().public_bytes_raw().hex()
    client.post(
        "/directory/register",
        json={
            "username": "bob",
            "public_key": bob_pub,
            "x25519_public_key": "x25519-bob",
            "endpoint": "https://bob.kin.dev",
        },
    )

    # 6 minutes ago
    stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    msg = f"bob:{stale_ts}".encode("utf-8")
    sig = bob_priv.sign(msg).hex()

    r = client.get(
        "/relay/inbox",
        headers={
            "X-Username": "bob",
            "X-Timestamp": stale_ts,
            "X-Signature": sig,
        }
    )
    assert r.status_code == 401
    assert "outside the allowed 5-minute window" in r.json()["detail"]


def test_inbox_auth_future_timestamp(client) -> None:
    """Test that fetching inbox with a timestamp > 5 minutes in the future is rejected."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    # Register Bob
    bob_priv = ed25519.Ed25519PrivateKey.generate()
    bob_pub = bob_priv.public_key().public_bytes_raw().hex()
    client.post(
        "/directory/register",
        json={
            "username": "bob",
            "public_key": bob_pub,
            "x25519_public_key": "x25519-bob",
            "endpoint": "https://bob.kin.dev",
        },
    )

    # 6 minutes in the future
    future_ts = (datetime.now(timezone.utc) + timedelta(minutes=6)).isoformat()
    msg = f"bob:{future_ts}".encode("utf-8")
    sig = bob_priv.sign(msg).hex()

    r = client.get(
        "/relay/inbox",
        headers={
            "X-Username": "bob",
            "X-Timestamp": future_ts,
            "X-Signature": sig,
        }
    )
    assert r.status_code == 401
    assert "outside the allowed 5-minute window" in r.json()["detail"]


def test_relay_mailbox_never_sees_plaintext(client) -> None:
    """Test §15.6 relay inspection requirement: stored/forwarded payload contains neither objective string nor payload substrings."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    bob_priv = ed25519.Ed25519PrivateKey.generate()
    bob_pub = bob_priv.public_key().public_bytes_raw().hex()
    client.post(
        "/directory/register",
        json={
            "username": "bob",
            "public_key": bob_pub,
            "x25519_public_key": "x25519-bob",
            "endpoint": "https://bob.kin.dev",
        },
    )

    sensitive_objective = "Confidential financial budget review and salary negotiation"
    opaque_ciphertext = "a1b2c3d4e5f67890deadbeefcafe1234567890abcdef"

    r = client.post(
        "/relay/mailbox/bob",
        json={
            "sender_username": "alice",
            "encrypted_blob": opaque_ciphertext,
        },
    )
    assert r.status_code == 200

    # Fetch inbox for Bob
    ts = datetime.now(timezone.utc).isoformat()
    msg = f"bob:{ts}".encode("utf-8")
    sig = bob_priv.sign(msg).hex()
    inbox_res = client.get(
        "/relay/inbox",
        headers={"X-Username": "bob", "X-Timestamp": ts, "X-Signature": sig},
    )
    assert inbox_res.status_code == 200

    raw_body = inbox_res.text
    messages = inbox_res.json()["messages"]
    assert len(messages) == 1

    stored_payload = messages[0]["encrypted_blob"]
    assert stored_payload == opaque_ciphertext

    # Assert plaintext string or JSON envelope fields NEVER appear anywhere in raw relay payload/response
    assert sensitive_objective not in raw_body
    assert "collaboration_mode" not in raw_body
    assert "goal" not in raw_body
