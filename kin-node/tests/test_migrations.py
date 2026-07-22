"""Tests for kin.storage.migrations and kin migrate CLI command."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from typer.testing import CliRunner

from kin.storage.db import get_connection, create_schema
from kin.storage.migrations import (
    run_migrations,
    ALL_MIGRATIONS,
)
from kin.identity.storage import InsecureBackendError
from kin.cli import app

runner = CliRunner()


def test_fresh_profile(tmp_path: Path) -> None:
    """Assert running migrations on a fresh empty DB reaches latest schema version."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    report = run_migrations(conn)

    assert not report.errors
    assert report.applied == [1, 2]
    assert report.starting_version == 0
    assert report.ending_version == 2
    assert set(report.applied).isdisjoint(set(report.skipped))

    # Check schema_migrations table
    cur = conn.cursor()
    cur.execute("SELECT version, name FROM schema_migrations ORDER BY version ASC")
    rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0] == (1, "v1_baseline")
    assert rows[1] == (2, "v11_session_records")
    conn.close()


def test_legacy_v1_profile(tmp_path: Path) -> None:
    """Assert legacy V1 profile without schema_migrations is cleanly backfilled and upgraded."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)

    # Manually create legacy V1 tables without schema_migrations
    conn.execute("CREATE TABLE identity (username TEXT, public_key TEXT, keychain_ref TEXT, protocol_version TEXT)")
    conn.execute("CREATE TABLE contacts (username TEXT PRIMARY KEY, display_name TEXT, public_key TEXT, x25519_public_key TEXT, endpoint TEXT, autonomy_level TEXT, fingerprint_verified_at TIMESTAMP)")
    conn.execute(
        """\
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY, contact_username TEXT, goal TEXT, context_json TEXT,
            status TEXT, created_at TIMESTAMP, updated_at TIMESTAMP, result_json TEXT,
            draft_content TEXT, draft_message_type TEXT
        )
        """
    )
    conn.execute("CREATE TABLE messages (message_id TEXT PRIMARY KEY, task_id TEXT, from_username TEXT, content TEXT, message_type TEXT, created_at TIMESTAMP, signature TEXT)")
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("CREATE TABLE processed_relay_messages (message_id INTEGER PRIMARY KEY, processed_at TIMESTAMP NOT NULL)")

    # Insert legacy data
    conn.execute("INSERT INTO identity VALUES ('legacy_alice', 'pubkey123', 'ref123', '0.1.0')")
    conn.execute("INSERT INTO contacts VALUES ('bob', 'Bob', 'bobpub', 'bobx25519', 'http://bob', 'always_ask', '2026-07-01T00:00:00Z')")
    conn.execute("INSERT INTO tasks (task_id, contact_username, goal, status) VALUES ('task-1', 'bob', 'Legacy task', 'completed')")
    conn.commit()

    report = run_migrations(conn)
    assert not report.errors
    assert 1 in report.applied
    assert 2 in report.applied
    assert set(report.applied).isdisjoint(set(report.skipped))

    # Assert legacy data remains byte-for-byte unchanged in content
    cur = conn.cursor()
    cur.execute("SELECT username, public_key FROM identity")
    assert cur.fetchone() == ("legacy_alice", "pubkey123")

    cur.execute("SELECT username, display_name FROM contacts")
    assert cur.fetchone() == ("bob", "Bob")

    cur.execute("SELECT task_id, goal, agent_name FROM tasks")
    assert cur.fetchone() == ("task-1", "Legacy task", None)

    conn.close()


def test_idempotency(tmp_path: Path) -> None:
    """Assert running migrations twice sequentially is a clean no-op and applied/skipped never overlap."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)

    report1 = run_migrations(conn)
    assert report1.applied == [1, 2]
    assert report1.skipped == []
    assert set(report1.applied).isdisjoint(set(report1.skipped))

    report2 = run_migrations(conn)
    assert not report2.errors
    assert report2.applied == []
    assert report2.skipped == [1, 2]
    assert report2.starting_version == 2
    assert report2.ending_version == 2
    assert set(report2.applied).isdisjoint(set(report2.skipped))

    conn.close()


def test_checksum_drift(tmp_path: Path) -> None:
    """Assert drift in recorded checksum causes fail-closed error."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    run_migrations(conn)

    # Tamper with recorded checksum of migration 1 in DB
    conn.execute("UPDATE schema_migrations SET checksum = 'tampered_bad_checksum' WHERE version = 1")
    conn.commit()

    report = run_migrations(conn)
    assert report.errors
    assert "Checksum drift detected" in report.errors[0]

    conn.close()


def test_unsupported_prior_schema(tmp_path: Path) -> None:
    """Assert legacy profile with unrecognized extra tables fails closed."""
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)

    conn.execute("CREATE TABLE identity (username TEXT, public_key TEXT)")
    conn.execute("CREATE TABLE unrecognized_custom_table (col1 TEXT)")
    conn.commit()

    report = run_migrations(conn)
    assert report.errors
    assert "Unsupported prior schema" in report.errors[0]

    conn.close()


def test_interrupted_migration(tmp_path: Path, monkeypatch) -> None:
    """Assert failure during atomic swap leaves original DB byte-for-byte untouched."""
    monkeypatch.setenv("KIN_UNSAFE_TEST_KEYRING", "1")
    profile_dir = tmp_path / ".kin" / "profiles" / "testprofile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "kin.db"

    conn = get_connection(db_path)
    conn.execute("CREATE TABLE identity (username TEXT, public_key TEXT, keychain_ref TEXT, protocol_version TEXT)")
    conn.execute("INSERT INTO identity VALUES ('alice', 'pubkey', 'ref', '0.1.0')")
    conn.commit()
    conn.close()

    original_bytes = db_path.read_bytes()

    def mock_replace(src, dst):
        raise OSError("Simulated disk replacement failure")

    monkeypatch.setattr("os.replace", mock_replace)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    result = runner.invoke(app, ["--profile", "testprofile", "migrate"])
    assert result.exit_code != 0

    # Verify original DB file is byte-for-byte unchanged
    assert db_path.read_bytes() == original_bytes

    # Verify failure report was generated outside profile
    reports = list((tmp_path / ".kin" / "migration-reports").glob("testprofile-*.json"))
    assert len(reports) == 1
    report_data = json.loads(reports[0].read_text())
    assert report_data["status"] == "failed"
    assert "Simulated disk replacement failure" in report_data["error"]


def test_missing_keychain(tmp_path: Path, monkeypatch) -> None:
    """Assert vault key retrieval failure causes kin migrate abort leaving original untouched."""
    profile_dir = tmp_path / ".kin" / "profiles" / "keyprofile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "kin.db"

    conn = get_connection(db_path)
    conn.execute("CREATE TABLE identity (username TEXT, public_key TEXT, keychain_ref TEXT, protocol_version TEXT)")
    conn.execute("INSERT INTO identity VALUES ('alice', 'pubkey', 'ref', '0.1.0')")
    conn.commit()
    conn.close()

    original_bytes = db_path.read_bytes()

    def mock_assert_secure():
        raise InsecureBackendError("Insecure keyring backend simulation")

    monkeypatch.setattr("kin.identity.storage._assert_secure_backend", mock_assert_secure)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    result = runner.invoke(app, ["--profile", "keyprofile", "migrate"])
    assert result.exit_code != 0
    assert db_path.read_bytes() == original_bytes

    reports = list((tmp_path / ".kin" / "migration-reports").glob("keyprofile-*.json"))
    assert len(reports) == 1
    report_data = json.loads(reports[0].read_text())
    assert report_data["status"] == "failed"
    assert "Insecure keyring backend simulation" in report_data["error"]


def test_disk_write_failure_during_staging(tmp_path: Path, monkeypatch) -> None:
    """Assert copytree failure during staging aborts cleanly leaving original untouched."""
    monkeypatch.setenv("KIN_UNSAFE_TEST_KEYRING", "1")
    profile_dir = tmp_path / ".kin" / "profiles" / "failcopy"
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "kin.db"

    conn = get_connection(db_path)
    create_schema(conn)
    conn.close()

    original_bytes = db_path.read_bytes()

    def mock_copytree(src, dst):
        raise IOError("Simulated disk copy failure during staging")

    monkeypatch.setattr("shutil.copytree", mock_copytree)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    result = runner.invoke(app, ["--profile", "failcopy", "migrate"])
    assert result.exit_code != 0
    assert db_path.read_bytes() == original_bytes


def test_migrate_profile_isolation(tmp_path: Path, monkeypatch) -> None:
    """Assert running kin migrate on Alice's profile leaves Bob's profile DB byte-for-byte unchanged."""
    monkeypatch.setenv("KIN_UNSAFE_TEST_KEYRING", "1")
    kin_home = tmp_path / ".kin"
    alice_dir = kin_home / "profiles" / "alice"
    bob_dir = kin_home / "profiles" / "bob"
    alice_dir.mkdir(parents=True, exist_ok=True)
    bob_dir.mkdir(parents=True, exist_ok=True)

    # Initialize Alice's DB as a legacy V1 profile
    alice_db = alice_dir / "kin.db"
    conn_a = get_connection(alice_db)
    conn_a.execute("CREATE TABLE identity (username TEXT, public_key TEXT, keychain_ref TEXT, protocol_version TEXT)")
    conn_a.execute("INSERT INTO identity VALUES ('alice', 'pubkeyA', 'refA', '0.1.0')")
    conn_a.commit()
    conn_a.close()

    # Initialize Bob's DB
    bob_db = bob_dir / "kin.db"
    conn_b = get_connection(bob_db)
    create_schema(conn_b)
    conn_b.execute(
        """\
        INSERT INTO sessions (
            session_id, type, owner_username, peer_username, status, turn_limit, created_at, updated_at
        ) VALUES ('bob-sess-1', 'collaborative', 'bob', 'charlie', 'active', 12, '2026-07-22T12:00:00Z', '2026-07-22T12:00:00Z')
        """
    )
    conn_b.commit()
    conn_b.close()

    bob_bytes_before = bob_db.read_bytes()

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    # Run kin migrate ONLY on Alice
    result = runner.invoke(app, ["--profile", "alice", "migrate"])
    assert result.exit_code == 0

    # Assert Bob's DB file is byte-for-byte unchanged
    bob_bytes_after = bob_db.read_bytes()
    assert bob_bytes_before == bob_bytes_after


def test_ordinary_command_refuses_legacy_profile(tmp_path: Path, monkeypatch) -> None:
    """Assert ordinary CLI commands refuse to execute on unmigrated legacy profiles without modifying DB."""
    monkeypatch.setenv("KIN_UNSAFE_TEST_KEYRING", "1")
    profile_dir = tmp_path / ".kin" / "profiles" / "legacypath"
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "kin.db"

    conn = get_connection(db_path)
    conn.execute("CREATE TABLE identity (username TEXT, public_key TEXT, keychain_ref TEXT, protocol_version TEXT)")
    conn.execute("CREATE TABLE contacts (username TEXT PRIMARY KEY, display_name TEXT, public_key TEXT, x25519_public_key TEXT, endpoint TEXT, autonomy_level TEXT, fingerprint_verified_at TIMESTAMP)")
    conn.execute("INSERT INTO identity VALUES ('alice', 'pubkey', 'ref', '0.1.0')")
    conn.commit()
    conn.close()

    original_bytes = db_path.read_bytes()

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    # Invoke ordinary CLI command 'kin tasks' against legacy profile
    result = runner.invoke(app, ["--profile", "legacypath", "tasks"])
    assert result.exit_code != 0
    assert "kin migrate" in result.output or "kin migrate" in str(result.stderr)
    assert db_path.read_bytes() == original_bytes

    # Now run kin migrate explicitly
    migrate_result = runner.invoke(app, ["--profile", "legacypath", "migrate"])
    assert migrate_result.exit_code == 0

    # Now ordinary CLI command works normally
    normal_result = runner.invoke(app, ["--profile", "legacypath", "tasks"])
    assert normal_result.exit_code == 0
