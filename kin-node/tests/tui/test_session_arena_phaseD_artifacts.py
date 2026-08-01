"""Artifact Import & Patch Apply Integration Test Suite (§14.8 Phase D).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.3, §14.8 build step 6
"""

from pathlib import Path
import pytest
from textual.app import App

from kin.artifacts.vault import ArtifactMetadata, store_artifact
from kin.schemas import DecisionKind, MessageKind
from kin.identity.storage import get_or_create_vault_key
from kin.tui.local_state import (
    apply_patch_action,
    ensure_profile_db,
    import_artifact_action,
    preview_patch_action,
)
from kin.tui.state import ArtifactView, SessionSummary
from kin.tui.widgets.approval_modals import ApproveConfirmModal, PatchApplyConfirmModal
from kin.tui.widgets.session_arena import SessionArenaWidget


class ArenaArtifactTestApp(App):
    """Test App harness mounting SessionArenaWidget with artifact views."""

    def __init__(self, session_summary=None, artifacts=None, **kwargs):
        super().__init__(**kwargs)
        self.arena_widget = SessionArenaWidget(
            session_summary=session_summary,
            artifacts=artifacts,
        )

    def compose(self):
        yield self.arena_widget


def _write_agent_card(tmp_path: Path, agent_id: str):
    """Helper writing a valid AgentCard YAML file to profile agents directory."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    ws_dir = (tmp_path / "workspace").as_posix()
    card_file = agents_dir / f"{agent_id}.yaml"
    card_yaml = f"""\
schema_version: "1.1"
id: "{agent_id}"
name: "Bob Helper Agent"
description: "Test agent card"
capabilities:
  tags: ["research"]
  accepts: ["text/plain", "text/x-diff"]
  produces: ["text/plain", "text/x-diff"]
adapter:
  type: "local_command"
  command: "echo"
  working_directory: "{ws_dir}"
boundaries:
  filesystem: "workspace_read_write_with_approval"
  max_runtime_seconds: 300
  max_artifact_bytes: 1048576
autonomy:
  relay_information: "always_ask"
  propose_actions: "always_ask"
  execute_local_actions: "always_ask"
"""
    card_file.write_text(card_yaml, encoding="utf-8")


def _setup_test_db(
    tmp_path: Path,
    session_id: str,
    artifact_id: str,
    raw_content: str,
    relative_target: str,
    mime_type: str = "text/plain",
    offered_by_agent_id: str = "agent-bob-helper",
    human_username: str = "bob_owner",
):
    """Helper creating a test profile DB, session, vault key, agent card file, artifact, and vault file."""
    _write_agent_card(tmp_path, offered_by_agent_id)
    db_path = tmp_path / "kin.db"
    conn = ensure_profile_db(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO sessions (session_id, initiator_username, receiver_username, status, type, created_at, updated_at)
        VALUES (?, 'alice_user', ?, 'active', 'research', '2026-08-01T12:00:00Z', '2026-08-01T12:00:00Z')
        """,
        (session_id, human_username),
    )

    vault_key = get_or_create_vault_key("default")
    store_artifact(
        conn,
        vault_key,
        session_id=session_id,
        raw_bytes=raw_content.encode("utf-8"),
        mime_type=mime_type,
        offered_by=offered_by_agent_id,
        preview_policy="text",
        max_bytes=1048576,
        artifact_id=artifact_id,
        relative_target_path=relative_target,
    )
    conn.commit()
    conn.close()


def _add_approval(tmp_path: Path, approval_id: str, session_id: str, decision: str = "approve_once", agent_id: str = "agent-bob-helper"):
    """Helper adding a decided approval to approvals table."""
    db_path = tmp_path / "kin.db"
    conn = ensure_profile_db(db_path)
    conn.execute(
        """
        INSERT INTO approvals (
            approval_id, session_id, agent_id, action_class,
            request_json, decision, decided_at, expires_at
        ) VALUES (?, ?, ?, 'workspace_write', '{}', ?, '2026-08-01T12:05:00Z', '2026-12-31T23:59:59Z')
        """,
        (approval_id, session_id, agent_id, decision),
    )
    conn.commit()
    conn.close()


# -----------------------------------------------------------------------------
# 1. Integration Test: Import Artifact Succeeds With Prior Approval
# -----------------------------------------------------------------------------
def test_artifact_import_succeeds_with_prior_approval(tmp_path):
    """Assert import_artifact_action writes target file when prior DECIDED approval exists (§14.8)."""
    session_id = "sess-art-1"
    artifact_id = "art-import-1"
    rel_target = "docs/output.txt"
    content = "Hello, world! Workspace import verified."

    _setup_test_db(tmp_path, session_id, artifact_id, content, rel_target)
    _add_approval(tmp_path, "app-1", session_id, decision="approve_once")

    ws_root = tmp_path / "workspace"
    success, rec_err = import_artifact_action(
        tmp_path,
        session_id=session_id,
        artifact_id=artifact_id,
        relative_target_path=rel_target,
        workspace_root=ws_root,
    )

    assert success is True
    assert rec_err is None
    written_file = ws_root / rel_target
    assert written_file.exists()
    assert written_file.read_text(encoding="utf-8") == content


# -----------------------------------------------------------------------------
# 2. Integration Test: Import Artifact Fails Without Prior Approval
# -----------------------------------------------------------------------------
def test_artifact_import_fails_without_prior_approval(tmp_path):
    """Assert import_artifact_action fails with WorkspaceWritePermissionDeniedError when no approval exists (§14.8)."""
    session_id = "sess-art-2"
    artifact_id = "art-import-2"
    rel_target = "docs/unapproved.txt"
    content = "Secret unapproved payload."

    _setup_test_db(tmp_path, session_id, artifact_id, content, rel_target)
    # NO approval added

    ws_root = tmp_path / "workspace"
    success, rec_err = import_artifact_action(
        tmp_path,
        session_id=session_id,
        artifact_id=artifact_id,
        relative_target_path=rel_target,
        workspace_root=ws_root,
    )

    assert success is False
    assert rec_err is not None
    assert "Workspace Write Permission Denied" in rec_err.what_happened
    assert not (ws_root / rel_target).exists()


# -----------------------------------------------------------------------------
# 3. Path Traversal Test
# -----------------------------------------------------------------------------
def test_artifact_import_path_traversal_rejected(tmp_path):
    """Assert relative target paths escaping workspace root raise UnsafeWorkspacePathError (§14.8)."""
    session_id = "sess-art-3"
    artifact_id = "art-import-3"
    unsafe_target = "../../etc/passwd"
    content = "Traversing payload"

    _setup_test_db(tmp_path, session_id, artifact_id, content, unsafe_target)
    _add_approval(tmp_path, "app-3", session_id, decision="approve_once")

    ws_root = tmp_path / "workspace"
    success, rec_err = import_artifact_action(
        tmp_path,
        session_id=session_id,
        artifact_id=artifact_id,
        relative_target_path=unsafe_target,
        workspace_root=ws_root,
    )

    assert success is False
    assert rec_err is not None
    assert "Unsafe Workspace Path Error" in rec_err.what_happened


# -----------------------------------------------------------------------------
# 4. Patch Drift Test
# -----------------------------------------------------------------------------
def test_patch_apply_stale_target_content_rejected(tmp_path):
    """Assert apply_patch_action rejects patch when target file content has drifted (§14.8)."""
    session_id = "sess-art-4"
    artifact_id = "art-patch-4"
    rel_target = "src/main.py"
    patch_content = (
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-original_line_1\n"
        "+modified_line_1\n"
        " context_line_2\n"
    )

    _setup_test_db(tmp_path, session_id, artifact_id, patch_content, rel_target, mime_type="text/x-diff")
    _add_approval(tmp_path, "app-4", session_id, decision="approve_once")

    # Target file contains MUTATED content (mismatched context line)
    ws_root = tmp_path / "workspace"
    target_file = ws_root / rel_target
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("MUTATED_LINE_1\ncontext_line_2\n", encoding="utf-8")

    success, rec_err = apply_patch_action(
        tmp_path,
        session_id=session_id,
        artifact_id=artifact_id,
        relative_target_path=rel_target,
        workspace_root=ws_root,
    )

    assert success is False
    assert rec_err is not None
    assert "Invalid Patch Artifact Error" in rec_err.what_happened
    # Target file is untouched/uncorrupted
    assert target_file.read_text(encoding="utf-8") == "MUTATED_LINE_1\ncontext_line_2\n"


# -----------------------------------------------------------------------------
# 5. Session Boundary Ownership Mismatch Test
# -----------------------------------------------------------------------------
def test_artifact_session_boundary_ownership_mismatch_rejected(tmp_path):
    """Assert attempting import for an artifact belonging to a different session is rejected (§14.8)."""
    _setup_test_db(tmp_path, "sess-real", "art-belonging-to-real", "data", "out.txt")

    success, rec_err = import_artifact_action(
        tmp_path,
        session_id="sess-attacker-99",
        artifact_id="art-belonging-to-real",
        relative_target_path="out.txt",
    )

    assert success is False
    assert rec_err is not None
    assert "Artifact ownership mismatch" in rec_err.what_happened


# -----------------------------------------------------------------------------
# 6. Adversarial Test: Human Username vs Agent ID Differentiation
# -----------------------------------------------------------------------------
def test_artifact_import_succeeds_when_human_username_differs_from_offered_by_agent_id(tmp_path):
    """Adversarial test: receiver_username ('bob_human') differs from offered_by ('agent-bob-helper'). Confirm import succeeds using correct agent identity lookup (§14.8)."""
    session_id = "sess-art-diff-id"
    artifact_id = "art-diff-1"
    rel_target = "docs/diff_identity.txt"
    content = "Import with distinct human and agent identities."

    _setup_test_db(
        tmp_path,
        session_id,
        artifact_id,
        content,
        rel_target,
        offered_by_agent_id="agent-bob-helper",
        human_username="bob_human",
    )
    _add_approval(tmp_path, "app-diff-1", session_id, decision="approve_once", agent_id="agent-bob-helper")

    ws_root = tmp_path / "workspace"
    success, rec_err = import_artifact_action(
        tmp_path,
        session_id=session_id,
        artifact_id=artifact_id,
        relative_target_path=rel_target,
        workspace_root=ws_root,
    )

    assert success is True
    assert rec_err is None
    written = ws_root / rel_target
    assert written.exists()
    assert written.read_text(encoding="utf-8") == content


# -----------------------------------------------------------------------------
# 7. Adversarial Test: Missing Agent Card On Disk Returns RecoverableError
# -----------------------------------------------------------------------------
def test_artifact_import_fails_when_agent_card_missing_on_disk(tmp_path):
    """Adversarial test: approval exists for agent_id 'agent-missing-99' but NO agent card exists on disk. Confirm RecoverableError is returned and NO synthetic card is fabricated (§14.8)."""
    session_id = "sess-art-missing-card"
    artifact_id = "art-missing-1"
    rel_target = "docs/missing_card.txt"
    content = "Content requiring valid agent card."

    db_path = tmp_path / "kin.db"
    conn = ensure_profile_db(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (session_id, initiator_username, receiver_username, status, type, created_at, updated_at) VALUES (?, 'alice', 'bob', 'active', 'research', '2026-08-01T12:00:00Z', '2026-08-01T12:00:00Z')",
        (session_id,),
    )
    vault_key = get_or_create_vault_key("default")
    store_artifact(
        conn,
        vault_key,
        session_id=session_id,
        raw_bytes=content.encode("utf-8"),
        mime_type="text/plain",
        offered_by="agent-missing-99",
        preview_policy="text",
        max_bytes=1048576,
        artifact_id=artifact_id,
        relative_target_path=rel_target,
    )
    conn.commit()
    conn.close()

    _add_approval(tmp_path, "app-missing-1", session_id, decision="approve_once", agent_id="agent-missing-99")

    ws_root = tmp_path / "workspace"
    success, rec_err = import_artifact_action(
        tmp_path,
        session_id=session_id,
        artifact_id=artifact_id,
        relative_target_path=rel_target,
        workspace_root=ws_root,
    )

    assert success is False
    assert rec_err is not None
    assert "Agent card not found for offering agent 'agent-missing-99'" in rec_err.what_happened
    assert not (ws_root / rel_target).exists()


# -----------------------------------------------------------------------------
# 6. Pilot Keypress & Collision Audit Test
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_outputs_lane_pilot_keypress_triggers_modals(tmp_path):
    """Assert pressing 'v' and 'a' via real pilot in Outputs lane triggers confirmation modals (§14.8)."""
    meta = ArtifactMetadata(
        artifact_id="art-pilot-1",
        session_id="sess-pilot",
        sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        mime_type="text/x-diff",
        size_bytes=128,
        offered_by="bob",
        preview_policy="text",
        created_at="2026-08-01T12:00:00Z",
        relative_target_path="src/pilot.py",
    )
    art_view = ArtifactView.from_metadata(meta)
    summary = SessionSummary(
        session_id="sess-pilot",
        status="active",
        type="research",
        initiator_username="alice",
        receiver_username="bob",
        created_at="2026-08-01T12:00:00Z",
        updated_at="2026-08-01T12:00:00Z",
    )

    app = ArenaArtifactTestApp(session_summary=summary, artifacts=[art_view])
    async with app.run_test() as pilot:
        arena = pilot.app.query_one(SessionArenaWidget)
        pilot.app.set_focus(arena)

        # 1. Press 'v' while in transcript lane -> no modal triggered
        arena.switch_lane("transcript")
        await pilot.press("v")
        assert len(pilot.app.screen_stack) == 1

        # 2. Switch to Outputs lane and press 'v' -> ApproveConfirmModal pushed
        arena.switch_lane("outputs")
        assert arena.active_lane == "outputs"
        await pilot.press("v")
        assert len(pilot.app.screen_stack) > 1
        assert pilot.app.screen_stack[-1].__class__.__name__ == "ApproveConfirmModal"
        await pilot.press("escape")
        assert len(pilot.app.screen_stack) == 1

        # 3. Press 'a' in Outputs lane -> PatchApplyConfirmModal pushed
        await pilot.press("a")
        assert len(pilot.app.screen_stack) > 1
        assert pilot.app.screen_stack[-1].__class__.__name__ == "PatchApplyConfirmModal"
        await pilot.press("escape")
        assert len(pilot.app.screen_stack) == 1
