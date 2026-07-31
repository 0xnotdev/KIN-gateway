"""Unit tests for DataTableWidget foundation component.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import time
import pytest

from kin.tui.widgets import ColumnDef, DataTableWidget, WidgetLifecycleState


def test_data_table_virtualization_10k_scale():
    """VIRTUALIZATION AT SCALE TEST (§14.5).

    Constructs 10,000 rows and asserts structural bounded row count (instantiated rows == min(total, window_size))
    and non-linear rendering overhead.
    """
    small_rows = [{"id": f"row_{i}", "name": f"Item {i}", "status": "active"} for i in range(10)]
    large_rows = [{"id": f"row_{i}", "name": f"Item {i}", "status": "active"} for i in range(10000)]

    small_table = DataTableWidget(rows=small_rows, visible_rows_window=10)
    large_table = DataTableWidget(rows=large_rows, visible_rows_window=10)

    small_rendered = small_table.render()
    large_rendered = large_table.render()

    # Structural Assertion: Count rendered data row lines in output
    small_row_lines = [l for l in small_rendered.splitlines() if "row_" in l]
    large_row_lines = [l for l in large_rendered.splitlines() if "row_" in l]

    # Assert instantiated rendered rows strictly equal min(total, window_size) == 10 for both
    assert len(small_row_lines) == 10, f"Expected 10 rendered rows for small table, got {len(small_row_lines)}"
    assert len(large_row_lines) == 10, (
        f"STRUCTURAL VIRTUALIZATION FAILURE: 10,000-row table instantiated {len(large_row_lines)} rows "
        f"instead of bounded window_size 10!"
    )

    # Output String Length Boundedness Assertion
    assert abs(len(large_rendered) - len(small_rendered)) < 200, (
        f"DataTable render output scaled linearly! Small len={len(small_rendered)}, Large len={len(large_rendered)}"
    )

    # Timing Performance Assertion
    t0 = time.perf_counter()
    large_table.render()
    large_time = time.perf_counter() - t0
    assert large_time < 0.05, f"10k DataTable render took too long: {large_time * 1000:.2f}ms"


def test_data_table_navigation():
    rows = [{"id": f"r{i}", "name": f"Name {i}", "status": "ok"} for i in range(20)]
    table = DataTableWidget(rows=rows, visible_rows_window=5)

    assert table.selected_index == 0
    table.cursor_down()
    assert table.selected_index == 1

    for _ in range(10):
        table.cursor_down()

    assert table.selected_index == 11
    assert table.window_offset > 0

    table.cursor_up()
    assert table.selected_index == 10
