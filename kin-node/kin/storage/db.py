"""SQLite connection and schema creation matching system-design-v1.md section 3."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) a SQLite database at *db_path* and return the connection."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the local data-model tables exactly as specified in section 3.

    Tables: identity, contacts, tasks, messages.
    Field names and types match the spec precisely.
    """
    conn.executescript(
        """\
        CREATE TABLE IF NOT EXISTS identity (
            username            TEXT,
            public_key          TEXT,
            keychain_ref        TEXT,
            protocol_version    TEXT
        );

        CREATE TABLE IF NOT EXISTS contacts (
            username                TEXT PRIMARY KEY,
            display_name            TEXT,
            public_key              TEXT,
            x25519_public_key       TEXT,
            endpoint                TEXT,
            autonomy_level          TEXT,
            fingerprint_verified_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tasks (
            task_id             TEXT PRIMARY KEY,
            contact_username    TEXT REFERENCES contacts(username),
            goal                TEXT,
            context_json        TEXT,
            status              TEXT,
            created_at          TIMESTAMP,
            updated_at          TIMESTAMP,
            result_json         TEXT,
            draft_content       TEXT,
            draft_message_type  TEXT,
            agent_name          TEXT,
            peer_agent_name     TEXT,
            peer_task_id        TEXT,
            origin_ref_id       TEXT
        );

        CREATE TABLE IF NOT EXISTS messages (
            message_id          TEXT PRIMARY KEY,
            task_id             TEXT REFERENCES tasks(task_id),
            from_username       TEXT,
            content             TEXT,
            message_type        TEXT,
            created_at          TIMESTAMP,
            signature           TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key                 TEXT PRIMARY KEY,
            value               TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS processed_relay_messages (
            message_id          INTEGER PRIMARY KEY,
            processed_at        TIMESTAMP NOT NULL
        );
        """
    )

    # Dynamic schema migration: add agent_name column to tasks table if it doesn't exist
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    if columns and "agent_name" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN agent_name TEXT")
        conn.commit()
    if columns and "peer_agent_name" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN peer_agent_name TEXT")
        conn.commit()
    if columns and "peer_task_id" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN peer_task_id TEXT")
        conn.commit()
    if columns and "origin_ref_id" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN origin_ref_id TEXT")
        conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    """Return a profile-local setting without exposing storage details to callers."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row is not None else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Create or replace a profile-local setting."""
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
