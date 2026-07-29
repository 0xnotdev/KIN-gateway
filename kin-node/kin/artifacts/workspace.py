"""Workspace import, patch preview, and patch application module (§15.8 M5 Phase 5)."""

from __future__ import annotations

import difflib
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from kin.artifacts.vault import (
    ArtifactMetadata,
    get_artifact_metadata,
    load_artifact_bytes,
)
from kin.policy.evaluator import PolicyDecision, PolicyResult
from kin.policy.persistence import evaluate_action_for_session
from kin.schemas import ActionClass, AgentCard, LocalCommandAdapterConfig


class UnsafeWorkspacePathError(Exception):
    """Raised when a workspace path violates security rules (traversal, absolute, null bytes, empty)."""
    pass


class WorkspaceNotConfiguredError(Exception):
    """Raised when an agent card has no local_command adapter or workspace configured."""
    pass


class WorkspaceWritePermissionDeniedError(Exception):
    """Raised when evaluate_action_for_session does not grant ALLOW for WORKSPACE_WRITE."""
    pass


class InvalidPatchArtifactError(Exception):
    """Raised when an artifact is not patch-shaped or patch parsing/application fails."""
    pass


@dataclass(frozen=True)
class WorkspacePatchPreview:
    """Structured read-only preview of applying a patch artifact to a workspace target file."""

    artifact_id: str
    relative_target_path: str
    target_exists: bool
    original_content: str
    patched_content: str
    unified_diff: str
    hunks_count: int


def resolve_safe_workspace_path(workspace_root: str | Path, relative_path: str) -> Path:
    """Resolve and validate relative_path cleanly inside workspace_root.

    Rejects:
    - Empty or whitespace-only paths
    - Null bytes (\x00)
    - Absolute paths (e.g. /etc/passwd, C:\\Windows)
    - Paths whose resolved target is not relative to resolved workspace_root
    """
    if not relative_path or not relative_path.strip():
        raise UnsafeWorkspacePathError("Relative target path cannot be empty.")

    if "\x00" in relative_path:
        raise UnsafeWorkspacePathError("Null bytes are forbidden in workspace paths.")

    rel_obj = Path(relative_path)
    if rel_obj.is_absolute():
        raise UnsafeWorkspacePathError(f"Absolute paths are forbidden: '{relative_path}'.")

    root_resolved = Path(workspace_root).resolve()
    candidate_resolved = (root_resolved / rel_obj).resolve()

    if not candidate_resolved.is_relative_to(root_resolved):
        raise UnsafeWorkspacePathError(
            f"Path traversal detected: '{relative_path}' resolves outside workspace root '{root_resolved}'."
        )

    return candidate_resolved


def validate_card_workspace(card: AgentCard, workspace_root: str | Path | None = None) -> Path:
    """Verify that card has a local_command adapter, and return the resolved workspace Path."""
    if not isinstance(card.adapter, LocalCommandAdapterConfig):
        raise WorkspaceNotConfiguredError(
            f"Agent '{card.id}' has adapter type '{card.adapter.type}'. Workspace operations require a local_command adapter."
        )

    root_str = workspace_root or card.adapter.working_directory
    if not root_str:
        raise WorkspaceNotConfiguredError(
            f"Agent '{card.id}' local_command adapter has no working_directory configured."
        )
    return Path(root_str).resolve()


def apply_unified_patch(original_text: str, patch_text: str) -> tuple[str, str, int]:
    """Apply a unified diff patch_text to original_text.

    Returns:
        (patched_text, unified_diff_str, hunks_count)
    Raises:
        InvalidPatchArtifactError if patch_text cannot be parsed, hunk header is invalid,
        or context/deleted lines do not match target original content.
    """
    if not patch_text or not patch_text.strip():
        raise InvalidPatchArtifactError("Patch content is empty.")

    lines = patch_text.splitlines()
    hunk_header_re = re.compile(
        r"^@@\s+-(?P<o_start>\d+)(?:,(?P<o_len>\d+))?\s+\+(?P<n_start>\d+)(?:,(?P<n_len>\d+))?\s+@@"
    )

    hunks: list[tuple[re.Match[str], list[str]]] = []
    current_hunk_lines: list[str] = []
    hunk_match: re.Match[str] | None = None

    for line in lines:
        m = hunk_header_re.match(line)
        if m:
            if current_hunk_lines and hunk_match:
                hunks.append((hunk_match, current_hunk_lines))
                current_hunk_lines = []
            hunk_match = m
        elif hunk_match is not None:
            if line.startswith(("-", "+", " ")) or line.startswith("\\ No newline"):
                current_hunk_lines.append(line)

    if hunk_match and current_hunk_lines:
        hunks.append((hunk_match, current_hunk_lines))

    if not hunks:
        raise InvalidPatchArtifactError("No valid unified diff hunks found in patch artifact.")

    orig_lines = original_text.splitlines() if original_text else []
    out_lines: list[str] = []
    orig_idx = 0

    for match, hunk_lines in hunks:
        o_start = int(match.group("o_start"))
        target_orig_idx = max(0, o_start - 1) if o_start > 0 else 0

        while orig_idx < target_orig_idx and orig_idx < len(orig_lines):
            out_lines.append(orig_lines[orig_idx])
            orig_idx += 1

        for hline in hunk_lines:
            if hline.startswith("\\ No newline"):
                continue
            prefix = hline[0]
            line_content = hline[1:]

            if prefix == " ":
                actual = orig_lines[orig_idx] if orig_idx < len(orig_lines) else "<EOF>"
                if orig_idx >= len(orig_lines) or orig_lines[orig_idx] != line_content:
                    raise InvalidPatchArtifactError(
                        f"Patch context mismatch at original line {orig_idx + 1}: expected '{line_content}', found '{actual}'"
                    )
                out_lines.append(orig_lines[orig_idx])
                orig_idx += 1
            elif prefix == "-":
                actual = orig_lines[orig_idx] if orig_idx < len(orig_lines) else "<EOF>"
                if orig_idx >= len(orig_lines) or orig_lines[orig_idx] != line_content:
                    raise InvalidPatchArtifactError(
                        f"Patch deletion mismatch at original line {orig_idx + 1}: expected '{line_content}', found '{actual}'"
                    )
                orig_idx += 1
            elif prefix == "+":
                out_lines.append(line_content)

    while orig_idx < len(orig_lines):
        out_lines.append(orig_lines[orig_idx])
        orig_idx += 1

    patched_text = "\n".join(out_lines)
    if original_text and original_text.endswith("\n") and not patched_text.endswith("\n"):
        patched_text += "\n"

    diff_lines = list(
        difflib.unified_diff(
            orig_lines,
            out_lines,
            fromfile="a/target",
            tofile="b/target",
            lineterm="",
        )
    )
    diff_str = "\n".join(diff_lines)

    return patched_text, diff_str, len(hunks)


def preview_patch_apply(
    conn: sqlite3.Connection,
    vault_key: bytes,
    artifact_id: str,
    workspace_root: str | Path,
    relative_target_path: str,
) -> WorkspacePatchPreview:
    """Generate a read-only preview of applying a patch artifact to a target file in the workspace.

    Does NOT modify any files on disk.
    """
    safe_target_path = resolve_safe_workspace_path(workspace_root, relative_target_path)
    meta = get_artifact_metadata(conn, artifact_id)
    raw_bytes = load_artifact_bytes(conn, vault_key, artifact_id)

    mime = (meta.mime_type or "").strip().lower()
    try:
        patch_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidPatchArtifactError(f"Patch artifact '{artifact_id}' contains invalid non-UTF-8 bytes.")

    from kin.artifacts.preview import _is_diff_content
    if mime not in ("text/x-diff", "text/x-patch") and not _is_diff_content(patch_text):
        raise InvalidPatchArtifactError(f"Artifact '{artifact_id}' (mime '{meta.mime_type}') is not a patch artifact.")

    target_exists = safe_target_path.exists() and safe_target_path.is_file()
    original_content = safe_target_path.read_text(encoding="utf-8") if target_exists else ""

    patched_content, unified_diff_str, hunks_count = apply_unified_patch(original_content, patch_text)

    return WorkspacePatchPreview(
        artifact_id=artifact_id,
        relative_target_path=relative_target_path,
        target_exists=target_exists,
        original_content=original_content,
        patched_content=patched_content,
        unified_diff=unified_diff_str,
        hunks_count=hunks_count,
    )


def _atomic_write_file(target_path: Path, content_bytes: bytes) -> None:
    """Write content_bytes to target_path using temp file + atomic replace."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f".tmp_{target_path.name}_{os.getpid()}")
    try:
        temp_path.write_bytes(content_bytes)
        temp_path.replace(target_path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def import_artifact_to_workspace(
    conn: sqlite3.Connection,
    vault_key: bytes,
    card: AgentCard,
    session_id: str,
    artifact_id: str,
    workspace_root: str | Path,
    relative_target_path: str,
    now: str,
) -> Path:
    """Import an artifact's raw bytes directly into the workspace target path.

    Gated by:
    1. Card workspace validation (requires local_command adapter).
    2. Path safety check (resolve_safe_workspace_path).
    3. Policy check via evaluate_action_for_session (must return PolicyDecision.ALLOW for WORKSPACE_WRITE).
    """
    resolved_root = validate_card_workspace(card, workspace_root)
    safe_target_path = resolve_safe_workspace_path(resolved_root, relative_target_path)

    session_ctx = {"session_id": session_id, "relative_target_path": relative_target_path}
    policy_res = evaluate_action_for_session(
        conn,
        card,
        ActionClass.WORKSPACE_WRITE,
        session_ctx,
        session_id,
        now,
    )
    if policy_res.decision != PolicyDecision.ALLOW:
        raise WorkspaceWritePermissionDeniedError(
            f"Workspace import for artifact '{artifact_id}' denied by policy: decision '{policy_res.decision.value}', reason: '{policy_res.reason}'"
        )

    raw_bytes = load_artifact_bytes(conn, vault_key, artifact_id)
    _atomic_write_file(safe_target_path, raw_bytes)
    return safe_target_path


def apply_patch_to_workspace(
    conn: sqlite3.Connection,
    vault_key: bytes,
    card: AgentCard,
    session_id: str,
    artifact_id: str,
    workspace_root: str | Path,
    relative_target_path: str,
    now: str,
) -> Path:
    """Apply a patch artifact to a workspace target file.

    Gated by:
    1. Card workspace validation (requires local_command adapter).
    2. Path safety check (resolve_safe_workspace_path).
    3. Policy check via evaluate_action_for_session (must return PolicyDecision.ALLOW for WORKSPACE_WRITE).
    """
    resolved_root = validate_card_workspace(card, workspace_root)
    preview = preview_patch_apply(conn, vault_key, artifact_id, resolved_root, relative_target_path)

    session_ctx = {"session_id": session_id, "relative_target_path": relative_target_path}
    policy_res = evaluate_action_for_session(
        conn,
        card,
        ActionClass.WORKSPACE_WRITE,
        session_ctx,
        session_id,
        now,
    )
    if policy_res.decision != PolicyDecision.ALLOW:
        raise WorkspaceWritePermissionDeniedError(
            f"Workspace patch apply for artifact '{artifact_id}' denied by policy: decision '{policy_res.decision.value}', reason: '{policy_res.reason}'"
        )

    patched_bytes = preview.patched_content.encode("utf-8")
    safe_target_path = resolve_safe_workspace_path(resolved_root, relative_target_path)
    _atomic_write_file(safe_target_path, patched_bytes)
    return safe_target_path
