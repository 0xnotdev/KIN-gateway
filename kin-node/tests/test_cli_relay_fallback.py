"""Integration tests for offline relay fallback in 'kin ask' / 'kin respond' and the 'kin fetch' command."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import httpx
import keyring
import keyring.backend
from typer.testing import CliRunner

from kin.cli import app as cli_app
from kin.storage.db import get_connection, create_schema
from kin.identity.keys import (
    generate_recovery_phrase,
    derive_key_pair,
    sign_message,
    derive_x25519_key_pair,
    encrypt_for_recipient,
)
from kin.identity.storage import save_private_key, save_x25519_private_key


class InMemoryKeyringForFallback(keyring.backend.KeyringBackend):
    """A dictionary-backed keyring for unit tests to avoid polluting the OS vault."""
    priority = 1
    KIN_TEST_BACKEND = True

    def __init__(self):
        self.passwords = {}

    def set_password(self, servicename, username, password):
        self.passwords[(servicename, username)] = password

    def get_password(self, servicename, username):
        return self.passwords.get((servicename, username))

    def delete_password(self, servicename, username):
        if (servicename, username) in self.passwords:
            del self.passwords[(servicename, username)]
            return 0
        return -1


@pytest.fixture(autouse=True)
def mock_keyring():
    """Fixture that intercepts keyring operations and routes them to InMemoryKeyringForFallback."""
    original_keyring = keyring.get_keyring()
    mem_keyring = InMemoryKeyringForFallback()
    keyring.set_keyring(mem_keyring)
    yield mem_keyring
    keyring.set_keyring(original_keyring)


@pytest.fixture
def temp_profile_dir() -> Path:
    """Fixture that creates a temporary directory for CLI profile data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_ask_connection_failure_falls_back_to_relay(runner, temp_profile_dir, mock_keyring) -> None:
    """Test that kin ask falls back to relay on connection failure and inserts local queued task."""
    db_path = temp_profile_dir / "kin.db"
    temp_profile_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    create_schema(conn)

    # Setup identity & keys
    own_phrase = generate_recovery_phrase()
    own_priv, own_pub = derive_key_pair(own_phrase)
    own_x25519_priv, own_x25519_pub = derive_x25519_key_pair(own_phrase)

    conn.execute("INSERT INTO identity VALUES (?, ?, ?, ?)", ("alice", own_pub.hex(), "keychain-ref", "0.1.0"))

    # Setup verified contact Bob
    bob_phrase = generate_recovery_phrase()
    bob_priv, bob_pub = derive_key_pair(bob_phrase)
    bob_x25519_priv, bob_x25519_pub = derive_x25519_key_pair(bob_phrase)

    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, endpoint, autonomy_level, fingerprint_verified_at, x25519_public_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("bob", "Bob", bob_pub.hex(), "http://localhost:9999", "always_ask", "2026-07-17T12:00:00Z", bob_x25519_pub.hex()),
    )
    conn.commit()
    conn.close()

    # Pre-populate keys in mocked keyring
    save_private_key("test-p", own_priv)
    save_x25519_private_key("test-p", own_x25519_priv)

    # Mock direct connection failure, but successful relay delivery
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"status": "queued"}

    def side_effect(url, *args, **kwargs):
        if "/tasks" in url:
            # direct connection error
            raise httpx.ConnectError("Connection refused")
        elif "/relay/mailbox" in url:
            return mock_post_res
        raise ValueError(f"Unexpected URL: {url}")

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.post", side_effect=side_effect) as mock_post,
    ):
        result = runner.invoke(cli_app, ["--profile", "test-p", "ask", "bob", "What is the status?"])
        output = result.stdout + result.stderr
        assert result.exit_code == 0
        assert "Direct connection to bob failed. Falling back to relay mailbox..." in output
        assert "Task queued at relay, contact is offline." in output

        # Verify calls
        assert mock_post.call_count == 2 # 1 direct (failed) + 1 relay (succeeded)
        
        # Verify local task status is queued-relay and task_id has local-queued- prefix
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT task_id, status, goal FROM tasks")
        row = cursor.fetchone()
        assert row is not None
        task_id, status, goal = row
        assert task_id.startswith("local-queued-")
        assert status == "queued-relay"
        assert goal == "What is the status?"
        conn.close()


def test_cli_ask_http_error_does_not_fall_back_to_relay(runner, temp_profile_dir, mock_keyring) -> None:
    """Test that kin ask does NOT fall back to relay on HTTP status error (e.g. 403) and exits 1."""
    db_path = temp_profile_dir / "kin.db"
    temp_profile_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    create_schema(conn)

    own_phrase = generate_recovery_phrase()
    own_priv, own_pub = derive_key_pair(own_phrase)
    conn.execute("INSERT INTO identity VALUES (?, ?, ?, ?)", ("alice", own_pub.hex(), "keychain-ref", "0.1.0"))

    # Setup verified contact Bob
    bob_phrase = generate_recovery_phrase()
    bob_priv, bob_pub = derive_key_pair(bob_phrase)
    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, endpoint, autonomy_level, fingerprint_verified_at, x25519_public_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("bob", "Bob", bob_pub.hex(), "http://localhost:9999", "always_ask", "2026-07-17T12:00:00Z", "x25519-bob"),
    )
    conn.commit()
    conn.close()

    save_private_key("test-p", own_priv)

    # Mock HTTP 403 Forbidden status error
    mock_response = MagicMock(status_code=403)
    mock_response.json.return_value = {"detail": "Access Denied"}
    mock_response.request = MagicMock()
    http_status_err = httpx.HTTPStatusError("Forbidden", request=mock_response.request, response=mock_response)

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.post", side_effect=http_status_err) as mock_post,
    ):
        result = runner.invoke(cli_app, ["--profile", "test-p", "ask", "bob", "What is the status?"])
        output = result.stdout + result.stderr
        assert result.exit_code == 1
        assert "Error from receiving node: Access Denied" in output
        assert "Falling back to relay" not in output

        mock_post.assert_called_once()  # only direct post was attempted


def test_cli_respond_connection_failure_falls_back_to_relay(runner, temp_profile_dir, mock_keyring) -> None:
    """Test that kin respond falls back to relay on connection failure and updates status locally to queued-relay."""
    db_path = temp_profile_dir / "kin.db"
    temp_profile_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    create_schema(conn)

    own_phrase = generate_recovery_phrase()
    own_priv, own_pub = derive_key_pair(own_phrase)
    own_x25519_priv, own_x25519_pub = derive_x25519_key_pair(own_phrase)

    conn.execute("INSERT INTO identity VALUES (?, ?, ?, ?)", ("alice", own_pub.hex(), "keychain-ref", "0.1.0"))

    # Setup verified contact Bob
    bob_phrase = generate_recovery_phrase()
    bob_priv, bob_pub = derive_key_pair(bob_phrase)
    bob_x25519_priv, bob_x25519_pub = derive_x25519_key_pair(bob_phrase)

    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, endpoint, autonomy_level, fingerprint_verified_at, x25519_public_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("bob", "Bob", bob_pub.hex(), "http://localhost:9999", "always_ask", "2026-07-17T12:00:00Z", bob_x25519_pub.hex()),
    )

    # Insert task needing response
    task_id = "test-respond-task"
    conn.execute(
        "INSERT INTO tasks (task_id, contact_username, goal, context_json, status, created_at, updated_at, draft_content, draft_message_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, "bob", "Goal", "{}", "input-required", "2026-07-17T12:00:00Z", "2026-07-17T12:00:00Z", "Outcome Accepted", "finalize_proposal"),
    )
    conn.commit()
    conn.close()

    save_private_key("test-p", own_priv)
    save_x25519_private_key("test-p", own_x25519_priv)

    # Mock connection failure on direct, success on relay
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"status": "queued"}

    def side_effect(url, *args, **kwargs):
        if f"/tasks/{task_id}/messages" in url:
            raise httpx.ConnectError("Connection refused")
        elif "/relay/mailbox" in url:
            return mock_post_res
        raise ValueError(f"Unexpected URL: {url}")

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.post", side_effect=side_effect) as mock_post,
    ):
        result = runner.invoke(cli_app, ["--profile", "test-p", "respond", task_id], input="a\n")
        output = result.stdout + result.stderr
        assert result.exit_code == 0
        assert "Direct connection to bob failed. Falling back to relay mailbox..." in output
        assert "Response queued — will be delivered when bob comes online. This has NOT yet been confirmed as final by them." in output

        # Verify task locally is marked "queued-relay" and NOT "completed", despite being finalize_accept
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, draft_content, draft_message_type FROM tasks WHERE task_id = ?", (task_id,))
        status, draft, msg_type = cursor.fetchone()
        assert status == "queued-relay"
        assert draft is None
        assert msg_type is None
        conn.close()


def test_cli_fetch_success_and_warnings(runner, temp_profile_dir, mock_keyring) -> None:
    """Test that kin fetch retrieves, decrypts, and successfully processes queued envelopes, showing correct skips and warnings."""
    db_path = temp_profile_dir / "kin.db"
    temp_profile_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    create_schema(conn)

    # Own Identity details
    own_phrase = generate_recovery_phrase()
    own_priv, own_pub = derive_key_pair(own_phrase)
    own_x25519_priv, own_x25519_pub = derive_x25519_key_pair(own_phrase)

    conn.execute("INSERT INTO identity VALUES (?, ?, ?, ?)", ("alice", own_pub.hex(), "keychain-ref", "0.1.0"))

    # Contacts details: verified Bob, unverified Mallory, and verified Charlie (who has no X25519 key)
    bob_phrase = generate_recovery_phrase()
    bob_priv, bob_pub = derive_key_pair(bob_phrase)
    bob_x25519_priv, bob_x25519_pub = derive_x25519_key_pair(bob_phrase)

    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, endpoint, autonomy_level, fingerprint_verified_at, x25519_public_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("bob", "Bob", bob_pub.hex(), "http://localhost:8321", "always_ask", "2026-07-17T12:00:00Z", bob_x25519_pub.hex()),
    )
    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, endpoint, autonomy_level, fingerprint_verified_at, x25519_public_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("mallory", "Mallory", "mallory-pub", "http://localhost:8322", "always_ask", None, "x25519-mallory"),
    )
    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, endpoint, autonomy_level, fingerprint_verified_at, x25519_public_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("charlie", "Charlie", "charlie-pub", "http://localhost:8323", "always_ask", "2026-07-17T12:00:00Z", None),
    )

    # Setup an active task locally for send_message matching test
    conn.execute(
        "INSERT INTO tasks (task_id, contact_username, goal, context_json, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("task-bob-111", "bob", "Bob's Goal", "{}", "working", "2026-07-17T12:00:00Z", "2026-07-17T12:00:00Z"),
    )
    conn.commit()
    conn.close()

    save_private_key("test-p", own_priv)
    save_x25519_private_key("test-p", own_x25519_priv)
    mock_keyring.set_password("kin-test-p-llm-openrouter", "api_key", "mock-openrouter-key")

    # Prepare decrypted envelopes:
    # 1. Create task envelope from Bob
    task_payload = {"goal": "Help me code", "context": {}, "requester_username": "bob"}
    task_payload_bytes = json.dumps(task_payload, separators=(",", ":")).encode("utf-8")
    task_sig = sign_message(bob_priv, task_payload_bytes).hex()
    task_envelope = {
        "type": "create_task",
        "payload_bytes": task_payload_bytes.hex(),
        "signature": task_sig,
    }
    task_envelope_bytes = json.dumps(task_envelope, separators=(",", ":")).encode("utf-8")
    task_ciphertext = encrypt_for_recipient(bob_x25519_priv, own_x25519_pub, task_envelope_bytes)

    # 2. Send message envelope from Bob (Happy Path)
    msg_payload = {"from_username": "bob", "content": "Here is response", "message_type": "proposal"}
    msg_payload_bytes = json.dumps(msg_payload, separators=(",", ":")).encode("utf-8")
    msg_sig = sign_message(bob_priv, msg_payload_bytes).hex()
    msg_envelope = {
        "type": "send_message",
        "task_id": "task-bob-111",
        "payload_bytes": msg_payload_bytes.hex(),
        "signature": msg_sig,
    }
    msg_envelope_bytes = json.dumps(msg_envelope, separators=(",", ":")).encode("utf-8")
    msg_ciphertext = encrypt_for_recipient(bob_x25519_priv, own_x25519_pub, msg_envelope_bytes)

    # 3. Send message envelope from Bob for UNRECOGNIZED task_id (Part D validation)
    unrec_envelope = {
        "type": "send_message",
        "task_id": "unrecognized-task-999",
        "payload_bytes": msg_payload_bytes.hex(),
        "signature": msg_sig,
    }
    unrec_envelope_bytes = json.dumps(unrec_envelope, separators=(",", ":")).encode("utf-8")
    unrec_ciphertext = encrypt_for_recipient(bob_x25519_priv, own_x25519_pub, unrec_envelope_bytes)

    # Mock inbox HTTP response
    mock_inbox = {
        "messages": [
            {"sender_username": "bob", "encrypted_blob": task_ciphertext.hex()},
            {"sender_username": "bob", "encrypted_blob": msg_ciphertext.hex()},
            {"sender_username": "bob", "encrypted_blob": unrec_ciphertext.hex()},
            {"sender_username": "mallory", "encrypted_blob": "deadbeef"}, # Unverified sender
            {"sender_username": "charlie", "encrypted_blob": "deadbeef"}, # No X25519 key
            {"sender_username": "bob", "encrypted_blob": "ffffffff"}, # Decryption failure
        ]
    }

    mock_get_res = MagicMock()
    mock_get_res.status_code = 200
    mock_get_res.json.return_value = mock_inbox

    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = '{"reply": "This is a fetched reply.", "message_type": "proposal"}'

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.get", return_value=mock_get_res),
        patch("litellm.acompletion", return_value=mock_resp) as mock_acompletion,
    ):
        result = runner.invoke(cli_app, ["--profile", "test-p", "fetch"])
        output = result.stdout + result.stderr
        assert result.exit_code == 0

        # Verify stdout prints
        assert "Fetched 6 message(s) from relay." in output
        
        # Happy paths
        assert "Successfully processed new task." in output
        assert "Successfully processed message for task 'task-bob-111'." in output

        # Unrecognized task warning prints (Part D check)
        assert "Warning: Received a reply for an unrecognized task 'unrecognized-task-999' — likely a local-queued task that hasn't been reconciled; message not processed." in output

        # Skips & warnings print
        assert "Warning: Sender 'mallory' is not a verified contact. Skipping message." in output
        assert "Warning: Contact 'charlie' has no registered X25519 public key. Skipping message." in output
        assert "Warning: Decryption failed for message from 'bob'" in output

        # Verify new task is inserted in DB with status "input-required" and correct draft content
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, draft_content, draft_message_type FROM tasks WHERE contact_username = 'bob' AND goal = 'Help me code'")
        row_task = cursor.fetchone()
        assert row_task is not None
        assert row_task[0] == "input-required"
        assert row_task[1] == "This is a fetched reply."
        assert row_task[2] == "proposal"

        # Verify message is appended to the active task and status transitions to "input-required" with correct draft
        cursor.execute("SELECT COUNT(*) FROM messages WHERE task_id = 'task-bob-111'")
        msg_count = cursor.fetchone()[0]
        assert msg_count == 1 # the proposal from bob was appended

        cursor.execute("SELECT status, draft_content, draft_message_type FROM tasks WHERE task_id = 'task-bob-111'")
        row_existing = cursor.fetchone()
        assert row_existing[0] == "input-required"
        assert row_existing[1] == "This is a fetched reply."
        assert row_existing[2] == "proposal"
        conn.close()


def test_offline_relay_reply_reconciliation(temp_profile_dir, mock_keyring) -> None:
    """Test full offline task reconciliation without mutating local-queued- primary key."""
    import asyncio
    from kin.node.models import CreateTaskRequest, SendMessageRequest
    from kin.node.routes import process_create_task, process_send_message, get_task_status

    db_alice = temp_profile_dir / "alice.db"
    db_bob = temp_profile_dir / "bob.db"

    conn_alice = get_connection(db_alice)
    conn_bob = get_connection(db_bob)
    create_schema(conn_alice)
    create_schema(conn_bob)

    # Setup keys
    alice_phrase = generate_recovery_phrase()
    alice_priv, alice_pub = derive_key_pair(alice_phrase)
    bob_phrase = generate_recovery_phrase()
    bob_priv, bob_pub = derive_key_pair(bob_phrase)

    # Database records
    conn_alice.execute("INSERT INTO identity VALUES (?, ?, ?, ?)", ("alice", alice_pub.hex(), "keychain-ref", "0.1.0"))
    conn_alice.execute(
        "INSERT INTO contacts (username, display_name, public_key, endpoint, autonomy_level, fingerprint_verified_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("bob", "Bob", bob_pub.hex(), "http://localhost:8321", "always_ask", "2026-07-17T12:00:00Z"),
    )

    conn_bob.execute("INSERT INTO identity VALUES (?, ?, ?, ?)", ("bob", bob_pub.hex(), "keychain-ref", "0.1.0"))
    conn_bob.execute(
        "INSERT INTO contacts (username, display_name, public_key, endpoint, autonomy_level, fingerprint_verified_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("alice", "Alice", alice_pub.hex(), "http://localhost:8322", "always_ask", "2026-07-17T12:00:00Z"),
    )

    # 1. Alice queues offline task locally
    local_ref_id = "local-queued-12345"
    conn_alice.execute(
        "INSERT INTO tasks (task_id, contact_username, goal, context_json, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (local_ref_id, "bob", "Offline Goal", "{}", "queued-relay", "2026-07-17T12:00:00Z", "2026-07-17T12:00:00Z"),
    )
    conn_alice.commit()

    # 2. Bob receives create_task envelope via fetch carrying local_ref_id
    task_req = CreateTaskRequest(goal="Offline Goal", requester_username="alice", context={})
    raw_payload = json.dumps(task_req.model_dump(), separators=(",", ":")).encode("utf-8")
    sig_alice = sign_message(alice_priv, raw_payload).hex()

    code, bob_res = asyncio.run(process_create_task(task_req, raw_payload, sig_alice, conn_bob, "bob-profile", local_ref_id=local_ref_id))
    assert code == 200
    bob_task_id = bob_res["task_id"]

    # Verify origin_ref_id was saved on Bob's side
    cur = conn_bob.cursor()
    cur.execute("SELECT origin_ref_id FROM tasks WHERE task_id = ?", (bob_task_id,))
    assert cur.fetchone()[0] == local_ref_id

    # 3. Bob sends reply back carrying origin_ref_id = local_ref_id
    msg_req1 = SendMessageRequest(from_username="bob", content="First reply from Bob", message_type="finalize_proposal", origin_ref_id=local_ref_id)
    raw_msg1 = json.dumps(msg_req1.model_dump(exclude_none=True), separators=(",", ":")).encode("utf-8")
    sig_bob1 = sign_message(bob_priv, raw_msg1).hex()

    # Alice processes Bob's reply addressed to path task_id = bob_task_id
    code_alice1, alice_res1 = asyncio.run(process_send_message(bob_task_id, msg_req1, raw_msg1, sig_bob1, conn_alice, "alice-profile"))
    assert code_alice1 == 200

    # 4. Assert primary key task_id on Alice's side is UNCHANGED, but peer_task_id is set to bob_task_id
    cur_alice = conn_alice.cursor()
    cur_alice.execute("SELECT task_id, peer_task_id, status FROM tasks WHERE task_id = ?", (local_ref_id,))
    row_alice = cur_alice.fetchone()
    assert row_alice is not None
    assert row_alice[0] == local_ref_id # Primary key NEVER mutated!
    assert row_alice[1] == bob_task_id

    # 5. Bob sends a SECOND message WITHOUT origin_ref_id (normal follow-up)
    msg_req2 = SendMessageRequest(from_username="bob", content="Second reply from Bob", message_type="finalize_accept")
    raw_msg2 = json.dumps(msg_req2.model_dump(exclude_none=True), separators=(",", ":")).encode("utf-8")
    sig_bob2 = sign_message(bob_priv, raw_msg2).hex()

    code_alice2, alice_res2 = asyncio.run(process_send_message(bob_task_id, msg_req2, raw_msg2, sig_bob2, conn_alice, "alice-profile"))
    assert code_alice2 == 200

    # 6. Confirm GET /tasks/{task_id} works on Alice's side using BOTH local_ref_id and bob_task_id
    res_local = asyncio.run(get_task_status(local_ref_id, conn_alice))
    res_peer = asyncio.run(get_task_status(bob_task_id, conn_alice))

    assert res_local.status_code == 200
    assert res_peer.status_code == 200
    data_local = json.loads(res_local.body)
    data_peer = json.loads(res_peer.body)
    assert len(data_local["history"]) == 2
    assert len(data_peer["history"]) == 2
    assert data_local["history"][0]["content"] == "First reply from Bob"
    assert data_peer["history"][1]["content"] == "Second reply from Bob"

    conn_alice.close()
    conn_bob.close()

