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

---

## Milestone M3

### 7. Outbound Delivery & Retry Queue Backoff Constants
- **Behavior**: Pending outbound session envelopes are queued in `outbound_envelope_queue` and retried via `retry_outbound_queue()` using exponential backoff formula: `min(3600, 10 * (2 ** (attempt_count - 1)))`.
- **Constants**: The retry sequence evaluates to 10s, 20s, 40s, 80s, ..., capped at a maximum 3600s (1 hour) interval. Moot items belonging to sessions in terminal states (`completed`, `failed`, `cancelled`, `expired`, `declined`) are automatically marked `'abandoned'` during queue sweeps.

### 8. Relay Blind-Forwarding & Plaintext Confidentiality
- **Behavior**: The encrypted relay mailbox (`kin-relay`) receives, stores, and forwards opaque X25519 ciphertext payloads.
- **Guarantees**: The relay server never sees plaintext session objectives, collaboration modes, proposals, or unencrypted payload JSON. Inspection unit tests (`test_relay_mailbox_never_sees_plaintext`) verify that raw relay mailbox stores contain only opaque ciphertext bytes and routing metadata (`sender_username`, `recipient_username`).

### 9. Peer Capability Negotiation & Fallback Behavior
- **Behavior**: Direct session dispatch (`dispatch_session`) fetches live peer capability advertisements via `GET /v1.1/capabilities`.
- **Fallback**: If the peer's direct endpoint is unreachable but a cached `CapabilityAdvertisement` exists in `peer_capabilities` table with age <= 72 hours, dispatch falls back to the cached advertisement and routes via encrypted relay mailbox. If no cached advertisement exists or if the cache is older than 72 hours, dispatch refuses outright (`CapabilityMismatchError`).

### 10. Defects Found & Fixed During Close-Out Review
During the formal Milestone M3 close-out review, three live runtime defects were identified and resolved prior to milestone sign-off:
1. **Missing `ed25519` Import in `kin/node/routes.py`**: `ed25519` was referenced in `get_contact_pubkey` closures inside `get_published_agent_cards` and `process_v11_session_envelope` but missing at module level. Added `from cryptography.hazmat.primitives.asymmetric import ed25519`.
2. **`list_cards()` Missing `include_disabled` & Published Card Data**: `list_cards()` lacked filtering on `enabled` and did not return `published_card_json`. Added `include_disabled: bool = False` parameter (preserving default behavior for existing CLI callers) and added `published_card_json` and parsed `published_card` dict to returned items. Updated `get_published_agent_cards` in `routes.py` to correctly extract published card projections.
3. **Standing Fastapi `TestClient` Coverage Requirement**: Added mandatory project rule in `README.md` requiring every route under `kin/node/routes.py` to be exercised via a real `fastapi.testclient.TestClient` call. Added real `TestClient` route tests for `POST /v1.1/sessions` and `GET /v1.1/agents/cards`, catching all route-level import and contract defects.
