"""Central motion and timing limits for the KIN terminal UI.

The values in this module are policy tokens, not widget-specific defaults. Keeping
them separate from the visual tokens in :mod:`kin.tui.tokens` makes timing behavior
easy to audit without mixing it with theme data.
"""


# Focus changes in Textual are discrete and currently have no animated transition.
# These bounds are retained as the design limit if a focus animation is introduced.
FOCUS_TRANSITION_MS_MIN: int = 80
FOCUS_TRANSITION_MS_MAX: int = 120

# A genuinely live-appended timeline event remains highlighted for exactly 120 ms.
EVENT_PULSE_DURATION_MS: int = 120

EXPAND_TRANSITION_MS_MIN: int = 120
EXPAND_TRANSITION_MS_MAX: int = 180
EXPAND_TRANSITION_MS: int = 150

# Modal screens are currently shown and dismissed synchronously (0 ms). Any future
# modal animation must remain at or below this cap.
MODAL_TRANSITION_MS: int = 0
MODAL_TRANSITION_MS_MAX: int = 120

SPINNER_FPS_MIN: int = 8
SPINNER_FPS_MAX: int = 12
SPINNER_FPS: int = 10
SPINNER_FRAME_INTERVAL_SECONDS: float = 1.0 / SPINNER_FPS

TOAST_DURATION_SEC_MIN: int = 3
TOAST_DURATION_SEC_MAX: int = 6
TOAST_DURATION_SEC: int = 4
TOAST_MAX_AMBER_PULSES: int = 2
TOAST_AMBER_PULSE_INTERVAL_MS: int = EVENT_PULSE_DURATION_MS


def milliseconds_to_seconds(duration_ms: int) -> float:
    """Convert an integer millisecond token to Textual's seconds unit."""
    return duration_ms / 1000.0


def clamp_toast_duration_seconds(duration_seconds: float) -> float:
    """Clamp a requested toast lifetime to the specification's inclusive range."""
    return min(TOAST_DURATION_SEC_MAX, max(TOAST_DURATION_SEC_MIN, duration_seconds))


# Compatibility aliases for callers from the earlier T7 implementation. New code
# uses the canonical names above, which mirror the wording of the audit spec.
FOCUS_TRANSITION_MIN_MS = FOCUS_TRANSITION_MS_MIN
FOCUS_TRANSITION_MAX_MS = FOCUS_TRANSITION_MS_MAX
FOCUS_TRANSITION_DEFAULT_MS = 100
EVENT_PULSE_MS = EVENT_PULSE_DURATION_MS
EXPAND_COLLAPSE_MIN_MS = EXPAND_TRANSITION_MS_MIN
EXPAND_COLLAPSE_MAX_MS = EXPAND_TRANSITION_MS_MAX
EXPAND_COLLAPSE_DEFAULT_MS = EXPAND_TRANSITION_MS
MODAL_ANIMATION_MAX_MS = MODAL_TRANSITION_MS_MAX
SPINNER_MIN_FPS = SPINNER_FPS_MIN
SPINNER_MAX_FPS = SPINNER_FPS_MAX
TOAST_MIN_VISIBLE_MS = TOAST_DURATION_SEC_MIN * 1000
TOAST_MAX_VISIBLE_MS = TOAST_DURATION_SEC_MAX * 1000
MAX_AMBER_PULSES_PER_EVENT = TOAST_MAX_AMBER_PULSES


def validate_timing_in_range(value_ms: int, minimum_ms: int, maximum_ms: int) -> bool:
    """Return whether a duration falls within inclusive motion bounds."""
    return minimum_ms <= value_ms <= maximum_ms
