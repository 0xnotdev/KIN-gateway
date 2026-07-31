"""Unit tests for SpinnerWidget foundation widget.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime, timezone
import pytest

from kin.tui.widgets import SpinnerWidget, WidgetLifecycleState


def test_spinner_cancellation_callback():
    cancelled = False

    def on_cancel():
        nonlocal cancelled
        cancelled = True

    spinner = SpinnerWidget(label="Syncing Data", cancel_callback=on_cancel)
    assert spinner.trigger_cancel() is True
    assert cancelled is True


def test_spinner_injectable_clock_and_disabled_reason():
    fixed_time = datetime(2026, 7, 27, 8, 45, 0, tzinfo=timezone.utc)
    spinner = SpinnerWidget(label="Building Index", now=fixed_time)
    assert "08:45:00" in spinner.render()

    spinner.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="User aborted operation")
    assert "Reason: User aborted operation" in spinner.render()
