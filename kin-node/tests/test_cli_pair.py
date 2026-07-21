"""Tests for the kin pair CLI command."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import keyring
import keyring.backend
import httpx
from typer.testing import CliRunner

from kin.cli import app
from kin.storage.db import get_connection
from kin.identity.keys import generate_recovery_phrase
from kin.identity.fingerprint import compute_fingerprint


class InMemoryKeyring(keyring.backend.KeyringBackend):
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
    """Fixture that intercepts keyring operations and routes them to InMemoryKeyring."""
    original_keyring = keyring.get_keyring()
    mem_keyring = InMemoryKeyring()
    keyring.set_keyring(mem_keyring)
    yield mem_keyring
    keyring.set_keyring(original_keyring)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_profile_dir() -> Path:
    """Fixture that creates a temporary directory for CLI profile data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_pair_lookup_success(runner, temp_profile_dir) -> None:
    """Test lookup of an existing contact succeeds and saves to contacts table on confirmation."""
    contact_name = "bob"
    
    # 1. Pre-initialize identity in local database
    db_path = temp_profile_dir / "kin.db"
    temp_profile_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    # Ensure tables are created
    conn.execute(
        "CREATE TABLE IF NOT EXISTS identity (username TEXT, public_key TEXT, keychain_ref TEXT, protocol_version TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS contacts (username TEXT PRIMARY KEY, display_name TEXT, public_key TEXT, x25519_public_key TEXT, endpoint TEXT, autonomy_level TEXT, fingerprint_verified_at TEXT)"
    )
    our_pubkey = b"\x01" * 32
    conn.execute(
        "INSERT INTO identity VALUES (?, ?, ?, ?)",
        ("alice", our_pubkey.hex(), "keychain-ref", "0.1.0"),
    )
    conn.commit()
    conn.close()

    # 2. Mock lookup response
    contact_pubkey = b"\x02" * 32
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "public_key": contact_pubkey.hex(),
        "x25519_public_key": "x25519-bob-pub",
        "endpoint": "https://bob.kin.dev",
    }

    # Expected fingerprint
    expected_fp = compute_fingerprint(our_pubkey, contact_pubkey)

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.get", return_value=mock_response) as mock_get,
    ):
        # Input 'y' to confirm the fingerprint
        result = runner.invoke(app, ["--profile", "test-p", "pair", contact_name], input="y\n")
        
        assert result.exit_code == 0
        assert f"Contact '{contact_name}' found!" in result.stdout
        assert contact_pubkey.hex() in result.stdout
        assert "https://bob.kin.dev" in result.stdout
        assert f"Computed Fingerprint: {expected_fp}" in result.stdout
        assert f"Success! Contact '{contact_name}' added and marked verified." in result.stdout
        mock_get.assert_called_once_with(f"http://localhost:8000/directory/lookup/{contact_name}")

        # Verify saved in local sqlite
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at FROM contacts")
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
        assert row[0] == "bob"
        assert row[1] == "bob"
        assert row[2] == contact_pubkey.hex()
        assert row[3] == "x25519-bob-pub"
        assert row[4] == "https://bob.kin.dev"
        assert row[5] == "always_ask"
        assert row[6] is not None  # Timestamp


def test_pair_lookup_aborted(runner, temp_profile_dir) -> None:
    """Test that lookup cancels and does not save contact if user declines confirmation."""
    contact_name = "bob"
    
    # 1. Pre-initialize identity in local database
    db_path = temp_profile_dir / "kin.db"
    temp_profile_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS identity (username TEXT, public_key TEXT, keychain_ref TEXT, protocol_version TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS contacts (username TEXT PRIMARY KEY, display_name TEXT, public_key TEXT, x25519_public_key TEXT, endpoint TEXT, autonomy_level TEXT, fingerprint_verified_at TEXT)"
    )
    our_pubkey = b"\x01" * 32
    conn.execute(
        "INSERT INTO identity VALUES (?, ?, ?, ?)",
        ("alice", our_pubkey.hex(), "keychain-ref", "0.1.0"),
    )
    conn.commit()
    conn.close()

    # 2. Mock lookup response
    contact_pubkey = b"\x02" * 32
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "public_key": contact_pubkey.hex(),
        "x25519_public_key": "x25519-bob-pub",
        "endpoint": "https://bob.kin.dev",
    }

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.get", return_value=mock_response) as mock_get,
    ):
        # Input 'n' to decline confirmation
        result = runner.invoke(app, ["--profile", "test-p", "pair", contact_name], input="n\n")
        
        assert result.exit_code == 0
        assert "Pairing aborted for safety." in result.stdout
        
        # Verify contacts table remains empty
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM contacts")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 0


def test_pair_lookup_no_local_identity(runner, temp_profile_dir) -> None:
    """Test lookup fails cleanly if there is no local identity initialized."""
    contact_name = "bob"
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "public_key": "pubkey-123",
        "x25519_public_key": "x25519-bob-pub",
        "endpoint": "https://bob.kin.dev",
    }

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.get", return_value=mock_response) as mock_get,
    ):
        result = runner.invoke(app, ["--profile", "test-p", "pair", contact_name])
        
        assert result.exit_code == 1
        assert "Error: You must initialize your identity (run 'kin pair' without arguments) before pairing with other contacts." in result.stderr
        
        # Verify no contacts saved
        db_path = temp_profile_dir / "kin.db"
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM contacts")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 0


def test_pair_lookup_nonexistent_contact(runner, temp_profile_dir) -> None:
    """Test lookup of a nonexistent contact returns clean error message (no traceback)."""
    contact_name = "unknown"
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"detail": "Username not found"}

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.get", return_value=mock_response) as mock_get,
    ):
        result = runner.invoke(app, ["--profile", "test-p", "pair", contact_name])
        
        assert result.exit_code == 1
        assert f"Contact '{contact_name}' not found in the relay directory." in result.stderr
        assert "Traceback" not in result.stderr
        mock_get.assert_called_once()


def test_pair_lookup_network_error(runner, temp_profile_dir) -> None:
    """Test that a network connection error is surfaced cleanly (no traceback)."""
    contact_name = "bob"
    
    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.get", side_effect=httpx.RequestError("Connection refused")) as mock_get,
    ):
        result = runner.invoke(app, ["--profile", "test-p", "pair", contact_name])
        
        assert result.exit_code == 1
        assert "Error connecting to relay: Connection refused" in result.stderr
        assert "Traceback" not in result.stderr
        mock_get.assert_called_once()


def test_pair_lookup_server_error(runner, temp_profile_dir) -> None:
    """Test that a 500 server error from the relay is handled cleanly (no traceback)."""
    contact_name = "bob"
    mock_response = MagicMock()
    mock_response.status_code = 500
    
    mock_request = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error", request=mock_request, response=mock_response
    )

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.get", return_value=mock_response) as mock_get,
    ):
        result = runner.invoke(app, ["--profile", "test-p", "pair", contact_name])
        
        assert result.exit_code == 1
        assert "Error connecting to relay: Internal Server Error" in result.stderr
        assert "Traceback" not in result.stderr
        mock_get.assert_called_once()


def test_pair_lookup_already_verified(runner, temp_profile_dir) -> None:
    """Test that lookup short-circuits and does not touch network if contact is already verified."""
    contact_name = "bob"
    
    # Pre-initialize identity and verified contact in local database
    db_path = temp_profile_dir / "kin.db"
    temp_profile_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS identity (username TEXT, public_key TEXT, keychain_ref TEXT, protocol_version TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS contacts (username TEXT PRIMARY KEY, display_name TEXT, public_key TEXT, x25519_public_key TEXT, endpoint TEXT, autonomy_level TEXT, fingerprint_verified_at TEXT)"
    )
    conn.execute(
        "INSERT INTO identity VALUES (?, ?, ?, ?)",
        ("alice", "pubkey-alice", "keychain-ref", "0.1.0"),
    )
    conn.execute(
        "INSERT INTO contacts VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("bob", "bob", "pubkey-bob", "x25519-bob", "https://bob.kin.dev", "always_ask", "2026-07-17T12:00:00Z"),
    )
    conn.commit()
    conn.close()

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("httpx.get") as mock_get,
    ):
        result = runner.invoke(app, ["--profile", "test-p", "pair", contact_name])
        
        assert result.exit_code == 0
        assert f"Already verified as a trusted contact: '{contact_name}' — no action needed." in result.stdout
        mock_get.assert_not_called()


def test_pair_setup_success(runner, temp_profile_dir) -> None:
    """Test successful first-run setup flow when no identity exists."""
    # Generate a real, valid recovery phrase to satisfy BIP39 checksum validation
    dummy_phrase = generate_recovery_phrase()
    words = dummy_phrase.split()
    word_3 = words[2]
    word_7 = words[6]
    
    # Mock lookup availability (404 = available) and register (200 = registered)
    mock_get_res = MagicMock()
    mock_get_res.status_code = 404
    mock_get_res.json.return_value = {"detail": "Username not found"}

    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"status": "registered"}

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("kin.identity.setup.generate_recovery_phrase", return_value=dummy_phrase),
        patch("random.sample", return_value=[2, 6]),  # word #3 and word #7
        patch("httpx.get", return_value=mock_get_res) as mock_get,
        patch("httpx.post", return_value=mock_post_res) as mock_post,
    ):
        # Interactive inputs: username selection first, then word confirmations
        inputs = f"alice\n{word_3}\n{word_7}\n"
        result = runner.invoke(app, ["--profile", "test-p", "pair"], input=inputs)

        # Check stdout and return code
        assert result.exit_code == 0
        assert "Choose your desired username:" in result.stdout
        assert "Welcome to KIN! No identity was found for this profile" in result.stdout
        assert "Success! Identity initialized and registered as 'alice'" in result.stdout

        # Verify availability check and registration calls were sent
        mock_get.assert_called_once_with("http://localhost:8000/directory/lookup/alice")
        mock_post.assert_called_once()
        call_url, call_kwargs = mock_post.call_args
        assert call_url[0] == "http://localhost:8000/directory/register"
        payload = call_kwargs["json"]
        assert payload["username"] == "alice"
        assert len(payload["public_key"]) == 64  # Hex encoded Ed25519 public key
        assert len(payload["x25519_public_key"]) == 64  # Hex encoded X25519 public key

        # Verify identity is committed locally in SQLite
        db_path = temp_profile_dir / "kin.db"
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT username, public_key FROM identity")
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
        assert row[0] == "alice"
        assert row[1] == payload["public_key"]


def test_pair_setup_username_taken(runner, temp_profile_dir) -> None:
    """Test that setup fails immediately if the chosen username is already taken.

    Verifies no recovery phrase is generated or shown, and no key pair is created/saved.
    """
    # Mock lookup returning 200 (taken)
    mock_get_res = MagicMock()
    mock_get_res.status_code = 200
    mock_get_res.json.return_value = {
        "public_key": "pubkey-some-other-alice",
        "x25519_public_key": "x25519-some-other-alice",
        "endpoint": "https://other-alice.kin.dev",
    }

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("kin.identity.setup.generate_recovery_phrase") as mock_generate_phrase,
        patch("httpx.get", return_value=mock_get_res) as mock_get,
    ):
        inputs = "alice\n"
        result = runner.invoke(app, ["--profile", "test-p", "pair"], input=inputs)

        # Check return code and stdout
        assert result.exit_code == 1
        assert "Choose your desired username:" in result.stdout
        assert "Error: Username 'alice' is already taken. Please try another username." in result.stderr
        
        # Verify key setup and phrase generation were never triggered
        mock_generate_phrase.assert_not_called()

        # Verify database has no identity row
        db_path = temp_profile_dir / "kin.db"
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='identity'")
        assert cursor.fetchone() is not None  # Schema is created
        cursor.execute("SELECT COUNT(*) FROM identity")
        assert cursor.fetchone()[0] == 0
        conn.close()


def test_pair_setup_already_initialized(runner, temp_profile_dir) -> None:
    """Test that setup is skipped if identity already exists in database."""
    # Pre-initialize database with an identity
    db_path = temp_profile_dir / "kin.db"
    temp_profile_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS identity (username TEXT, public_key TEXT, keychain_ref TEXT, protocol_version TEXT)"
    )
    conn.execute(
        "INSERT INTO identity VALUES (?, ?, ?, ?)",
        ("existing-user", "pubkey-123", "keychain-ref", "0.1.0"),
    )
    conn.commit()
    conn.close()

    with patch("kin.cli.get_profile_dir", return_value=temp_profile_dir):
        result = runner.invoke(app, ["--profile", "test-p", "pair"])
        
        assert result.exit_code == 0
        assert "Identity already initialized for username: 'existing-user'" in result.stdout
