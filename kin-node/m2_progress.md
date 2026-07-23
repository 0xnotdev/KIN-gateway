# Milestone M2 Progress & Verification Report

**Status**: COMPLETED  
**Authority**: `KIN-V1.1-MASTER-SPEC.md` §15.5, constrained by §6, §8.2-8.4, §9.4, §15.1, §15.2.

---

## 1. Executive Summary

Milestone M2 (**Agent Registry & Policy Evaluator**) has been implemented and validated across `kin-node`.

### Deliverables Completed:
1. **Strict Nested Schemas (`kin/schemas.py`)**:
   - Replaced loose `dict[str, Any]` fields in `AgentCard` with discriminated union `AdapterConfig` (`EmbeddedAdapterConfig`, `WebhookAdapterConfig`, `LocalCommandAdapterConfig`, `SdkAdapterConfig`), `AgentCapabilities`, `AgentBoundaries`, and `AgentAutonomy`.
   - Enforced `extra="forbid"` on all nested models, rejecting raw secret fields (e.g. `webhook_secret`) in YAML definitions.
   - Enforced path normalization on `LocalCommandAdapterConfig.working_directory` via `Path(v).as_posix()`.
   - Updated `PublishedAgentCard` to use strict `AgentCapabilities`.

2. **Storage Migration 0003 (`kin/storage/migrations.py`)**:
   - Appended `MIGRATION_0003_SQL` adding `card_version` to `agents` table and creating `peer_agent_cards` table with index `idx_peer_agent_cards_status`.
   - Maintained 100% checksum integrity for migrations 0001 and 0002.

3. **Identity Storage Extension (`kin/identity/storage.py`)**:
   - Added `get_agent_credential_service(profile, agent_id, purpose)` for computing profile-scoped keychain service names (`kin-{profile}-agent-{id}-{purpose}`).

4. **Agent Registry Package (`kin/agent_registry/`)**:
   - `loader.py`: Safe YAML parser enforcing `schema_version == "1.1"`, ID matching, and single strict credential reference format matching `kin-{profile}-agent-{id}-{purpose}`.
   - `availability.py`: Environmental readiness and policy status engine (`NEEDS_KEY`, `NEEDS_WORKSPACE`, `READY`, `POLICY_BLOCKED`) with `AVAILABILITY_EXPLANATIONS`.
   - `registry.py`: `get_agents_dir`, `scan_local_cards` (skipping legacy V1 cards without error), `register_card` (AES-256-GCM encryption for local card JSON, version tracking, `enabled` state preservation), `publish_card` (field-by-field allowlist construction), `list_cards`, `get_card`, `set_enabled`, and `import_card`.
   - `peer_cards.py`: `cache_peer_card` (canonical JCS `compute_content_hash` staleness tracking), `mark_reviewed`, `is_stale`.

5. **Policy Evaluator Package (`kin/policy/`)**:
   - `evaluator.py`: Pure, deterministic evaluation of `ActionClass` requests.
     - **Strict Execution Order**: Step 1 (**Hard Boundary Denial**) executes and short-circuits BEFORE Step 2 (**Prior Approval Check**). Tested explicitly: hard denials cannot be bypassed by prior approval grants.
     - `session_context` is strictly informational and structurally isolated from local command execution.
   - `persistence.py`: `evaluate_action_for_session()` querying active non-expired bounded approvals from SQLite database and `record_approval_decision()` write path with encrypted audit logging.

6. **CLI Extensions (`kin/cli.py`)**:
   - Mounted `agent_app` subcommand group (`kin agent list`, `kin agent inspect`, `kin agent validate`, `kin agent enable`, `kin agent disable`, `kin agent import`, `kin agent publish`).
   - Enforced `enabled` flag checks on `publish` (disabled agents refuse publishing) and human `list` output.
   - Clean profile context propagation and error handling without tracebacks.

7. **Test Suite**:
   - All 229 pytest items in `kin-node` (up from 201 baseline) and 11 items in `kin-relay` pass 100%.

---

## 2. File Registry

### Modified Files:
- `kin/schemas.py`: Nested schema models, discriminated union adapter configs, strict validators, path normalization.
- `kin/identity/storage.py`: Added `get_agent_credential_service()`.
- `kin/storage/migrations.py`: Added `MIGRATION_0003_SQL` and appended Migration 3 to `ALL_MIGRATIONS`.
- `kin/cli.py`: Mounted `agent` subcommand group (`list`, `inspect`, `validate`, `enable`, `disable`, `import`, `publish`) with enabled state enforcement.
- `tests/conftest.py`: Updated `sample_agent_card` and `sample_published_card` fixtures to nested schemas.
- `tests/test_migrations.py`: Extended test suite for Migration 0003 idempotency and version checks.
- `tests/test_storage.py`: Updated `EXPECTED_SCHEMA` for Migration 0003.

### New Files:
- `kin/agent_registry/__init__.py`: Package marker.
- `kin/agent_registry/loader.py`: YAML parser, card validation, credential_ref exact match.
- `kin/agent_registry/availability.py`: Availability computation and explanation dictionary with `POLICY_BLOCKED` support.
- `kin/agent_registry/registry.py`: Card scanning, encrypted registration, allowlisted publishing, import, list, set_enabled.
- `kin/agent_registry/peer_cards.py`: Peer card caching and content-hash staleness tracking.
- `kin/policy/__init__.py`: Package marker.
- `kin/policy/evaluator.py`: Pure policy decision engine with boundary short-circuiting and explicit autonomy mapping documentation.
- `kin/policy/persistence.py`: SQLite approval persistence query bridge and `record_approval_decision()` write path with audit logging.
- `tests/test_agent_registry.py`: Loader, scanner, availability, peer card, and legacy V1 coexistence tests.
- `tests/test_agent_projection.py`: Allowlist projection contract and secret leakage prevention tests.
- `tests/test_policy_evaluator.py`: Hard boundary override, approval class matrix, autonomy, persistence query, and `record_approval_decision()` write path tests.
- `tests/test_cli_agent.py`: CLI subcommands smoke tests with human and `--json` outputs and enable/disable enforcement.

---

## 3. Full Test Output

### `pytest kin-node` Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 230 items / 1 deselected / 229 selected

tests\test_agent_projection.py ..                                        [  0%]
tests\test_agent_registry.py ............                                [  6%]
tests\test_agent_roster.py ................                              [ 13%]
tests\test_audit.py ..                                                   [ 13%]
tests\test_cli_agent.py .....                                            [ 16%]
tests\test_cli_ask.py ............................                       [ 28%]
tests\test_cli_pair.py ..........                                        [ 32%]
tests\test_cli_relay_fallback.py .....                                   [ 34%]
tests\test_compatibility.py ....                                         [ 36%]
tests\test_export.py ....                                                [ 38%]
tests\test_fingerprint.py ...                                            [ 39%]
tests\test_harness_isolation.py ....                                     [ 41%]
tests\test_keys.py .............                                         [ 47%]
tests\test_migrations.py ..........                                      [ 51%]
tests\test_policy_evaluator.py .........                                 [ 55%]
tests\test_schemas.py ..............                                     [ 61%]
tests\test_session_recovery.py .                                         [ 62%]
tests\test_session_reducer.py .......................................... [ 80%]
............................                                             [ 92%]
tests\test_setup.py ...                                                  [ 93%]
tests\test_storage.py .                                                  [ 94%]
tests\test_storage_keychain.py ............                              [ 99%]
tests\test_vault.py .                                                    [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 229 passed, 1 deselected, 1 warning in 17.55s ================
```

### `pytest kin-relay` Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0
rootdir: D:\KIN\kin-relay
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 11 items

tests\test_relay.py ...........                                          [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 11 passed, 1 warning in 0.98s ========================
```

---

## 4. Known Limitations

1. **No Live Transport/Dispatch Wire Coupling**: No live transport or peer card network exchange exists in M2; peer card caching (`cache_peer_card`) and publishing (`publish_card`) are exercised via direct function calls and CLI commands without live socket transmission.
2. **Interactive Approval UI Scope**: `record_approval_decision()` provides the programmatic DB write path with audit logging for owner approval decisions, while interactive terminal prompt UI belongs to Milestone M5.
3. **Owner Acceptance Hardcode**: `PublishedAgentCard.requires_owner_acceptance` is hardcoded to `True` for V1.1 as autonomous peer card acceptance is out of scope for M2.
4. **Action Class Autonomy Mapping Scope**: Per §8.3's table, autonomy settings in V1.1 only ever govern `INFORMATIONAL_RELAY` (via `relay_information`); `propose_actions` and `execute_local_actions` exist on the `AgentAutonomy` schema for future milestones and are intentionally unmapped in `evaluate_action()`.
5. **Working Directory Validation vs Sandboxing**: `LocalCommandAdapterConfig.working_directory` rejects relative paths and `..` traversal segments at schema validation time and normalizes via `Path(v).as_posix()`; full runtime process sandboxing is deferred to adapter execution in M4.

---

## 5. Open Questions for Tech Lead

1. **Provisional Boundary Ceilings Configurability**: `AgentBoundaries` currently enforces fixed schema-level sanity caps (`max_runtime_seconds <= 3600` and `max_artifact_bytes <= 52,428,800`). Should these caps remain static hard limits in schema, or be configurable per node/profile in future milestones?
