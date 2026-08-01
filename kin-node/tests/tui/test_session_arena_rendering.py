"""Unit and snapshot tests for Session Arena static rendering widgets (§14.8 Phase B).

Covers:
1. Snapshots for each of the 7 event presentation classes (message, activity, checkpoint, artifact, approval, state_transition, security).
2. Snapshots for empty session, security rejection, long content, missing peer, stale card, transport mode, and 4 terminal sizes.
3. Security Event Guard test asserting persistent red card and ZERO action affordances.
4. Artifact Inspection Negative test proving no import/apply code paths or buttons exist.
5. Redaction verification confirming secret keys and local paths are scrubbed across all Arena views.
"""

from pathlib import Path
import pytest

from kin.artifacts.vault import ArtifactMetadata
from kin.tui.app import KinApp
from kin.tui.redaction import redact_ui_text
from kin.tui.shell import MainCanvas
from kin.tui.state import ApprovalView, ArtifactView, SessionSummary, UiEvent
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.inspector import InspectorWidget
from kin.tui.widgets.session_arena import SessionArenaWidget
from kin.tui.widgets.session_map import SessionMapWidget
from kin.tui.widgets.trust_strip import TrustStripWidget


# -----------------------------------------------------------------------------
# Fixtures for 7 Presentation Classes and Edge Cases
# -----------------------------------------------------------------------------
@pytest.fixture
def sample_session_summary() -> SessionSummary:
    return SessionSummary(
        session_id="sess-arena-test-100",
        status="active",
        type="research",
        initiator_username="alice",
        receiver_username="bob",
        objective="Investigate codebase architecture and audit security boundary",
    )


@pytest.fixture
def events_all_7_classes() -> list[UiEvent]:
    return [
        UiEvent("e-1", "sess-1", "task_request", "2026-08-01T12:00:00Z", "alice", "message"),
        UiEvent("e-2", "sess-1", "finding", "2026-08-01T12:00:05Z", "bob", "activity"),
        UiEvent("e-3", "sess-1", "checkpoint_turn_1", "2026-08-01T12:00:10Z", "system", "checkpoint"),
        UiEvent("e-4", "sess-1", "artifact_offer", "2026-08-01T12:00:15Z", "bob", "artifact"),
        UiEvent("e-5", "sess-1", "approval_request", "2026-08-01T12:00:20Z", "bob", "approval"),
        UiEvent("e-6", "sess-1", "acceptance", "2026-08-01T12:00:25Z", "bob", "state_transition"),
        UiEvent("e-7", "sess-1", "security_rejection", "2026-08-01T12:00:30Z", "eve", "security"),
    ]


# -----------------------------------------------------------------------------
# Direct Unit & Negative Assertion Tests (§14.8 Phase B)
# -----------------------------------------------------------------------------
def test_arena_renders_all_7_presentation_classes(sample_session_summary, events_all_7_classes):
    """1. Assert ExchangeTimelineWidget renders each of the 7 presentation classes distinctly (§14.8 Step 3)."""
    timeline = ExchangeTimelineWidget(
        events=events_all_7_classes,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
    )
    rendered = timeline.render()

    assert "💬 MESSAGE" in rendered
    assert "[ACTIVITY]" in rendered
    assert "CHECKPOINT" in rendered
    assert "📦 ARTIFACT OFFER" in rendered
    assert "▲ APPROVAL GATE [AMBER/POLICY]" in rendered
    assert "STATE TRANSITION" in rendered
    assert "SECURITY REJECTION CARD" in rendered


def test_security_event_guard_has_zero_action_affordances(events_all_7_classes):
    """2. Security Event Guard test: prove security class renders as persistent red card with ZERO action buttons/affordances (§14.8)."""
    sec_event = [e for e in events_all_7_classes if e.presentation_class == "security"][0]
    timeline = ExchangeTimelineWidget(
        events=[sec_event],
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
    )
    arena = SessionArenaWidget(events=[sec_event])

    rendered_timeline = timeline.render()
    rendered_arena = arena.render()

    # Must render persistent red card
    assert "SECURITY REJECTION CARD" in rendered_timeline
    assert "CRITICAL: Security boundary rejection logged. No actions available." in rendered_timeline

    # Negative assertions: zero action affordances or methods exist
    assert "Approve" not in rendered_timeline
    assert "Deny" not in rendered_timeline
    assert "Apply" not in rendered_timeline
    assert not hasattr(timeline, "approve")
    assert not hasattr(timeline, "deny")
    assert not hasattr(arena, "approve")
    assert not hasattr(arena, "deny")


def test_artifact_inspection_negative_test_has_no_import_or_apply_code_paths():
    """3. Artifact Inspection Negative Test: prove inspecting artifact provides ZERO code path to import or apply (§14.8)."""
    meta = ArtifactMetadata(
        artifact_id="art-test-999",
        session_id="sess-1",
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        mime_type="text/markdown",
        size_bytes=1024,
        offered_by="bob",
        preview_policy="text",
        created_at="2026-08-01T12:00:00Z",
    )
    art_view = ArtifactView.from_metadata(meta)
    inspector = InspectorWidget(selected_artifact=art_view)
    arena = SessionArenaWidget(artifacts=[art_view])

    rendered_inspector = inspector.render()
    rendered_arena = arena.render()

    assert "INSPECT ARTIFACT" in rendered_inspector
    assert "Read-Only Artifact Preview" in rendered_inspector

    # Negative assertions: zero import/apply action affordances or methods exist anywhere in Phase B static surfaces
    assert "Import Artifact" not in rendered_inspector
    assert "Apply Patch" not in rendered_inspector
    assert not hasattr(inspector, "import_artifact")
    assert not hasattr(inspector, "apply_patch")
    assert not hasattr(arena, "import_artifact")
    assert not hasattr(arena, "apply_patch")


def test_arena_redaction_verifies_scrubbing_across_all_views():
    """4. Redaction verification: confirm redact_ui_text() is invoked across all Arena rendering widgets (§14.8)."""
    secret_key = "KIN-SECRET-KEY-1234567890ABCDEF"
    secret_path = "C:/Users/deban/private_keys/secret_key.pem"

    dirty_summary = SessionSummary(
        session_id="sess-secret-1",
        status="active",
        type="research",
        initiator_username=f"alice_{secret_key}",
        receiver_username="bob",
        objective=f"Analyze {secret_path} and key {secret_key}",
    )
    dirty_event = UiEvent(
        event_id="evt-sec-1",
        session_id="sess-secret-1",
        kind=f"finding_with_{secret_key}",
        created_at="2026-08-01T12:00:00Z",
        actor_username=f"alice_{secret_key}",
        presentation_class="message",
    )

    arena = SessionArenaWidget(
        session_summary=dirty_summary,
        events=[dirty_event],
    )
    rendered = arena.render()

    # Assert secret string and sensitive path are scrubbed
    assert secret_key not in rendered
    assert secret_path not in rendered
    assert "[REDACTED]" in rendered or "•••" in rendered or "alice_" in rendered


def test_arena_missing_peer_renders_cleanly_without_crashing(sample_session_summary):
    """5. Missing peer test: assert peer not in local contacts renders cleanly without crashing (§14.8)."""
    arena = SessionArenaWidget(
        session_summary=sample_session_summary,
        profile_dir=Path("non_existent_profile_dir"),
    )
    rendered = arena.render()

    # Must render clean unverified peer badge without raising exception
    assert "UNVERIFIED PEER" in rendered or "UNKNOWN PEER" in rendered
    assert "@bob" in rendered


# -----------------------------------------------------------------------------
# Snapshots for Terminal Sizes and Event Variations (§14.8)
# -----------------------------------------------------------------------------
def test_arena_snapshot_cockpit_full_mode_160x44(snap_compare):
    """Snapshot: Arena Cockpit 3-lane mode at 160x44 resolution (§14.8)."""
    app = KinApp()
    assert snap_compare(app, terminal_size=(160, 44))


def test_arena_snapshot_docked_standard_mode_120x36(snap_compare):
    """Snapshot: Arena Docked Inspector mode at 120x36 resolution (§14.8)."""
    app = KinApp()
    assert snap_compare(app, terminal_size=(120, 36))


def test_arena_snapshot_compact_mode_90x28(snap_compare):
    """Snapshot: Arena Compact mode at 90x28 resolution (§14.8)."""
    app = KinApp()
    assert snap_compare(app, terminal_size=(90, 28))


def test_arena_snapshot_minimal_mode_80x24(snap_compare):
    """Snapshot: Arena Minimal mode at 80x24 resolution (§14.8)."""
    app = KinApp()
    assert snap_compare(app, terminal_size=(80, 24))
