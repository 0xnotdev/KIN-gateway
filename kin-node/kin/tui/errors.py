"""Global Error Boundary and Diagnostic Logger for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §10.3, §14.1
"""

from contextlib import contextmanager
import datetime
import traceback
from pathlib import Path
from typing import Callable, Generator, Optional, Tuple, TypeVar

from kin.tui.state import RecoverableError

T = TypeVar("T")


def get_diagnostics_log_path(profile_dir: Optional[Path] = None) -> Path:
    """Resolve the diagnostics log path for a profile directory.

    Default location: ~/.kin/profiles/default/diagnostics.log
    """
    if profile_dir is None:
        profile_dir = Path.home() / ".kin" / "profiles" / "default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir / "diagnostics.log"


def log_exception_to_diagnostics(
    exc: Exception, profile_dir: Optional[Path] = None
) -> str:
    """Write an uncaught exception traceback to diagnostics.log with timestamp.

    Returns the formatted technical detail string.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    tech_detail = f"[{timestamp}] Exception: {type(exc).__name__}: {str(exc)}\n{tb_str}"

    log_path = get_diagnostics_log_path(profile_dir)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(tech_detail)
            f.write("\n" + "=" * 60 + "\n")
    except Exception as write_err:
        # Emergency stderr fallback if log file write fails
        print(f"Warning: Failed writing to diagnostics log: {write_err}")

    return tech_detail


from kin.tui.redaction import redact_ui_text


def convert_exception_to_recoverable_error(
    exc: Exception, profile_dir: Optional[Path] = None
) -> RecoverableError:
    """Convert an arbitrary Exception into a structured RecoverableError card."""
    tech_detail = log_exception_to_diagnostics(exc, profile_dir)
    exc_type = type(exc).__name__
    exc_msg = str(exc) or "An unexpected runtime error occurred."

    return RecoverableError(
        what_happened=redact_ui_text(f"Unexpected {exc_type}: {exc_msg}"),
        impact="The current operation was safely interrupted.",
        preserved="All previous session state and storage items remain intact.",
        next_action="Press 'r' to retry operation or check diagnostics.log for technical details.",
        technical_detail=redact_ui_text(tech_detail),
    )


@contextmanager
def tui_error_boundary(
    profile_dir: Optional[Path] = None,
    on_error: Optional[Callable[[RecoverableError], None]] = None,
) -> Generator[None, None, None]:
    """Context manager catching any exception during TUI operation.

    Converts exception to RecoverableError, logs traceback to diagnostics.log,
    and prevents raw tracebacks from reaching the TUI.
    """
    try:
        yield
    except Exception as exc:
        rec_err = convert_exception_to_recoverable_error(exc, profile_dir)
        if on_error is not None:
            on_error(rec_err)
