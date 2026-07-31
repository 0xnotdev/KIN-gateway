"""Unit tests for TimelineWidget foundation component.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import time
import pytest

from kin.tui.widgets import TimelineItem, TimelineWidget, WidgetLifecycleState


def test_timeline_virtualization_10k_scale():
    """VIRTUALIZATION AT SCALE TEST (§14.5).

    Constructs 10,000 timeline events and asserts structural bounded event count (min(total, window_size))
    and non-linear rendering overhead.
    """
    items = [TimelineItem(f"12:{i%60:02d}", "✓", f"Event #{i}", f"Payload body {i}") for i in range(10000)]
    timeline = TimelineWidget(items=items, visible_items_window=8)

    rendered = timeline.render()

    # Structural Assertion: Count rendered event lines in output
    event_lines = [l for l in rendered.splitlines() if "Event #" in l]

    # Assert instantiated rendered events strictly equal min(total, window_size) == 8
    assert len(event_lines) == 8, (
        f"STRUCTURAL VIRTUALIZATION FAILURE: 10,000-event timeline instantiated {len(event_lines)} events "
        f"instead of bounded window_size 8!"
    )
    assert "Timeline (10000 events)" in rendered

    # Timing Performance Assertion
    t0 = time.perf_counter()
    timeline.render()
    render_time = time.perf_counter() - t0
    assert render_time < 0.05, f"10k Timeline render took too long: {render_time * 1000:.2f}ms"


def test_timeline_scroll_lock_on_append():
    """SCROLL-LOCK PROTECTION TEST (§14.5).

    Proves that if a user has scrolled away from the bottom of a Timeline,
    injecting new fixture items MUST NOT force-scroll them back down.
    """
    items = [TimelineItem(f"10:{i:02d}", "●", f"Initial Event #{i}") for i in range(20)]
    timeline = TimelineWidget(items=items, visible_items_window=5)

    # Initial state: at bottom of timeline (selected_index = 19)
    assert timeline.selected_index == 19
    assert timeline.user_scrolled_up is False

    # User scrolls up 5 steps
    for _ in range(5):
        timeline.scroll_up()

    saved_index = timeline.selected_index
    saved_offset = timeline.window_offset
    assert timeline.user_scrolled_up is True
    assert saved_index == 14

    # Inject / append new live events mid-scroll
    for i in range(10):
        timeline.append_event(TimelineItem(f"11:{i:02d}", "!", f"New Live Event #{i}"))

    # ASSERT SCROLL LOCK HELD: selected_index and window_offset were NOT changed by new event appends!
    assert timeline.selected_index == saved_index, (
        f"Scroll lock failed! Expected selected_index to stay {saved_index}, but got {timeline.selected_index}"
    )
    assert timeline.window_offset == saved_offset, (
        f"Scroll lock failed! Expected window_offset to stay {saved_offset}, but got {timeline.window_offset}"
    )
    assert "[SCROLL LOCK ACTIVE]" in timeline.render()
