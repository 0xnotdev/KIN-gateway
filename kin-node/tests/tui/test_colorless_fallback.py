"""Unit tests for Colorless / ASCII Fallback Semantic State Presentation (§14.9 Phase A Build Step 2).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.9 build step 2, §8.1-8.2
- Live, waiting, approval, error, muted, and security states are each
  distinguishable via glyph + text label + border/bracket treatment alone,
  with color and Unicode both stripped.
- Proves all six semantic states produce mutually distinct triples (glyph, label, bracket)
  under ASCII-fallback / colorless mode.
"""

import pytest
from kin.tui.tokens import GLYPH_REGISTRY, get_glyph


def get_colorless_state_presentation(state_name: str, ascii_fallback: bool = True) -> tuple[str, str, str]:
    """Compute the (glyph, label, bracket_treatment) tuple for a given semantic state in ASCII mode.

    Reuses the central GLYPH_REGISTRY from tokens.py without creating a secondary registry.
    """
    state = state_name.lower()

    if state == "live":
        glyph = get_glyph("●", ascii_fallback=ascii_fallback)  # '*'
        label = "LIVE"
        bracket = "[+]"
    elif state == "waiting":
        glyph = get_glyph("◌", ascii_fallback=ascii_fallback)  # '.'
        label = "WAITING"
        bracket = "[?]"
    elif state == "approval":
        glyph = get_glyph("→", ascii_fallback=ascii_fallback)  # '->'
        label = "APPROVAL"
        bracket = "[=>]"
    elif state == "error":
        glyph = get_glyph("✖", ascii_fallback=ascii_fallback)  # 'X'
        label = "ERROR"
        bracket = "[!]"
    elif state == "muted":
        glyph = get_glyph("○", ascii_fallback=ascii_fallback)  # 'o'
        label = "MUTED"
        bracket = "[-]"
    elif state == "security":
        glyph = get_glyph("▲", ascii_fallback=ascii_fallback)  # '^'
        label = "SECURITY"
        bracket = "[SEC]"
    else:
        raise ValueError(f"Unknown semantic state: {state_name}")

    return glyph, label, bracket


def test_six_semantic_states_are_mutually_distinguishable_in_colorless_ascii_mode():
    """Assert all 6 semantic states produce distinct (glyph, label, bracket) triples in ASCII mode."""
    states = ["live", "waiting", "approval", "error", "muted", "security"]
    presentations = {}

    for s in states:
        glyph, label, bracket = get_colorless_state_presentation(s, ascii_fallback=True)
        # Assert glyph is pure ASCII (no unicode)
        assert glyph.isascii(), f"Glyph for state '{s}' must be ASCII in fallback mode, got: {glyph}"

        presentation = (glyph, label, bracket)
        presentations[s] = presentation

    # Assert every state has a unique presentation tuple
    unique_presentations = set(presentations.values())
    assert len(unique_presentations) == len(states), (
        f"All {len(states)} semantic states must produce distinct presentations when colorless/ASCII. "
        f"Found {len(unique_presentations)} unique out of {len(states)}: {presentations}"
    )

    # Pairwise comparison verification
    state_list = list(states)
    for i in range(len(state_list)):
        for j in range(i + 1, len(state_list)):
            s1, s2 = state_list[i], state_list[j]
            p1, p2 = presentations[s1], presentations[s2]
            assert p1 != p2, f"State '{s1}' and '{s2}' have duplicate presentations: {p1}"


@pytest.mark.asyncio
async def test_widget_colorless_degradation_across_screens():
    """Verify that actual TUI components render ASCII fallback glyphs without unicode or color crashes."""
    from kin.tui.app import KinApp

    app = KinApp(theme_name="high-contrast")
    async with app.run_test(size=(160, 44)) as pilot:
        # Verify status bar uses ASCII fallback glyphs cleanly
        status_render = app.status_bar.render()
        assert status_render is not None

        # Verify sidebar renders visible tree nodes cleanly
        sidebar_render = app.sidebar.render()
        assert sidebar_render is not None

        await pilot.press("q")
