# Milestone M1 Progress Report: Local Storage, Vault Encryption, Audit Writer, Export & Migration

## Executive Summary
Milestone M1 introduces complete storage, schema migration, vault encryption at rest, centralized audit logging, transcript export, and atomic profile migration for the KIN system. All V1.1 session records, events, artifacts, approvals, and audit events can be created, recovered, exported, and audited locally without modifying frozen M0 contracts or changing V1 operational network flows.

All requested Fix-Back items have been fully addressed and verified:
1. **Legacy Profile Migration Refusal**: Legacy profiles predating `schema_migrations` raise `LegacyProfileMigrationRequired` on ordinary CLI invocations and exit 1 cleanly with instructions to run `kin migrate`.
2. **Duplicate Delivery vs Security Rejection**: Centralized audit writer distinguishes benign redeliveries (`duplicate_delivery`) from sequence reuse payload mismatches (`security_rejection`).
3. **Migration Report Integrity**: Fixed report tracking so `report.applied` and `report.skipped` never share version numbers during a migration run.
4. **Keyring Vault Validation in Migration**: Vault key readiness is validated during `kin migrate`'s staging phase before atomic DB replacement.
5. **Canonical JCS Content Hashing**: Export payload hashes now use `kin.schemas.compute_content_hash` (RFC 8785 canonical JCS + base64url).

Key accomplishments:
- **Ordered Migration Runner (`kin/storage/migrations.py`)**: Built an idempotent migration system with `schema_migrations` tracking, SHA-256 drift detection, legacy V1 profile backfilling (Migration 0001 `v1_baseline`), and V1.1 schema creation (Migration 0002 `v11_session_records`).
- **Encryption at Rest (`kin/storage/vault.py` & `kin/identity/storage.py`)**: Keyring-backed 32-byte vault key (`kin-<profile>-vault-key`) with AES-256-GCM encryption for all sensitive fields (objectives, snapshots, payloads, artifact bytes, approvals) and versioned `v1:` tokens.
- **Audit & Session Event Writer (`kin/audit/writer.py`)**: Centralized single-path audit writer and session event log with sequence deduplication. Differentiates `duplicate_delivery` (benign retries with matching content hash) from `security_rejection` (sequence reuse with mismatched content hash).
- **Deterministic Export (`kin/audit/export.py` & `legacy.py`)**: Deterministic JSON and Markdown session transcript export ordered strictly by `event_order`, payload decryption, private note redaction control (`include_private_notes`), canonical JCS hashing, and read-only projection for legacy V1 task threads.
- **Atomic CLI Migration (`kin/cli.py`)**: Added `kin migrate` command resolving profile boundaries via `ProfileContextResolver`, copying profiles to staging, validating schema/data integrity and vault key readiness, and atomically committing changes via `os.replace` with external failure reporting.
- **Comprehensive Test Suite**: Created tests covering migrations, vault encryption, audit immutability/deduplication, export, session state recovery, and legacy profile command refusal. All 125 tests are 100% green.

---

## File Modification Registry

- `kin-node/kin/identity/storage.py`: Added `get_vault_key_service` and `get_or_create_vault_key` functions with secure backend assertions.
- `kin-node/kin/storage/vault.py`: New module implementing AES-256-GCM field and byte encryption/decryption routines with `v1:` prefixes.
- `kin-node/kin/storage/migrations.py`: New ordered SQLite migration runner with checksum drift detection, legacy V1 profile validation/backfill, `LegacyProfileMigrationRequired` exception, and Migration 0001/0002 definitions.
- `kin-node/kin/storage/db.py`: Updated `create_schema(conn, *, allow_legacy_migration=False)` to enforce legacy profile check and raise `LegacyProfileMigrationRequired`.
- `kin-node/kin/audit/__init__.py`: Package marker for `kin.audit`.
- `kin-node/kin/audit/writer.py`: New module providing `write_audit_event` and `append_session_event` with sequence deduplication (`duplicate_delivery`) and security rejection checks (`security_rejection`).
- `kin-node/kin/audit/export.py`: New module implementing deterministic JSON and Markdown session export with event_order sorting, payload decryption, and RFC 8785 canonical JCS hashing.
- `kin-node/kin/audit/legacy.py`: New module projecting legacy V1 tasks and messages into read-only event structures.
- `kin-node/kin/cli.py`: Added `open_profile_db` helper to catch `LegacyProfileMigrationRequired` and present clean non-traceback errors, updated all CLI commands to use `open_profile_db`, and added `kin migrate` command with staging validation, vault key readiness check, atomic DB replacement, and failure reporting.
- `kin-node/tests/test_storage.py`: Updated `EXPECTED_SCHEMA` to verify all V1 and V1.1 tables created by `create_schema`.
- `kin-node/tests/test_migrations.py`: New test suite for fresh DB migration, legacy backfilling, idempotency, checksum drift, interrupted migration atomicity, fail-closed invalid schemas, missing keychains, copy errors, profile isolation, and ordinary command refusal on unmigrated profiles.
- `kin-node/tests/test_vault.py`: New test suite checking raw SQLite binary files to assert encrypted secrets are unreadable in cleartext.
- `kin-node/tests/test_audit.py`: New test suite verifying SQLite trigger immutability (UPDATE/DELETE rejection), sequence deduplication (`duplicate_delivery`), and security rejection paths (`SEQUENCE_REUSE_MISMATCH`).
- `kin-node/tests/test_export.py`: New test suite for golden Markdown/JSON export fixtures, event ordering, private note redaction, and legacy task projection.
- `kin-node/tests/test_session_recovery.py`: New test suite verifying session state reconstruction from SQLite without in-memory state.
- `kin-node/tests/test_cli_pair.py`: Updated test fixtures to use `create_schema(conn)` for proper schema initialization.

---

## Code Diffs and File Contents Summary

### 1. Silent Auto-Migration Closure (`kin/storage/db.py` & `kin/storage/migrations.py`)
```python
# kin/storage/migrations.py
class LegacyProfileMigrationRequired(Exception):
    """Raised when an ordinary CLI command encounters a legacy profile that requires explicit 'kin migrate'."""
    pass

# kin/storage/db.py
def create_schema(conn: sqlite3.Connection, *, allow_legacy_migration: bool = False) -> None:
    """Ensure database schema is created and up to date using the migration system."""
    from kin.storage.migrations import run_migrations, is_legacy_unmigrated_profile, LegacyProfileMigrationRequired

    if not allow_legacy_migration and is_legacy_unmigrated_profile(conn):
        raise LegacyProfileMigrationRequired(
            "This profile predates KIN's schema migration system. "
            "Run `kin migrate` before using this profile again."
        )

    report = run_migrations(conn)
    if report.errors:
        raise RuntimeError(f"Database schema creation/migration failed: {'; '.join(report.errors)}")
```

### 2. Clean CLI Presentation (`kin/cli.py`)
```python
def open_profile_db(db_path: Path | str) -> sqlite3.Connection:
    """Open DB connection and ensure schema, presenting clean error if legacy profile migration is required."""
    conn = get_connection(db_path)
    try:
        create_schema(conn, allow_legacy_migration=False)
    except LegacyProfileMigrationRequired as err:
        try:
            conn.close()
        except Exception:
            pass
        typer.echo(f"ERROR: {err}", err=True)
        raise typer.Exit(1)
    return conn
```

### 3. Duplicate Delivery vs Security Rejection (`kin/audit/writer.py`)
```python
        if existing:
            ex_event_id, ex_content_hash = existing
            if ex_content_hash == content_hash:
                # Exact duplicate delivery -> benign retry
                write_audit_event(
                    conn,
                    category="duplicate_delivery",
                    actor=actor_username,
                    action="append_session_event_retry",
                    status="info",
                    detail_json=json.dumps({
                        "session_id": session_id,
                        "sequence": sequence,
                        "content_hash": content_hash,
                        "event_id": ex_event_id,
                    }),
                )
                conn.commit()
                return {"status": "duplicate", "event_id": ex_event_id}
            else:
                # Sequence reuse with different content -> security rejection anomaly
                write_audit_event(
                    conn,
                    category="security_rejection",
                    actor=actor_username,
                    action="append_session_event_rejected",
                    status="warning",
                    detail_json=json.dumps({
                        "session_id": session_id,
                        "sequence": sequence,
                        "error_code": "SEQUENCE_REUSE_MISMATCH",
                        "existing_hash": ex_content_hash,
                        "incoming_hash": content_hash,
                    }),
                )
                conn.commit()
                return {"status": "rejected", "error_code": "SEQUENCE_REUSE_MISMATCH"}
```

---

## Verbatim Test Execution Output

Below is the complete output from running `pytest kin-node`:

```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 126 items / 1 deselected / 125 selected

kin-node\tests\test_agent_roster.py ................                     [ 12%]
kin-node\tests\test_audit.py ..                                          [ 14%]
kin-node\tests\test_cli_ask.py ............................              [ 36%]
kin-node\tests\test_cli_pair.py ..........                               [ 44%]
kin-node\tests\test_cli_relay_fallback.py .....                          [ 48%]
kin-node\tests\test_export.py ....                                       [ 52%]
kin-node\tests\test_fingerprint.py ...                                   [ 54%]
kin-node\tests\test_harness_isolation.py ....                            [ 57%]
kin-node\tests\test_keys.py .............                                [ 68%]
kin-node\tests\test_migrations.py ..........                             [ 76%]
kin-node\tests\test_schemas.py ........                                  [ 82%]
kin-node\tests\test_session_recovery.py .                                [ 83%]
kin-node\tests\test_session_reducer.py ....                              [ 86%]
kin-node\tests\test_setup.py ...                                         [ 88%]
kin-node\tests\test_storage.py .                                         [ 89%]
kin-node\tests\test_storage_keychain.py ............                     [ 99%]
kin-node\tests\test_vault.py .                                           [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 125 passed, 1 deselected, 1 warning in 14.32s ================
```

---

## Open Questions for Tech Lead

1. **`llm_backend.py` schema initialization**:
   `llm_backend.py` invokes `create_schema(conn)` directly without arguments (`allow_legacy_migration=False`). This ensures that background LLM process connections refuse unmigrated legacy databases safely unless `kin migrate` has been executed beforehand. Please confirm if LLM backend connections should ever attempt auto-migration or if the current fail-closed design is preferred.

2. **Audit event logging on legacy refusal**:
   Currently, when an ordinary CLI command raises `LegacyProfileMigrationRequired`, `open_profile_db` immediately exits 1 without recording an audit event (since `audit_events` table may not yet exist on an unmigrated V1 profile). Once `kin migrate` completes, all subsequent operations generate audit logs normally. Please confirm this behavior is aligned with expectation.

3. **Vault Key storage backend in headless/server environments**:
   `kin migrate` verifies vault key availability via `get_or_create_vault_key(profile_name)` during validation. In automated CI or headless Linux deployments without Secret Service/KWallet, `KEYRING_CRYPTOGRAPHY_KEY` or an environment keyring backend will be needed. The test suite uses `KIN_UNSAFE_TEST_KEYRING=1` for isolated testing.
