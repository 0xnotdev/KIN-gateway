"""Unit and Parity Tests for kin guide (§14.6 Phase D3, §5.9).

Covers the six named guide pages, title/body search filtering, next action presence,
deterministic render_guide_markdown() output, and ModalScreen instantiation.
"""

import pytest

from kin.tui.guide import GUIDE_PAGES, GuideOverlayScreen, render_guide_markdown


# -----------------------------------------------------------------------------
# 6.12 Guide — Six Named Pages, Search Filter, Markdown Parity
# -----------------------------------------------------------------------------
def test_guide_pages_exact_structure_and_titles():
    """6.12 Assert exactly six named guide pages exist with exact required titles and next actions (§14.6 Phase D3)."""
    assert len(GUIDE_PAGES) == 6

    expected_titles = [
        "Start here",
        "Meet your agents",
        "Send good work",
        "Watch and steer",
        "Work safely",
        "Fix a problem",
    ]

    actual_titles = [p.title for p in GUIDE_PAGES]
    assert actual_titles == expected_titles

    for page in GUIDE_PAGES:
        assert page.title
        assert page.body
        assert page.next_action
        assert page.next_action.startswith("Press ") or page.next_action.startswith("Run ")


def test_guide_search_filtering():
    """6.12 Assert GuideOverlayScreen search filters pages by query substring (§14.6 Phase D3)."""
    from io import StringIO
    from rich.console import Console

    screen = GuideOverlayScreen()

    # Search for "agents"
    screen.search_query = "agents"
    console = Console(file=StringIO(), width=100)
    console.print(screen.render_pages())
    rendered_agents = console.file.getvalue()
    assert "Meet your agents" in rendered_agents

    # Search for non-matching string
    screen.search_query = "nonexistent_query_string_xyz"
    console2 = Console(file=StringIO(), width=100)
    console2.print(screen.render_pages())
    rendered_empty = console2.file.getvalue()
    assert "No guide pages matching" in rendered_empty


def test_guide_markdown_rendering_determinism_and_parity():
    """6.12 Assert render_guide_markdown() output is deterministic and matches GUIDE_PAGES (§14.6 Phase D3)."""
    md1 = render_guide_markdown()
    md2 = render_guide_markdown()

    assert md1 == md2
    assert "# KIN Terminal UI Guide" in md1
    for page in GUIDE_PAGES:
        assert f"## {page.title}" in md1
        assert page.body in md1
        assert page.next_action in md1
