"""Shared Widget Lifecycle State Contract for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5 (build step 4)
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, Union

from kin.tui.layout import Breakpoint, classify_breakpoint


class WidgetLifecycleState(str, Enum):
    """The seven standard lifecycle states required for all KIN TUI widgets (§14.5)."""

    LOADING = "loading"
    EMPTY = "empty"
    NORMAL = "normal"
    FOCUSED = "focused"
    DISABLED = "disabled"
    RECOVERABLE_ERROR = "recoverable_error"
    NARROW = "narrow"


def is_narrow_breakpoint(breakpoint_or_width: Union[Breakpoint, int], height: int = 44) -> bool:
    """Classify whether a breakpoint or width/height pair corresponds to NARROW presentation mode (§14.5).

    Derives directly from layout.py's classify_breakpoint() to prevent layout drift.
    """
    if isinstance(breakpoint_or_width, str):
        bp = breakpoint_or_width
    else:
        bp = classify_breakpoint(breakpoint_or_width, height)

    return bp in ("compact", "minimal")


class LifecycleWidgetMixin:
    """Mixin enforcing the shared 7-state lifecycle contract across all foundation widgets."""

    def __init__(
        self,
        lifecycle_state: WidgetLifecycleState = WidgetLifecycleState.NORMAL,
        disabled_reason: Optional[str] = None,
        now: Optional[Union[datetime, str, float]] = None,
        retry_callback: Optional[Callable[[], None]] = None,
        next_action_label: Optional[str] = None,
        next_action_callback: Optional[Callable[[], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._lifecycle_state: WidgetLifecycleState = lifecycle_state
        self._disabled_reason: Optional[str] = disabled_reason
        self._last_updated_at: Optional[datetime] = None
        self._retry_callback: Optional[Callable[[], None]] = retry_callback
        self._next_action_label: Optional[str] = next_action_label
        self._next_action_callback: Optional[Callable[[], None]] = next_action_callback

        self.update_clock(now)

        # Enforce contract rules on init
        if self._lifecycle_state == WidgetLifecycleState.DISABLED:
            self._validate_disabled_reason(self._disabled_reason)

    @property
    def lifecycle_state(self) -> WidgetLifecycleState:
        return self._lifecycle_state

    @property
    def disabled_reason(self) -> Optional[str]:
        return self._disabled_reason

    @property
    def last_updated_at(self) -> Optional[datetime]:
        return self._last_updated_at

    def update_clock(self, now: Optional[Union[datetime, str, float]] = None) -> None:
        """Update injectable clock timestamp without wall-clock coupling."""
        if now is None:
            self._last_updated_at = datetime.now(timezone.utc)
        elif isinstance(now, datetime):
            self._last_updated_at = now
        elif isinstance(now, str):
            try:
                self._last_updated_at = datetime.fromisoformat(now)
            except ValueError:
                self._last_updated_at = datetime.now(timezone.utc)
        elif isinstance(now, (int, float)):
            self._last_updated_at = datetime.fromtimestamp(now, timezone.utc)

    def _validate_disabled_reason(self, reason: Optional[str]) -> str:
        if not reason or not isinstance(reason, str) or not reason.strip():
            raise ValueError(
                "disabled_reason (non-empty string) is strictly required when setting DISABLED state! "
                "Disabling a widget without providing an explicit user-facing reason is prohibited (§14.5)."
            )
        return reason.strip()

    def set_lifecycle_state(
        self,
        state: WidgetLifecycleState,
        *,
        disabled_reason: Optional[str] = None,
        now: Optional[Union[datetime, str, float]] = None,
        retry_callback: Optional[Callable[[], None]] = None,
        next_action_label: Optional[str] = None,
        next_action_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """Set widget lifecycle state and validate state parameters (§14.5)."""
        if state == WidgetLifecycleState.DISABLED:
            # Use provided reason or fallback to existing reason
            target_reason = disabled_reason or self._disabled_reason
            self._disabled_reason = self._validate_disabled_reason(target_reason)
        elif disabled_reason is not None:
            self._disabled_reason = disabled_reason

        self._lifecycle_state = state

        if now is not None:
            self.update_clock(now)

        if retry_callback is not None:
            self._retry_callback = retry_callback

        if next_action_label is not None:
            self._next_action_label = next_action_label

        if next_action_callback is not None:
            self._next_action_callback = next_action_callback
