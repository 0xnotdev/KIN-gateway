"""Database storage logic for kin-relay using raw sqlite3."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database and return the connection.

    Enables foreign keys and disables the single-thread restriction.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create directory_entries and mailbox tables matching spec section 3."""
    conn.executescript(
        """\
        CREATE TABLE IF NOT EXISTS directory_entries (
            username      TEXT PRIMARY KEY,
            public_key    TEXT NOT NULL,
            x25519_public_key TEXT NOT NULL,
            endpoint      TEXT NOT NULL,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mailbox (
            message_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            username       TEXT NOT NULL REFERENCES directory_entries(username),
            sender_username TEXT NOT NULL,
            encrypted_blob TEXT NOT NULL,
            received_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at     TIMESTAMP NOT NULL
        );
        """
    )
