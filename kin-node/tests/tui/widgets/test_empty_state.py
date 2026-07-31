"""Unit tests for EmptyStateWidget foundation widget.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import pytest

from kin.tui.widgets import EmptyStateWidget, WidgetLifecycleState


def test_empty_state_action_callback():
    action_triggered = False

    def on_action():
        nonlocal action_triggered
        action_triggered = True

    empty = EmptyStateWidget(title="No Active Peers", next_action_callback=on_action)
    assert empty.trigger_action() is True
    assert action_triggered is True


def test_empty_state_disabled_with_reason():
    empty = EmptyStateWidget(title="Inbox Empty")
    empty.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Offline mode enabled")
    rendered = empty.render()
    assert "Reason: Offline mode enabled" in rendered
