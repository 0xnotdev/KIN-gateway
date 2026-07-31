"""DispatchController for managing the 7-step session dispatch wizard state (§C1).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.7 Phase C
"""

from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from kin.schemas import SessionType
from kin.tui.local_state import (
    get_all_agent_summaries,
    get_local_agents_summaries,
    get_local_contacts_summaries,
)
from kin.tui.state import AgentCardView, ContactSummary, ContextPantryItem, DispatchDraft


class DispatchStep(Enum):
    PEER_SELECTION = 0
    SENDER_AGENT_SELECTION = 1
    RECEIVER_AGENT_SELECTION = 2
    COLLABORATION_TYPE = 3
    GOAL_INPUT = 4
    CONTEXT_PANTRY = 5
    REVIEW_DISPATCH = 6


STEP_NAMES = [
    "Select Peer Contact",
    "Select Your Agent",
    "Select Their Agent",
    "Collaboration Mode",
    "Define Goal",
    "Context Pantry",
    "Review & Dispatch",
]

# Master session type values sourced directly from kin.schemas.SessionType
VALID_SESSION_TYPES = tuple(st.value for st in SessionType)


class DispatchController:
    """Manages state, navigation, and validation for the 7-step Dispatch Wizard (§C1)."""

    def __init__(
        self,
        profile_name: str = "default",
        profile_dir: Optional[Path] = None,
        initial_draft: Optional[DispatchDraft] = None,
    ) -> None:
        self.profile_name = profile_name
        self.profile_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)
        self.draft: DispatchDraft = initial_draft or DispatchDraft()
        self.current_step: DispatchStep = DispatchStep(self.draft.current_step)

    def set_step(self, step: Union[int, DispatchStep]) -> bool:
        """Set active wizard step with validation."""
        target_step = DispatchStep(step) if isinstance(step, int) else step

        # Cannot skip ahead past uncompleted required steps
        if target_step.value > self.current_step.value:
            if not self.validate_current_step():
                return False

        self.current_step = target_step
        self.draft.current_step = target_step.value
        self.draft.dirty = True
        return True

    def next_step(self) -> bool:
        if self.current_step.value < len(STEP_NAMES) - 1:
            return self.set_step(self.current_step.value + 1)
        return False

    def prev_step(self) -> bool:
        if self.current_step.value > 0:
            return self.set_step(self.current_step.value - 1)
        return False

    def validate_current_step(self) -> bool:
        """Validate current step requirements before advancing (§C1)."""
        if self.current_step == DispatchStep.PEER_SELECTION:
            return bool(self.draft.peer_username)
        elif self.current_step == DispatchStep.SENDER_AGENT_SELECTION:
            return bool(self.draft.sender_agent_id)
        elif self.current_step == DispatchStep.RECEIVER_AGENT_SELECTION:
            return bool(self.draft.receiver_agent_id)
        elif self.current_step == DispatchStep.COLLABORATION_TYPE:
            return self.draft.session_type in VALID_SESSION_TYPES
        elif self.current_step == DispatchStep.GOAL_INPUT:
            return bool(self.draft.goal and self.draft.goal.strip())
        elif self.current_step == DispatchStep.CONTEXT_PANTRY:
            return True  # Pantry items are optional
        elif self.current_step == DispatchStep.REVIEW_DISPATCH:
            return (
                bool(self.draft.peer_username)
                and bool(self.draft.sender_agent_id)
                and bool(self.draft.receiver_agent_id)
                and bool(self.draft.goal)
            )
        return True

    def select_peer(self, username: str) -> None:
        self.draft.peer_username = username
        self.draft.dirty = True

    def select_sender_agent(self, agent_id: str) -> None:
        self.draft.sender_agent_id = agent_id
        self.draft.dirty = True

    def select_receiver_agent(self, agent_id: str) -> None:
        self.draft.receiver_agent_id = agent_id
        self.draft.dirty = True

    def set_session_type(self, session_type: str) -> None:
        if session_type in VALID_SESSION_TYPES:
            self.draft.session_type = session_type
            self.draft.dirty = True

    def set_goal(self, goal: str) -> None:
        self.draft.goal = goal
        self.draft.dirty = True

    def add_pantry_item(self, item: ContextPantryItem) -> None:
        self.draft.pantry_items.append(item)
        self.draft.dirty = True

    def remove_pantry_item(self, index: int) -> bool:
        if 0 <= index < len(self.draft.pantry_items):
            self.draft.pantry_items.pop(index)
            self.draft.dirty = True
            return True
        return False
