"""Terminal Breakpoint Classification and Layout Geometry for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §3.1, §3.2, §3.3, §14.3
"""

from typing import Literal

Breakpoint = Literal["wide", "standard", "compact", "minimal"]

# Sidebar width constraints (columns)
SIDEBAR_DEFAULT_WIDTH = 32
SIDEBAR_MIN_WIDTH = 24
SIDEBAR_MAX_WIDTH = 42

# Inspector width constraints (columns)
INSPECTOR_DEFAULT_WIDTH = 38
INSPECTOR_MIN_WIDTH = 30
INSPECTOR_MAX_WIDTH = 52


def classify_breakpoint(cols: int, rows: int) -> Breakpoint:
    """Classify terminal dimensions into responsive breakpoint tiers (§3.2).

    Rules:
      wide     : cols >= 160 and rows >= 44
      standard : 120 <= cols <= 159 and rows >= 36 (or cols >= 160 and 36 <= rows < 44)
      compact  : 90 <= cols <= 119 and rows >= 28 (or cols >= 90 and 28 <= rows < 36)
      minimal  : cols < 90 or rows < 28
    """
    if cols < 90 or rows < 28:
        return "minimal"
    if cols >= 160 and rows >= 44:
        return "wide"
    if cols >= 120 and rows >= 36:
        return "standard"
    if cols >= 90 and rows >= 28:
        return "compact"
    return "minimal"


def clamp_sidebar_width(width: int) -> int:
    """Clamp sidebar width to valid range [24, 42]."""
    return max(SIDEBAR_MIN_WIDTH, min(width, SIDEBAR_MAX_WIDTH))


def clamp_inspector_width(width: int) -> int:
    """Clamp inspector width to valid range [30, 52]."""
    return max(INSPECTOR_MIN_WIDTH, min(width, INSPECTOR_MAX_WIDTH))


def is_minimal_breakpoint(cols: int, rows: int) -> bool:
    """Check if terminal dimensions classify as minimal breakpoint tier (<90 cols or <28 rows)."""
    return classify_breakpoint(cols, rows) == "minimal"
