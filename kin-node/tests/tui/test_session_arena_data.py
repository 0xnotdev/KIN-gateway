"""Unit tests for Session Arena data layer and event classification (§14.8 Phase A).

Covers:
1. Chronological merging of session_events and audit_events covering all 6 reachable presentation classes.
2. Strict ValueError exception on unrecognized audit categories.
3. Inclusion of decided approvals in get_approvals_for_session vs exclusion in get_pending_approvals.
4. Session list and detail queries using migrated DB schema (initiator_username/receiver_username).
5. Artifact view querying for session artifacts.
"""

from pathlib import Path
import pytest

from kin.schemas import MessageKind
from kin.tui.local_state import (
    ensure_profile_db,
    get_approvals_for_session,
    get_artifacts_for_session,
    get_pending_approvals,
    get_session_detail,
    get_session_events,
    get_session_list,
)
from kin.tui.state import (
    AUDIT_CATEGORY_MAPPING,
    map_audit_category_to_presentation_class,
    map_event_kind_to_presentation_class,
    UiEvent,
)


@pytest.fixture
def session_db(tmp_path: Path):
    """Seed profile SQLite DB with session records across session_events, audit_events, approvals, artifacts."""
    db_path = tmp_path / "kin.db"
    conn = ensure_profile_db(db_path)
    cur = conn.cursor()

    # 1. Seed sessions table row
    cur.execute(
        """
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, turn_limit, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "sess-arena-100",
            "research",
            "alice",
            "bob",
            "active",
            "Investigate codebase architecture",
            12,
            "2026-08-01T10:00:00Z",
            "2026-08-01T10:05:00Z",
        ),
    )

    # 2. Seed session_events covering message, state_transition, activity, artifact, approval
    events_data = [
        ("evt-1", "sess-arena-100", 1, "alice", "task_request", "2026-08-01T10:00:05Z"),
        ("evt-2", "sess-arena-100", 2, "bob", "acceptance", "2026-08-01T10:00:10Z"),
        ("evt-3", "sess-arena-100", 3, "bob", "finding", "2026-08-01T10:00:15Z"),
        ("evt-4", "sess-arena-100", 4, "bob", "artifact_offer", "2026-08-01T10:00:20Z"),
        ("evt-5", "sess-arena-100", 5, "bob", "approval_request", "2026-08-01T10:00:25Z"),
    ]
    for row in events_data:
        cur.execute(
            """
            INSERT INTO session_events (
                event_id, session_id, event_order, actor_username, kind, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    # 3. Seed audit_events for security_rejection (security class)
    cur.execute(
        """
        INSERT INTO audit_events (
            audit_id, correlation_id, session_id, category, actor_username, summary, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "aud-sec-1",
            "corr-1",
            "sess-arena-100",
            "security_rejection",
            "eve",
            "Signature verification failed for sequence 4",
            "2026-08-01T10:00:18Z",  # Interleaved between evt-3 and evt-4
        ),
    )

    # 4. Seed approvals table: 1 pending, 1 decided (approved)
    cur.execute(
        """
        INSERT INTO approvals (
            approval_id, session_id, agent_id, action_class, expires_at, decision, decided_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "appr-pending-1",
            "sess-arena-100",
            "scout-1",
            "workspace_write",
            "2026-08-01T12:00:00Z",
            None,
            None,
        ),
    )
    cur.execute(
        """
        INSERT INTO approvals (
            approval_id, session_id, agent_id, action_class, expires_at, decision, decided_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "appr-decided-1",
            "sess-arena-100",
            "scout-1",
            "workspace_write",
            "2026-08-01T11:00:00Z",
            "approve_once",
            "2026-08-01T10:04:00Z",
        ),
    )

    # 5. Seed artifacts table
    cur.execute(
        """
        INSERT INTO artifacts (
            artifact_id, session_id, sha256, mime_type, bytes_encrypted, offered_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "art-1",
            "sess-arena-100",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "text/markdown",
            b"Report contents",
            "bob",
            "2026-08-01T10:00:22Z",
        ),
    )

    conn.commit()
    conn.close()
    return tmp_path


def test_session_list_and_detail_queries(session_db: Path):
    """Assert get_session_list and get_session_detail return accurate SessionSummary (§14.8 Phase A)."""
    sessions = get_session_list(session_db)
    assert len(sessions) == 1
    summary = sessions[0]
    assert summary.session_id == "sess-arena-100"
    assert summary.type == "research"
    assert summary.initiator_username == "alice"
    assert summary.receiver_username == "bob"
    assert summary.objective == "Investigate codebase architecture"

    detail = get_session_detail(session_db, "sess-arena-100")
    assert detail is not None
    assert detail.session_id == "sess-arena-100"
    assert detail.initiator_username == "alice"

    # Non-existent session
    assert get_session_detail(session_db, "non-existent") is None


def test_session_events_merging_all_6_classes_chronological(session_db: Path):
    """Assert session_events and audit_events merge chronologically covering all 6 reachable presentation classes (§14.8 Phase A)."""
    events = get_session_events(session_db, "sess-arena-100")
    assert len(events) == 6

    # Verify strict chronological order
    created_timestamps = [e.created_at for e in events]
    assert created_timestamps == sorted(created_timestamps)

    # Verify mapped presentation classes
    p_classes = {e.event_id: e.presentation_class for e in events}
    assert p_classes["evt-1"] == "message"            # task_request
    assert p_classes["evt-2"] == "state_transition"   # acceptance
    assert p_classes["evt-3"] == "activity"           # finding
    assert p_classes["aud-sec-1"] == "security"       # security_rejection from audit_events!
    assert p_classes["evt-4"] == "artifact"           # artifact_offer
    assert p_classes["evt-5"] == "approval"           # approval_request

    # Verify all 6 presentation classes are represented
    all_classes = {e.presentation_class for e in events}
    assert all_classes == {"message", "state_transition", "activity", "security", "artifact", "approval"}


def test_unrecognized_audit_category_raises():
    """Assert an unrecognized audit category raises ValueError matching map_event_kind_to_presentation_class (§14.8 Phase A)."""
    with pytest.raises(ValueError, match="Unrecognized audit category"):
        map_audit_category_to_presentation_class("fabricated_invalid_category")

    # Verify valid mappings return expected presentation classes
    assert map_audit_category_to_presentation_class("security_rejection") == "security"
    assert map_audit_category_to_presentation_class("duplicate_delivery") == "activity"
    assert map_audit_category_to_presentation_class("session_status_updated") == "state_transition"
    assert map_audit_category_to_presentation_class("approval_request") == "approval"

    # Verify session_event_ prefix delegation
    assert map_audit_category_to_presentation_class("session_event_task_request") == "message"


def test_get_approvals_for_session_includes_decided(session_db: Path):
    """Assert get_approvals_for_session includes decided approvals while get_pending_approvals excludes them (§14.8 Phase A)."""
    # 1. get_pending_approvals excludes decided approval
    pending = get_pending_approvals(session_db)
    assert len(pending) == 1
    assert pending[0].request.approval_id == "appr-pending-1"

    # 2. get_approvals_for_session includes both pending and decided approvals for session
    all_session_approvals = get_approvals_for_session(session_db, "sess-arena-100")
    assert len(all_session_approvals) == 2
    app_ids = {a.request.approval_id for a in all_session_approvals}
    assert app_ids == {"appr-pending-1", "appr-decided-1"}

    # Assert decided approval has non-None decision
    decided_view = next(a for a in all_session_approvals if a.request.approval_id == "appr-decided-1")
    assert decided_view.decision is not None
    assert decided_view.decision.decision.value == "approve_once"


def test_get_artifacts_for_session(session_db: Path):
    """Assert get_artifacts_for_session queries artifacts into List[ArtifactView] (§14.8 Phase A)."""
    artifacts = get_artifacts_for_session(session_db, "sess-arena-100")
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art.metadata.artifact_id == "art-1"
    assert art.metadata.mime_type == "text/markdown"
    assert art.metadata.offered_by == "bob"
    assert art.preview_available is True
