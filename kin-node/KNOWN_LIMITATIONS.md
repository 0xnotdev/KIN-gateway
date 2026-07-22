# KIN V1.1 Known Architectural Limitations

This document tracks known design and implementation limitations in current M0/M1 local storage, schema validation, audit, export, and session reducer code prior to Milestone M2 (relay/transport integration).

---

## 1. Outbound Delivery State Representation
- **Current Behavior**: Outbound delivery state is currently represented exclusively via `sessions.status` (`queued`, `sent`, `delivered` are status values within the session state transition matrix).
- **Limitation**: No separate dedicated `delivery_state` column or indexed table exists yet on local session records.
- **Resolution Plan**: Deferred to **Milestone M3** when the live network transport layer and peer delivery queues are built.

---

## 2. In-Memory Session State vs. Event-Sourced Storage
- **Current Behavior**: `SessionState` objects are held in memory during processing and persisted to SQLite via `session_events` rows and session metadata updates.
- **Limitation**: Session state reconstruction reads from SQLite without an in-memory real-time event streaming bus or external message broker.
- **Resolution Plan**: Local SQLite queries provide complete deterministic event order reconstruction suitable for V1.1 local node operations.

---

## 3. Keychain Vault Backend Availability in Headless / CI Environments
- **Current Behavior**: `get_or_create_vault_key` checks `_assert_secure_backend()` to enforce OS-level secure credential storage (macOS Keychain, Windows Credential Manager, Linux Secret Service).
- **Limitation**: Headless CI environments or automated test runners without a running D-Bus/Secret Service daemon fail unless `KIN_UNSAFE_TEST_KEYRING=1` or an explicit test keyring backend is enabled.
- **Resolution Plan**: `KIN_UNSAFE_TEST_KEYRING` is used in isolated test harnesses. Production server nodes will configure headless vault secrets via environment or key service wrappers.

---

## 4. Local Audit Event Storage Triggers
- **Current Behavior**: SQLite triggers prevent `UPDATE` and `DELETE` on `audit_events` rows.
- **Limitation**: Tamper-resistance is enforced at the SQLite database engine layer for local nodes. If an attacker gains root access to the raw `.db` file on disk, raw file mutation is prevented by OS permissions and checksum drift detection, but not by a remote append-only ledger.
- **Resolution Plan**: Remote peer cryptographic signatures and export JCS hashes verify transcript integrity across node boundaries.

---

## 5. SessionEvent.kind Closed-Set Validation
- **Current Behavior**: `SessionEvent.kind` is validated against a closed set comprising all `MessageKind` enum values and recognized internal event kinds (`InternalEventKind`: `message`, `envelope_received`, `public_msg`, `private_note`, `outbound_envelope_queued`). Unrecognized arbitrary strings (e.g. `hacked_kind`) are strictly rejected with `ValidationError`.
- **Limitation**: Any future internal event kind added to local node workflows must be explicitly registered in `InternalEventKind` or `MessageKind`.
- **Resolution Plan**: `MessageKind` and `InternalEventKind` form a strict, closed contract preventing arbitrary unvalidated event injection into session audit storage.

---

## 6. SessionEvent Schema & Protocol Versioning Layer
- **Current Behavior**: `SessionEvent` Pydantic model enforces `schema_version: Literal["1.1"] = "1.1"` and `protocol_version: Literal["1.1"] = "1.1"` at the Python validation layer before database insertion.
- **Limitation**: `session_events` SQLite table does not contain dedicated `schema_version` or `protocol_version` columns; versioning is implicitly anchored at the table level by Migration 0002 (`v11_session_records`).
- **Resolution Plan**: Validation-layer enforcement guarantees contract compliance on all constructed `SessionEvent` objects without duplicating static constant columns in the SQLite database rows.
