"""Pure, deterministic policy evaluator for KIN V1.1 agent action requests.

Implements §8.3 approval class matrix and §8.2 security invariants.
Pure logic: no database access, no internal system clock reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from kin.schemas import (
    TIMESTAMP_REGEX,
    ActionClass,
    AgentCard,
    ApprovalDecision,
    ApprovalRequest,
    AutonomyLevel,
    DecisionKind,
    RiskLabel,
)


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRES_APPROVAL = "requires_approval"


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    approval_request: ApprovalRequest | None = None
    reason: str = ""


# Default action-class -> autonomy-field mapping per §8.3.
# NOTE: Per §8.3's table, autonomy settings in V1.1 only ever loosen INFORMATIONAL_RELAY (via relay_information).
# Action classes WORKSPACE_WRITE and SHELL_NETWORK_EXTERNAL always require explicit owner approval (or hard denial),
# while WORKSPACE_READ is governed directly by card.boundaries.filesystem.
# The `propose_actions` and `execute_local_actions` fields on AgentAutonomy exist in the card schema for future
# milestones but are intentionally not mapped to action classes in V1.1 policy evaluation.
ACTION_CLASS_TO_AUTONOMY_FIELD: dict[ActionClass, str | None] = {
    ActionClass.INFORMATIONAL_RELAY: "relay_information",
    ActionClass.SESSION_PARTICIPATION: None,
    ActionClass.ARTIFACT_RECEIPT: None,
    ActionClass.WORKSPACE_READ: None,
    ActionClass.WORKSPACE_WRITE: None,
    ActionClass.SHELL_NETWORK_EXTERNAL: None,
}

# Fixed mapping from ActionClass to RiskLabel for ApprovalRequests
ACTION_CLASS_RISK_MAP: dict[ActionClass, RiskLabel] = {
    ActionClass.INFORMATIONAL_RELAY: RiskLabel.LOW,
    ActionClass.SESSION_PARTICIPATION: RiskLabel.MEDIUM,
    ActionClass.ARTIFACT_RECEIPT: RiskLabel.LOW,
    ActionClass.WORKSPACE_READ: RiskLabel.MEDIUM,
    ActionClass.WORKSPACE_WRITE: RiskLabel.HIGH,
    ActionClass.SHELL_NETWORK_EXTERNAL: RiskLabel.CRITICAL,
}


def evaluate_action(
    card: AgentCard,
    action_class: ActionClass,
    session_context: dict[str, Any],
    now: str,
    prior_approval: ApprovalDecision | None = None,
    prior_approval_expires_at: str | None = None,
) -> PolicyResult:
    """Evaluate an action request against an AgentCard, boundaries, autonomy, and prior approvals.

    STRICT EVALUATION ORDER:
    1. Hard Boundary Denial Check: Runs FIRST and short-circuits. Boundary denials CANNOT
       be overridden by prior_approval.
    2. Prior Approval Check: Non-expired 'always_allow_bounded' grants ALLOW; explicit 'deny'
       grants DENY.
    3. Autonomy Mapping & Fallback: Maps autonomy level or returns REQUIRES_APPROVAL with
       a fully specified ApprovalRequest.

    Note: session_context is informational only. It MUST NOT contain or honor any peer-supplied
    tool or command name. The function signature intentionally has no tool_name parameter.
    """
    # --------------------------------------------------------------------------
    # STEP 1: Hard Boundary Denial Check (MUST execute first and short-circuit)
    # --------------------------------------------------------------------------
    if action_class == ActionClass.SHELL_NETWORK_EXTERNAL:
        if card.boundaries.shell == "deny" and card.boundaries.network_access == "deny":
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="Hard boundary denial: agent boundaries forbid both shell and network access.",
            )

    elif action_class == ActionClass.WORKSPACE_WRITE:
        if card.boundaries.filesystem in ("none", "workspace_read"):
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason=f"Hard boundary denial: filesystem boundary '{card.boundaries.filesystem}' forbids workspace writes.",
            )

    elif action_class == ActionClass.WORKSPACE_READ:
        if card.boundaries.filesystem == "none":
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="Hard boundary denial: filesystem boundary is set to 'none'.",
            )

    # --------------------------------------------------------------------------
    # STEP 2: Prior Approval Check
    # --------------------------------------------------------------------------
    if prior_approval is not None:
        if prior_approval.decision in (DecisionKind.ALWAYS_ALLOW_BOUNDED, "always_allow_bounded"):
            if prior_approval_expires_at is None or now < prior_approval_expires_at:
                return PolicyResult(
                    decision=PolicyDecision.ALLOW,
                    reason="Action permitted by valid non-expired bounded prior approval.",
                )
        elif prior_approval.decision in (DecisionKind.DENY, "deny"):
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="Action explicitly denied by prior approval decision.",
            )
        # Note: EDIT_CONSTRAINTS or expired ALWAYS_ALLOW_BOUNDED falls through to Step 3.

    # --------------------------------------------------------------------------
    # STEP 3: Autonomy Level & Default Mapping
    # --------------------------------------------------------------------------
    autonomy_field = ACTION_CLASS_TO_AUTONOMY_FIELD.get(action_class)
    if autonomy_field is not None:
        level = getattr(card.autonomy, autonomy_field)
        if level == AutonomyLevel.ALWAYS_ALLOW:
            return PolicyResult(
                decision=PolicyDecision.ALLOW,
                reason=f"Action permitted by card autonomy level '{level.value}'.",
            )
        elif level == AutonomyLevel.NEVER:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason=f"Action denied by card autonomy level '{level.value}'.",
            )

    # Fallthrough default: REQUIRES_APPROVAL with constructed ApprovalRequest
    session_id = session_context.get("session_id", "sess-unknown")
    risk_label = ACTION_CLASS_RISK_MAP.get(action_class, RiskLabel.HIGH)
    ts = now if TIMESTAMP_REGEX.match(now) else "2026-07-23T12:00:00.000Z"

    approval_request = ApprovalRequest(
        schema_version="1.1",
        approval_id=f"req-{session_id}-{action_class.value}",
        session_id=session_id,
        agent_id=card.id,
        action_class=action_class,
        summary=f"Approval request for action '{action_class.value}'",
        reason=f"Action '{action_class.value}' requires owner approval.",
        risk_label=risk_label,
        requested_scope={"session_context": session_context},
        expires_at=ts,
    )

    return PolicyResult(
        decision=PolicyDecision.REQUIRES_APPROVAL,
        approval_request=approval_request,
        reason=f"Action '{action_class.value}' requires owner approval.",
    )
