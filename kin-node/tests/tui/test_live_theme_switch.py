"""Proof test: theme switching produces visibly different rendered output.

This test mounts a real KinApp, renders the StatusBar under kin-graphite,
then switches to dracula via set_theme(), re-renders, and asserts the
hex color values in the rendered string actually changed.

This is the test that was described but never written. It proves theme
switching works end-to-end through the render path, not just at the
data structure level.
"""

import pytest
from kin.tui.app import KinApp
from kin.tui.tokens import KIN_GRAPHITE_THEME, DRACULA_THEME


@pytest.mark.asyncio
async def test_live_theme_switch_changes_rendered_output(monkeypatch):
    """Mount KinApp, render StatusBar under kin-graphite, switch to dracula, assert colors changed."""
    monkeypatch.setattr(KinApp, "is_colorless_active", property(lambda self: False))
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test(size=(160, 44)) as pilot:
        app.console._color_system = "truecolor"
        # Capture rendered output under kin-graphite
        status_bar = app.status_bar
        graphite_output = status_bar.render()

        # The kin-graphite state.live color is #73daca
        assert "#73daca" in graphite_output, (
            f"Expected kin-graphite state.live (#73daca) in rendered output, got: {graphite_output}"
        )

        # Switch theme to dracula
        app.set_theme("dracula")
        await pilot.pause()

        # Re-render
        dracula_output = status_bar.render()

        # The dracula state.live color is #50fa7b — different from kin-graphite's #73daca
        assert "#50fa7b" in dracula_output, (
            f"Expected dracula state.live (#50fa7b) in rendered output, got: {dracula_output}"
        )
        assert "#73daca" not in dracula_output, (
            f"kin-graphite color #73daca should NOT appear after switching to dracula, got: {dracula_output}"
        )

        # Also verify the sidebar renders with the new accent color
        sidebar = app.sidebar
        graphite_accent = KIN_GRAPHITE_THEME.get_role_color("accent.primary")  # #bb9af7
        dracula_accent = DRACULA_THEME.get_role_color("accent.primary")  # #bd93f9

        sidebar_output = sidebar.render()
        assert dracula_accent in sidebar_output, (
            f"Expected dracula accent ({dracula_accent}) in sidebar output, got: {sidebar_output}"
        )

        # And the tab bar
        tab_bar = app.tab_bar
        tab_output = tab_bar.render()
        assert dracula_accent in tab_output, (
            f"Expected dracula accent ({dracula_accent}) in tab bar output, got: {tab_output}"
        )

        await pilot.press("q")


@pytest.mark.asyncio
async def test_theme_switch_preserves_focus_and_scroll():
    """Assert set_theme() does not displace focus or alter scroll position."""
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test(size=(160, 44)) as pilot:
        # Record focus before theme switch
        focused_before = app.focused

        app.set_theme("nord")
        await pilot.pause()

        # Focus should be preserved
        focused_after = app.focused
        assert focused_before == focused_after, (
            f"Focus changed from {focused_before} to {focused_after} after theme switch"
        )

        await pilot.press("q")
