"""Unit tests for ProgressBarWidget foundation widget.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import pytest

from kin.tui.widgets import ProgressBarWidget, WidgetLifecycleState


def test_progress_bar_rendering_and_updates():
    pbar = ProgressBarWidget(progress=0.60, label="File Download")
    rendered = pbar.render()
    assert "60%" in rendered
    assert "File Download" in rendered

    pbar.set_progress(1.0)
    assert "100%" in pbar.render()


def test_progress_bar_disabled_with_reason():
    pbar = ProgressBarWidget(progress=0.30)
    pbar.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Disk full")
    rendered = pbar.render()
    assert "Reason: Disk full" in rendered
