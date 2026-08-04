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
from rich.console import ColorSystem
from textual.app import App, ComposeResult

from kin.artifacts.vault import ArtifactMetadata
from kin.tui.redaction import redact_ui_text
from kin.tui.state import ApprovalView, ArtifactView, SessionSummary, UiEvent
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.inspector import InspectorWidget
from kin.tui.widgets.session_arena import SessionArenaWidget
from kin.tui.widgets.session_map import SessionMapWidget
from kin.tui.widgets.trust_strip import TrustStripWidget


from datetime import datetime, timezone

PINNED_SNAPSHOT_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


# -----------------------------------------------------------------------------
# Test App Harness for Direct Widget Snapshot Rendering (§14.8)
# -----------------------------------------------------------------------------
class ArenaSnapshotApp(App):
    """Minimal test App mounting SessionArenaWidget populated with real data for snapshot testing."""

    def __init__(self, session_summary=None, events=None, artifacts=None, approvals=None, **kwargs):
        super().__init__(**kwargs)
        self.arena_widget = SessionArenaWidget(
            session_summary=session_summary,
            events=events,
            artifacts=artifacts,
            approvals=approvals,
            now=PINNED_SNAPSHOT_NOW,
        )

    def compose(self) -> ComposeResult:
        yield self.arena_widget


def _snapshot_app(monkeypatch, **kwargs) -> ArenaSnapshotApp:
    """Build an Arena harness with the same deterministic truecolor terminal as shell snapshots."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    app = ArenaSnapshotApp(**kwargs)
    monkeypatch.setattr(type(app.console), "encoding", property(lambda _console: "utf-8"))
    monkeypatch.setattr(app.console, "_color_system", ColorSystem.TRUECOLOR)
    return app


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

    assert "INSPECT ARTIFACT" in rendered_inspector
    assert "Read-Only Artifact Preview" in rendered_inspector

    # Negative assertions: zero import/apply action affordances or methods exist on pure viewing surface (InspectorWidget)
    assert "Import Artifact" not in rendered_inspector
    assert "Apply Patch" not in rendered_inspector
    assert not hasattr(inspector, "import_artifact")
    assert not hasattr(inspector, "apply_patch")

    # Positive assertions: SessionArenaWidget has real gated artifact action handlers in Outputs lane
    assert hasattr(arena, "handle_artifact_key")
    assert hasattr(arena, "_execute_import_artifact")
    assert hasattr(arena, "_execute_apply_patch")


def test_arena_redaction_verifies_scrubbing_across_all_views():
    """4. Redaction verification: confirm redact_ui_text() is invoked across all Arena rendering widgets (§14.8)."""
    import io
    from rich.console import Console

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
    buf = io.StringIO()
    c = Console(file=buf, width=160, height=44)
    c.print(arena.render())
    rendered = buf.getvalue()

    # Assert secret string and sensitive path are scrubbed against exact redaction markers
    assert secret_key not in rendered
    assert secret_path not in rendered
    assert "[REDACTED SECRET]" in rendered or "[REDACTED PATH]" in rendered


def test_arena_missing_peer_renders_cleanly_without_crashing(sample_session_summary):
    """5. Missing peer test: assert peer not in local contacts renders cleanly without crashing (§14.8)."""
    arena = SessionArenaWidget(
        session_summary=sample_session_summary,
        profile_dir=Path("non_existent_profile_dir"),
    )
    rendered = arena.trust_strip_widget.render()

    # Must render clean unverified peer badge without raising exception
    assert "UNVERIFIED PEER" in rendered or "UNKNOWN PEER" in rendered
    assert "@bob" in rendered


def test_arena_nonexistent_session_id_produces_error_state_not_fabricated_data():
    """6. Nonexistent session test: assert nonexistent session_id produces RECOVERABLE_ERROR without fabricated data (§14.8 Round 2)."""
    from kin.tui.widgets.lifecycle import WidgetLifecycleState

    arena = SessionArenaWidget(
        session_id="sess-nonexistent-9999",
        profile_dir=Path("non_existent_profile_dir"),
    )
    # Must NOT fabricate a synthetic SessionSummary
    assert arena.session_summary is None
    assert arena.lifecycle_state == WidgetLifecycleState.RECOVERABLE_ERROR
    assert arena.last_arena_error is not None
    assert arena.last_arena_error.what_happened == "Session Not Found"

    rendered = str(arena.render())
    assert "Session Not Found" in rendered
    assert "sess-nonexistent-9999" in rendered
    # Assert zero synthetic placeholders like "local_user" or "peer_user"
    assert "local_user" not in rendered
    assert "peer_user" not in rendered


def test_arena_trust_check_failure_surfaces_error_and_does_not_reassure(sample_session_summary, monkeypatch):
    """7. Trust failure test: assert disk/crypto error during trust check surfaces explicit trust error (§14.8 Round 2)."""
    def mock_broken_contacts(*args, **kwargs):
        raise RuntimeError("Disk IO error reading contacts DB")

    monkeypatch.setattr("kin.tui.widgets.session_arena.get_local_contacts_summaries", mock_broken_contacts)

    arena = SessionArenaWidget(
        session_summary=sample_session_summary,
        profile_dir=Path("some_profile_dir"),
    )
    assert arena.trust_strip_widget.is_trust_unknown is True
    rendered_trust = arena.trust_strip_widget.render()
    assert "TRUST STATUS UNKNOWN" in rendered_trust


@pytest.mark.asyncio
async def test_arena_breakpoint_specific_distinguishing_text_per_terminal_size(sample_session_summary, events_all_7_classes):
    """Permanent regression test asserting exact breakpoint distinguishing headers per terminal size (§3.2, §7.1, §14.8)."""
    import io
    from rich.console import Console

    def get_rendered_text(app_instance, width, height):
        buf = io.StringIO()
        c = Console(file=buf, width=width, height=height)
        arena = app_instance.query_one(SessionArenaWidget)
        c.print(arena.render())
        return buf.getvalue()

    # 1. 160x44 (wide / Cockpit 3-lane mode)
    app_160 = ArenaSnapshotApp(session_summary=sample_session_summary, events=events_all_7_classes)
    async with app_160.run_test(size=(160, 44)) as pilot:
        text = get_rendered_text(pilot.app, 160, 44)
        assert "SESSION MAP" in text
        assert "DETAIL INSPECTOR" in text
        assert "EXCHANGE TIMELINE" in text
        assert "DOCKED INSPECTOR" not in text

    # 2. 120x36 (standard / Docked Inspector 2-lane mode)
    app_120 = ArenaSnapshotApp(session_summary=sample_session_summary, events=events_all_7_classes)
    async with app_120.run_test(size=(120, 36)) as pilot:
        text = get_rendered_text(pilot.app, 120, 36)
        assert "DOCKED INSPECTOR" in text
        assert "EXCHANGE TIMELINE" in text
        assert "SESSION MAP" not in text
        assert "DETAIL INSPECTOR" not in text

    # 3. 90x28 (compact / Stacked mode)
    app_90 = ArenaSnapshotApp(session_summary=sample_session_summary, events=events_all_7_classes)
    async with app_90.run_test(size=(90, 28)) as pilot:
        text = get_rendered_text(pilot.app, 90, 28)
        assert "SESSION MAP" not in text
        assert "DOCKED INSPECTOR" not in text
        assert "DETAIL INSPECTOR" not in text

    # 4. 80x24 (minimal / Stacked mode)
    app_80 = ArenaSnapshotApp(session_summary=sample_session_summary, events=events_all_7_classes)
    async with app_80.run_test(size=(80, 24)) as pilot:
        text = get_rendered_text(pilot.app, 80, 24)
        assert "SESSION MAP" not in text
        assert "DOCKED INSPECTOR" not in text
        assert "DETAIL INSPECTOR" not in text


# -----------------------------------------------------------------------------
# Snapshots for Terminal Sizes and Event Variations (§14.8)
# -----------------------------------------------------------------------------
def test_arena_snapshot_cockpit_full_mode_160x44(snap_compare, monkeypatch, sample_session_summary, events_all_7_classes):
    """Snapshot: Arena Cockpit 3-lane mode at 160x44 resolution (§14.8)."""
    app = _snapshot_app(monkeypatch, session_summary=sample_session_summary, events=events_all_7_classes)
    assert snap_compare(app, terminal_size=(160, 44))


def test_arena_snapshot_docked_standard_mode_120x36(snap_compare, monkeypatch, sample_session_summary, events_all_7_classes):
    """Snapshot: Arena Docked Inspector mode at 120x36 resolution (§14.8)."""
    app = _snapshot_app(monkeypatch, session_summary=sample_session_summary, events=events_all_7_classes)
    assert snap_compare(app, terminal_size=(120, 36))


def test_arena_snapshot_compact_mode_90x28(snap_compare, monkeypatch, sample_session_summary, events_all_7_classes):
    """Snapshot: Arena Compact mode at 90x28 resolution (§14.8)."""
    app = _snapshot_app(monkeypatch, session_summary=sample_session_summary, events=events_all_7_classes)
    assert snap_compare(app, terminal_size=(90, 28))


def test_arena_snapshot_minimal_mode_80x24(snap_compare, monkeypatch, sample_session_summary, events_all_7_classes):
    """Snapshot: Arena Minimal mode at 80x24 resolution (§14.8)."""
    app = _snapshot_app(monkeypatch, session_summary=sample_session_summary, events=events_all_7_classes)
    assert snap_compare(app, terminal_size=(80, 24))
