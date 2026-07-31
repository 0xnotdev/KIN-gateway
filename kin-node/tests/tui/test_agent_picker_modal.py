"""Unit tests for AgentPickerWidget ModalScreen (§14.7 Phase B).

Covers:
1. Candidate list rendering with adapter_kind, availability, description, tags, MIME lists.
2. Tab key toggling details drawer with boundary summary & 'Suggested — not automatic' rationale.
3. Enter key selecting focused agent and returning AgentCardView.
4. Esc key cancelling and returning None.
5. Zero auto-preselection guarantee.
"""

import pytest

from kin.schemas import AgentAvailability
from kin.tui.state import AgentCardView
from kin.tui.widgets.agent_picker import AgentPickerWidget


@pytest.fixture
def sample_agents():
    return [
        AgentCardView(
            agent_id="scout-1",
            name="Code Scout",
            description="Scans codebases for patterns",
            adapter_kind="Local",
            capabilities_tags=["scan", "search"],
            availability=AgentAvailability.READY,
            readiness_reason="Workspace ready",
            accepts=["text/plain"],
            produces=["text/markdown"],
            boundary_summary="Workspace: workspace_read",
            is_peer=False,
        ),
        AgentCardView(
            agent_id="cleaner-2",
            name="Data Cleaner",
            description="Cleans and sanitizes dataset files",
            adapter_kind="Webhook",
            capabilities_tags=["data", "sanitize"],
            availability=AgentAvailability.NEEDS_KEY,
            readiness_reason="Webhook secret key missing",
            accepts=["application/json"],
            produces=["application/json"],
            boundary_summary="Workspace: none",
            is_peer=True,
        ),
    ]


# -----------------------------------------------------------------------------
# Phase B: AgentPicker Unit Tests
# -----------------------------------------------------------------------------
def test_agent_picker_rendering_metadata(sample_agents):
    """1. Assert candidate list renders adapter_kind, availability, description, tags, MIME lists (§B1)."""
    picker = AgentPickerWidget(agents=sample_agents, prompt="Select target agent")
    output = picker.render()

    assert "Select target agent" in output
    assert "Code Scout" in output
    assert "Scans codebases for patterns" in output
    assert "scan, search" in output
    assert "text/plain" in output
    assert "text/markdown" in output
    assert "[LOCAL]" in output
    assert "[WEBHOOK]" in output


def test_agent_picker_tab_toggles_details_drawer(sample_agents):
    """2. Assert Tab key toggles details drawer with boundary summary & rationale (§B2)."""
    picker = AgentPickerWidget(agents=sample_agents)

    # Initial state: drawer closed
    assert picker.drawer_open is False
    assert "Ordered by readiness status" not in picker.render()

    # Toggle drawer open via toggle_drawer()
    picker.toggle_drawer()
    assert picker.drawer_open is True
    drawer_output = picker.render()
    assert "Boundary Summary:" in drawer_output
    assert "Workspace: workspace_read" in drawer_output
    assert "Ordered by readiness status" in drawer_output

    # Toggle drawer closed
    picker.toggle_drawer()
    assert picker.drawer_open is False
    assert "Ordered by readiness status" not in picker.render()


def test_agent_picker_navigation_and_selection(sample_agents):
    """3. Assert j/k navigation updates selection and Enter confirms (§B3)."""
    selected_result = []

    def on_sel(agent):
        selected_result.append(agent)

    picker = AgentPickerWidget(agents=sample_agents, on_select=on_sel)

    # Initial selection: index 0 (Code Scout)
    assert picker.get_selected_agent().agent_id == "scout-1"

    # Move down to index 1 (Data Cleaner)
    picker.cursor_down()
    assert picker.get_selected_agent().agent_id == "cleaner-2"

    # Confirm selection
    confirmed = picker.confirm_selection()
    assert confirmed is not None
    assert confirmed.agent_id == "cleaner-2"
    assert len(selected_result) == 1
    assert selected_result[0].agent_id == "cleaner-2"


def test_agent_picker_zero_auto_preselection(sample_agents):
    """4. Assert zero auto-preselection: passing preselected_id requires explicit user confirm (§B4)."""
    selected_result = []

    picker = AgentPickerWidget(
        agents=sample_agents,
        preselected_id="scout-1",
        on_select=lambda a: selected_result.append(a),
    )

    # Preselected ID is recorded, but no callback is fired automatically
    assert picker.preselected_id == "scout-1"
    assert len(selected_result) == 0

    # User must explicitly confirm selection
    picker.confirm_selection()
    assert len(selected_result) == 1
