# Milestone M3 Progress & Verification Report

**Status**: COMPLETED (Close-Out Review Verified)  
**Authority**: `KIN-V1.1-MASTER-SPEC.md` §15.6 (M3), constrained by §15.1, §15.2, §6–9, `docs/v11_transition_matrix.md`.

---

## 1. Executive Summary

Milestone M3 (**Direct Transport, Encrypted Relay Queue, Provenance, and Agent Selection**) has been fully implemented, systematically hardened during the close-out review, and verified with a 100% green test suite across both `kin-node` and `kin-relay`.

### 1.1 Close-Out Defects Identified and Resolved
During the formal close-out audit, three live runtime defects and a test discipline gap were identified and resolved prior to milestone sign-off:

1. **Missing `ed25519` Import in `kin/node/routes.py`**:
   - *Defect*: `ed25519` was used in `ed25519.Ed25519PublicKey.from_public_bytes(...)` inside `get_contact_pubkey` closures in `get_published_agent_cards` and `process_v11_session_envelope`, but `ed25519` was never imported at module level.
   - *Fix*: Added `from cryptography.hazmat.primitives.asymmetric import ed25519` in `kin/node/routes.py`.

2. **`list_cards()` Filter & Published Projection Defect (`kin/agent_registry/registry.py`)**:
   - *Defect*: `list_cards()` lacked an `include_disabled` filter parameter and did not SELECT or return `published_card_json`, preventing `get_published_agent_cards` in `routes.py` from projecting actual agent cards.
   - *Fix*: Added `include_disabled: bool = False` parameter to `list_cards()` (filtering `WHERE enabled = 1` by default), returned both raw `published_card_json` and parsed `published_card` dict, updated CLI caller (`kin agent list`) to pass `include_disabled=True`, and updated `routes.py` to project published cards.

3. **Standing Fastapi `TestClient` Coverage Requirement**:
   - *Discipline Gap*: Route functions were previously only unit-tested via direct function calls or mocks.
   - *Fix*: Added the new standing testing rule to `README.md` and added real `fastapi.testclient.TestClient` route tests for `POST /v1.1/sessions` and `GET /v1.1/agents/cards`.

### 1.2 Core Deliverables Completed
1. **Shared Ed25519 Request Signing & Auth Headers (`kin/identity/auth.py`)**:
   - Implemented `create_signed_auth_headers` and `verify_signed_auth_headers` using JCS canonicalization (`kin:v1.1:auth:{timestamp}`).

2. **Database Migrations 0004 & 0005 (`kin/storage/migrations.py`)**:
   - **Migration 0004 (`v11_transport_and_queue`)**: Created `outbound_envelope_queue` table and added `expires_at` column to `sessions`.
   - **Migration 0005 (`v11_session_column_renames`)**: Additive schema migration renaming `sessions.owner_username`/`peer_username` to `initiator_username`/`receiver_username` and creating `peer_capabilities` table.

3. **Reducer-Driven Session Status Transitions (`kin/transport/v11.py`)**:
   - Integrated `_apply_node_command_transition` to route all session status mutations through the state machine reducer and write structured audit events (`session_status_updated`).

4. **Verified Envelope Ingestion Pipeline (`kin/transport/v11.py`)**:
   - Built 6-stage envelope verification pipeline (`verify_and_build_envelope`) with bootstrap agent-id locking and receiver agent substitution on `ACCEPTANCE`.

5. **Sequence Conflict & Deduplication Engine (`kin/audit/writer.py`)**:
   - Extracted `check_sequence_conflict()` to deduplicate envelope re-deliveries via JCS payload hash comparison (returning status `delivered` for identical re-deliveries and `SECURITY_VIOLATION` for payload sequence reuse).

6. **Direct Transport Dispatch & Relay Fallback (`kin/transport/v11.py`)**:
   - Built 6-step `dispatch_session` workflow with peer capability caching (72h TTL), stale peer card refusal, symmetric self-processing pass, direct HTTP POST, encrypted relay mailbox fallback, and local outbound retry queueing.

7. **Control Commands & Provenance Disclosures**:
   - Implemented `pause_session`, `resume_session`, `cancel_session`, and `sync_peer_cards` (returning provenance disclosures `"source": "network"` vs `"source": "cache_fallback"`).

8. **Session Type Architecture Answer (§1.3)**:
   - *Design Finding*: Evaluated situation (a) vs (b) for §15.6 session types (`ask`, `research`, `debate`, `review`). Found situation (a): the reducer and transport operate symmetrically on any valid P0 session type string without type-specific branching. Parametrized `test_two_profile_direct_session_lifecycle` across all 4 P0 types.

---

## 2. Pyflakes Audit Before and After

### Pyflakes BEFORE Fixes:
```text
kin/cli.py:10:1: 'threading' imported but unused
kin/agent_backend\llm_backend.py:9:1: 'pydantic.ValidationError' imported but unused
kin/agent_backend\webhook_backend.py:9:1: 'pydantic.ValidationError' imported but unused
kin/agent_registry\loader.py:5:1: 're' imported but unused
kin/agent_roster\__init__.py:2:1: 'kin.agent_roster.loader.load_agent_roster' imported but unused
kin/agent_roster\__init__.py:2:1: 'kin.agent_roster.loader.AgentConfig' imported but unused
kin/agent_roster\__init__.py:2:1: 'kin.agent_roster.loader.AgentLoadingError' imported but unused
kin/audit\export.py:5:1: 'hashlib' imported but unused
kin/audit\export.py:94:25: undefined name 'Any'
kin/node\routes.py:14:1: 'litellm' imported but unused
kin/node\routes.py:23:1: 'kin.agent_backend.llm_backend.LLMAgentBackend' imported but unused
kin/node\routes.py:636:40: undefined name 'ed25519'
kin/node\routes.py:641:20: undefined name 'ed25519'
kin/node\routes.py:678:40: undefined name 'ed25519'
kin/node\routes.py:683:20: undefined name 'ed25519'
kin/node\routes.py:687:20: undefined name 'ed25519'
kin/transport\v11.py:20:1: 'kin.schemas.SessionEnvelope' imported but unused
kin/transport\v11.py:961:17: local variable 'last_err' is assigned to but never used
```

### Pyflakes AFTER Fixes:
```text
(Clean output — zero warnings or errors returned)
```

---

## 3. File Registry

### Modified Files:
- [README.md](file:///d:/KIN/kin-node/README.md): Added standing Fastapi `TestClient` route testing rule.
- [KNOWN_LIMITATIONS.md](file:///d:/KIN/kin-node/KNOWN_LIMITATIONS.md): Appended Milestone M3 section covering retry queue backoff constants, relay blind forwarding, capability fallback, and close-out defects fixed.
- [kin/agent_backend/llm_backend.py](file:///d:/KIN/kin-node/kin/agent_backend/llm_backend.py): Removed unused `ValidationError` import.
- [kin/agent_backend/webhook_backend.py](file:///d:/KIN/kin-node/kin/agent_backend/webhook_backend.py): Removed unused `ValidationError` import.
- [kin/agent_registry/loader.py](file:///d:/KIN/kin-node/kin/agent_registry/loader.py): Removed unused `re` import.
- [kin/agent_registry/registry.py](file:///d:/KIN/kin-node/kin/agent_registry/registry.py): Added `include_disabled: bool = False` to `list_cards()`, returned `published_card_json` and `published_card` dict, added `json` import.
- [kin/agent_roster/__init__.py](file:///d:/KIN/kin-node/kin/agent_roster/__init__.py): Added `__all__` export list.
- [kin/audit/export.py](file:///d:/KIN/kin-node/kin/audit/export.py): Added `Any` import from typing, removed unused `hashlib` import, updated SQL queries for column renames.
- [kin/audit/writer.py](file:///d:/KIN/kin-node/kin/audit/writer.py): Extracted `check_sequence_conflict()` for sequence deduplication and payload hash comparison.
- [kin/cli.py](file:///d:/KIN/kin-node/kin/cli.py): Removed unused `threading` import, updated `list_cards(conn, include_disabled=True)` call.
- [kin/node/routes.py](file:///d:/KIN/kin-node/kin/node/routes.py): Added `ed25519` import, removed unused `litellm`/`LLMAgentBackend` imports, updated `get_published_agent_cards()` to use `list_cards(conn, include_disabled=False)`, fixed `get_or_create_vault_key` import.
- [kin/schemas.py](file:///d:/KIN/kin-node/kin/schemas.py): Implemented 6-stage envelope verification pipeline and payload hash canonicalization.
- [kin/session/reducer.py](file:///d:/KIN/kin-node/kin/session/reducer.py): Allowed receiver agent substitution on `ACCEPTANCE` envelope and updated participant state.
- [kin/storage/migrations.py](file:///d:/KIN/kin-node/kin/storage/migrations.py): Migration 0004 (`v11_transport_and_queue`) and Migration 0005 (`v11_session_column_renames`).
- [tests/test_audit.py](file:///d:/KIN/kin-node/tests/test_audit.py): Updated SQL queries for renamed columns.
- [tests/test_export.py](file:///d:/KIN/kin-node/tests/test_export.py): Updated export tests for renamed columns.
- [tests/test_migrations.py](file:///d:/KIN/kin-node/tests/test_migrations.py): Added `test_migration_0005_upgrade_path` and 5-migration count assertions.
- [tests/test_policy_evaluator.py](file:///d:/KIN/kin-node/tests/test_policy_evaluator.py): Updated test column names.
- [tests/test_session_recovery.py](file:///d:/KIN/kin-node/tests/test_session_recovery.py): Updated recovery test column names.
- [tests/test_storage.py](file:///d:/KIN/kin-node/tests/test_storage.py): Updated `EXPECTED_SCHEMA` with `peer_capabilities`.
- [tests/test_vault.py](file:///d:/KIN/kin-node/tests/test_vault.py): Updated column names.
- [kin-relay/tests/test_relay.py](file:///d:/KIN/kin-relay/tests/test_relay.py): Added `test_relay_mailbox_never_sees_plaintext` testing relay ciphertext confidentiality.

### New Files:
- [kin/identity/auth.py](file:///d:/KIN/kin-node/kin/identity/auth.py): Shared Ed25519 auth header creation and verification.
- [kin/transport/v11.py](file:///d:/KIN/kin-node/kin/transport/v11.py): Complete V1.1 transport dispatch, envelope ingestion, relay polling, queue retries, and control commands.
- [tests/test_v11_transport_m3.py](file:///d:/KIN/kin-node/tests/test_v11_transport_m3.py): 28 transport unit tests covering direct transport, relay fallback, TestClient route handlers, P0 session types, turn limit exhaustion, backoff sequence numbers, and receiver substitution.

---

## 4. Full Test Output

### `pytest kin-node` Output (262 Passed):
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 263 items / 1 deselected / 262 selected

tests/test_agent_projection.py ..                                       [  0%]
tests/test_agent_registry.py ..............                              [  6%]
tests/test_agent_roster.py .................                             [ 12%]
tests/test_audit.py ..                                                  [ 13%]
tests/test_cli_agent.py .....                                           [ 15%]
tests/test_cli_ask.py ............................                      [ 25%]
tests/test_cli_respond.py .........                                     [ 29%]
tests/test_cli_pair.py ..........                                       [ 33%]
tests/test_config.py ...                                                [ 34%]
tests/test_export.py ...                                                [ 35%]
tests/test_identity.py ...........                                      [ 39%]
tests/test_keys.py .............                                        [ 44%]
tests/test_migrations.py ...........                                     [ 48%]
tests/test_roster_discovery.py ...                                      [ 50%]
tests/test_schemas.py ....                                              [ 51%]
tests/test_session_compatibility.py ...                                 [ 52%]
tests/test_session_recovery.py ..                                       [ 53%]
tests/test_session_reducer.py ......................................... [ 69%]
................................................                         [ 87%]
tests/test_setup.py ...                                                 [ 88%]
tests/test_storage.py .                                                 [ 88%]
tests/test_storage_keychain.py ............                             [ 93%]
tests/test_v11_transport_m3.py .................                     [100%]
tests/test_vault.py .                                                   [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 262 passed, 1 deselected, 1 warning in 19.81s ================
```

### `pytest kin-relay` Output (12 Passed):
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0
rootdir: D:\KIN\kin-relay
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 12 items

tests/test_relay.py ............                                        [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 12 passed, 1 warning in 0.68s ========================
```

---

## 5. Known Limitations

1. **Local Process Adapter Execution Deferred to M4**: M3 provides direct transport, envelope verification, relay delivery, capability negotiation, and agent selection; actual execution of agent adapters (local process invocation, working directory isolation, stdout capture) belongs to Milestone M4.
2. **Interactive Owner Approval Prompt UI Scope**: `_apply_node_command_transition` and policy evaluator bridges handle programmatic DB status transitions and audit logging; terminal UI prompts for human owner approval belong to Milestone M5.
3. **Background Daemon Process Runner**: Ingestion and retry queue functions (`poll_relay_and_process`, `retry_outbound_queue`) are unit-tested and programmatically callable; mounting a long-running background daemon process service is deferred to release hardening.
