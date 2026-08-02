"""Minimal 80x24 breakpoint adaptation test suite (§14.9 Phase E)."""

import pytest
from kin.tui.layout import classify_breakpoint, is_minimal_breakpoint
from kin.tui.widgets.lifecycle import is_narrow_breakpoint


def test_minimal_breakpoint_classification():
    """Assert terminal size 80x24 and below classifies as minimal / compact breakpoint."""
    assert classify_breakpoint(80, 24) == "minimal"
    assert is_minimal_breakpoint(80, 24) is True
    assert is_narrow_breakpoint(80, 24) is True

    # Standard wide terminal
    assert classify_breakpoint(165, 45) == "wide"
    assert is_minimal_breakpoint(165, 45) is False
    assert is_narrow_breakpoint(165, 45) is False


def test_minimal_breakpoint_graceful_adaptation():
    """Assert classification handles boundary thresholds (89x27 vs 90x28)."""
    assert classify_breakpoint(89, 27) == "minimal"
    assert classify_breakpoint(90, 28) in ("compact", "standard")
