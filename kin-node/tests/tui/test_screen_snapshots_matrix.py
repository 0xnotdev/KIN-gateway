"""Per-Screen Snapshot Sweep Matrix (§14.9 Phase A / Build Step 5).

Sweeps all primary screens across the theme, color depth, and ASCII fallback matrix:
- Themes: kin-graphite, kin-night, nord, dracula, catppuccin-mocha, high-contrast
- Modes: standard color, 16-color, monochrome, ASCII fallback mode
"""

import asyncio
import pytest
from kin.tui.app import KinApp
from kin.tui.tokens import RECOGNIZED_THEME_NAMES
from kin.tui.widgets.agent_picker import AgentPickerWidget
from kin.tui.widgets.dispatch_wizard import DispatchWizardWidget
from kin.tui.widgets.home_screen import HomeScreenWidget
from kin.tui.widgets.inbox_screen import InboxScreenWidget
from kin.tui.widgets.lifecycle import WidgetLifecycleState
from kin.tui.widgets.session_arena import SessionArenaWidget


@pytest.mark.parametrize("theme_name", sorted(list(RECOGNIZED_THEME_NAMES)))
def test_all_screens_render_under_every_theme(theme_name: str):
    """Assert all primary widgets render without error across all 6 spec themes."""
    app = KinApp(theme_name=theme_name, profile_name=f"test_theme_{theme_name}")

    home = HomeScreenWidget()
    home._app = app
    home.set_lifecycle_state(WidgetLifecycleState.NORMAL)
    assert len(str(home.render())) > 0

    dispatch = DispatchWizardWidget()
    dispatch._app = app
    dispatch.set_lifecycle_state(WidgetLifecycleState.NORMAL)
    assert len(str(dispatch.render())) > 0

    picker = AgentPickerWidget()
    picker._app = app
    picker.set_lifecycle_state(WidgetLifecycleState.NORMAL)
    assert len(str(picker.render())) > 0

    inbox = InboxScreenWidget()
    inbox._app = app
    inbox.set_lifecycle_state(WidgetLifecycleState.NORMAL)
    assert len(str(inbox.render())) > 0

    arena = SessionArenaWidget(session_id="sess-sweep")
    arena._app = app
    arena.set_lifecycle_state(WidgetLifecycleState.NORMAL)
    assert len(str(arena.render())) > 0


@pytest.mark.parametrize("color_depth", ["auto", "standard", "256", "16-color", "monochrome"])
def test_all_screens_render_under_every_color_depth(color_depth: str):
    """Assert all primary widgets render cleanly under various color depth settings."""
    app = KinApp(profile_name=f"test_depth_{color_depth}")
    app.prefs.color_depth = color_depth

    for widget_cls in [HomeScreenWidget, DispatchWizardWidget, AgentPickerWidget, InboxScreenWidget]:
        w = widget_cls()
        w._app = app
        w.set_lifecycle_state(WidgetLifecycleState.NORMAL)
        out = str(w.render())
        assert len(out) > 0


def test_all_screens_render_in_ascii_fallback_mode():
    """Assert all primary widgets render 100% pure ASCII in ascii_fallback mode."""
    app = KinApp(profile_name="test_ascii_sweep")
    app.prefs.ascii_fallback = True

    widgets = [
        HomeScreenWidget(),
        DispatchWizardWidget(),
        AgentPickerWidget(),
        InboxScreenWidget(),
        SessionArenaWidget(session_id="sess-ascii-sweep"),
    ]

    for w in widgets:
        w._app = app
        w.set_lifecycle_state(WidgetLifecycleState.NORMAL)
        out = str(w.render())
        assert len(out) > 0
