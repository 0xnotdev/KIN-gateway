"""SQLite connection and schema creation matching system-design-v1.md section 3."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) a SQLite database at *db_path* and return the connection."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection, *, allow_legacy_migration: bool = False) -> None:
    """Create the local data-model tables by running ordered schema migrations."""
    from kin.storage.migrations import (
        run_migrations,
        is_legacy_unmigrated_profile,
        LegacyProfileMigrationRequired,
    )
    if not allow_legacy_migration and is_legacy_unmigrated_profile(conn):
        raise LegacyProfileMigrationRequired(
            "This profile predates KIN's schema migration system. "
            "Run `kin migrate` before using this profile again."
        )
    report = run_migrations(conn)
    if report.errors:
        raise RuntimeError(f"Schema migration failed: {'; '.join(report.errors)}")


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
