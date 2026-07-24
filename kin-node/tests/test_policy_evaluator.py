"""Unit and contract tests for kin.policy evaluator, boundaries, autonomy, and persistence."""

from __future__ import annotations

from pathlib import Path
import pytest

from kin.schemas import (
    ActionClass,
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    ApprovalDecision,
    AutonomyLevel,
    DecisionKind,
    LocalCommandAdapterConfig,
    RiskLabel,
)
from kin.storage.db import get_connection, create_schema
from kin.policy.evaluator import (
    PolicyDecision,
    PolicyResult,
    evaluate_action,
)
from kin.policy.persistence import evaluate_action_for_session


@pytest.fixture
def test_db(tmp_path: Path):
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def default_card():
    return AgentCard(
        schema_version="1.1",
        id="policy-agent",
        name="Policy Test Agent",
        description="Agent for testing policy rules",
        adapter=LocalCommandAdapterConfig(type="local_command", command="python script.py", working_directory="/tmp"),
        capabilities=AgentCapabilities(tags=["policy"], accepts=["text/plain"]),
        boundaries=AgentBoundaries(
            network_access="allow",
            filesystem="workspace_read_write_with_approval",
            shell="approval_required",
            max_runtime_seconds=600,
            max_artifact_bytes=1000000,
        ),
        autonomy=AgentAutonomy(
            relay_information=AutonomyLevel.ALWAYS_ASK,
            propose_actions=AutonomyLevel.ALWAYS_ASK,
            execute_local_actions=AutonomyLevel.ALWAYS_ASK,
        ),
    )


def test_hard_boundary_override_short_circuits_before_prior_approval(default_card):
    """CRITICAL SECURITY INVARIANT TEST: Hard boundary denial MUST execute and short-circuit BEFORE prior approval check.

    A card with shell=deny and network_access=deny must return DENY for SHELL_NETWORK_EXTERNAL
    even if a valid non-expired always_allow_bounded prior_approval is passed in.
    """
    card_denied = default_card.model_copy(deep=True)
    card_denied.boundaries.shell = "deny"
    card_denied.boundaries.network_access = "deny"

    valid_prior_approval = ApprovalDecision(
        schema_version="1.1",
        approval_id="app-123",
        session_id="sess-123",
        decision=DecisionKind.ALWAYS_ALLOW_BOUNDED,
        decided_by="owner",
        decided_at="2026-07-22T10:00:00.000Z",
    )

    now = "2026-07-23T12:00:00.000Z"
    context = {"session_id": "sess-123"}

    res = evaluate_action(
        card=card_denied,
        action_class=ActionClass.SHELL_NETWORK_EXTERNAL,
        session_context=context,
        now=now,
        prior_approval=valid_prior_approval,
        prior_approval_expires_at="2026-07-25T10:00:00.000Z",
    )

    # MUST be DENY, not ALLOW!
    assert res.decision == PolicyDecision.DENY
    assert "Hard boundary denial" in res.reason


def test_approval_class_table_default_always_ask_outcomes(default_card):
    """Verify each ActionClass row against default always_ask card autonomy."""
    now = "2026-07-23T12:00:00.000Z"
    ctx = {"session_id": "sess-table-test"}

    # 1. INFORMATIONAL_RELAY -> REQUIRES_APPROVAL (LOW risk)
    r_relay = evaluate_action(default_card, ActionClass.INFORMATIONAL_RELAY, ctx, now)
    assert r_relay.decision == PolicyDecision.REQUIRES_APPROVAL
    assert r_relay.approval_request.risk_label == RiskLabel.LOW

    # 2. SESSION_PARTICIPATION -> REQUIRES_APPROVAL (MEDIUM risk)
    r_part = evaluate_action(default_card, ActionClass.SESSION_PARTICIPATION, ctx, now)
    assert r_part.decision == PolicyDecision.REQUIRES_APPROVAL
    assert r_part.approval_request.risk_label == RiskLabel.MEDIUM

    # 3. ARTIFACT_RECEIPT -> REQUIRES_APPROVAL (LOW risk)
    r_art = evaluate_action(default_card, ActionClass.ARTIFACT_RECEIPT, ctx, now)
    assert r_art.decision == PolicyDecision.REQUIRES_APPROVAL
    assert r_art.approval_request.risk_label == RiskLabel.LOW

    # 4. WORKSPACE_READ -> REQUIRES_APPROVAL (MEDIUM risk)
    r_read = evaluate_action(default_card, ActionClass.WORKSPACE_READ, ctx, now)
    assert r_read.decision == PolicyDecision.REQUIRES_APPROVAL
    assert r_read.approval_request.risk_label == RiskLabel.MEDIUM

    # 5. WORKSPACE_WRITE -> REQUIRES_APPROVAL (HIGH risk)
    r_write = evaluate_action(default_card, ActionClass.WORKSPACE_WRITE, ctx, now)
    assert r_write.decision == PolicyDecision.REQUIRES_APPROVAL
    assert r_write.approval_request.risk_label == RiskLabel.HIGH

    # 6. SHELL_NETWORK_EXTERNAL -> REQUIRES_APPROVAL (CRITICAL risk)
    r_shell = evaluate_action(default_card, ActionClass.SHELL_NETWORK_EXTERNAL, ctx, now)
    assert r_shell.decision == PolicyDecision.REQUIRES_APPROVAL
    assert r_shell.approval_request.risk_label == RiskLabel.CRITICAL


def test_autonomy_overrides(default_card):
    """Verify relay_information autonomy level overrides (ALWAYS_ALLOW -> ALLOW, NEVER -> DENY)."""
    now = "2026-07-23T12:00:00.000Z"
    ctx = {"session_id": "sess-autonomy"}

    # ALWAYS_ALLOW
    c_allow = default_card.model_copy(deep=True)
    c_allow.autonomy.relay_information = AutonomyLevel.ALWAYS_ALLOW
    r_allow = evaluate_action(c_allow, ActionClass.INFORMATIONAL_RELAY, ctx, now)
    assert r_allow.decision == PolicyDecision.ALLOW

    # NEVER
    c_never = default_card.model_copy(deep=True)
    c_never.autonomy.relay_information = AutonomyLevel.NEVER
    r_never = evaluate_action(c_never, ActionClass.INFORMATIONAL_RELAY, ctx, now)
    assert r_never.decision == PolicyDecision.DENY


def test_expired_prior_approval_falls_through(default_card):
    """Verify an expired prior approval falls through to REQUIRES_APPROVAL instead of granting ALLOW."""
    now = "2026-07-23T12:00:00.000Z"
    expired_prior_approval = ApprovalDecision(
        schema_version="1.1",
        approval_id="app-old",
        session_id="sess-exp",
        decision=DecisionKind.ALWAYS_ALLOW_BOUNDED,
        decided_by="owner",
        decided_at="2026-07-20T10:00:00.000Z",
    )

    r = evaluate_action(
        card=default_card,
        action_class=ActionClass.WORKSPACE_READ,
        session_context={"session_id": "sess-exp"},
        now=now,
        prior_approval=expired_prior_approval,
        prior_approval_expires_at="2026-07-22T10:00:00.000Z",  # Expired relative to now
    )

    assert r.decision == PolicyDecision.REQUIRES_APPROVAL


def test_edit_constraints_prior_approval_does_not_grant_allow(default_card):
    """Verify decision=edit_constraints does NOT grant ALLOW."""
    now = "2026-07-23T12:00:00.000Z"
    edit_approval = ApprovalDecision(
        schema_version="1.1",
        approval_id="app-edit",
        session_id="sess-edit",
        decision=DecisionKind.EDIT_CONSTRAINTS,
        decided_by="owner",
        decided_at="2026-07-23T10:00:00.000Z",
    )

    r = evaluate_action(
        card=default_card,
        action_class=ActionClass.WORKSPACE_WRITE,
        session_context={"session_id": "sess-edit"},
        now=now,
        prior_approval=edit_approval,
        prior_approval_expires_at="2026-07-25T10:00:00.000Z",
    )

    assert r.decision == PolicyDecision.REQUIRES_APPROVAL


def test_prior_approval_deny(default_card):
    """Verify decision=deny prior approval returns DENY."""
    now = "2026-07-23T12:00:00.000Z"
    deny_approval = ApprovalDecision(
        schema_version="1.1",
        approval_id="app-deny",
        session_id="sess-deny",
        decision=DecisionKind.DENY,
        decided_by="owner",
        decided_at="2026-07-23T10:00:00.000Z",
    )

    r = evaluate_action(
        card=default_card,
        action_class=ActionClass.WORKSPACE_WRITE,
        session_context={"session_id": "sess-deny"},
        now=now,
        prior_approval=deny_approval,
        prior_approval_expires_at="2026-07-25T10:00:00.000Z",
    )

    assert r.decision == PolicyDecision.DENY


def test_peer_attempts_to_name_a_local_tool_isolation(default_card):
    """Prove structurally that peer-supplied tool_name in session_context has NO effect on policy decision or local command."""
    now = "2026-07-23T12:00:00.000Z"

    # Context 1: Normal context
    ctx1 = {"session_id": "sess-1"}

    # Context 2: Peer attempting malicious tool insertion
    ctx2 = {
        "session_id": "sess-1",
        "tool_name": "rm -rf /",
        "command": "malicious_shell_override",
    }

    r1 = evaluate_action(default_card, ActionClass.WORKSPACE_READ, ctx1, now)
    r2 = evaluate_action(default_card, ActionClass.WORKSPACE_READ, ctx2, now)

    # 1. Decisions are identical
    assert r1.decision == r2.decision

    # 2. Local card adapter command remains untouched
    assert default_card.adapter.command == "python script.py"


def test_persistence_evaluate_action_for_session(test_db, default_card):
    """Assert evaluate_action_for_session queries SQLite approvals table and evaluates bounded grants."""
    now = "2026-07-23T12:00:00.000Z"
    sess_id = "sess-db-1"

    # 1. Create sessions parent row
    test_db.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status, turn_limit, created_at, updated_at
        ) VALUES (?, 'collaborative', 'alice', 'bob', 'active', 12, ?, ?)
        """,
        (sess_id, now, now),
    )

    # 2. Insert approvals row with always_allow_bounded
    test_db.execute(
        """\
        INSERT INTO approvals (
            approval_id, session_id, agent_id, action_class, decision, decided_at, expires_at
        ) VALUES ('app-db-1', ?, ?, 'workspace_read', 'always_allow_bounded', ?, '2026-07-25T00:00:00Z')
        """,
        (sess_id, default_card.id, now),
    )
    test_db.commit()

    res = evaluate_action_for_session(
        conn=test_db,
        card=default_card,
        action_class=ActionClass.WORKSPACE_READ,
        session_context={"session_id": sess_id},
        session_id=sess_id,
        now=now,
    )

    assert res.decision == PolicyDecision.ALLOW
    assert "bounded prior approval" in res.reason


def test_record_approval_decision_write_path(test_db, default_card):
    """Assert record_approval_decision writes validated ApprovalDecision to approvals table and logs audit event."""
    from kin.policy.persistence import record_approval_decision
    now = "2026-07-23T12:00:00.000Z"
    sess_id = "sess-rec-1"
    vault_key = b"01234567890123456789012345678901"

    # Create sessions row for foreign key
    test_db.execute(
        "INSERT INTO sessions (session_id, type, initiator_username, receiver_username, status, turn_limit, created_at, updated_at) "
        "VALUES (?, 'collaborative', 'alice', 'bob', 'active', 12, ?, ?)",
        (sess_id, now, now),
    )
    test_db.commit()

    decision = ApprovalDecision(
        schema_version="1.1",
        approval_id="app-rec-123",
        session_id=sess_id,
        decision=DecisionKind.ALWAYS_ALLOW_BOUNDED,
        decided_by="owner_alice",
        decided_at=now,
    )

    # Call write path
    record_approval_decision(
        conn=test_db,
        vault_key=vault_key,
        approval_decision=decision,
        agent_id=default_card.id,
        action_class=ActionClass.WORKSPACE_READ,
        expires_at="2026-07-25T12:00:00.000Z",
    )

    # Assert row written to approvals table
    row = test_db.execute(
        "SELECT approval_id, session_id, agent_id, action_class, decision, expires_at FROM approvals WHERE approval_id = ?",
        ("app-rec-123",),
    ).fetchone()
    assert row is not None
    assert row[0] == "app-rec-123"
    assert row[2] == default_card.id
    assert row[3] == "workspace_read"
    assert row[4] == "always_allow_bounded"

    # Assert audit log entry written to audit_events table
    audit_row = test_db.execute("SELECT category, summary FROM audit_events WHERE session_id = ?", (sess_id,)).fetchone()
    assert audit_row is not None
    assert audit_row[0] == "approval_decision"
    assert "always_allow_bounded" in audit_row[1]

    # Assert evaluate_action_for_session evaluates this newly recorded decision correctly
    res = evaluate_action_for_session(
        conn=test_db,
        card=default_card,
        action_class=ActionClass.WORKSPACE_READ,
        session_context={"session_id": sess_id},
        session_id=sess_id,
        now=now,
    )
    assert res.decision == PolicyDecision.ALLOW
