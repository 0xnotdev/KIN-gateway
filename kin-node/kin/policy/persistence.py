"""Persistence integration for Policy Evaluator against active SQLite session approvals."""

from __future__ import annotations

import sqlite3
from typing import Any

from kin.schemas import ActionClass, AgentCard, ApprovalDecision, ApprovalRequest, DecisionKind
from kin.policy.evaluator import PolicyResult, evaluate_action


def evaluate_action_for_session(
    conn: sqlite3.Connection,
    card: AgentCard,
    action_class: ActionClass,
    session_context: dict[str, Any],
    session_id: str,
    now: str,
) -> PolicyResult:
    """Evaluate an action request using active approvals stored in SQLite for the session.

    Looks up the most recent non-expired approval row for (session_id, card.id, action_class)
    with decision == 'always_allow_bounded' or 'deny', deserializes into ApprovalDecision,
    and delegates to evaluate_action().
    """
    cur = conn.cursor()
    cur.execute(
        """\
        SELECT approval_id, session_id, agent_id, action_class, request_json, decision, decided_at, expires_at
        FROM approvals
        WHERE session_id = ? AND agent_id = ? AND action_class = ? AND expires_at > ?
        ORDER BY decided_at DESC LIMIT 1
        """,
        (session_id, card.id, action_class.value, now),
    )
    row = cur.fetchone()

    prior_approval: ApprovalDecision | None = None
    prior_approval_expires_at: str | None = None

    if row is not None:
        approval_id, sess_id, agent_id, act_class_str, req_json, decision_str, decided_at, expires_at = row
        try:
            decision_kind = DecisionKind(decision_str)
        except ValueError:
            decision_kind = decision_str

        prior_approval = ApprovalDecision(
            schema_version="1.1",
            approval_id=approval_id,
            session_id=sess_id,
            decision=decision_kind,
            decided_by="owner",
            decided_at=decided_at or now,
        )
        prior_approval_expires_at = expires_at

    return evaluate_action(
        card=card,
        action_class=action_class,
        session_context=session_context,
        now=now,
        prior_approval=prior_approval,
        prior_approval_expires_at=prior_approval_expires_at,
    )


def record_approval_decision(
    conn: sqlite3.Connection,
    vault_key: bytes,
    approval_decision: ApprovalDecision,
    *,
    agent_id: str,
    action_class: ActionClass,
    expires_at: str,
    request_json: str | None = None,
) -> None:
    """Record a validated owner ApprovalDecision in the local SQLite approvals table and log an audit event.

    Args:
        conn: SQLite connection to profile database.
        vault_key: 32-byte vault key for encrypted audit log writing.
        approval_decision: Validated ApprovalDecision model instance.
        agent_id: Target agent ID governed by this decision.
        action_class: Target ActionClass governed by this decision.
        expires_at: ISO 8601 UTC timestamp when this decision expires.
        request_json: Optional raw request JSON string or payload dict.
    """
    from kin.audit.writer import write_audit_event

    conn.execute(
        """\
        INSERT INTO approvals (
            approval_id, session_id, agent_id, action_class,
            request_json, decision, decided_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            approval_decision.approval_id,
            approval_decision.session_id,
            agent_id,
            action_class.value,
            request_json,
            approval_decision.decision.value if isinstance(approval_decision.decision, DecisionKind) else str(approval_decision.decision),
            approval_decision.decided_at,
            expires_at,
        ),
    )

    write_audit_event(
        conn,
        vault_key,
        category="approval_decision",
        session_id=approval_decision.session_id,
        actor_username=approval_decision.decided_by,
        summary=f"Approval decision '{approval_decision.decision.value if isinstance(approval_decision.decision, DecisionKind) else approval_decision.decision}' recorded for agent '{agent_id}' action '{action_class.value}'",
        payload={
            "approval_id": approval_decision.approval_id,
            "agent_id": agent_id,
            "action_class": action_class.value,
            "decision": approval_decision.decision.value if isinstance(approval_decision.decision, DecisionKind) else str(approval_decision.decision),
            "expires_at": expires_at,
        },
        correlation_id=approval_decision.session_id,
    )
    conn.commit()


def create_pending_approval(
    conn: sqlite3.Connection,
    vault_key: bytes,
    approval_request: ApprovalRequest,
    *,
    agent_id: str,
    action_class: ActionClass,
    expires_at: str,
) -> str:
    """Insert a pending approval row (decision = NULL) into approvals table and write audit event."""
    from kin.audit.writer import write_audit_event

    req_json = approval_request.model_dump_json()

    conn.execute(
        """\
        INSERT INTO approvals (
            approval_id, session_id, agent_id, action_class,
            request_json, decision, decided_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)
        """,
        (
            approval_request.approval_id,
            approval_request.session_id,
            agent_id,
            action_class.value,
            req_json,
            expires_at,
        ),
    )

    write_audit_event(
        conn,
        vault_key,
        category="approval_request",
        session_id=approval_request.session_id,
        actor_username=agent_id,
        summary=f"Pending approval request created for agent '{agent_id}' action '{action_class.value}'",
        payload={
            "approval_id": approval_request.approval_id,
            "agent_id": agent_id,
            "action_class": action_class.value,
            "expires_at": expires_at,
        },
        correlation_id=approval_request.session_id,
    )
    conn.commit()
    return approval_request.approval_id
