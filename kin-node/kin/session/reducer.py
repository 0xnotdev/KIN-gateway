"""V1.1 Session State Machine Reducer with Two-Owner Authority and Role Verification."""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kin.schemas import MessageKind, VerifiedEnvelope
from kin.session.transition_matrix import (
    RESUMABLE_STATES,
    TERMINAL_STATES,
    is_valid_transition,
)


class ParticipantInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    agent_id: str
    role: str  # "owner" or "agent"


class SessionState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    initiator_username: str
    receiver_username: str
    status: str = "draft"
    current_turn: int = 0
    max_turns: int = Field(12, ge=1)
    actor_sequences: dict[str, int] = Field(default_factory=dict)
    participants: dict[str, ParticipantInfo] = Field(default_factory=dict)  # username -> ParticipantInfo
    last_resumable_status: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def owner_usernames(self) -> set[str]:
        """Return the set of human owner usernames for both bilateral participants."""
        owners = {self.initiator_username, self.receiver_username}
        for un, p in self.participants.items():
            if p.role == "owner":
                owners.add(un)
        return owners


class ReducerResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    new_state: SessionState
    error_code: str | None = None
    error_message: str | None = None


# Strict MessageKind to state transition mapping for peer envelopes
PEER_KIND_TRANSITION_MAP: dict[MessageKind, str | None] = {
    MessageKind.TASK_REQUEST: "sent",
    MessageKind.ACCEPTANCE: "accepted",
    MessageKind.DECLINE: "declined",
    MessageKind.CLARIFICATION: "needs_clarification",
    MessageKind.PROPOSAL: "active",
    MessageKind.COUNTERPROPOSAL: "active",
    MessageKind.FINDING: "active",
    MessageKind.QUESTION: "active",
    MessageKind.ANSWER: "active",
    MessageKind.ARTIFACT_OFFER: "active",
    MessageKind.ARTIFACT_ACCEPT: "active",
    MessageKind.APPROVAL_REQUEST: "awaiting_owner_approval",
    MessageKind.FINAL_RESULT: "completed",
    MessageKind.CANCEL: "cancelled",
    MessageKind.STATUS_EVENT: None,
    MessageKind.PLAN: "active",
    MessageKind.PARTICIPANT_CHANGED: None,
    MessageKind.APPROVAL_DECISION: None,  # Rejected for peer envelopes; owner-only action!
}

TURN_CONSUMING_KINDS: set[MessageKind] = {
    MessageKind.TASK_REQUEST,
    MessageKind.PROPOSAL,
    MessageKind.COUNTERPROPOSAL,
    MessageKind.FINDING,
    MessageKind.QUESTION,
    MessageKind.ANSWER,
    MessageKind.ARTIFACT_OFFER,
    MessageKind.ARTIFACT_ACCEPT,
}

OWNER_ONLY_KINDS: set[MessageKind] = {
    MessageKind.CANCEL,
    MessageKind.APPROVAL_DECISION,
}


def process_peer_envelope(
    state: SessionState, verified_envelope: VerifiedEnvelope
) -> ReducerResult:
    """Process a cryptographically verified peer envelope through the state machine reducer."""
    envelope = verified_envelope.envelope

    # 1. Enforce terminal state immutability
    if state.status in TERMINAL_STATES:
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="TERMINAL_STATE_IMMUTABLE",
            error_message=f"Session is in terminal state '{state.status}' and cannot accept new events.",
        )

    # 2. Enforce Session ID match
    if envelope.session_id != state.session_id:
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="SESSION_ID_MISMATCH",
            error_message=f"Envelope session_id '{envelope.session_id}' does not match state '{state.session_id}'.",
        )

    # 3. Enforce participant authorization & agent match
    if state.participants:
        if envelope.actor_username not in state.participants:
            return ReducerResult(
                success=False,
                new_state=state,
                error_code="UNAUTHORIZED_ACTOR",
                error_message=f"Actor '{envelope.actor_username}' is not a registered session participant.",
            )

        participant_info = state.participants[envelope.actor_username]
        is_unaccepted_receiver_accept = (
            envelope.kind == MessageKind.ACCEPTANCE
            and envelope.actor_username == state.receiver_username
            and state.status in ("draft", "sent", "queued", "delivered", "peer_review")
        )
        if envelope.actor_agent_id != participant_info.agent_id and not is_unaccepted_receiver_accept:
            return ReducerResult(
                success=False,
                new_state=state,
                error_code="UNAUTHORIZED_AGENT",
                error_message=f"Actor agent ID '{envelope.actor_agent_id}' does not match registered agent '{participant_info.agent_id}'.",
            )

        # 4. Role Check: Reject owner-only control events if sent by an agent actor
        if envelope.kind in OWNER_ONLY_KINDS and participant_info.role != "owner":
            return ReducerResult(
                success=False,
                new_state=state,
                error_code="UNAUTHORIZED_ROLE_ACTION",
                error_message=f"Kind '{envelope.kind.value}' requires human owner authority and cannot be issued by agent '{envelope.actor_agent_id}'.",
            )

    # 5. Enforce sequence monotonicity per actor
    last_seq = state.actor_sequences.get(envelope.actor_username, 0)
    expected_seq = last_seq + 1

    if envelope.sequence == last_seq:
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="DUPLICATE_SEQUENCE",
            error_message=f"Duplicate sequence number {envelope.sequence} from actor '{envelope.actor_username}'.",
        )
    elif envelope.sequence != expected_seq:
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="OUT_OF_ORDER_SEQUENCE",
            error_message=f"Out of order sequence {envelope.sequence} from actor '{envelope.actor_username}' (expected {expected_seq}).",
        )

    # 6. Determine target status strictly from MessageKind mapping
    mapped_target = PEER_KIND_TRANSITION_MAP.get(envelope.kind)
    target_status = mapped_target if mapped_target is not None else state.status

    if target_status != state.status:
        if not is_valid_transition(state.status, target_status) and not is_unaccepted_receiver_accept:
            return ReducerResult(
                success=False,
                new_state=state,
                error_code="INVALID_STATE_TRANSITION",
                error_message=f"Cannot transition from '{state.status}' to '{target_status}' via envelope kind '{envelope.kind}'.",
            )

    # 7. Turn limit enforcement
    new_turn = state.current_turn
    if envelope.kind in TURN_CONSUMING_KINDS:
        if state.current_turn >= state.max_turns and target_status not in TERMINAL_STATES:
            return ReducerResult(
                success=False,
                new_state=state,
                error_code="TURN_LIMIT_EXCEEDED",
                error_message=f"Session reached maximum turn limit ({state.max_turns}).",
            )
        new_turn += 1

    # 8. Checkpoint management for resumable states
    new_last_resumable = state.last_resumable_status
    if target_status in RESUMABLE_STATES:
        new_last_resumable = state.status if state.status not in RESUMABLE_STATES else state.last_resumable_status

    # Produce updated state
    new_sequences = dict(state.actor_sequences)
    new_sequences[envelope.actor_username] = envelope.sequence

    new_events = list(state.events)
    new_events.append(envelope.model_dump(mode="json"))

    new_participants = dict(state.participants)
    if envelope.kind == MessageKind.ACCEPTANCE:
        acc_ag_id = envelope.payload.get("accepting_agent_id") or envelope.payload.get("receiver_agent_id") or envelope.actor_agent_id
        role = "receiver" if envelope.actor_username == state.receiver_username else "owner"
        new_participants[envelope.actor_username] = ParticipantInfo(agent_id=acc_ag_id, role=role)

    updated_state = SessionState(
        session_id=state.session_id,
        initiator_username=state.initiator_username,
        receiver_username=state.receiver_username,
        status=target_status,
        current_turn=new_turn,
        max_turns=state.max_turns,
        actor_sequences=new_sequences,
        participants=new_participants,
        last_resumable_status=new_last_resumable,
        events=new_events,
    )

    return ReducerResult(success=True, new_state=updated_state)


def process_node_command(
    state: SessionState, command: str, payload: dict[str, Any] | None = None
) -> ReducerResult:
    """Process local node / transport infrastructure commands (e.g. mark_queued, mark_delivered, mark_expired)."""
    if state.status in TERMINAL_STATES:
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="TERMINAL_STATE_IMMUTABLE",
            error_message=f"Session is in terminal state '{state.status}'.",
        )

    NODE_COMMAND_MAP = {
        "mark_queued": "queued",
        "mark_delivered": "delivered",
        "mark_peer_review": "peer_review",
        "mark_expired": "expired",
        "mark_failed": "failed",
        "mark_awaiting_peer": "awaiting_peer",
        "mark_awaiting_owner_approval": "awaiting_owner_approval",
    }

    target_status = NODE_COMMAND_MAP.get(command)
    if not target_status:
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="UNKNOWN_NODE_COMMAND",
            error_message=f"Unknown local node command '{command}'.",
        )

    if not is_valid_transition(state.status, target_status):
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="INVALID_STATE_TRANSITION",
            error_message=f"Node command '{command}' cannot transition from '{state.status}' to '{target_status}'.",
        )

    updated_state = SessionState(
        session_id=state.session_id,
        initiator_username=state.initiator_username,
        receiver_username=state.receiver_username,
        status=target_status,
        current_turn=state.current_turn,
        max_turns=state.max_turns,
        actor_sequences=state.actor_sequences,
        participants=state.participants,
        last_resumable_status=state.last_resumable_status,
        events=state.events,
    )
    return ReducerResult(success=True, new_state=updated_state)


def process_owner_command(
    state: SessionState, owner_username: str, action: str, payload: dict[str, Any] | None = None
) -> ReducerResult:
    """Process local human owner actions for either human owner participant (initiator or receiver)."""
    if owner_username not in state.owner_usernames:
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="UNAUTHORIZED_OWNER",
            error_message=f"User '{owner_username}' is not a recognized human owner of this session.",
        )

    if state.status in TERMINAL_STATES:
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="TERMINAL_STATE_IMMUTABLE",
            error_message=f"Session is in terminal state '{state.status}'.",
        )

    if action == "owner_pause":
        target_status = "paused"
    elif action == "owner_resume":
        target_status = "active"
    elif action == "owner_cancel":
        target_status = "cancelled"
    elif action == "owner_approval_decision":
        decision = (payload or {}).get("decision")
        if decision in ("approve_once", "always_allow_bounded", "edit_constraints"):
            target_status = "active"
        elif decision == "deny":
            target_status = "paused"
        else:
            return ReducerResult(
                success=False,
                new_state=state,
                error_code="INVALID_APPROVAL_DECISION",
                error_message=f"Invalid approval decision '{decision}'.",
            )
    else:
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="UNKNOWN_OWNER_ACTION",
            error_message=f"Unknown owner action '{action}'.",
        )

    if not is_valid_transition(state.status, target_status):
        return ReducerResult(
            success=False,
            new_state=state,
            error_code="INVALID_STATE_TRANSITION",
            error_message=f"Owner action '{action}' cannot transition from '{state.status}' to '{target_status}'.",
        )

    new_last_resumable = state.last_resumable_status
    if target_status in RESUMABLE_STATES:
        new_last_resumable = state.status

    updated_state = SessionState(
        session_id=state.session_id,
        initiator_username=state.initiator_username,
        receiver_username=state.receiver_username,
        status=target_status,
        current_turn=state.current_turn,
        max_turns=state.max_turns,
        actor_sequences=state.actor_sequences,
        participants=state.participants,
        last_resumable_status=new_last_resumable,
        events=state.events,
    )
    return ReducerResult(success=True, new_state=updated_state)


def reconstruct_session_state(
    conn: sqlite3.Connection,
    vault_key: bytes,
    session_id: str,
) -> SessionState | None:
    """Reconstruct a full SessionState object from local storage (sessions + session_events).

    Returns:
        SessionState with restored actor_sequences, participants, current_turn, status,
        or None if session_id is not found in database.
    """
    cur = conn.cursor()
    cur.execute(
        """\
        SELECT session_id, initiator_username, receiver_username, status,
               sender_agent_id, receiver_agent_id, turn_limit
        FROM sessions WHERE session_id = ?
        """,
        (session_id,),
    )
    row = cur.fetchone()
    if not row:
        return None

    (
        sess_id,
        init_un,
        rec_un,
        status,
        sender_agent_id,
        receiver_agent_id,
        turn_limit,
    ) = row

    participants: dict[str, ParticipantInfo] = {}
    if init_un:
        participants[init_un] = ParticipantInfo(
            agent_id=sender_agent_id or init_un, role="owner"
        )
    if rec_un:
        participants[rec_un] = ParticipantInfo(
            agent_id=receiver_agent_id or rec_un, role="owner"
        )

    cur.execute(
        """\
        SELECT actor_username, MAX(sequence) FROM session_events
        WHERE session_id = ? AND sequence IS NOT NULL
        GROUP BY actor_username
        """,
        (session_id,),
    )
    actor_sequences: dict[str, int] = {}
    for un, max_seq in cur.fetchall():
        if un and max_seq is not None:
            actor_sequences[un] = int(max_seq)

    turn_kinds = [k.value for k in TURN_CONSUMING_KINDS]
    placeholders = ",".join("?" * len(turn_kinds))
    cur.execute(
        f"SELECT COUNT(*) FROM session_events WHERE session_id = ? AND kind IN ({placeholders})",
        [session_id, *turn_kinds],
    )
    current_turn = cur.fetchone()[0] or 0

    # Query all session events in chronological event_order
    cur.execute(
        """\
        SELECT event_id, sequence, actor_username, kind, visibility, payload_json, created_at
        FROM session_events WHERE session_id = ? ORDER BY event_order ASC
        """,
        (session_id,),
    )
    events_list: list[dict[str, Any]] = []
    for ev_row in cur.fetchall():
        payload_enc = ev_row[5]
        payload_dict = {}
        if payload_enc:
            try:
                from kin.storage.vault import decrypt_field
                dec_str = decrypt_field(vault_key, payload_enc)
                import json
                payload_dict = json.loads(dec_str)
            except Exception:
                payload_dict = {"raw": payload_enc}

        events_list.append({
            "event_id": ev_row[0],
            "sequence": ev_row[1],
            "actor_username": ev_row[2],
            "kind": ev_row[3],
            "visibility": ev_row[4],
            "payload": payload_dict,
            "created_at": ev_row[6],
        })

    return SessionState(
        session_id=sess_id,
        initiator_username=init_un,
        receiver_username=rec_un,
        status=status,
        current_turn=current_turn,
        max_turns=turn_limit or 12,
        actor_sequences=actor_sequences,
        participants=participants,
        events=events_list,
    )
