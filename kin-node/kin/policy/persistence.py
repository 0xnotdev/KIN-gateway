"""Persistence integration for Policy Evaluator against active SQLite session approvals."""

from __future__ import annotations

import sqlite3
from typing import Any

from kin.schemas import ActionClass, AgentCard, ApprovalDecision, ApprovalRequest, DecisionKind
from kin.policy.evaluator import PolicyResult, evaluate_action


class ApprovalNotFoundError(Exception):
    """Raised when an approval request is not found for a session."""
    pass


class ApprovalAlreadyDecidedError(Exception):
    """Raised when attempting to decide an approval request that was already decided."""
    pass


class ApprovalExpiredError(Exception):
    """Raised when attempting to decide an expired approval request."""
    pass


class InvalidDecisionValueError(Exception):
    """Raised when decision-specific validations fail (e.g. missing DENY reason)."""
    pass


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
    excluding consumed approve_once rows, deserializes into ApprovalDecision, and delegates to evaluate_action().
    If evaluate_action returns ALLOW because of an approve_once decision, marks consumed_at in SQLite.
    """
    cur = conn.cursor()
    cur.execute(
        """\
        SELECT approval_id, session_id, agent_id, action_class, request_json, decision, decided_at, expires_at
        FROM approvals
        WHERE session_id = ? AND agent_id = ? AND action_class = ? AND expires_at > ?
          AND (decision != 'approve_once' OR consumed_at IS NULL)
        ORDER BY decided_at DESC LIMIT 1
        """,
        (session_id, card.id, action_class.value, now),
    )
    row = cur.fetchone()

    prior_approval: ApprovalDecision | None = None
    prior_approval_expires_at: str | None = None
    matching_approval_id: str | None = None
    matching_decision_kind: DecisionKind | str | None = None

    if row is not None:
        approval_id, sess_id, agent_id, act_class_str, req_json, decision_str, decided_at, expires_at = row
        matching_approval_id = approval_id
        try:
            decision_kind = DecisionKind(decision_str)
        except ValueError:
            decision_kind = decision_str
        matching_decision_kind = decision_kind

        prior_approval = ApprovalDecision(
            schema_version="1.1",
            approval_id=approval_id,
            session_id=sess_id,
            decision=decision_kind,
            decided_by="owner",
            decided_at=decided_at or now,
        )
        prior_approval_expires_at = expires_at

    res = evaluate_action(
        card=card,
        action_class=action_class,
        session_context=session_context,
        now=now,
        prior_approval=prior_approval,
        prior_approval_expires_at=prior_approval_expires_at,
    )

    # If ALLOW was granted due to an approve_once decision, consume it now
    if (
        res.decision.value == "allow"
        and matching_approval_id is not None
        and matching_decision_kind in (DecisionKind.APPROVE_ONCE, "approve_once")
    ):
        conn.execute(
            "UPDATE approvals SET consumed_at = ? WHERE approval_id = ?",
            (now, matching_approval_id),
        )
        conn.commit()

    return res


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
    """Record a validated owner ApprovalDecision in the local SQLite approvals table (UPSERT) and log an audit event.

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

    decision_str = (
        approval_decision.decision.value
        if isinstance(approval_decision.decision, DecisionKind)
        else str(approval_decision.decision)
    )

    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM approvals WHERE approval_id = ?",
        (approval_decision.approval_id,),
    )
    exists = cur.fetchone() is not None

    if exists:
        conn.execute(
            """\
            UPDATE approvals
            SET decision = ?, decided_at = ?, request_json = COALESCE(?, request_json)
            WHERE approval_id = ?
            """,
            (
                decision_str,
                approval_decision.decided_at,
                request_json,
                approval_decision.approval_id,
            ),
        )
    else:
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
                decision_str,
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
        summary=f"Approval decision '{decision_str}' recorded for agent '{agent_id}' action '{action_class.value}'",
        payload={
            "approval_id": approval_decision.approval_id,
            "agent_id": agent_id,
            "action_class": action_class.value,
            "decision": decision_str,
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


def decide_approval(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    approval_id: str,
    session_id: str,
    decision: DecisionKind | str,
    owner_username: str,
    now: str,
    reason: str | None = None,
    constraints: dict[str, Any] | None = None,
) -> ApprovalDecision:
    """Record an owner decision for a pending approval, update persistence, and apply state machine transition.

    Args:
        conn: Profile database SQLite connection.
        vault_key: 32-byte vault key for encrypted audit writing.
        approval_id: Target pending approval ID.
        session_id: Target session ID.
        decision: DecisionKind or string decision value.
        owner_username: Human owner username submitting the decision.
        now: ISO 8601 UTC timestamp string.
        reason: Mandatory non-empty reason string if decision is DENY.
        constraints: Mandatory non-empty dict if decision is EDIT_CONSTRAINTS, optional otherwise.

    Returns:
        Validated ApprovalDecision instance.
    """
    from kin.transport.v11 import _apply_owner_command_transition

    d_kind = DecisionKind(decision) if isinstance(decision, str) else decision

    cur = conn.cursor()
    cur.execute(
        "SELECT session_id, agent_id, action_class, decision, expires_at FROM approvals WHERE approval_id = ?",
        (approval_id,),
    )
    row = cur.fetchone()

    if not row or row[0] != session_id:
        raise ApprovalNotFoundError(f"Approval request '{approval_id}' not found for session '{session_id}'.")

    _, agent_id, act_class_str, existing_decision, expires_at = row

    if existing_decision is not None:
        raise ApprovalAlreadyDecidedError(f"Approval request '{approval_id}' has already been decided ('{existing_decision}').")

    if expires_at <= now:
        raise ApprovalExpiredError(f"Approval request '{approval_id}' expired at '{expires_at}' (current time: '{now}').")

    # Decision-specific validations
    final_constraints: dict[str, Any] | None = None
    if d_kind == DecisionKind.DENY:
        if not reason or not reason.strip():
            raise InvalidDecisionValueError("DENY decision requires a non-empty reason string.")
        final_constraints = {"reason": reason.strip()}
    elif d_kind == DecisionKind.EDIT_CONSTRAINTS:
        if not constraints:
            raise InvalidDecisionValueError("EDIT_CONSTRAINTS decision requires a non-empty constraints dictionary.")
        final_constraints = constraints
    else:
        final_constraints = constraints

    # Validate owner authorization and state machine transition feasibility BEFORE writing decision
    from kin.session.reducer import process_owner_command, reconstruct_session_state
    from kin.transport.v11 import _apply_owner_command_transition

    state = reconstruct_session_state(conn, vault_key, session_id)
    if not state:
        raise ApprovalNotFoundError(f"Session '{session_id}' state could not be reconstructed.")

    trial_res = process_owner_command(state, owner_username, "owner_approval_decision", {"decision": d_kind.value})
    if not trial_res.success:
        raise RuntimeError(f"Owner command transition rejected on state '{state.status}': {trial_res.error_message}")

    approval_decision = ApprovalDecision(
        schema_version="1.1",
        approval_id=approval_id,
        session_id=session_id,
        decision=d_kind,
        decided_by=owner_username,
        decided_at=now,
        constraints=final_constraints,
    )

    trans_res = _apply_owner_command_transition(
        conn,
        vault_key,
        session_id,
        owner_username,
        "owner_approval_decision",
        payload={"decision": d_kind.value},
    )
    if trans_res is None:
        raise RuntimeError(f"Session state transition for owner action 'owner_approval_decision' failed.")

    record_approval_decision(
        conn,
        vault_key,
        approval_decision,
        agent_id=agent_id,
        action_class=ActionClass(act_class_str),
        expires_at=expires_at,
    )

    return approval_decision
