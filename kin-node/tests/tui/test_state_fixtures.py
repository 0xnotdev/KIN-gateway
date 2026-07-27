"""Unit tests for typed view model fixture factories and peer security boundary.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.8, §14.1, §14.6
"""

from datetime import datetime, timezone
import pytest

from kin.schemas import (
    ActionClass,
    AgentAvailability,
    ApprovalRequest,
    DecisionKind,
    InternalEventKind,
    MessageKind,
    RiskLabel,
)
from kin.session.transition_matrix import VALID_TRANSITIONS
from kin.tui.fixtures import (
    ALL_4_DECISION_KINDS,
    ALL_4_RISK_LABELS,
    ALL_8_AVAILABILITY_VALUES,
    ALL_16_SESSION_STATUSES,
    FROZEN_CLOCK,
    make_agent_card_view_fixture,
    make_all_agent_card_view_fixtures,
    make_all_approval_view_fixtures,
    make_all_session_summary_fixtures,
    make_approval_view_fixture,
    make_artifact_view_fixture,
    make_default_uistate_fixture,
    make_recoverable_error_fixture,
    make_session_summary_fixture,
)
from kin.tui.state import (
    ApprovalView,
    AgentCardView,
    UiEvent,
    map_event_kind_to_presentation_class,
)


def test_session_summary_factories_cover_all_16_statuses():
    """Assert fixture factories produce valid SessionSummary for all 16 transition statuses."""
    summaries = make_all_session_summary_fixtures()
    assert set(summaries.keys()) == set(VALID_TRANSITIONS.keys())
    assert len(summaries) == 16
    for status, summary in summaries.items():
        assert summary.status == status
        assert len(summary.participant_display_names) > 0
        assert summary.current_turn <= summary.max_turns


def test_agent_card_view_factories_cover_all_8_availabilities():
    """Assert fixture factories produce valid AgentCardView for all 8 availability states."""
    views = make_all_agent_card_view_fixtures()
    assert len(views) == 8
    availabilities = {v.availability for v in views}
    assert availabilities == set(ALL_8_AVAILABILITY_VALUES)


def test_approval_view_factories_cover_risk_labels_and_decisions():
    """Assert approval view factories cover all 4 risk labels and 4 decision kinds."""
    views = make_all_approval_view_fixtures()
    # 4 risk labels + 4 decision kinds = 8 total
    assert len(views) == 8

    # Assert risk labels represented
    risk_labels_found = {v.request.risk_label for v in views if v.decision is None}
    assert risk_labels_found == set(ALL_4_RISK_LABELS)

    # Assert decision kinds represented
    decisions_found = {v.decision.decision for v in views if v.decision is not None}
    assert decisions_found == set(ALL_4_DECISION_KINDS)


def test_approval_view_injectable_clock_determinism():
    """Regression test proving time_remaining is stable when a fixed clock is supplied.

    Proves that when `now` is passed (datetime or string), time_remaining is perfectly deterministic
    and independent of wall-clock execution time, but falls back to wall-clock when omitted.
    """
    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="appr-test-clk",
        session_id="sess-clk-001",
        agent_id="code-scout",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Test injectable clock",
        reason="Verification",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-26T13:00:00.000Z",
    )

    # 1. Deterministic calculation with explicit datetime now (1 hour before expiry)
    now_dt = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
    view_fixed = ApprovalView(request=req, now=now_dt)
    assert view_fixed.time_remaining == 3600.0

    # 2. Deterministic calculation with explicit ISO string now
    view_str = ApprovalView(request=req, now="2026-07-26T12:30:00.000Z")
    assert view_str.time_remaining == 1800.0

    # 3. Fallback to real wall-clock time when `now` is omitted (now_dt is in the past relative to 2026-07-26)
    view_wall = ApprovalView(request=req)
    assert view_wall.time_remaining is not None
    # Verify that omitting `now` evaluated wall-clock without crashing
    assert isinstance(view_wall.time_remaining, float)


def test_artifact_view_factory_mime_variants():
    """Assert ArtifactView factories produce correct display size and preview availability for MIME variants."""
    md_view = make_artifact_view_fixture("markdown")
    assert md_view.preview_available is True
    assert "KB" in md_view.display_size

    csv_view = make_artifact_view_fixture("csv")
    assert csv_view.preview_available is True
    assert "MB" in csv_view.display_size

    bin_view = make_artifact_view_fixture("binary")
    assert bin_view.preview_available is False
    assert "B" in bin_view.display_size


def test_recoverable_error_factories():
    """Assert recoverable error factories construct valid technical detail cards."""
    for failure in ("relay", "keychain", "adapter"):
        err = make_recoverable_error_fixture(failure)
        assert err.what_happened
        assert err.impact
        assert err.preserved
        assert err.next_action
        assert err.technical_detail is not None


def test_default_uistate_fixture_construction():
    """Assert default UiState constructs cleanly."""
    state = make_default_uistate_fixture()
    assert state.profile_health.keychain_ok is True
    assert len(state.workspaces) == 2
    assert state.active_tab_id == "tab-home"


def test_peer_agent_card_view_security_isolation():
    """CRITICAL SECURITY TEST: Peer AgentCardView MUST NOT leak private local fields.

    Asserts none of {adapter, working_directory, credential_ref, boundaries} leak into
    a peer AgentCardView context.
    """
    peer_view = make_agent_card_view_fixture(AgentAvailability.READY, is_peer=True)

    assert peer_view.is_peer is True

    # Assert peer AgentCardView has no adapter/directory/credential attributes
    forbidden_attrs = ["adapter", "working_directory", "credential_ref", "boundaries"]
    for attr in forbidden_attrs:
        assert not hasattr(
            peer_view, attr
        ), f"Peer AgentCardView leaked private attribute '{attr}'!"

    # Assert __dict__ does not expose adapter config or working directory
    view_dict_keys = peer_view.__dict__.keys()
    for forbidden in forbidden_attrs:
        assert (
            forbidden not in view_dict_keys
        ), f"Peer AgentCardView dict exposed forbidden key '{forbidden}'"


def test_exhaustive_presentation_class_mapping_purity():
    """EXHAUSTIVE mapping test for every MessageKind and InternalEventKind member.

    Asserts every single enum member maps to a valid presentation class per §7.2,
    and invalid kinds raise ValueError (loud failure mode for schema additions).
    """
    # 1. Test all 18 MessageKind members
    for m_kind in MessageKind:
        p_class = map_event_kind_to_presentation_class(m_kind)
        assert p_class in (
            "message",
            "activity",
            "checkpoint",
            "artifact",
            "approval",
            "state_transition",
            "security",
        )
        # Verify string name mapping equivalence
        assert map_event_kind_to_presentation_class(m_kind.value) == p_class

    # 2. Test all 7 InternalEventKind members
    for i_kind in InternalEventKind:
        p_class = map_event_kind_to_presentation_class(i_kind)
        assert p_class in (
            "message",
            "activity",
            "checkpoint",
            "artifact",
            "approval",
            "state_transition",
            "security",
        )
        assert map_event_kind_to_presentation_class(i_kind.value) == p_class

    # 3. Assert adapter_error explicitly maps to "security" (error visibility guarantee)
    assert map_event_kind_to_presentation_class(InternalEventKind.ADAPTER_ERROR) == "security"

    # 4. Assert unrecognized kinds raise ValueError
    with pytest.raises(ValueError, match="Unrecognized event kind"):
        map_event_kind_to_presentation_class("nonexistent_event_kind_12345")
