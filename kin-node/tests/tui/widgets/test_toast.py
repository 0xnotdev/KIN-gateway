"""Unit tests for ToastWidget foundation widget.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import pytest

from kin.tui.widgets import ToastWidget, WidgetLifecycleState


def test_toast_severities_and_dismiss():
    dismissed = False

    def on_dismiss():
        nonlocal dismissed
        dismissed = True

    toast = ToastWidget(message="Settings saved", severity="success", dismiss_callback=on_dismiss)
    assert "[SUCCESS] Settings saved" in toast.render()
    assert toast.trigger_dismiss() is True
    assert dismissed is True


def test_toast_disabled_with_reason():
    toast = ToastWidget(message="Alert")
    toast.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Do not disturb mode active")
    rendered = toast.render()
    assert "Reason: Do not disturb mode active" in rendered
