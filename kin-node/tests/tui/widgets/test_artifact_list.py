"""Unit tests for ArtifactListWidget.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import pytest

from kin.artifacts.vault import ArtifactMetadata
from kin.tui.state import ArtifactView
from kin.tui.widgets import ArtifactListWidget


def test_artifact_list_sha256_digest_truncation():
    """REAL SHA-256 DIGEST TRUNCATION TEST (§14.5).

    Verifies ArtifactListWidget correctly formats a 64-character SHA-256 hex digest
    into first-8...last-8 format (e.g. a1b2c3d4...e5f6a7b8).
    """
    real_sha256 = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
    assert len(real_sha256) == 64

    meta = ArtifactMetadata(
        artifact_id="art_summary_json",
        session_id="sess_101",
        sha256=real_sha256,
        mime_type="application/json",
        size_bytes=2048,
        offered_by="scout",
        preview_policy="text",
        created_at="2026-07-28T12:00:00Z",
    )
    art_view = ArtifactView.from_metadata(meta)
    widget = ArtifactListWidget(artifacts=[art_view])

    rendered = widget.render()

    # Assert 64-char hash formatted to first-8...last-8
    expected_truncated = "a1b2c3d4...e9f0a1b2"
    assert expected_truncated in rendered
    assert real_sha256 not in rendered  # Full 64-char string is truncated in display
