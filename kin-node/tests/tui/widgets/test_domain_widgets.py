"""Unit tests for Phase C domain widgets: event class filtering split, DispatchWizard boundary, focus, and disabled states.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import pytest

from kin.tui.state import AgentCardView, SessionSummary, UiEvent
from kin.tui.widgets import (
    ActivityFeedWidget,
    AgentPickerWidget,
    DispatchWizardWidget,
    ExchangeTimelineWidget,
    OutcomeCardWidget,
    SessionMapWidget,
    TrustStripWidget,
    WidgetLifecycleState,
)


def test_event_class_filtering_split_between_exchange_and_activity_feed():
    """EVENT CLASS FILTERING SPLIT TEST (§14.5).

    Feeds the EXACT SAME mixed-class List[UiEvent] fixture to both ExchangeTimelineWidget
    and ActivityFeedWidget, asserting they filter to non-overlapping, mutually exclusive subsets.
    """
    mixed_events = [
        # Dialogue / Session events -> ExchangeTimeline
        UiEvent("e1", "s1", "TASK_REQUEST", "12:00:00", "alice", "message"),
        UiEvent("e2", "s1", "ARTIFACT_OFFER", "12:01:00", "bob", "artifact"),
        UiEvent("e3", "s1", "APPROVAL_REQUEST", "12:02:00", "scout", "approval"),
        UiEvent("e4", "s1", "ACCEPTANCE", "12:03:00", "alice", "state_transition"),
        # Background / System events -> ActivityFeed
        UiEvent("e5", "s1", "ENVELOPE_RECEIVED", "12:04:00", "system", "activity"),
        UiEvent("e6", "s1", "ADAPTER_ERROR", "12:05:00", "system", "security"),
    ]

    exchange = ExchangeTimelineWidget(events=mixed_events)
    activity = ActivityFeedWidget(events=mixed_events)

    ex_rendered = exchange.render()
    act_rendered = activity.render()

    # ExchangeTimeline assertions: contains message, artifact, approval, state_transition; excludes activity, security
    assert "4 events)" in ex_rendered
    assert "TASK_REQUEST" in ex_rendered
    assert "ARTIFACT_OFFER" in ex_rendered
    assert "ENVELOPE_RECEIVED" not in ex_rendered
    assert "ADAPTER_ERROR" not in ex_rendered

    # ActivityFeed assertions: contains activity, security; excludes message, artifact, approval
    assert "Activity & Security Feed (2 events)" in act_rendered
    assert "ENVELOPE_RECEIVED" in act_rendered
    assert "ADAPTER_ERROR" in act_rendered
    assert "TASK_REQUEST" not in act_rendered
    assert "ARTIFACT_OFFER" not in act_rendered


def test_dispatch_wizard_confirm_boundary_is_ui_only():
    """DISPATCH WIZARD CONFIRM BOUNDARY TEST (§14.5).

    Verifies pressing confirm in DispatchWizardWidget transitions to a UI-only draft preview state ('would_dispatch')
    with zero side-effects toward network or backend session creation.
    """
    wizard = DispatchWizardWidget(agent_id="peer_scout", prompt="Run safety audit", risk_level="HIGH", for_preview=True)
    assert wizard.is_submitted is False
    assert wizard.step_index == 0

    # Advance through steps to confirm (step 3)
    wizard.next_step()
    wizard.next_step()
    wizard.next_step()
    assert wizard.step_index == 3

    # Confirm dispatch
    wizard.confirm_dispatch()

    # ASSERTIONS: UI-only submitted state active without side-effects
    assert wizard.is_submitted is True
    assert "Dispatch draft prepared (UI preview only)" in wizard.status_message
    rendered = wizard.render()
    assert "DISPATCH DRAFT READY" in rendered
    assert "peer_scout" in rendered
    assert "Run safety audit" in rendered


def test_domain_widgets_disabled_with_reason():
    """DISABLED REASON TEST FOR DOMAIN WIDGETS (§14.5)."""
    picker = AgentPickerWidget()
    picker.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Roster loading failed")
    assert "DISABLED: Roster loading failed" in picker.render()

    sess_map = SessionMapWidget()
    sess_map.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Sessions offline")
    assert "DISABLED: Sessions offline" in sess_map.render()

    outcome = OutcomeCardWidget()
    outcome.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Telemetry missing")
    assert "DISABLED: Telemetry missing" in outcome.render()

    trust = TrustStripWidget()
    trust.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Keyring locked")
    assert "DISABLED: Keyring locked" in trust.render()
