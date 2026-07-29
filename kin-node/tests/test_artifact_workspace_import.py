"""Tests for workspace artifact import, patch preview/apply, and path safety (§15.8 M5 Phase 5)."""

import hashlib
import sqlite3
import pytest
from pathlib import Path

from kin.artifacts.vault import ArtifactMetadata, store_artifact
from kin.artifacts.workspace import (
    InvalidPatchArtifactError,
    UnsafeWorkspacePathError,
    WorkspaceNotConfiguredError,
    WorkspacePatchPreview,
    WorkspaceWritePermissionDeniedError,
    apply_patch_to_workspace,
    import_artifact_to_workspace,
    preview_patch_apply,
    resolve_safe_workspace_path,
)
from kin.policy import (
    create_pending_approval,
    decide_approval,
)
from kin.schemas import (
    ActionClass,
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    ApprovalRequest,
    AutonomyLevel,
    DecisionKind,
    EmbeddedAdapterConfig,
    LocalCommandAdapterConfig,
    RiskLabel,
)
from kin.storage.migrations import run_migrations


@pytest.fixture
def profile_db():
    """Create an in-memory SQLite database initialized via run_migrations."""
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def local_agent_card(tmp_path: Path):
    """Return an AgentCard with a local_command adapter pointing to tmp_path."""
    return AgentCard(
        schema_version="1.1",
        id="ag_local_workspace",
        name="Local Workspace Agent",
        description="Local agent for workspace import tests",
        adapter=LocalCommandAdapterConfig(
            type="local_command",
            command="python",
            working_directory=str(tmp_path),
        ),
        capabilities=AgentCapabilities(tags=["local"], accepts=["text/plain"], produces=["text/plain"]),
        boundaries=AgentBoundaries(
            network_access="allow",
            filesystem="workspace_read_write_with_approval",
            shell="approval_required",
            max_runtime_seconds=300,
            max_artifact_bytes=10000000,
        ),
        autonomy=AgentAutonomy(
            relay_information=AutonomyLevel.ALWAYS_ASK,
            propose_actions=AutonomyLevel.ALWAYS_ASK,
            execute_local_actions=AutonomyLevel.ALWAYS_ASK,
        ),
    )


@pytest.fixture
def embedded_agent_card():
    """Return an AgentCard with an embedded adapter (workspace-less)."""
    return AgentCard(
        schema_version="1.1",
        id="ag_embedded",
        name="Embedded Agent",
        description="Embedded agent without workspace",
        adapter=EmbeddedAdapterConfig(type="embedded", provider="local", model="test-v1"),
        capabilities=AgentCapabilities(tags=["embedded"], accepts=["text/plain"], produces=["text/plain"]),
        boundaries=AgentBoundaries(
            network_access="allow",
            filesystem="workspace_read_write_with_approval",
            shell="approval_required",
            max_runtime_seconds=300,
            max_artifact_bytes=10000000,
        ),
        autonomy=AgentAutonomy(
            relay_information=AutonomyLevel.ALWAYS_ASK,
            propose_actions=AutonomyLevel.ALWAYS_ASK,
            execute_local_actions=AutonomyLevel.ALWAYS_ASK,
        ),
    )


def _setup_session(conn: sqlite3.Connection, session_id: str, status: str = "awaiting_owner_approval"):
    """Helper to seed a valid session into SQLite."""
    now = "2026-07-29T12:00:00Z"
    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status, turn_limit, created_at, updated_at
        ) VALUES (?, 'collaborative', 'alice', 'bob', ?, 12, ?, ?)
        """,
        (session_id, status, now, now),
    )
    conn.commit()


def _store(conn, vault_key, session_id, artifact_id, raw_bytes, mime_type="text/plain"):
    """Helper wrapper for store_artifact."""
    return store_artifact(
        conn,
        vault_key,
        session_id=session_id,
        raw_bytes=raw_bytes,
        mime_type=mime_type,
        offered_by="alice",
        preview_policy="auto",
        max_bytes=10000000,
        artifact_id=artifact_id,
    )


def test_path_traversal_rejection(tmp_path: Path):
    """1. Required test: resolve_safe_workspace_path rejects path traversal, absolute paths, null bytes, empty strings."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    dangerous_inputs = [
        "../../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\System32\\cmd.exe",
        "subdir/with\x00null/file.txt",
        "",
        "   ",
        "subdir/../../outside.txt",
        "..\\..\\windows_escape.txt",
    ]

    for bad_input in dangerous_inputs:
        with pytest.raises(UnsafeWorkspacePathError):
            resolve_safe_workspace_path(workspace_root, bad_input)

    # Confirm filesystem under workspace_root is untouched
    assert list(workspace_root.glob("**/*")) == []


def test_valid_relative_path_accepted(tmp_path: Path):
    """2. Valid relative paths resolve correctly under workspace_root."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    rel_path = "subdir/nested/target.txt"
    resolved = resolve_safe_workspace_path(workspace_root, rel_path)

    expected = (workspace_root / "subdir" / "nested" / "target.txt").resolve()
    assert resolved == expected


def test_patch_preview_on_existing_file(profile_db, tmp_path: Path):
    """3. Patch preview on existing file: returns structured preview, leaves real file COMPLETELY UNCHANGED."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_prev_1"
    _setup_session(profile_db, session_id)

    target_file = tmp_path / "src" / "app.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    initial_content = "def hello():\n    print('Hello World')\n"
    target_file.write_text(initial_content, encoding="utf-8")

    patch_bytes = b"--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1,2 @@\n def hello():\n-    print('Hello World')\n+    print('Hello KIN V1.1')\n"
    _store(profile_db, vault_key, session_id, "art_patch_1", patch_bytes, mime_type="text/x-diff")

    preview = preview_patch_apply(profile_db, vault_key, "art_patch_1", tmp_path, "src/app.py")

    assert isinstance(preview, WorkspacePatchPreview)
    assert preview.target_exists is True
    assert preview.original_content == initial_content
    assert "Hello KIN V1.1" in preview.patched_content
    assert preview.hunks_count > 0

    # CRITICAL AUDIT ASSERTION: File on disk remains COMPLETELY UNCHANGED
    assert target_file.read_text(encoding="utf-8") == initial_content


def test_patch_preview_on_new_file(profile_db, tmp_path: Path):
    """4. Patch preview targeting non-existent file: shows valid preview, file is NOT created on disk."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_prev_new"
    _setup_session(profile_db, session_id)

    patch_bytes = b"--- /dev/null\n+++ b/new_module.py\n@@ -0,0 +1,2 @@\n+# New file\n+x = 42\n"
    _store(profile_db, vault_key, session_id, "art_patch_new", patch_bytes, mime_type="text/x-patch")

    preview = preview_patch_apply(profile_db, vault_key, "art_patch_new", tmp_path, "new_module.py")

    assert preview.target_exists is False
    assert preview.original_content == ""
    assert "x = 42" in preview.patched_content

    # File must NOT exist on disk after preview
    assert not (tmp_path / "new_module.py").exists()


def test_import_blocked_without_approval(profile_db, local_agent_card, tmp_path: Path):
    """5. Import blocked without approval: import_artifact_to_workspace raises WorkspaceWritePermissionDeniedError, no write occurs."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_imp_no_app"
    _setup_session(profile_db, session_id)

    art_bytes = b"Important raw data content"
    _store(profile_db, vault_key, session_id, "art_raw_1", art_bytes)

    target_rel = "data/output.txt"
    now = "2026-07-29T12:05:00Z"

    with pytest.raises(WorkspaceWritePermissionDeniedError):
        import_artifact_to_workspace(profile_db, vault_key, local_agent_card, session_id, "art_raw_1", tmp_path, target_rel, now)

    # Confirm no file was written
    assert not (tmp_path / target_rel).exists()


def test_import_succeeds_after_approval(profile_db, local_agent_card, tmp_path: Path):
    """6. Import succeeds after decision: file created with exact content matching stored artifact sha256."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_imp_ok"
    _setup_session(profile_db, session_id)

    art_bytes = b"Verified payload content bytes"
    expected_sha256 = hashlib.sha256(art_bytes).hexdigest()
    _store(profile_db, vault_key, session_id, "art_imp_ok", art_bytes)

    # Create pending approval and decide ALWAYS_ALLOW_BOUNDED
    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_imp_1",
        session_id=session_id,
        agent_id=local_agent_card.id,
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Import artifact",
        reason="Allow write",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id=local_agent_card.id, action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")
    decide_approval(profile_db, vault_key, approval_id="req_imp_1", session_id=session_id, decision=DecisionKind.ALWAYS_ALLOW_BOUNDED, owner_username="alice", now="2026-07-29T12:01:00Z")

    target_rel = "docs/imported.txt"
    now = "2026-07-29T12:05:00Z"
    written_path = import_artifact_to_workspace(profile_db, vault_key, local_agent_card, session_id, "art_imp_ok", tmp_path, target_rel, now)

    assert written_path.exists()
    file_bytes = written_path.read_bytes()
    assert file_bytes == art_bytes
    assert hashlib.sha256(file_bytes).hexdigest() == expected_sha256


def test_import_blocked_by_explicit_deny(profile_db, local_agent_card, tmp_path: Path):
    """7. Import blocked by explicit DENY decision."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_imp_deny"
    _setup_session(profile_db, session_id)

    art_bytes = b"Dangerous payload"
    _store(profile_db, vault_key, session_id, "art_deny", art_bytes)

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_deny_1",
        session_id=session_id,
        agent_id=local_agent_card.id,
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Import payload",
        reason="Needs approval",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id=local_agent_card.id, action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")
    decide_approval(profile_db, vault_key, approval_id="req_deny_1", session_id=session_id, decision=DecisionKind.DENY, owner_username="alice", now="2026-07-29T12:01:00Z", reason="Security denial")

    with pytest.raises(WorkspaceWritePermissionDeniedError):
        import_artifact_to_workspace(profile_db, vault_key, local_agent_card, session_id, "art_deny", tmp_path, "forbidden.txt", "2026-07-29T12:05:00Z")

    assert not (tmp_path / "forbidden.txt").exists()


def test_apply_patch_to_workspace_flow(profile_db, local_agent_card, tmp_path: Path):
    """8. apply_patch_to_workspace: policy-gated patch application resulting in modified file."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_apply_patch"
    _setup_session(profile_db, session_id)

    target_file = tmp_path / "code.py"
    target_file.write_text("x = 1\n", encoding="utf-8")

    patch_bytes = b"--- a/code.py\n+++ b/code.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
    _store(profile_db, vault_key, session_id, "art_patch_apply", patch_bytes, mime_type="text/x-diff")

    # 1. Attempt without approval -> blocked
    with pytest.raises(WorkspaceWritePermissionDeniedError):
        apply_patch_to_workspace(profile_db, vault_key, local_agent_card, session_id, "art_patch_apply", tmp_path, "code.py", "2026-07-29T12:05:00Z")
    assert target_file.read_text(encoding="utf-8") == "x = 1\n"

    # 2. Grant approval and re-attempt -> succeeds
    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_patch_1",
        session_id=session_id,
        agent_id=local_agent_card.id,
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Apply patch",
        reason="Allow patch",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id=local_agent_card.id, action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")
    decide_approval(profile_db, vault_key, approval_id="req_patch_1", session_id=session_id, decision=DecisionKind.ALWAYS_ALLOW_BOUNDED, owner_username="alice", now="2026-07-29T12:01:00Z")

    applied_path = apply_patch_to_workspace(profile_db, vault_key, local_agent_card, session_id, "art_patch_apply", tmp_path, "code.py", "2026-07-29T12:05:00Z")
    assert applied_path.exists()
    assert applied_path.read_text(encoding="utf-8") == "x = 2\n"


def test_workspaceless_adapter_rejection(profile_db, embedded_agent_card, tmp_path: Path):
    """9. Workspace-less adapter rejection: cards without local_command adapter cleanly raise WorkspaceNotConfiguredError."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_wl"
    _setup_session(profile_db, session_id)

    art_bytes = b"Test content"
    _store(profile_db, vault_key, session_id, "art_wl", art_bytes)

    with pytest.raises(WorkspaceNotConfiguredError, match="Workspace operations require a local_command adapter"):
        import_artifact_to_workspace(profile_db, vault_key, embedded_agent_card, session_id, "art_wl", tmp_path, "test.txt", "2026-07-29T12:00:00Z")


def test_import_approve_once_single_use_consumption(profile_db, local_agent_card, tmp_path: Path):
    """10. Single-use APPROVE_ONCE interaction: first import consumes approval, second import attempt is blocked."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_imp_ao"
    _setup_session(profile_db, session_id)

    art1_bytes = b"First import file"
    _store(profile_db, vault_key, session_id, "art_ao_file1", art1_bytes)

    art2_bytes = b"Second import file"
    _store(profile_db, vault_key, session_id, "art_ao_file2", art2_bytes)

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_ao_import",
        session_id=session_id,
        agent_id=local_agent_card.id,
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Import file once",
        reason="Needs single-use write approval",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id=local_agent_card.id, action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")
    decide_approval(profile_db, vault_key, approval_id="req_ao_import", session_id=session_id, decision=DecisionKind.APPROVE_ONCE, owner_username="alice", now="2026-07-29T12:01:00Z")

    now_eval = "2026-07-29T12:05:00Z"

    # Call 1: MUST succeed and consume the APPROVE_ONCE decision
    p1 = import_artifact_to_workspace(profile_db, vault_key, local_agent_card, session_id, "art_ao_file1", tmp_path, "file1.txt", now_eval)
    assert p1.exists()
    assert p1.read_bytes() == art1_bytes

    # Call 2: MUST fail because APPROVE_ONCE was consumed by Call 1
    with pytest.raises(WorkspaceWritePermissionDeniedError):
        import_artifact_to_workspace(profile_db, vault_key, local_agent_card, session_id, "art_ao_file2", tmp_path, "file2.txt", now_eval)

    assert not (tmp_path / "file2.txt").exists()
