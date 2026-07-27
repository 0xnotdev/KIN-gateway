"""Unit tests for central keybinding registry, collision validation, and priority rules.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.1, §5.2, §5.3, §14.4
"""

import pytest

from kin.tui.help import generate_help_markdown
from kin.tui.keymap import (
    DEFAULT_KEYMAP,
    KeyBindingSpec,
    KeymapCollisionError,
    validate_keymap_registry,
)


def test_keymap_registry_no_collisions():
    """Assert central keymap registry validates cleanly without collisions (§14.4)."""
    validate_keymap_registry(DEFAULT_KEYMAP)


def test_keymap_collision_detection():
    """Assert validator raises KeymapCollisionError when two bindings collide in same section."""
    colliding = [
        KeyBindingSpec("d", "action1", "Label 1", priority=False, suppressed_when_text_focused=True, section="global"),
        KeyBindingSpec("d", "action2", "Label 2", priority=False, suppressed_when_text_focused=True, section="global"),
    ]
    with pytest.raises(KeymapCollisionError, match="Keybinding collision detected on key 'd'"):
        validate_keymap_registry(colliding)


def test_every_printable_character_has_text_yield_justification():
    """Assert every single printable character binding yields when text-focused and is NOT priority (§14.4)."""
    for b in DEFAULT_KEYMAP:
        # Single printable character check
        if len(b.key) == 1 and b.key.isalnum():
            assert not b.priority, f"Printable character '{b.key}' must NOT have priority=True!"
            assert b.suppressed_when_text_focused, f"Printable character '{b.key}' must be suppressed when text focused!"
            assert b.justification, f"Binding '{b.key}' missing explicit priority justification!"


def test_help_overlay_generated_from_keymap():
    """Assert contextual help overlay content is generated dynamically from keymap registry."""
    md = generate_help_markdown()
    assert "# KIN V1.1 Terminal UI — Keyboard Reference" in md
    assert "Command Palette" in md
    assert "Quick Switcher" in md
    assert "Smart Quit / Return Home" in md
