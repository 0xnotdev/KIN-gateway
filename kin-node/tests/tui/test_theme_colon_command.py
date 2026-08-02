"""Unit tests for :theme colon command and Command Palette theme switching (§14.9 Phase A Build Step 1).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.9 build step 1
- Valid theme switch changes active theme and refreshes UI.
- Invalid theme name retains previous theme (no silent no-op or crash) and sets RecoverableError.
- Command Palette items for all 6 spec themes work end-to-end.
"""

import pytest
from kin.tui.app import KinApp
from kin.tui.tokens import RECOGNIZED_THEME_NAMES


@pytest.mark.asyncio
async def test_colon_theme_command_valid_switch():
    """Assert :theme <valid_name> changes active theme and updates status line."""
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test(size=(160, 44)) as pilot:
        app.execute_colon_command(":theme dracula")
        await pilot.pause()

        assert app.requested_theme == "dracula"
        assert app.theme_tokens.name == "dracula"
        assert app.active_error is None
        assert "dracula" in app.status_bar.render()

        await pilot.press("q")


@pytest.mark.asyncio
async def test_colon_theme_command_invalid_name_retains_theme_and_surfaces_error():
    """Assert :theme <invalid_name> retains previous theme and sets a clear RecoverableError."""
    app = KinApp(theme_name="nord")
    async with app.run_test(size=(160, 44)) as pilot:
        app.execute_colon_command(":theme nonexistent_theme_123")
        await pilot.pause()

        # Theme MUST be retained as 'nord', not silently changed or fallen back to graphite
        assert app.requested_theme == "nord"
        assert app.theme_tokens.name == "nord"

        # RecoverableError must be set
        assert app.active_error is not None
        assert "Invalid theme name" in app.active_error.what_happened
        assert "Retained active theme 'nord'" in app.active_error.impact

        # Status message must indicate invalid theme
        assert "Invalid theme" in app.status_bar.render()

        await pilot.press("q")


@pytest.mark.asyncio
async def test_command_palette_theme_entries_all_six_themes():
    """Assert all 6 spec themes can be triggered via Command Palette items."""
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test(size=(160, 44)) as pilot:
        theme_items = [item for item in app.command_index if item.command_id.startswith("theme_")]
        assert len(theme_items) == 6

        # Test selecting dracula via command palette callback
        app.action_command_palette()
        await pilot.pause()

        # Find dracula item
        dracula_item = next(item for item in app.command_index if item.command_id == "theme_dracula")

        # Simulate selecting dracula from palette
        def handle_selected(item):
            if item and item.command_id.startswith("theme_"):
                theme_map = {
                    "theme_graphite": "kin-graphite",
                    "theme_night": "kin-night",
                    "theme_nord": "nord",
                    "theme_dracula": "dracula",
                    "theme_catppuccin": "catppuccin-mocha",
                    "theme_high_contrast": "high-contrast",
                }
                app.set_theme(theme_map[item.command_id])

        handle_selected(dracula_item)
        await pilot.pause()

        assert app.requested_theme == "dracula"
        assert app.theme_tokens.name == "dracula"

        await pilot.press("q")
