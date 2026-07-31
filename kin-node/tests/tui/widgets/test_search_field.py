"""Unit tests for SearchFieldWidget foundation component.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime, timezone
import pytest

from kin.tui.widgets import SearchFieldWidget, WidgetLifecycleState


def test_search_field_debouncing_with_injectable_clock():
    query_log = []

    def on_change(q: str):
        query_log.append(q)

    search = SearchFieldWidget(on_query_change=on_change, debounce_ms=150.0)

    t1 = datetime(2026, 7, 27, 10, 0, 0, 0, tzinfo=timezone.utc)
    search.set_query("a", now=t1)
    assert query_log == ["a"]

    # Call within debounce window (50ms later)
    t2 = datetime(2026, 7, 27, 10, 0, 0, 50000, tzinfo=timezone.utc)
    search.set_query("ab", now=t2)
    # Debounced: callback should NOT have fired yet
    assert query_log == ["a"]

    # Call after debounce window (200ms later)
    t3 = datetime(2026, 7, 27, 10, 0, 0, 250000, tzinfo=timezone.utc)
    search.set_query("abc", now=t3)
    assert query_log == ["a", "abc"]


def test_search_field_match_count_and_clear():
    search = SearchFieldWidget(value="test")
    search.update_match_count(42)
    rendered = search.render()
    assert "[42 matches]" in rendered

    search.clear()
    assert search.query == ""
    assert search.match_count is None


def test_search_field_disabled_with_reason():
    search = SearchFieldWidget()
    search.set_lifecycle_state(WidgetLifecycleState.DISABLED, disabled_reason="Index updating")
    rendered = search.render()
    assert "DISABLED: Index updating" in rendered
