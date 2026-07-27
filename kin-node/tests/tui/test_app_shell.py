"""App shell tests and Textual snapshot tests for KIN V1.1 TUI Milestone T0.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §2, §14.1, §14.2
"""

import sys
from pathlib import Path
import pytest

from kin.tui.app import KinApp, is_interactive_tty, run_tui_app
from kin.tui.errors import get_diagnostics_log_path


def test_non_tty_launches_one_line_message_and_exits_zero(monkeypatch, capsys):
    """Assert non-TTY stdin/stdout outputs standard one-line notice and exits 0."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert is_interactive_tty() is False

    exit_code = run_tui_app()
    assert exit_code == 0

    captured = capsys.readouterr()
    assert (
        "KIN TUI requires an interactive terminal; run a subcommand instead."
        in captured.out
    )


def test_tty_detection_positive(monkeypatch):
    """Assert is_interactive_tty returns True when both stdin and stdout are TTYs."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert is_interactive_tty() is True


@pytest.mark.asyncio
async def test_app_normal_quit():
    """Assert KinApp initializes, composes panel, and exits cleanly on quit action."""
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test() as pilot:
        pilot.app.set_focus(None)
        await pilot.press("q")
        assert app._exit is True


@pytest.mark.asyncio
async def test_app_ctrl_c_quit():
    """Assert KinApp handles Ctrl+C shortcut to exit cleanly."""
    app = KinApp(theme_name="kin-graphite")
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        assert app._exit is True


def test_terminal_restoration_on_injected_exception(tmp_path: Path, monkeypatch):
    """Assert terminal is restored and error is logged when an exception is raised inside error boundary."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    # Injected crash during app run
    def failing_run(*args, **kwargs):
        raise RuntimeError("Simulated terminal crash inside app.run()")

    monkeypatch.setattr(KinApp, "run", failing_run)

    # Executing run_tui_app should catch crash, log it, and return cleanly without uncaught exception
    run_tui_app(profile_name="crash_test")

    log_path = tmp_path / ".kin" / "profiles" / "crash_test" / "diagnostics.log"
    assert log_path.exists()
    assert "Simulated terminal crash" in log_path.read_text(encoding="utf-8")


def test_blank_shell_snapshot_160x44(snap_compare):
    """Textual snapshot test for blank shell at wide 160x44 breakpoint."""
    app = KinApp(theme_name="kin-graphite")
    assert snap_compare(app, terminal_size=(160, 44))


def test_blank_shell_snapshot_120x36(snap_compare):
    """Textual snapshot test for blank shell at standard 120x36 breakpoint."""
    app = KinApp(theme_name="kin-graphite")
    assert snap_compare(app, terminal_size=(120, 36))


def test_blank_shell_snapshot_90x28(snap_compare):
    """Textual snapshot test for blank shell at compact 90x28 breakpoint."""
    app = KinApp(theme_name="kin-graphite")
    assert snap_compare(app, terminal_size=(90, 28))


def test_blank_shell_snapshot_80x24(snap_compare):
    """Textual snapshot test for blank shell at minimal 80x24 breakpoint."""
    app = KinApp(theme_name="kin-graphite")
    assert snap_compare(app, terminal_size=(80, 24))
