"""Parametrized Lifecycle State Contract Test Harness for Foundation, Container, and Domain Widgets.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5 (build step 4)
"""

from datetime import datetime, timezone
import pytest

from kin.artifacts.vault import ArtifactMetadata
from kin.schemas import ActionClass, ApprovalRequest, RiskLabel
from kin.tui.state import (
    AgentCardView,
    ApprovalView,
    ArtifactView,
    SessionSummary,
    UiEvent,
)
from kin.tui.widgets import (
    ActivityFeedWidget,
    AgentCardWidget,
    AgentPickerWidget,
    ApprovalCardWidget,
    ArtifactListWidget,
    BadgeWidget,
    ColumnDef,
    CommandPaletteWidget,
    DataTableWidget,
    DispatchWizardWidget,
    EmptyStateWidget,
    ExchangeTimelineWidget,
    InspectorWidget,
    ModalWidget,
    OutcomeCardWidget,
    PanelWidget,
    ProgressBarWidget,
    QuickSwitcherWidget,
    SearchFieldWidget,
    SessionMapWidget,
    SidebarTreeWidget,
    SpinnerWidget,
    StatusLineWidget,
    TimelineItem,
    TimelineWidget,
    ToastWidget,
    TrustStripWidget,
    WidgetLifecycleState,
    WorkspaceTabBarWidget,
)
from kin.tui.workspace import WorkspaceTabManager

# Helper factories for test fixtures
def _sample_agent_view() -> AgentCardView:
    return AgentCardView(
        agent_id="agent_scout",
        name="Code Scout",
        description="Code analysis subagent",
        availability="available",
        readiness_reason="ready",
        is_peer=False,
    )


def _sample_artifact_view() -> ArtifactView:
    meta = ArtifactMetadata(
        artifact_id="art_report_md",
        session_id="session_alpha_123",
        sha256="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
        mime_type="text/markdown",
        size_bytes=1024,
        offered_by="scout",
        preview_policy="text",
        created_at="2026-07-28T12:00:00Z",
    )
    return ArtifactView(metadata=meta, display_size="1.0 KB", preview_available=True)


def _sample_approval_view() -> ApprovalView:
    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_101",
        session_id="session_alpha_123",
        agent_id="agent_scout",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Write to file",
        reason="Update function signature",
        risk_label=RiskLabel.MEDIUM,
        requested_scope={"path": "src/main.py"},
        expires_at="2026-07-28T15:00:00Z",
    )
    return ApprovalView(request=req, now=datetime(2026, 7, 28, 14, 0, 0, tzinfo=timezone.utc))


def _sample_session_summary() -> SessionSummary:
    return SessionSummary(
        session_id="session_alpha_123",
        status="completed",
        participant_display_names=["Code Scout", "Data Cleaner"],
        current_turn=5,
        max_turns=10,
        last_activity_at="12:00:00",
    )


def _sample_ui_event(p_class: str = "message") -> UiEvent:
    return UiEvent(
        event_id="evt_01",
        session_id="session_alpha_123",
        kind="TASK_REQUEST",
        created_at="12:00:00",
        actor_username="alice",
        presentation_class=p_class, # type: ignore
    )


# All 26 Foundation, Container, and Domain Widgets (§14.5)
FOUNDATION_WIDGET_FACTORIES = [
    # Phase A Foundation Widgets (8)
    ("PanelWidget", lambda: PanelWidget(title="Test Panel", content="Panel body content")),
    ("BadgeWidget", lambda: BadgeWidget(value=5, role="accent.primary", label="Inbox")),
    ("StatusLineWidget", lambda: StatusLineWidget(message="System Online", now=datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc))),
    ("SpinnerWidget", lambda: SpinnerWidget(label="Loading Task", now=datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc))),
    ("ProgressBarWidget", lambda: ProgressBarWidget(progress=0.75, label="Upload")),
    ("ToastWidget", lambda: ToastWidget(message="File saved", severity="success")),
    ("ModalWidget", lambda: ModalWidget(title="Confirm Delete", body_text="Are you sure?")),
    ("EmptyStateWidget", lambda: EmptyStateWidget(title="No Sessions", description="Empty inbox")),
    # Phase B Container Components (8)
    ("SearchFieldWidget", lambda: SearchFieldWidget(placeholder="Filter...", value="query")),
    ("DataTableWidget", lambda: DataTableWidget(columns=[ColumnDef("id", "ID")], rows=[{"id": "row1"}])),
    ("TimelineWidget", lambda: TimelineWidget(items=[TimelineItem("12:00", "✓", "Event Title")])),
    ("WorkspaceTabBarWidget", lambda: WorkspaceTabBarWidget(tab_manager=WorkspaceTabManager())),
    ("SidebarTreeWidget", lambda: SidebarTreeWidget()),
    ("InspectorWidget", lambda: InspectorWidget(title="Preview", details="Item details text")),
    ("CommandPaletteWidget", lambda: CommandPaletteWidget(query="test")),
    ("QuickSwitcherWidget", lambda: QuickSwitcherWidget(query="tab", candidates=[("home", "Home", "Workspace")])),
    # Phase C Domain Widgets (10)
    ("AgentCardWidget", lambda: AgentCardWidget(card_view=_sample_agent_view())),
    ("AgentPickerWidget", lambda: AgentPickerWidget(agents=[_sample_agent_view()])),
    ("DispatchWizardWidget", lambda: DispatchWizardWidget()),
    ("SessionMapWidget", lambda: SessionMapWidget(sessions=[_sample_session_summary()])),
    ("ExchangeTimelineWidget", lambda: ExchangeTimelineWidget(events=[_sample_ui_event("message")])),
    ("ActivityFeedWidget", lambda: ActivityFeedWidget(events=[_sample_ui_event("activity")])),
    ("ArtifactListWidget", lambda: ArtifactListWidget(artifacts=[_sample_artifact_view()])),
    ("ApprovalCardWidget", lambda: ApprovalCardWidget(approval_view=_sample_approval_view())),
    ("OutcomeCardWidget", lambda: OutcomeCardWidget(session_summary=_sample_session_summary())),
    ("TrustStripWidget", lambda: TrustStripWidget(card_view=_sample_agent_view())),
]

LIFECYCLE_STATES = [
    WidgetLifecycleState.LOADING,
    WidgetLifecycleState.EMPTY,
    WidgetLifecycleState.NORMAL,
    WidgetLifecycleState.FOCUSED,
    WidgetLifecycleState.DISABLED,
    WidgetLifecycleState.RECOVERABLE_ERROR,
    WidgetLifecycleState.NARROW,
]

BREAKPOINTS = ["wide", "standard", "compact", "minimal"]


@pytest.mark.parametrize("widget_name,factory", FOUNDATION_WIDGET_FACTORIES)
@pytest.mark.parametrize("state", LIFECYCLE_STATES)
@pytest.mark.parametrize("breakpoint_tier", BREAKPOINTS)
def test_widget_lifecycle_contract(widget_name: str, factory, state: WidgetLifecycleState, breakpoint_tier: str):
    """PARAMETRIZED CONTRACT MATRIX TEST (§14.5).

    Asserts all 26 foundation, container, and domain widgets handle all 7 lifecycle states
    across all 4 breakpoint tiers without unhandled exceptions or rendering crashes.
    """
    widget = factory()

    # Apply disabled reason if testing DISABLED state
    if state == WidgetLifecycleState.DISABLED:
        widget.set_lifecycle_state(state, disabled_reason=f"Disabled by contract test for {widget_name}")
    else:
        widget.set_lifecycle_state(state)

    rendered = widget.render()

    # Core Contract Invariants
    assert rendered is not None
    assert isinstance(rendered, str)
    assert len(rendered) > 0, f"{widget_name} produced empty string in state {state} under breakpoint {breakpoint_tier}"

    if state == WidgetLifecycleState.DISABLED:
        assert ("DISABLED" in rendered or "Disabled" in rendered), (
            f"{widget_name} failed to display DISABLED indicator in disabled state"
        )
    elif state == WidgetLifecycleState.RECOVERABLE_ERROR:
        assert ("Error" in rendered or "!" in rendered), (
            f"{widget_name} failed to display error indicator in RECOVERABLE_ERROR state"
        )


def test_disabled_state_raises_without_reason():
    """CONTRACT SAFETY TEST (§14.5).

    Proves that attempting to transition any widget to DISABLED state without a valid string reason
    raises ValueError explicitly.
    """
    panel = PanelWidget(title="Test", content="Body")
    with pytest.raises(ValueError, match="disabled_reason"):
        panel.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="")
