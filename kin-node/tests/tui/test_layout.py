"""Unit tests for layout geometry and breakpoint classification.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §3.2, §14.3
"""

import pytest

from kin.tui.layout import (
    INSPECTOR_DEFAULT_WIDTH,
    INSPECTOR_MAX_WIDTH,
    INSPECTOR_MIN_WIDTH,
    SIDEBAR_DEFAULT_WIDTH,
    SIDEBAR_MAX_WIDTH,
    SIDEBAR_MIN_WIDTH,
    classify_breakpoint,
    clamp_inspector_width,
    clamp_sidebar_width,
)


def test_classify_breakpoint_exhaustive_boundaries():
    """Exhaustive boundary testing for classify_breakpoint at all transition edges.

    Tests every boundary value (89/90/119/120/159/160 columns; 27/28/35/36/43/44 rows)
    and interior points per tier.
    """
    # 1. Wide tier: cols >= 160 and rows >= 44
    assert classify_breakpoint(160, 44) == "wide"
    assert classify_breakpoint(200, 60) == "wide"

    # Edge: 160 cols but row height below 44 -> drops to standard if rows >= 36
    assert classify_breakpoint(160, 43) == "standard"
    assert classify_breakpoint(160, 36) == "standard"
    # Edge: 160 cols but row height 28-35 -> drops to compact
    assert classify_breakpoint(160, 35) == "compact"
    assert classify_breakpoint(160, 28) == "compact"
    # Edge: 160 cols but row height < 28 -> drops to minimal
    assert classify_breakpoint(160, 27) == "minimal"

    # 2. Standard tier: 120 <= cols <= 159 and rows >= 36
    assert classify_breakpoint(159, 44) == "standard"
    assert classify_breakpoint(159, 36) == "standard"
    assert classify_breakpoint(120, 36) == "standard"
    assert classify_breakpoint(120, 44) == "standard"

    # Edge: 120-159 cols but rows < 36
    assert classify_breakpoint(159, 35) == "compact"
    assert classify_breakpoint(120, 28) == "compact"
    assert classify_breakpoint(120, 27) == "minimal"

    # 3. Compact tier: 90 <= cols <= 119 and rows >= 28
    assert classify_breakpoint(119, 36) == "compact"
    assert classify_breakpoint(119, 28) == "compact"
    assert classify_breakpoint(90, 28) == "compact"
    assert classify_breakpoint(90, 50) == "compact"

    # Edge: 90-119 cols but rows < 28
    assert classify_breakpoint(119, 27) == "minimal"
    assert classify_breakpoint(90, 27) == "minimal"

    # 4. Minimal tier: cols < 90 or rows < 28
    assert classify_breakpoint(89, 28) == "minimal"
    assert classify_breakpoint(89, 50) == "minimal"
    assert classify_breakpoint(200, 27) == "minimal"
    assert classify_breakpoint(89, 27) == "minimal"


def test_explicit_80x24_minimal_checkpoint_bar():
    """Explicit test for 80x24 checkpoint bar requirement (§3.2, §14.3)."""
    assert classify_breakpoint(80, 24) == "minimal"


def test_sidebar_width_clamping():
    """Assert sidebar width clamps strictly between [24, 42]."""
    assert clamp_sidebar_width(32) == 32
    assert clamp_sidebar_width(20) == SIDEBAR_MIN_WIDTH  # 24
    assert clamp_sidebar_width(24) == SIDEBAR_MIN_WIDTH
    assert clamp_sidebar_width(42) == SIDEBAR_MAX_WIDTH  # 42
    assert clamp_sidebar_width(50) == SIDEBAR_MAX_WIDTH


def test_inspector_width_clamping():
    """Assert inspector width clamps strictly between [30, 52]."""
    assert clamp_inspector_width(38) == 38
    assert clamp_inspector_width(25) == INSPECTOR_MIN_WIDTH  # 30
    assert clamp_inspector_width(30) == INSPECTOR_MIN_WIDTH
    assert clamp_inspector_width(52) == INSPECTOR_MAX_WIDTH  # 52
    assert clamp_inspector_width(60) == INSPECTOR_MAX_WIDTH
