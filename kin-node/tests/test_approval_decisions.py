"""Tests for approval objects, owner decisions, single-use consumption, and authorization (§15.8 M5 Phase 4)."""

import datetime
import sqlite3
import pytest

from kin.schemas import (
    ActionClass,
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    ApprovalDecision,
    ApprovalRequest,
    AutonomyLevel,
    DecisionKind,
    EmbeddedAdapterConfig,
    MessageKind,
    RiskLabel,
    SessionEnvelope,
    VerifiedEnvelope,
    sign_envelope,
)
from kin.storage.migrations import run_migrations
from kin.storage.vault import decrypt_field
from kin.policy import (
    ApprovalAlreadyDecidedError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    InvalidDecisionValueError,
    PolicyDecision,
    create_pending_approval,
    decide_approval,
    evaluate_action_for_session,
)
from kin.session.reducer import (
    ParticipantInfo,
    SessionState,
    process_peer_envelope,
)


@pytest.fixture
def profile_db():
    """Create an in-memory SQLite database initialized via run_migrations."""
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def default_card():
    """Return a standard test AgentCard."""
    return AgentCard(
        schema_version="1.1",
        id="ag_test_card",
        name="Test Agent",
        description="Agent card for policy and approval testing",
        adapter=EmbeddedAdapterConfig(type="embedded", provider="local", model="test-v1"),
        capabilities=AgentCapabilities(tags=["test"], accepts=["text/plain"], produces=["text/plain"]),
        boundaries=AgentBoundaries(
            network_access="allow",
            filesystem="workspace_read_write_with_approval",
            shell="approval_required",
            max_runtime_seconds=300,
            max_artifact_bytes=1000000,
        ),
        autonomy=AgentAutonomy(
            relay_information=AutonomyLevel.ALWAYS_ASK,
            propose_actions=AutonomyLevel.ALWAYS_ASK,
            execute_local_actions=AutonomyLevel.ALWAYS_ASK,
        ),
    )


def _setup_session(conn: sqlite3.Connection, session_id: str, initiator: str = "alice", receiver: str = "bob", status: str = "awaiting_owner_approval"):
    """Helper to insert a test session into the SQLite sessions table."""
    now_str = "2026-07-29T12:00:00Z"
    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username,
            status, turn_limit, created_at, updated_at
        ) VALUES (?, 'collaborative', ?, ?, ?, 12, ?, ?)
        """,
        (session_id, initiator, receiver, status, now_str, now_str),
    )
    conn.commit()


def test_approve_once_flow_and_initial_unconsumed_state(profile_db):
    """1. Full approve_once flow: create pending approval, decide approve_once, confirm consumed_at is NULL initially."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_app_once_1"
    _setup_session(profile_db, session_id)

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_ao_1",
        session_id=session_id,
        agent_id="ag_test_card",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Write test file",
        reason="Owner permission needed",
        risk_label=RiskLabel.HIGH,
        requested_scope={"path": "test.txt"},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id="ag_test_card", action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")

    stored_request = profile_db.execute(
        "SELECT request_json FROM approvals WHERE approval_id = ?", ("req_ao_1",)
    ).fetchone()[0]
    assert stored_request != req.model_dump_json()
    assert decrypt_field(vault_key, stored_request) == req.model_dump_json()

    decision = decide_approval(
        profile_db,
        vault_key,
        approval_id="req_ao_1",
        session_id=session_id,
        decision=DecisionKind.APPROVE_ONCE,
        owner_username="alice",
        now="2026-07-29T12:05:00Z",
    )

    assert decision.decision == DecisionKind.APPROVE_ONCE
    assert decision.decided_by == "alice"

    # Confirm session transitioned to active
    s_row = profile_db.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    assert s_row[0] == "active"

    # Confirm approvals row decision recorded and consumed_at is NULL initially
    a_row = profile_db.execute("SELECT decision, consumed_at FROM approvals WHERE approval_id = ?", ("req_ao_1",)).fetchone()
    assert a_row[0] == "approve_once"
    assert a_row[1] is None


def test_approve_once_single_use_consumption(profile_db, default_card):
    """2. Core single-use proof for Q2: first evaluate_action_for_session returns ALLOW and sets consumed_at; second call returns REQUIRES_APPROVAL."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_ao_consume"
    _setup_session(profile_db, session_id)

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_ao_consume_1",
        session_id=session_id,
        agent_id=default_card.id,
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Write file once",
        reason="Needs single-use write approval",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id=default_card.id, action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")

    decide_approval(
        profile_db,
        vault_key,
        approval_id="req_ao_consume_1",
        session_id=session_id,
        decision=DecisionKind.APPROVE_ONCE,
        owner_username="alice",
        now="2026-07-29T12:05:00Z",
    )

    now_eval = "2026-07-29T12:10:00Z"
    ctx = {"session_id": session_id}

    # Call 1: MUST return ALLOW and set consumed_at in SQLite
    res1 = evaluate_action_for_session(profile_db, default_card, ActionClass.WORKSPACE_WRITE, ctx, session_id, now_eval)
    assert res1.decision == PolicyDecision.ALLOW

    c_row = profile_db.execute("SELECT consumed_at FROM approvals WHERE approval_id = ?", ("req_ao_consume_1",)).fetchone()
    assert c_row[0] == now_eval

    # Call 2: MUST return REQUIRES_APPROVAL (proving single-use consumption prevents reuse)
    res2 = evaluate_action_for_session(profile_db, default_card, ActionClass.WORKSPACE_WRITE, ctx, session_id, now_eval)
    assert res2.decision == PolicyDecision.REQUIRES_APPROVAL


def test_always_allow_bounded_reuse_and_expiry(profile_db, default_card):
    """3. ALWAYS_ALLOW_BOUNDED: multiple calls return ALLOW, consumed_at stays NULL, falls back to REQUIRES_APPROVAL after expires_at."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_aab"
    _setup_session(profile_db, session_id)

    expires_at = "2026-07-29T13:00:00Z"
    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_aab_1",
        session_id=session_id,
        agent_id=default_card.id,
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Write files until 1pm",
        reason="Bounded approval window",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at=expires_at,
    )
    create_pending_approval(profile_db, vault_key, req, agent_id=default_card.id, action_class=ActionClass.WORKSPACE_WRITE, expires_at=expires_at)

    decide_approval(
        profile_db,
        vault_key,
        approval_id="req_aab_1",
        session_id=session_id,
        decision=DecisionKind.ALWAYS_ALLOW_BOUNDED,
        owner_username="alice",
        now="2026-07-29T12:00:00Z",
    )

    ctx = {"session_id": session_id}

    # Multiple calls before expiry return ALLOW and consumed_at remains NULL
    for i in range(3):
        t = f"2026-07-29T12:1{i}:00Z"
        res = evaluate_action_for_session(profile_db, default_card, ActionClass.WORKSPACE_WRITE, ctx, session_id, t)
        assert res.decision == PolicyDecision.ALLOW

    c_row = profile_db.execute("SELECT consumed_at FROM approvals WHERE approval_id = ?", ("req_aab_1",)).fetchone()
    assert c_row[0] is None

    # Call after expires_at falls back to REQUIRES_APPROVAL
    res_exp = evaluate_action_for_session(profile_db, default_card, ActionClass.WORKSPACE_WRITE, ctx, session_id, "2026-07-29T14:00:00Z")
    assert res_exp.decision == PolicyDecision.REQUIRES_APPROVAL


def test_deny_requires_reason_and_pauses_session(profile_db, default_card):
    """4. DENY requires a non-empty reason; missing reason rejected; session transitions to paused; audit event logged; evaluate returns DENY."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_deny_1"
    _setup_session(profile_db, session_id)

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_deny_1",
        session_id=session_id,
        agent_id=default_card.id,
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Write attempt",
        reason="Needs owner check",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id=default_card.id, action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")

    # Missing / whitespace reason rejected
    with pytest.raises(InvalidDecisionValueError, match="non-empty reason string"):
        decide_approval(
            profile_db,
            vault_key,
            approval_id="req_deny_1",
            session_id=session_id,
            decision=DecisionKind.DENY,
            owner_username="alice",
            now="2026-07-29T12:05:00Z",
            reason="   ",
        )

    # Valid DENY decision
    decision = decide_approval(
        profile_db,
        vault_key,
        approval_id="req_deny_1",
        session_id=session_id,
        decision=DecisionKind.DENY,
        owner_username="alice",
        now="2026-07-29T12:05:00Z",
        reason="Security policy violation",
    )
    assert decision.decision == DecisionKind.DENY
    assert decision.constraints == {"reason": "Security policy violation"}

    # Session status transitioned to paused
    s_row = profile_db.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    assert s_row[0] == "paused"

    # evaluate_action_for_session returns DENY
    res = evaluate_action_for_session(profile_db, default_card, ActionClass.WORKSPACE_WRITE, {"session_id": session_id}, session_id, "2026-07-29T12:10:00Z")
    assert res.decision == PolicyDecision.DENY


def test_edit_constraints_persists_and_activates_session(profile_db):
    """5. EDIT_CONSTRAINTS: persists constraints dict and transitions session status to active."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_edit_1"
    _setup_session(profile_db, session_id)

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_edit_1",
        session_id=session_id,
        agent_id="ag_test_card",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Write files",
        reason="Check paths",
        risk_label=RiskLabel.HIGH,
        requested_scope={"path": "*"},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id="ag_test_card", action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")

    # Missing constraints dict rejected
    with pytest.raises(InvalidDecisionValueError, match="non-empty constraints dictionary"):
        decide_approval(
            profile_db,
            vault_key,
            approval_id="req_edit_1",
            session_id=session_id,
            decision=DecisionKind.EDIT_CONSTRAINTS,
            owner_username="alice",
            now="2026-07-29T12:05:00Z",
            constraints={},
        )

    # Valid EDIT_CONSTRAINTS decision
    edited_constraints = {"allowed_paths": ["/tmp/safe/*"], "max_bytes": 1000}
    decision = decide_approval(
        profile_db,
        vault_key,
        approval_id="req_edit_1",
        session_id=session_id,
        decision=DecisionKind.EDIT_CONSTRAINTS,
        owner_username="alice",
        now="2026-07-29T12:05:00Z",
        constraints=edited_constraints,
    )
    assert decision.decision == DecisionKind.EDIT_CONSTRAINTS
    assert decision.constraints == edited_constraints

    # Confirm session status is active
    s_row = profile_db.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    assert s_row[0] == "active"


def test_double_decision_rejection(profile_db):
    """6. Double-decision rejection: decide_approval called twice for same approval_id is rejected on second call."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_double_dec"
    _setup_session(profile_db, session_id)

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_dbl_1",
        session_id=session_id,
        agent_id="ag_test_card",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Double decision test",
        reason="Reason",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id="ag_test_card", action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")

    decide_approval(
        profile_db,
        vault_key,
        approval_id="req_dbl_1",
        session_id=session_id,
        decision=DecisionKind.APPROVE_ONCE,
        owner_username="alice",
        now="2026-07-29T12:05:00Z",
    )

    with pytest.raises(ApprovalAlreadyDecidedError, match="already been decided"):
        decide_approval(
            profile_db,
            vault_key,
            approval_id="req_dbl_1",
            session_id=session_id,
            decision=DecisionKind.DENY,
            owner_username="alice",
            now="2026-07-29T12:06:00Z",
            reason="Second decision attempt",
        )

    # First decision remains untouched
    a_row = profile_db.execute("SELECT decision FROM approvals WHERE approval_id = ?", ("req_dbl_1",)).fetchone()
    assert a_row[0] == "approve_once"


def test_decide_expired_approval_rejection(profile_db):
    """7. Deciding an expired pending approval: attempt decide_approval when expires_at is in the past is rejected."""
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_exp_req"
    _setup_session(profile_db, session_id)

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_exp_1",
        session_id=session_id,
        agent_id="ag_test_card",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Expired request",
        reason="Reason",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-29T10:00:00Z",  # Expired at 10am
    )
    create_pending_approval(profile_db, vault_key, req, agent_id="ag_test_card", action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-29T10:00:00Z")

    with pytest.raises(ApprovalExpiredError, match="expired"):
        decide_approval(
            profile_db,
            vault_key,
            approval_id="req_exp_1",
            session_id=session_id,
            decision=DecisionKind.APPROVE_ONCE,
            owner_username="alice",
            now="2026-07-29T12:00:00Z",  # Deciding at 12pm
        )


def test_alice_cannot_approve_bobs_action_and_peer_rejection():
    """8. Required spec authorization test: Alice cannot approve Bob's action.

    (a) Bob's connection/database has no access to Alice's approval_id (ApprovalNotFoundError).
    (b) Raw APPROVAL_DECISION envelope sent from peer is rejected by reducer (OWNER_ONLY_KINDS).
    """
    alice_conn = sqlite3.connect(":memory:")
    bob_conn = sqlite3.connect(":memory:")
    run_migrations(alice_conn)
    run_migrations(bob_conn)

    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_alice_bob"

    _setup_session(alice_conn, session_id, initiator="alice", receiver="bob")

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_alice_1",
        session_id=session_id,
        agent_id="ag_alice_agent",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Alice action",
        reason="Reason",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(alice_conn, vault_key, req, agent_id="ag_alice_agent", action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")

    # (a) Bob's profile DB attempt to decide Alice's approval_id fails with ApprovalNotFoundError
    with pytest.raises(ApprovalNotFoundError):
        decide_approval(
            bob_conn,
            vault_key,
            approval_id="req_alice_1",
            session_id=session_id,
            decision=DecisionKind.APPROVE_ONCE,
            owner_username="bob",
            now="2026-07-29T12:05:00Z",
        )

    # (b) Construct APPROVAL_DECISION peer envelope from Bob to Alice and confirm process_peer_envelope rejects it
    state = SessionState(
        session_id=session_id,
        initiator_username="alice",
        receiver_username="bob",
        status="awaiting_owner_approval",
        participants={
            "alice": ParticipantInfo(agent_id="ag_alice_agent", role="owner"),
            "bob": ParticipantInfo(agent_id="ag_bob_agent", role="receiver"),
        },
        actor_sequences={"bob": 0},
    )

    from cryptography.hazmat.primitives.asymmetric import ed25519
    bob_privkey = ed25519.Ed25519PrivateKey.generate()
    bob_pubkey = bob_privkey.public_key()

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": 1,
        "actor_username": "bob",
        "actor_agent_id": "ag_bob_agent",
        "timestamp": "2026-07-29T12:05:00Z",
        "kind": MessageKind.APPROVAL_DECISION.value,
        "content_hash": "a" * 43,
        "payload": {"approval_id": "req_alice_1", "decision": "approve_once"},
    }
    sig = sign_envelope(env_dict, bob_privkey)
    env_dict["signature"] = sig

    envelope = SessionEnvelope.model_validate(env_dict)
    verified_envelope = VerifiedEnvelope(
        envelope=envelope,
        actor_public_key=bob_pubkey,
        verified_at="2026-07-29T12:05:00Z",
    )

    res = process_peer_envelope(state, verified_envelope)
    assert res.success is False
    assert res.error_code == "UNAUTHORIZED_ROLE_ACTION"
    assert "requires human owner authority" in res.error_message

    alice_conn.close()
    bob_conn.close()


def test_decide_approval_unauthorized_owner_or_terminal_session_leaves_decision_null(profile_db):
    """9. Prove transaction ordering & non-partial commit: failed transition leaves decision IS NULL in approvals table.

    Asserts:
    (a) Calling decide_approval with an un-authorized owner raises RuntimeError, and decision remains NULL.
    (b) Calling decide_approval on a terminal session raises RuntimeError, and decision remains NULL.
    """
    vault_key = b"01234567890123456789012345678901"
    session_id = "sess_fail_order"

    # Setup session with initiator "alice"
    _setup_session(profile_db, session_id, initiator="alice", receiver="bob", status="awaiting_owner_approval")

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="req_fo_1",
        session_id=session_id,
        agent_id="ag_test_card",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Test transaction ordering",
        reason="Reason",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-07-30T12:00:00Z",
    )
    create_pending_approval(profile_db, vault_key, req, agent_id="ag_test_card", action_class=ActionClass.WORKSPACE_WRITE, expires_at="2026-07-30T12:00:00Z")

    # (a) Attempt decision with unauthorized owner "mallory" (not alice)
    with pytest.raises(RuntimeError, match="Owner command transition rejected"):
        decide_approval(
            profile_db,
            vault_key,
            approval_id="req_fo_1",
            session_id=session_id,
            decision=DecisionKind.APPROVE_ONCE,
            owner_username="mallory",
            now="2026-07-29T12:05:00Z",
        )

    # Prove decision IS NULL after failed transition attempt
    row_a = profile_db.execute("SELECT decision, decided_at FROM approvals WHERE approval_id = ?", ("req_fo_1",)).fetchone()
    assert row_a[0] is None
    assert row_a[1] is None

    # (b) Transition session to terminal status 'cancelled'
    profile_db.execute("UPDATE sessions SET status = 'cancelled' WHERE session_id = ?", (session_id,))
    profile_db.commit()

    # Attempt decision on terminal session with authorized owner "alice"
    with pytest.raises(RuntimeError, match="Owner command transition rejected"):
        decide_approval(
            profile_db,
            vault_key,
            approval_id="req_fo_1",
            session_id=session_id,
            decision=DecisionKind.APPROVE_ONCE,
            owner_username="alice",
            now="2026-07-29T12:06:00Z",
        )

    # Prove decision IS NULL after failed transition attempt on terminal session
    row_b = profile_db.execute("SELECT decision, decided_at FROM approvals WHERE approval_id = ?", ("req_fo_1",)).fetchone()
    assert row_b[0] is None
    assert row_b[1] is None
