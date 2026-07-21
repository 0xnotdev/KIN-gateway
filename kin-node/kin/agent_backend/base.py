"""Agent backend interface per system-design-v1.md section 1.1."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal
from pydantic import BaseModel


class AgentBackendRequest(BaseModel):
    task_goal: str
    context: dict[str, Any]
    conversation_history: list[str]


class AgentBackendResponse(BaseModel):
    reply: str
    message_type: Literal[
        "proposal", "counter_proposal", "question", "answer", "confirmation"
    ]


class BaseAgentBackend(ABC):
    """Abstract base class/interface for pluggable agent backends."""

    @abstractmethod
    def generate_response(self, request: AgentBackendRequest) -> AgentBackendResponse:
        """Generate a response given task_goal, context, and conversation history."""
        ...
