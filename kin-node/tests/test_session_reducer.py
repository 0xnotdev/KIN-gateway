"""Unit tests for V1.1 Session Reducer with authority splitting and role verification."""

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.schemas import (
    MessageKind,
    SessionEnvelope,
    VerifiedEnvelope,
    compute_content_hash,
    sign_envelope,
    verify_and_build_envelope,
)
from kin.session.reducer import (
    ParticipantInfo,
    SessionState,
    process_node_command,
    process_owner_command,
    process_peer_envelope,
)
from kin.session.transition_matrix import (
    VALID_TRANSITIONS,
    TERMINAL_STATES,
    is_valid_transition,
)


def build_verified_envelope(
    session_id: str = "sess-100",
    sequence: int = 1,
    actor: str = "alice",
    agent_id: str = "scout",
    kind: MessageKind = MessageKind.TASK_REQUEST,
    priv_key: ed25519.Ed25519PrivateKey | None = None,
    payload: dict | None = None,
) -> VerifiedEnvelope:
    if priv_key is None:
        priv_key = ed25519.Ed25519PrivateKey.generate()

    if payload is None:
        payload = {"goal": "test"}
    hash_str = compute_content_hash(payload)

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": sequence,
        "actor_username": actor,
        "actor_agent_id": agent_id,
        "timestamp": "2026-07-22T12:00:00.000Z",
        "kind": kind.value if isinstance(kind, MessageKind) else kind,
        "content_hash": hash_str,
        "payload": payload,
    }
    sig = sign_envelope(env_dict, priv_key)
    env_dict["signature"] = sig

    participant_map = {actor: agent_id}
    get_pub = lambda u: priv_key.public_key() if u == actor else None

    res = verify_and_build_envelope(env_dict, get_pub, session_id, participant_map)
    assert res.success is True
    return res.verified_envelope


def test_transition_matrix_declined_and_expiry():
    """Verify state transition validator supports declined and expiry transitions."""
    assert is_valid_transition("peer_review", "declined") is True
    assert is_valid_transition("peer_review", "expired") is True
    assert is_valid_transition("paused", "expired") is True
    assert is_valid_transition("declined", "active") is False


def test_peer_envelope_happy_path_lifecycle(alice_keys, bob_keys):
    """Test standard peer envelope state machine transitions using conftest key fixtures."""
    participants = {
        "alice": ParticipantInfo(agent_id="scout", role="owner"),
        "bob": ParticipantInfo(agent_id="cleaner", role="agent"),
    }
    state = SessionState(
        session_id="sess-100",
        initiator_username="alice",
        receiver_username="bob",
        status="draft",
        participants=participants,
    )

    alice_key = alice_keys["private_key"]
    bob_key = bob_keys["private_key"]

    # draft -> sent via task_request
    v_env1 = build_verified_envelope("sess-100", 1, "alice", "scout", MessageKind.TASK_REQUEST, alice_key)
    res1 = process_peer_envelope(state, v_env1)
    assert res1.success is True
    assert res1.new_state.status == "sent"

    # node command: sent -> delivered -> peer_review
    res_node1 = process_node_command(res1.new_state, "mark_delivered")
    assert res_node1.success is True
    res_node2 = process_node_command(res_node1.new_state, "mark_peer_review")
    assert res_node2.success is True
    assert res_node2.new_state.status == "peer_review"

    # peer_review -> accepted via ACCEPTANCE
    v_env2 = build_verified_envelope("sess-100", 1, "bob", "cleaner", MessageKind.ACCEPTANCE, bob_key)
    res2 = process_peer_envelope(res_node2.new_state, v_env2)
    assert res2.success is True
    assert res2.new_state.status == "accepted"


def test_bilateral_owner_command_authority():
    """Test that BOTH human owners (Alice and Bob) can pause/resume/cancel their participation."""
    participants = {
        "alice": ParticipantInfo(agent_id="scout", role="owner"),
        "bob": ParticipantInfo(agent_id="finance-analyst", role="owner"),
    }
    state = SessionState(
        session_id="sess-100",
        initiator_username="alice",
        receiver_username="bob",
        status="active",
        participants=participants,
    )

    # Bob (receiver human owner) can pause session
    res_bob_pause = process_owner_command(state, "bob", "owner_pause")
    assert res_bob_pause.success is True
    assert res_bob_pause.new_state.status == "paused"

    # Alice (initiator human owner) can resume session
    res_alice_resume = process_owner_command(res_bob_pause.new_state, "alice", "owner_resume")
    assert res_alice_resume.success is True
    assert res_alice_resume.new_state.status == "active"

    # Bob (receiver human owner) can cancel session
    res_bob_cancel = process_owner_command(res_alice_resume.new_state, "bob", "owner_cancel")
    assert res_bob_cancel.success is True
    assert res_bob_cancel.new_state.status == "cancelled"

    # Unauthorized third party Charlie fails
    res_charlie = process_owner_command(state, "charlie", "owner_cancel")
    assert res_charlie.success is False
    assert res_charlie.error_code == "UNAUTHORIZED_OWNER"


def test_agent_role_cannot_issue_cancel(bob_keys):
    """Verify an agent role (role='agent') CANNOT issue CANCEL via peer envelope using bob_keys fixture."""
    participants = {
        "bob": ParticipantInfo(agent_id="cleaner", role="agent"),
    }
    state = SessionState(
        session_id="sess-100",
        initiator_username="alice",
        receiver_username="bob",
        status="active",
        participants=participants,
    )

    bob_key = bob_keys["private_key"]
    v_env = build_verified_envelope("sess-100", 1, "bob", "cleaner", MessageKind.CANCEL, bob_key)
    res = process_peer_envelope(state, v_env)
    assert res.success is False
    assert res.error_code == "UNAUTHORIZED_ROLE_ACTION"


# -----------------------------------------------------------------------------
# TASK 2: Exhaustive Reducer Transition & Rejection Tests
# -----------------------------------------------------------------------------

LEGAL_TRANSITIONS_DATA = [
    # (from_state, to_state, mechanism, detail)
    ("draft", "sent", "peer", MessageKind.TASK_REQUEST),
    ("draft", "cancelled", "owner", "owner_cancel"),
    ("draft", "expired", "node", "mark_expired"),
    ("sent", "queued", "node", "mark_queued"),
    ("sent", "delivered", "node", "mark_delivered"),
    ("sent", "failed", "node", "mark_failed"),
    ("sent", "expired", "node", "mark_expired"),
    ("queued", "delivered", "node", "mark_delivered"),
    ("queued", "failed", "node", "mark_failed"),
    ("queued", "expired", "node", "mark_expired"),
    ("delivered", "peer_review", "node", "mark_peer_review"),
    ("delivered", "failed", "node", "mark_failed"),
    ("delivered", "expired", "node", "mark_expired"),
    ("peer_review", "accepted", "peer", MessageKind.ACCEPTANCE),
    ("peer_review", "declined", "peer", MessageKind.DECLINE),
    ("peer_review", "needs_clarification", "peer", MessageKind.CLARIFICATION),
    ("peer_review", "cancelled", "owner", "owner_cancel"),
    ("peer_review", "expired", "node", "mark_expired"),
    ("needs_clarification", "peer_review", "node", "mark_peer_review"),
    ("needs_clarification", "cancelled", "owner", "owner_cancel"),
    ("needs_clarification", "failed", "node", "mark_failed"),
    ("needs_clarification", "expired", "node", "mark_expired"),
    ("accepted", "active", "peer", MessageKind.PROPOSAL),
    ("accepted", "cancelled", "owner", "owner_cancel"),
    ("accepted", "expired", "node", "mark_expired"),
    ("active", "awaiting_owner_approval", "peer", MessageKind.APPROVAL_REQUEST),
    ("active", "awaiting_peer", "node", "mark_awaiting_peer"),
    ("active", "paused", "owner", "owner_pause"),
    ("active", "completed", "peer", MessageKind.FINAL_RESULT),
    ("active", "failed", "node", "mark_failed"),
    ("active", "cancelled", "owner", "owner_cancel"),
    ("active", "expired", "node", "mark_expired"),
    ("awaiting_owner_approval", "active", "owner", ("owner_approval_decision", {"decision": "approve_once"})),
    ("awaiting_owner_approval", "paused", "owner", ("owner_approval_decision", {"decision": "deny"})),
    ("awaiting_owner_approval", "failed", "node", "mark_failed"),
    ("awaiting_owner_approval", "cancelled", "owner", "owner_cancel"),
    ("awaiting_owner_approval", "expired", "node", "mark_expired"),
    ("awaiting_peer", "active", "peer", MessageKind.PROPOSAL),
    ("awaiting_peer", "paused", "owner", "owner_pause"),
    ("awaiting_peer", "failed", "node", "mark_failed"),
    ("awaiting_peer", "cancelled", "owner", "owner_cancel"),
    ("awaiting_peer", "expired", "node", "mark_expired"),
    ("paused", "active", "owner", "owner_resume"),
    ("paused", "cancelled", "owner", "owner_cancel"),
    ("paused", "failed", "node", "mark_failed"),
    ("paused", "expired", "node", "mark_expired"),
]


@pytest.mark.parametrize("from_state,to_state,mechanism,detail", LEGAL_TRANSITIONS_DATA)
def test_all_legal_transitions_in_matrix(from_state: str, to_state: str, mechanism: str, detail: any, alice_keys):
    """(a) Assert every legal (from_state -> to_state) pair in VALID_TRANSITIONS succeeds."""
    participants = {
        "alice": ParticipantInfo(agent_id="scout", role="owner"),
    }
    state = SessionState(
        session_id="sess-matrix",
        initiator_username="alice",
        receiver_username="bob",
        status=from_state,
        participants=participants,
    )

    if mechanism == "peer":
        kind = detail
        v_env = build_verified_envelope("sess-matrix", 1, "alice", "scout", kind, alice_keys["private_key"])
        res = process_peer_envelope(state, v_env)
    elif mechanism == "node":
        cmd = detail
        res = process_node_command(state, cmd)
    elif mechanism == "owner":
        if isinstance(detail, tuple):
            action, payload = detail
            res = process_owner_command(state, "alice", action, payload)
        else:
            action = detail
            res = process_owner_command(state, "alice", action)
    else:
        pytest.fail(f"Unknown mechanism {mechanism}")

    assert res.success is True, f"Failed legal transition {from_state} -> {to_state} via {mechanism}: {res.error_message}"
    assert res.new_state.status == to_state


NON_TERMINAL_ILLEGAL_TRANSITIONS = [
    ("draft", "node", "mark_failed"),
    ("sent", "node", "mark_peer_review"),
    ("queued", "node", "mark_peer_review"),
    ("delivered", "node", "mark_queued"),
    ("peer_review", "node", "mark_queued"),
    ("needs_clarification", "node", "mark_queued"),
    ("accepted", "node", "mark_peer_review"),
    ("active", "node", "mark_queued"),
    ("awaiting_owner_approval", "node", "mark_queued"),
    ("awaiting_peer", "node", "mark_queued"),
    ("paused", "node", "mark_queued"),
]


@pytest.mark.parametrize("from_state,mechanism,command", NON_TERMINAL_ILLEGAL_TRANSITIONS)
def test_illegal_transitions_from_non_terminal_states(from_state: str, mechanism: str, command: str):
    """(b) Attempt illegal transitions from every non-terminal state, asserting INVALID_STATE_TRANSITION and unchanged state."""
    state = SessionState(
        session_id="sess-illegal",
        initiator_username="alice",
        receiver_username="bob",
        status=from_state,
    )

    res = process_node_command(state, command)
    assert res.success is False
    assert res.error_code == "INVALID_STATE_TRANSITION"
    assert res.new_state.status == from_state


def test_duplicate_sequence_number_rejection(alice_keys):
    """(c) Duplicate sequence number sent twice by same actor produces DUPLICATE_SEQUENCE and leaves state unchanged."""
    participants = {
        "alice": ParticipantInfo(agent_id="scout", role="owner"),
    }
    state = SessionState(
        session_id="sess-seq",
        initiator_username="alice",
        receiver_username="bob",
        status="active",
        actor_sequences={"alice": 1},
        participants=participants,
    )

    v_env = build_verified_envelope("sess-seq", 1, "alice", "scout", MessageKind.PROPOSAL, alice_keys["private_key"])
    res = process_peer_envelope(state, v_env)

    assert res.success is False
    assert res.error_code == "DUPLICATE_SEQUENCE"
    assert res.new_state.status == "active"
    assert res.new_state.actor_sequences["alice"] == 1


def test_out_of_order_sequence_number_rejection(alice_keys):
    """(d) Skipped / out-of-order sequence number produces OUT_OF_ORDER_SEQUENCE and leaves state unchanged."""
    participants = {
        "alice": ParticipantInfo(agent_id="scout", role="owner"),
    }
    state = SessionState(
        session_id="sess-seq",
        initiator_username="alice",
        receiver_username="bob",
        status="active",
        actor_sequences={"alice": 1},
        participants=participants,
    )

    # Sequence 3 skips sequence 2
    v_env = build_verified_envelope("sess-seq", 3, "alice", "scout", MessageKind.PROPOSAL, alice_keys["private_key"])
    res = process_peer_envelope(state, v_env)

    assert res.success is False
    assert res.error_code == "OUT_OF_ORDER_SEQUENCE"
    assert res.new_state.status == "active"
    assert res.new_state.actor_sequences["alice"] == 1


@pytest.mark.parametrize("terminal_state", list(TERMINAL_STATES))
def test_terminal_state_immutability_all_five_states(terminal_state: str, alice_keys):
    """(e) Envelope delivered to a session in EACH of the 5 terminal states returns TERMINAL_STATE_IMMUTABLE."""
    participants = {
        "alice": ParticipantInfo(agent_id="scout", role="owner"),
    }
    state = SessionState(
        session_id="sess-term",
        initiator_username="alice",
        receiver_username="bob",
        status=terminal_state,
        participants=participants,
    )

    # 1. Test peer envelope
    v_env = build_verified_envelope("sess-term", 1, "alice", "scout", MessageKind.PROPOSAL, alice_keys["private_key"])
    res_peer = process_peer_envelope(state, v_env)
    assert res_peer.success is False
    assert res_peer.error_code == "TERMINAL_STATE_IMMUTABLE"
    assert res_peer.new_state.status == terminal_state

    # 2. Test node command
    res_node = process_node_command(state, "mark_failed")
    assert res_node.success is False
    assert res_node.error_code == "TERMINAL_STATE_IMMUTABLE"
    assert res_node.new_state.status == terminal_state

    # 3. Test owner command
    res_owner = process_owner_command(state, "alice", "owner_pause")
    assert res_owner.success is False
    assert res_owner.error_code == "TERMINAL_STATE_IMMUTABLE"
    assert res_owner.new_state.status == terminal_state


def test_turn_limit_enforcement_and_non_turn_consuming_kinds(alice_keys):
    """(f) Driving current_turn to max_turns rejects turn-consuming kinds with TURN_LIMIT_EXCEEDED while status_event succeeds."""
    participants = {
        "alice": ParticipantInfo(agent_id="scout", role="owner"),
    }
    state = SessionState(
        session_id="sess-turn",
        initiator_username="alice",
        receiver_username="bob",
        status="active",
        current_turn=12,
        max_turns=12,
        participants=participants,
    )

    # Turn-consuming kind (PROPOSAL) -> Rejected
    v_env_prop = build_verified_envelope("sess-turn", 1, "alice", "scout", MessageKind.PROPOSAL, alice_keys["private_key"])
    res_prop = process_peer_envelope(state, v_env_prop)
    assert res_prop.success is False
    assert res_prop.error_code == "TURN_LIMIT_EXCEEDED"
    assert res_prop.new_state.current_turn == 12

    # Non-turn-consuming kind (STATUS_EVENT) -> Succeeds
    v_env_stat = build_verified_envelope("sess-turn", 1, "alice", "scout", MessageKind.STATUS_EVENT, alice_keys["private_key"])
    res_stat = process_peer_envelope(state, v_env_stat)
    assert res_stat.success is True
    assert res_stat.new_state.current_turn == 12


def test_max_turns_cannot_be_increased_by_events_or_commands(alice_keys, bob_keys):
    """(g) Prove max_turns is strictly pass-through across process_peer_envelope/node/owner and invariant to state value."""
    participants = {
        "alice": ParticipantInfo(agent_id="scout", role="owner"),
        "bob": ParticipantInfo(agent_id="cleaner", role="agent"),
    }
    state12 = SessionState(
        session_id="sess-max12",
        initiator_username="alice",
        receiver_username="bob",
        status="active",
        current_turn=2,
        max_turns=12,
        participants=participants,
    )
    state20 = SessionState(
        session_id="sess-max20",
        initiator_username="alice",
        receiver_username="bob",
        status="active",
        current_turn=2,
        max_turns=20,
        participants=participants,
    )

    alice_key = alice_keys["private_key"]
    payload_tampered = {"goal": "Sneaky goal", "max_turns": 9999, "turn_limit": 9999}

    # Sequence of operations to run on both states:
    # 1. Peer envelope (PROPOSAL)
    v_env12 = build_verified_envelope("sess-max12", 1, "alice", "scout", MessageKind.PROPOSAL, alice_key, payload=payload_tampered)
    v_env20 = build_verified_envelope("sess-max20", 1, "alice", "scout", MessageKind.PROPOSAL, alice_key, payload=payload_tampered)

    res12_1 = process_peer_envelope(state12, v_env12)
    res20_1 = process_peer_envelope(state20, v_env20)
    assert res12_1.success is True and res12_1.new_state.max_turns == 12
    assert res20_1.success is True and res20_1.new_state.max_turns == 20

    # 2. Node command (mark_awaiting_peer)
    res12_2 = process_node_command(res12_1.new_state, "mark_awaiting_peer", payload_tampered)
    res20_2 = process_node_command(res20_1.new_state, "mark_awaiting_peer", payload_tampered)
    assert res12_2.success is True and res12_2.new_state.max_turns == 12
    assert res20_2.success is True and res20_2.new_state.max_turns == 20

    # 3. Owner command (owner_pause)
    res12_3 = process_owner_command(res12_2.new_state, "alice", "owner_pause", payload_tampered)
    res20_3 = process_owner_command(res20_2.new_state, "alice", "owner_pause", payload_tampered)
    assert res12_3.success is True and res12_3.new_state.max_turns == 12
    assert res20_3.success is True and res20_3.new_state.max_turns == 20

    # 4. Owner command (owner_resume)
    res12_4 = process_owner_command(res12_3.new_state, "alice", "owner_resume", payload_tampered)
    res20_4 = process_owner_command(res20_3.new_state, "alice", "owner_resume", payload_tampered)
    assert res12_4.success is True and res12_4.new_state.max_turns == 12
    assert res20_4.success is True and res20_4.new_state.max_turns == 20
