"""Unit tests for PanelWidget foundation widget.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from kin.tui.widgets import PanelWidget, WidgetLifecycleState


def test_panel_widget_normal_rendering():
    panel = PanelWidget(title="Agent Control", content="Status: Running", footer="Press Ctrl+C to stop")
    rendered = panel.render()
    assert "Agent Control" in rendered
    assert "Status: Running" in rendered
    assert "Press Ctrl+C to stop" in rendered


def test_panel_widget_disabled_with_reason():
    panel = PanelWidget(title="Agent Control")
    panel.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Agent unresponsive")
    rendered = panel.render()
    assert "Reason: Agent unresponsive" in rendered
