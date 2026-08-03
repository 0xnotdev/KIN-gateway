"""Motion Timing Limits & Hysteresis Controls (§14.9 Phase A / Build Step 3).

Defines spec-enforced constants and helpers for animation durations, frame rates,
keystroke immediacy, and reflow scoping.
"""

from typing import Any, Dict, List, Optional, Tuple


# Spec-defined timing thresholds (§14.9 step 3)
FOCUS_TRANSITION_MIN_MS: int = 80
FOCUS_TRANSITION_MAX_MS: int = 120
FOCUS_TRANSITION_DEFAULT_MS: int = 100

EVENT_PULSE_MS: int = 120

EXPAND_COLLAPSE_MIN_MS: int = 120
EXPAND_COLLAPSE_MAX_MS: int = 180
EXPAND_COLLAPSE_DEFAULT_MS: int = 150

MODAL_ANIMATION_MAX_MS: int = 120

SPINNER_MIN_FPS: int = 8
SPINNER_MAX_FPS: int = 12

TOAST_MIN_VISIBLE_MS: int = 3000
TOAST_MAX_VISIBLE_MS: int = 6000

MAX_AMBER_PULSES_PER_EVENT: int = 2


def validate_timing_in_range(val_ms: int, min_ms: int, max_ms: int) -> bool:
    """Assert a motion duration is within spec-mandated minimum and maximum boundaries."""
    return min_ms <= val_ms <= max_ms


class AmberPulseTracker:
    """Tracks amber pulse counts per event to enforce max 2 pulses (no indefinite pulsing)."""

    def __init__(self, max_pulses: int = MAX_AMBER_PULSES_PER_EVENT):
        self.max_pulses = max_pulses
        self._counts: Dict[str, int] = {}

    def trigger_pulse(self, event_id: str) -> bool:
        """Attempt to trigger an amber pulse for event_id.

        Returns True if pulse allowed, False if capped at max_pulses.
        """
        current = self._counts.get(event_id, 0)
        if current >= self.max_pulses:
            return False
        self._counts[event_id] = current + 1
        return True

    def get_pulse_count(self, event_id: str) -> int:
        return self._counts.get(event_id, 0)


class MotionFrameController:
    """Controls keystroke priority and reflow isolation during animations."""

    def __init__(self):
        self.animation_in_flight: bool = False
        self.processed_keystrokes: List[str] = []
        self.layout_reflow_count: int = 0

    def process_key(self, key_name: str) -> Tuple[bool, str]:
        """Process a key event immediately, even if an animation is currently in flight.

        'Keystrokes always win': key events are processed same-frame and never queued
        behind animation frame callbacks.
        """
        self.processed_keystrokes.append(key_name)
        # Keystrokes cancel or pre-empt in-flight animation
        if self.animation_in_flight:
            self.animation_in_flight = False
            return True, f"Key '{key_name}' processed same-frame (animation pre-empted)"
        return True, f"Key '{key_name}' processed same-frame"

    def record_update(self, widget_id: str, is_full_screen: bool = False) -> Dict[str, Any]:
        """Record a widget update, enforcing localized refresh rather than full-screen reflow."""
        if is_full_screen:
            self.layout_reflow_count += 1
        return {
            "widget_id": widget_id,
            "reflow_triggered": is_full_screen,
            "total_reflows": self.layout_reflow_count,
        }
