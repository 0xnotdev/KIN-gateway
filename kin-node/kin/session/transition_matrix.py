"""Authoritative state transition matrix for V1.1 session lifecycle state machine."""

from __future__ import annotations

from typing import Final

# Complete valid state transitions matrix
VALID_TRANSITIONS: Final[dict[str, set[str]]] = {
    "draft": {"sent", "cancelled", "expired"},
    "sent": {"queued", "delivered", "failed", "expired"},
    "queued": {"delivered", "failed", "expired"},
    "delivered": {"peer_review", "failed", "expired"},
    "peer_review": {"accepted", "declined", "needs_clarification", "cancelled", "expired"},
    "needs_clarification": {"peer_review", "cancelled", "failed", "expired"},
    "accepted": {"active", "cancelled", "expired"},
    "active": {
        "awaiting_owner_approval",
        "awaiting_peer",
        "paused",
        "completed",
        "failed",
        "cancelled",
        "expired",
    },
    "awaiting_owner_approval": {"active", "paused", "failed", "cancelled", "expired"},
    "awaiting_peer": {"active", "paused", "failed", "cancelled", "expired"},
    "paused": {"active", "cancelled", "failed", "expired"},
    "completed": set(),  # Terminal
    "failed": set(),     # Terminal
    "cancelled": set(),  # Terminal
    "expired": set(),    # Terminal
    "declined": set(),   # Terminal
}

TERMINAL_STATES: Final[set[str]] = {"completed", "failed", "cancelled", "expired", "declined"}
RESUMABLE_STATES: Final[set[str]] = {"awaiting_owner_approval", "awaiting_peer", "paused"}


def is_valid_transition(current_status: str, next_status: str) -> bool:
    """Check if transitioning from current_status to next_status is permitted."""
    allowed = VALID_TRANSITIONS.get(current_status, set())
    return next_status in allowed


def is_terminal_state(status: str) -> bool:
    """Return True if status is a terminal state."""
    return status in TERMINAL_STATES
