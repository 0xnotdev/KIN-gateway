"""Unit tests for BadgeWidget foundation widget.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import pytest

from kin.tui.widgets import BadgeWidget, WidgetLifecycleState


def test_badge_widget_role_consumption():
    badge = BadgeWidget(value=3, role="accent.primary", label="Inbox")
    rendered = badge.render()
    assert "(3 Inbox)" in rendered

    # Reject literal color strings (§14.5)
    with pytest.raises(ValueError, match="Literal color"):
        BadgeWidget(value=1, role="#ff0000")


def test_badge_widget_disabled_with_reason():
    badge = BadgeWidget(value=5, role="accent.primary")
    badge.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Keychain locked")
    rendered = badge.render()
    assert "DISABLED: Keychain locked" in rendered
