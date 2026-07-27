"""Unit tests for TUI global error boundary and diagnostics logger.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §10.3, §14.1
"""

from pathlib import Path
import pytest

from kin.tui.errors import (
    convert_exception_to_recoverable_error,
    get_diagnostics_log_path,
    log_exception_to_diagnostics,
    tui_error_boundary,
)
from kin.tui.state import RecoverableError


def test_exception_conversion_to_recoverable_error(tmp_path: Path):
    """Assert arbitrary exception converts to RecoverableError and writes to diagnostics log."""
    profile_dir = tmp_path / "profile"
    try:
        raise ValueError("Simulated network timeout test exception")
    except ValueError as test_exc:
        rec_err = convert_exception_to_recoverable_error(test_exc, profile_dir=profile_dir)

    assert isinstance(rec_err, RecoverableError)
    assert "ValueError" in rec_err.what_happened
    assert "Simulated network timeout" in rec_err.what_happened
    assert rec_err.technical_detail is not None
    assert "Traceback" in rec_err.technical_detail

    # Verify diagnostics.log content
    log_path = get_diagnostics_log_path(profile_dir)
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "ValueError: Simulated network timeout" in content
    assert "Traceback" in content


def test_tui_error_boundary_catches_exception_without_crashing(tmp_path: Path):
    """Assert tui_error_boundary catches uncaught exceptions and invokes error handler."""
    profile_dir = tmp_path / "profile"
    caught_errors = []

    def handle_error(err: RecoverableError) -> None:
        caught_errors.append(err)

    # Injected exception inside error boundary block
    with tui_error_boundary(profile_dir=profile_dir, on_error=handle_error):
        raise RuntimeError("Injected runtime failure inside TUI operation")

    # Assert exception was caught and converted
    assert len(caught_errors) == 1
    err = caught_errors[0]
    assert "RuntimeError" in err.what_happened
    assert "Injected runtime failure" in err.what_happened

    # Assert diagnostics log recorded entry
    log_path = get_diagnostics_log_path(profile_dir)
    assert log_path.exists()
    assert "Injected runtime failure" in log_path.read_text(encoding="utf-8")
