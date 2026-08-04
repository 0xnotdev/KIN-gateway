"""Unit tests for Settings UI preference wire-up (§14.9 Phase A2).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.9
- Verifies SettingsScreenWidget and SettingsModal preference changes update
  app.prefs.ascii_fallback, app.prefs.color_depth, and app.prefs.theme.
"""

import pytest
from kin.tui.widgets.settings_screen import SettingsModal, SettingsScreenWidget


@pytest.mark.asyncio
async def test_settings_ui_updates_persisted_preferences(build_tui_app):
    """Assert preference changes from SettingsScreenWidget update app.prefs attributes."""
    app = build_tui_app(theme_name="kin-graphite", profile_name="test_profile_settings")
    async with app.run_test(size=(160, 44)) as pilot:
        # Preconditions
        app.prefs.ascii_fallback = False
        app.prefs.color_depth = "auto"
        assert app.prefs.ascii_fallback is False
        assert app.prefs.color_depth == "auto"

        # Instantiate SettingsScreenWidget wired to app.set_preference
        widget = SettingsScreenWidget(
            current_theme=app.prefs.theme,
            color_depth=app.prefs.color_depth,
            ascii_fallback=app.prefs.ascii_fallback,
            reduced_motion=app.prefs.reduced_motion,
            on_preference_change=app.set_preference,
        )

        # Simulate toggling ascii_fallback checkbox
        widget.on_checkbox_changed(
            type("CheckboxEvent", (), {
                "checkbox": type("CheckboxObj", (), {"id": "check-ascii-mode"})(),
                "value": True,
            })()
        )
        await pilot.pause()

        assert app.prefs.ascii_fallback is True
        assert app.is_ascii_fallback_active is True

        # Simulate changing color_depth select dropdown
        widget.on_select_changed(
            type("SelectEvent", (), {
                "select": type("SelectObj", (), {"id": "select-color-depth"})(),
                "value": "monochrome",
            })()
        )
        await pilot.pause()

        assert app.prefs.color_depth == "monochrome"
        assert app.is_colorless_active is True

        await pilot.press("q")


@pytest.mark.asyncio
async def test_settings_modal_is_reachable_from_global_f2_binding(build_tui_app, tmp_path):
    app = build_tui_app(profile_name="settings-reachable", profile_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("f2")
        assert isinstance(app.screen, SettingsModal)
        assert app.screen.current_theme == app.requested_theme
        await pilot.press("escape")
        assert len(app.screen_stack) == 1
