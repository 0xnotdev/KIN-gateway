"""Ordered SQLite migration runner with drift detection and legacy V1 backfill."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import hashlib
import sqlite3
from typing import Callable


class LegacyProfileMigrationRequired(Exception):
    """Raised when an operation requires a database schema migration on a legacy profile."""
    pass


@dataclass
class Migration:
    version: int
    name: str
    up_sql: str
    up_fn: Callable[[sqlite3.Connection], None] | None = None

    @property
    def checksum(self) -> str:
        content = self.up_sql.strip()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class MigrationReport:
    applied: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    starting_version: int = 0
    ending_version: int = 0
    errors: list[str] = field(default_factory=list)


MIGRATION_0001_SQL = """\
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

MIGRATION_0002_SQL = """\
CREATE TABLE IF NOT EXISTS agents (
    agent_id             TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    adapter_type         TEXT NOT NULL,
    local_card_json      TEXT,
    published_card_json  TEXT,
    enabled              INTEGER NOT NULL DEFAULT 1,
    availability         TEXT NOT NULL DEFAULT 'ready',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id                 TEXT PRIMARY KEY,
    type                       TEXT NOT NULL,
    owner_username             TEXT NOT NULL,
    peer_username              TEXT NOT NULL,
    status                     TEXT NOT NULL,
    objective                  TEXT,
    sender_agent_id            TEXT,
    receiver_agent_id          TEXT,
    participant_snapshot_json  TEXT,
    turn_limit                 INTEGER NOT NULL DEFAULT 12,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL,
    terminal_result_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_status_updated ON sessions(status, updated_at);

CREATE TABLE IF NOT EXISTS session_events (
    event_id       TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL REFERENCES sessions(session_id),
    event_order    INTEGER NOT NULL,
    sequence       INTEGER,
    actor_username TEXT NOT NULL,
    actor_agent_id TEXT,
    kind           TEXT NOT NULL,
    visibility     TEXT NOT NULL DEFAULT 'peer_visible',
    payload_json   TEXT,
    signature      TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE(session_id, event_order)
);
CREATE INDEX IF NOT EXISTS idx_session_events_session_order ON session_events(session_id, event_order);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id     TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id),
    sha256          TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    bytes_encrypted BLOB,
    metadata_json   TEXT,
    offered_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON artifacts(sha256);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id   TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id),
    agent_id      TEXT,
    action_class  TEXT NOT NULL,
    request_json  TEXT,
    decision      TEXT,
    decided_at    TEXT,
    expires_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_expires_at ON approvals(expires_at);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id        TEXT PRIMARY KEY,
    correlation_id  TEXT NOT NULL,
    session_id      TEXT,
    category        TEXT NOT NULL,
    actor_username  TEXT,
    summary         TEXT NOT NULL,
    payload_json    TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_session ON audit_events(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at);

CREATE TRIGGER IF NOT EXISTS trg_session_events_no_update
BEFORE UPDATE ON session_events
BEGIN SELECT RAISE(ABORT, 'session_events is append-only: UPDATE is forbidden'); END;

CREATE TRIGGER IF NOT EXISTS trg_session_events_no_delete
BEFORE DELETE ON session_events
BEGIN SELECT RAISE(ABORT, 'session_events is append-only: DELETE is forbidden'); END;

CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only: UPDATE is forbidden'); END;

CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only: DELETE is forbidden'); END;
"""

MIGRATION_0003_SQL = """\
ALTER TABLE agents ADD COLUMN card_version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS peer_agent_cards (
    peer_username   TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    card_json       TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'fresh',
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    PRIMARY KEY (peer_username, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_peer_agent_cards_status ON peer_agent_cards(status);
"""

MIGRATION_0004_SQL = """\
CREATE TABLE IF NOT EXISTS outbound_envelope_queue (
    queue_id            TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(session_id),
    sequence            INTEGER NOT NULL,
    recipient_username  TEXT NOT NULL,
    envelope_kind       TEXT NOT NULL,
    envelope_json_enc   TEXT NOT NULL,
    delivery_state      TEXT NOT NULL DEFAULT 'pending',
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    next_retry_at       TEXT NOT NULL,
    last_error          TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE(session_id, sequence, recipient_username)
);
CREATE INDEX IF NOT EXISTS idx_outbound_queue_pending ON outbound_envelope_queue(delivery_state, next_retry_at);

ALTER TABLE sessions ADD COLUMN expires_at TEXT;
"""

MIGRATION_0005_SQL = """\
ALTER TABLE sessions RENAME COLUMN owner_username TO initiator_username;
ALTER TABLE sessions RENAME COLUMN peer_username TO receiver_username;

CREATE TABLE IF NOT EXISTS peer_capabilities (
    peer_username       TEXT PRIMARY KEY,
    capability_json     TEXT NOT NULL,
    fetched_at          TEXT NOT NULL
);
"""

MIGRATION_0006_SQL = """\
ALTER TABLE approvals ADD COLUMN consumed_at TEXT;
"""


def _up_0001(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_0001_SQL)


def _up_0002(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_0002_SQL)


def _up_0003(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_0003_SQL)


def _up_0004(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_0004_SQL)


def _up_0005(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_0005_SQL)


def _up_0006(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_0006_SQL)


ALL_MIGRATIONS: list[Migration] = [
    Migration(version=1, name="v1_baseline", up_sql=MIGRATION_0001_SQL, up_fn=_up_0001),
    Migration(version=2, name="v11_session_records", up_sql=MIGRATION_0002_SQL, up_fn=_up_0002),
    Migration(version=3, name="v11_agent_registry_extensions", up_sql=MIGRATION_0003_SQL, up_fn=_up_0003),
    Migration(version=4, name="v11_transport_and_queue", up_sql=MIGRATION_0004_SQL, up_fn=_up_0004),
    Migration(version=5, name="v11_session_column_renames", up_sql=MIGRATION_0005_SQL, up_fn=_up_0005),
    Migration(version=6, name="v11_approval_consumed_at", up_sql=MIGRATION_0006_SQL, up_fn=_up_0006),
]




def is_legacy_unmigrated_profile(conn: sqlite3.Connection) -> bool:
    """Return True if schema_migrations does not exist but V1 legacy tables exist."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
    if cur.fetchone() is not None:
        return False

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('identity', 'contacts', 'tasks', 'messages', 'settings')")
    tables = {row[0] for row in cur.fetchall()}
    return bool(tables)


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """\
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum   TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _introspect_tables(conn: sqlite3.Connection) -> dict[str, list[str]]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall() if not row[0].startswith("sqlite_")]
    res = {}
    for tbl in tables:
        cur.execute(f"PRAGMA table_info('{tbl}')")
        res[tbl] = [row[1] for row in cur.fetchall()]
    return res


def _validate_and_backfill_legacy_v1(conn: sqlite3.Connection, m1: Migration) -> str | None:
    """Validate legacy V1 profile and retroactively backfill migration 0001.

    Returns None on success, or an error string on invalid/unsupported prior schema.
    """
    tables = _introspect_tables(conn)
    allowed_v1_tables = {
        "schema_migrations", "identity", "contacts", "tasks",
        "messages", "settings", "processed_relay_messages"
    }

    # Check for unrecognized extra tables
    extra_tables = set(tables.keys()) - allowed_v1_tables
    if extra_tables:
        return f"Unsupported prior schema: unrecognized tables present ({', '.join(sorted(extra_tables))})"

    # Required base columns per table if the table exists
    req_cols = {
        "identity": {"username", "public_key"},
        "contacts": {"username", "display_name", "public_key"},
        "tasks": {
            "task_id", "contact_username", "goal", "context_json", "status",
            "created_at", "updated_at", "result_json", "draft_content", "draft_message_type"
        },
        "messages": {"message_id", "task_id", "from_username", "content", "message_type", "created_at", "signature"},
        "settings": {"key", "value"},
        "processed_relay_messages": {"message_id", "processed_at"},
    }

    for tbl, required in req_cols.items():
        if tbl in tables:
            actual = set(tables[tbl])
            missing = required - actual
            if missing:
                return f"Unsupported prior schema: {tbl} table missing required columns ({', '.join(sorted(missing))})"

    # Check optional tasks columns if tasks table exists. If missing, ALTER TABLE to add them.
    if "tasks" in tables:
        actual_task_cols = set(tables["tasks"])
        optional_task_cols = ["agent_name", "peer_agent_name", "peer_task_id", "origin_ref_id"]
        for col in optional_task_cols:
            if col not in actual_task_cols:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT")

    # Re-run migration 0001 up_fn/SQL to ensure any missing base tables are created
    if m1.up_fn:
        m1.up_fn(conn)
    elif m1.up_sql:
        conn.executescript(m1.up_sql)

    # Record 0001 as backfilled
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
        (m1.version, m1.name, f"{now_str} (backfilled)", m1.checksum)
    )
    conn.commit()
    return None


def run_migrations(conn: sqlite3.Connection) -> MigrationReport:
    """Execute pending database migrations sequentially with drift detection and failure isolation."""
    report = MigrationReport()

    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
    has_migrations_table = cur.fetchone() is not None

    if not has_migrations_table:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('identity', 'contacts', 'tasks', 'messages', 'settings')")
        has_legacy_tables = bool(cur.fetchall())

        _ensure_migrations_table(conn)

        if has_legacy_tables:
            err = _validate_and_backfill_legacy_v1(conn, ALL_MIGRATIONS[0])
            if err:
                report.errors.append(err)
                return report
            report.applied.append(1)

    cur.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version ASC")
    applied_rows = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    if applied_rows:
        report.starting_version = max(applied_rows.keys())
    else:
        report.starting_version = 0

    # Drift Detection check on existing migrations
    for m in ALL_MIGRATIONS:
        if m.version in applied_rows:
            recorded_name, recorded_checksum = applied_rows[m.version]
            if recorded_checksum != m.checksum:
                report.errors.append(
                    f"Checksum drift detected for migration {m.version:04d}_{m.name}: "
                    f"stored={recorded_checksum[:12]}, expected={m.checksum[:12]}"
                )
                return report
            if m.version not in report.applied:
                report.skipped.append(m.version)

    # Apply pending migrations
    for m in ALL_MIGRATIONS:
        if m.version in applied_rows:
            continue

        try:
            conn.execute("BEGIN IMMEDIATE")
            if m.up_fn:
                m.up_fn(conn)
            elif m.up_sql:
                conn.executescript(m.up_sql)

            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (m.version, m.name, now_str, m.checksum)
            )
            conn.commit()
            report.applied.append(m.version)
        except Exception as e:
            conn.rollback()
            report.errors.append(f"Migration {m.version:04d}_{m.name} failed: {e}")
            break

    cur.execute("SELECT MAX(version) FROM schema_migrations")
    max_ver = cur.fetchone()[0]
    report.ending_version = max_ver if max_ver is not None else 0

    return report
