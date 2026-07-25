"""Base adapter models, capability declarations, and output validation engine per §9.3 and §2.1."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Final, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from kin.schemas import (
    ActionClass,
    AgentCard,
    ApprovalRequest,
    MessageKind,
)


class InputItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["message", "artifact"]
    content: str | None = None
    ref: str | None = None


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    actor: str
    content: str


class AdapterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    protocol_version: Literal["1.1"] = "1.1"

    session: dict[str, Any]  # id, type, turn
    self_participant: dict[str, Any]  # agent_id, card_snapshot
    peer: dict[str, Any]  # person, agent_id, card_snapshot
    objective: str
    inputs: list[InputItem] = Field(default_factory=list)
    history: list[HistoryItem] = Field(default_factory=list)
    local_policy: dict[str, str] = Field(default_factory=dict)


class AdapterActivityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_kind: Literal["activity"] = "activity"
    label: str


class AdapterApprovalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_kind: Literal["approval_request"] = "approval_request"
    approval_request: ApprovalRequest


class AdapterErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_kind: Literal["error"] = "error"
    code: str
    message: str


AdapterEvent = Union[AdapterActivityEvent, AdapterApprovalEvent, AdapterErrorEvent]


class AdapterArtifactItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_or_bytes: Union[str, bytes]
    mime_type: str


class AdapterMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MessageKind
    content: str


class AdapterErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class AdapterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    protocol_version: Literal["1.1"] = "1.1"

    events: list[AdapterEvent] = Field(default_factory=list)
    message: AdapterMessage | None = None
    artifacts: list[AdapterArtifactItem] = Field(default_factory=list)
    terminal: bool = False
    error: AdapterErrorInfo | None = None


class AdapterCapabilityDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_type: str
    allowed_action_classes: set[ActionClass]
    allowed_event_kinds: set[str]


# Pre-defined capability declarations per adapter type
CAPABILITY_DECLARATIONS: dict[str, AdapterCapabilityDeclaration] = {
    "embedded": AdapterCapabilityDeclaration(
        adapter_type="embedded",
        allowed_action_classes={
            ActionClass.INFORMATIONAL_RELAY,
            ActionClass.SESSION_PARTICIPATION,
            ActionClass.ARTIFACT_RECEIPT,
        },
        allowed_event_kinds={"activity", "approval_request", "error"},
    ),
    "webhook": AdapterCapabilityDeclaration(
        adapter_type="webhook",
        allowed_action_classes={
            ActionClass.INFORMATIONAL_RELAY,
            ActionClass.SESSION_PARTICIPATION,
            ActionClass.ARTIFACT_RECEIPT,
        },
        allowed_event_kinds={"activity", "approval_request", "error"},
    ),
    "local_command": AdapterCapabilityDeclaration(
        adapter_type="local_command",
        allowed_action_classes={
            ActionClass.INFORMATIONAL_RELAY,
            ActionClass.SESSION_PARTICIPATION,
            ActionClass.ARTIFACT_RECEIPT,
            ActionClass.WORKSPACE_READ,
            ActionClass.WORKSPACE_WRITE,
            ActionClass.SHELL_NETWORK_EXTERNAL,
        },
        allowed_event_kinds={"activity", "approval_request", "error"},
    ),
}

# Closed list of forbidden scratchpad / chain-of-thought field names
FORBIDDEN_REASONING_KEYS: Final[set[str]] = {
    "reasoning",
    "thinking",
    "chain_of_thought",
    "scratchpad",
    "internal_notes",
}

# Heuristic secret / API key pattern regex
SECRET_PATTERN_REGEX = re.compile(
    r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|bearer\s+[a-zA-Z0-9_\-\.]{20,}|sk[_-]live[_-][a-zA-Z0-9]{24,}|ghp_[a-zA-Z0-9]{36})"
)


@dataclass
class ValidationOutcome:
    valid: bool
    rejection_reason: str | None = None
    sanitized_response: AdapterResponse | None = None


def validate_adapter_output(
    response: AdapterResponse,
    card: AgentCard,
    conn: sqlite3.Connection | None = None,
    vault_key: bytes | None = None,
    session_id: str | None = None,
) -> ValidationOutcome:
    """Validate adapter response against security redaction rules, secret patterns, and capability declarations."""
    from kin.audit.writer import write_audit_event

    adapter_type_str = card.adapter.type.value if hasattr(card.adapter.type, "value") else str(card.adapter.type)

    # 1. Capability Declaration Check
    caps = CAPABILITY_DECLARATIONS.get(adapter_type_str)
    if caps:
        for ev in response.events:
            ev_kind = ev.event_kind
            if ev_kind not in caps.allowed_event_kinds:
                msg = f"Adapter '{adapter_type_str}' emitted disallowed event kind '{ev_kind}'."
                if conn and vault_key and session_id:
                    write_audit_event(
                        conn,
                        vault_key,
                        category="security_rejection",
                        session_id=session_id,
                        actor_username=card.id,
                        summary=msg,
                        payload={"adapter_type": adapter_type_str, "disallowed_event": ev_kind},
                    )
                return ValidationOutcome(valid=False, rejection_reason=msg)

            if ev_kind == "approval_request" and isinstance(ev, AdapterApprovalEvent):
                req_act_class = ev.approval_request.action_class
                if req_act_class not in caps.allowed_action_classes:
                    msg = f"Adapter '{adapter_type_str}' emitted approval request for disallowed action class '{req_act_class.value}'."
                    if conn and vault_key and session_id:
                        write_audit_event(
                            conn,
                            vault_key,
                            category="security_rejection",
                            session_id=session_id,
                            actor_username=card.id,
                            summary=msg,
                            payload={"adapter_type": adapter_type_str, "disallowed_action_class": req_act_class.value},
                        )
                    return ValidationOutcome(valid=False, rejection_reason=msg)

    # 2. Check for forbidden chain-of-thought / scratchpad keys in response dump
    resp_dump = response.model_dump(mode="python")

    def _check_keys(obj: Any) -> str | None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.lower() in FORBIDDEN_REASONING_KEYS:
                    return f"Response contains forbidden scratchpad/chain-of-thought key '{k}'."
                res = _check_keys(v)
                if res:
                    return res
        elif isinstance(obj, list):
            for item in obj:
                res = _check_keys(item)
                if res:
                    return res
        return None

    cot_err = _check_keys(resp_dump)
    if cot_err:
        if conn and vault_key and session_id:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                session_id=session_id,
                actor_username=card.id,
                summary=cot_err,
                payload={"reason": cot_err},
            )
        return ValidationOutcome(valid=False, rejection_reason=cot_err)

    # 3. Check for Secret / API Key leakage
    text_content = ""
    if response.message and response.message.content:
        text_content += response.message.content
    for ev in response.events:
        if isinstance(ev, AdapterActivityEvent):
            text_content += " " + ev.label

    if SECRET_PATTERN_REGEX.search(text_content):
        msg = "Adapter output contains content matching API key or secret token pattern."
        if conn and vault_key and session_id:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                session_id=session_id,
                actor_username=card.id,
                summary=msg,
                payload={"reason": "secret_leakage_detected"},
            )
        return ValidationOutcome(valid=False, rejection_reason=msg)

    # 4. Check for owner-only message kinds emitted by adapter
    if response.message and response.message.kind in (MessageKind.CANCEL, MessageKind.APPROVAL_DECISION):
        msg = f"Adapter attempted to emit owner-only message kind '{response.message.kind.value}'."
        if conn and vault_key and session_id:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                session_id=session_id,
                actor_username=card.id,
                summary=msg,
                payload={"kind": response.message.kind.value},
            )
        return ValidationOutcome(valid=False, rejection_reason=msg)

    return ValidationOutcome(valid=True, sanitized_response=response)
