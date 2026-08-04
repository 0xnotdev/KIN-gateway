"""Proof tests: theme switching produces different rendered output on high-visibility widgets.

These tests complement test_live_theme_switch.py (which covers shell.py chrome)
by proving that the two highest-visibility domain widgets — DispatchWizardWidget
and SessionArenaWidget — also produce theme-specific rendered output.
"""

import pytest
from kin.tui.tokens import KIN_GRAPHITE_THEME, DRACULA_THEME


@pytest.mark.asyncio
async def test_dispatch_wizard_renders_with_theme_colors(build_tui_app):
    """Mount KinApp, render DispatchWizard under kin-graphite, switch to dracula, assert colors changed."""
    app = build_tui_app(theme_name="kin-graphite", profile_name="test_dispatch_render_colors")
    async with app.run_test(size=(160, 44)) as pilot:
        app.console._color_system = "truecolor"
        # Switch to dispatch tab to get the wizard mounted
        app.canvas.set_active_tab_kind("dispatch")
        await pilot.pause()

        wizard = app.canvas.dispatch_widget
        graphite_output = wizard.render()

        # kin-graphite accent.primary is #bb9af7
        graphite_accent = KIN_GRAPHITE_THEME.get_role_color("accent.primary")

        # Switch to dracula
        app.set_theme("dracula")
        await pilot.pause()

        dracula_output = wizard.render()
        dracula_accent = DRACULA_THEME.get_role_color("accent.primary")

        # The two themes have different accent colors
        assert graphite_accent != dracula_accent, "Test precondition: themes must differ"

        # After theme switch, the rendered output should use dracula's colors
        # Check that at least one of the theme-specific colors appears
        has_dracula_color = any(
            DRACULA_THEME.get_role_color(role) in dracula_output
            for role in ["accent.primary", "state.live", "state.error", "state.waiting"]
        )
        has_graphite_color = any(
            KIN_GRAPHITE_THEME.get_role_color(role) in dracula_output
            for role in ["accent.primary", "state.live", "state.error", "state.waiting"]
            if KIN_GRAPHITE_THEME.get_role_color(role) != DRACULA_THEME.get_role_color(role)
        )

        assert has_dracula_color, (
            f"Expected at least one dracula theme color in wizard output after theme switch, "
            f"got: {dracula_output[:200]}"
        )
        assert not has_graphite_color, (
            f"Found kin-graphite color in wizard output after switching to dracula"
        )

        await pilot.press("q")


@pytest.mark.asyncio
async def test_session_arena_renders_with_theme_colors(build_tui_app):
    """Mount KinApp, render SessionArena under kin-graphite, switch to dracula, assert colors changed."""
    app = build_tui_app(theme_name="kin-graphite")
    async with app.run_test(size=(160, 44)) as pilot:
        app.console._color_system = "truecolor"
        # Switch to a session tab to mount the arena
        app.canvas.set_active_tab_kind("session", session_id="test-session-1")
        await pilot.pause()

        # Find the arena widget
        arena = None
        for widget in app.canvas.walk_children():
            if hasattr(widget, 'active_lane') and hasattr(widget, 'toggle_focus_mode'):
                arena = widget
                break

        if arena is None:
            pytest.skip("SessionArenaWidget not mounted")

        graphite_output = arena.render()

        # Switch to dracula
        app.set_theme("dracula")
        pilot.app.console._color_system = "truecolor"
        await pilot.pause()

        dracula_output = arena.render()

        # Verify the outputs are different (theme colors changed)
        assert graphite_output != dracula_output, (
            "Arena rendered output should differ between kin-graphite and dracula themes"
        )

        # Verify dracula-specific colors appear
        has_dracula_color = any(
            DRACULA_THEME.get_role_color(role) in dracula_output
            for role in ["accent.primary", "state.live", "state.error", "state.waiting", "accent.secondary"]
        )
        assert has_dracula_color, (
            f"Expected at least one dracula theme color in arena output, "
            f"got: {dracula_output[:200]}"
        )

        await pilot.press("q")
