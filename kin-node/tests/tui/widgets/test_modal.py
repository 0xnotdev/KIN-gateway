"""Unit tests for ModalWidget foundation widget.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import pytest

from kin.tui.widgets import ModalWidget, WidgetLifecycleState


def test_modal_widget_rendering():
    modal = ModalWidget(title="Discard Changes", body_text="Unsaved edits will be lost.")
    rendered = modal.render()
    assert "Discard Changes" in rendered
    assert "Unsaved edits will be lost." in rendered
    assert "[Confirm (y)]" in rendered
    assert "[Cancel (n)]" in rendered


def test_modal_widget_disabled_with_reason():
    modal = ModalWidget(title="Delete Account")
    modal.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Requires admin approval")
    rendered = modal.render()
    assert "Reason: Requires admin approval" in rendered
