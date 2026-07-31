"""Unit tests for StatusLineWidget foundation widget.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime, timezone
import pytest

from kin.tui.widgets import StatusLineWidget, WidgetLifecycleState


def test_status_line_injectable_clock():
    fixed_time = datetime(2026, 7, 27, 10, 15, 30, tzinfo=timezone.utc)
    status = StatusLineWidget(message="Relay Connected", now=fixed_time)
    rendered = status.render()
    assert "Relay Connected" in rendered
    assert "10:15:30" in rendered


def test_status_line_disabled_with_reason():
    status = StatusLineWidget(message="Node Active")
    status.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Network adapter offline")
    rendered = status.render()
    assert "Reason: Network adapter offline" in rendered
