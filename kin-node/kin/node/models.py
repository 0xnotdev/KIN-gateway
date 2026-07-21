"""Pydantic models matching the JSON shapes in system-design-v1.md sections 4.1 and 4.4."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Section 4.1 — Agent Card (discovery)
# ---------------------------------------------------------------------------

class AgentCard(BaseModel):
    name: str
    username: str
    public_key: str
    endpoint: str
    capabilities: list[str]
    protocol_version: str


# ---------------------------------------------------------------------------
# Section 4.4 — POST /tasks  (create a task)
# ---------------------------------------------------------------------------

class CreateTaskRequest(BaseModel):
    goal: str
    context: dict[str, Any]
    requester_username: str


class CreateTaskResponse(BaseModel):
    task_id: str
    status: Literal["submitted"]


# ---------------------------------------------------------------------------
# Section 4.4 — POST /tasks/{task_id}/messages  (send a message within a task)
# ---------------------------------------------------------------------------

MessageType = Literal[
    "proposal",
    "counter_proposal",
    "question",
    "answer",
    "confirmation",
    "finalize_proposal",
    "finalize_accept",
]


class SendMessageRequest(BaseModel):
    from_username: str
    content: str
    message_type: MessageType
    origin_ref_id: str | None = None


SendMessageStatus = Literal["working", "input-required", "completed", "failed"]


class SendMessageResponse(BaseModel):
    status: SendMessageStatus


# ---------------------------------------------------------------------------
# Section 4.4 — GET /tasks/{task_id}  (check task status)
# ---------------------------------------------------------------------------

TaskStatus = Literal["submitted", "working", "input-required", "completed", "failed"]


class TaskHistoryEntry(BaseModel):
    from_username: str
    content: str
    message_type: MessageType
    created_at: str


class TaskDraft(BaseModel):
    content: str
    message_type: MessageType


class TaskStatusResponse(BaseModel):
    status: TaskStatus
    history: list[TaskHistoryEntry]
    result: dict[str, Any] | None = None
    draft: TaskDraft | None = None


# ---------------------------------------------------------------------------
# Section 4.4 — GET /relay/inbox  (fetch waiting messages)
# ---------------------------------------------------------------------------

class RelayInboxResponse(BaseModel):
    messages: list[str]
