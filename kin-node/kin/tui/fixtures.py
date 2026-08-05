"""Fixture factories for typed UI view models in KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.1
"""

from typing import Dict, List, Optional
from kin.artifacts.vault import ArtifactMetadata
from kin.schemas import (
    ActionClass,
    AgentAutonomy,
    AgentAvailability,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    ApprovalDecision,
    ApprovalRequest,
    AutonomyLevel,
    DecisionKind,
    LocalCommandAdapterConfig,
    PublishedAgentCard,
    RiskLabel,
)
from kin.session.transition_matrix import VALID_TRANSITIONS
from kin.tui.state import (
    AgentCardView,
    ApprovalView,
    ArtifactView,
    HealthSnapshot,
    RecoverableError,
    SessionSummary,
    SidebarItem,
    UiEvent,
    UiState,
    WorkspaceTab,
)

FROZEN_CLOCK = "2026-07-26T12:00:00.000Z"

# 1. SessionSummary factories for all 16 valid transition statuses
ALL_16_SESSION_STATUSES = sorted(list(VALID_TRANSITIONS.keys()))


def make_session_summary_fixture(
    status: str, session_id: str = "sess-test-001"
) -> SessionSummary:
    if status not in VALID_TRANSITIONS:
        raise ValueError(f"Unknown session status '{status}' not in VALID_TRANSITIONS")
    return SessionSummary(
        session_id=session_id,
        status=status,
        participant_display_names=["Alice (Owner)", "Code Scout (Agent)"],
        current_turn=3,
        max_turns=10,
        last_activity_at=FROZEN_CLOCK,
    )


def make_all_session_summary_fixtures() -> Dict[str, SessionSummary]:
    return {
        st: make_session_summary_fixture(st, f"sess-{st}")
        for st in ALL_16_SESSION_STATUSES
    }


# 2. AgentCardView factories for all 8 AgentAvailability enum values from kin.schemas
ALL_8_AVAILABILITY_VALUES = [
    AgentAvailability.READY,
    AgentAvailability.BUSY,
    AgentAvailability.RESERVED,
    AgentAvailability.NEEDS_KEY,
    AgentAvailability.NEEDS_WORKSPACE,
    AgentAvailability.WAITING_FOR_APPROVAL,
    AgentAvailability.OFFLINE,
    AgentAvailability.POLICY_BLOCKED,
]


def make_agent_card_view_fixture(
    availability: AgentAvailability,
    is_peer: bool = False,
) -> AgentCardView:
    reason_map = {
        AgentAvailability.READY: "Agent is online and ready for tasks.",
        AgentAvailability.BUSY: "Agent is currently processing a session task.",
        AgentAvailability.RESERVED: "Agent is reserved for dedicated session execution.",
        AgentAvailability.NEEDS_KEY: "Agent requires key configuration.",
        AgentAvailability.NEEDS_WORKSPACE: "Agent requires workspace path initialization.",
        AgentAvailability.WAITING_FOR_APPROVAL: "Agent is waiting for owner approval.",
        AgentAvailability.OFFLINE: "Agent endpoint is offline.",
        AgentAvailability.POLICY_BLOCKED: "Agent is blocked by security policy.",
    }
    reason = reason_map[availability]

    if is_peer:
        pub_card = PublishedAgentCard(
            schema_version="1.1",
            protocol_version="1.1",
            agent_id="data-cleaner",
            name="Data Cleaner",
            description="Converts raw tabular data into validated CSV artifacts.",
            capabilities=AgentCapabilities(tags=["data-cleaning", "csv"], accepts=["text/csv"]),
            availability=availability,
            requires_owner_acceptance=True,
        )
        return AgentCardView.from_published_card(pub_card, readiness_reason=reason)
    else:
        card = AgentCard(
            schema_version="1.1",
            id="code-scout",
            name="Code Scout",
            description="Reviews repository diffs and proposes patch fixes.",
            adapter=LocalCommandAdapterConfig(type="local_command", command="codex", working_directory="/work/code"),
            capabilities=AgentCapabilities(tags=["code-review", "patch-proposal"], accepts=["text/x-diff"]),
            boundaries=AgentBoundaries(
                network_access="deny",
                filesystem="none",
                shell="deny",  # nosec B604
                max_runtime_seconds=900,
                max_artifact_bytes=10_000_000,
            ),
            autonomy=AgentAutonomy(
                relay_information=AutonomyLevel.ALWAYS_ASK,
                propose_actions=AutonomyLevel.ALWAYS_ASK,
                execute_local_actions=AutonomyLevel.ALWAYS_ASK,
            ),
        )
        return AgentCardView.from_local_card(card, availability=availability, readiness_reason=reason)


def make_all_agent_card_view_fixtures() -> List[AgentCardView]:
    return [make_agent_card_view_fixture(avail) for avail in ALL_8_AVAILABILITY_VALUES]


# 3. ApprovalView factories for all 4 RiskLabel values + 4 DecisionKind variants
ALL_4_RISK_LABELS = [
    RiskLabel.LOW,
    RiskLabel.MEDIUM,
    RiskLabel.HIGH,
    RiskLabel.CRITICAL,
]

ALL_4_DECISION_KINDS = [
    DecisionKind.APPROVE_ONCE,
    DecisionKind.DENY,
    DecisionKind.EDIT_CONSTRAINTS,
    DecisionKind.ALWAYS_ALLOW_BOUNDED,
]


def make_approval_view_fixture(
    risk_label: RiskLabel = RiskLabel.MEDIUM,
    decision_kind: Optional[DecisionKind] = None,
    now: Optional[str] = FROZEN_CLOCK,
) -> ApprovalView:
    req = ApprovalRequest(
        schema_version="1.1",
        approval_id=f"appr-{risk_label.value.lower()}-001",
        session_id="sess-test-001",
        agent_id="code-scout",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary=f"Requesting write access for {risk_label.value} risk action.",
        reason="Modify source files",
        risk_label=risk_label,
        requested_scope={"path": "/work/src/main.py"},
        expires_at="2026-07-26T13:00:00.000Z",
    )
    decision = None
    if decision_kind is not None:
        decision = ApprovalDecision(
            schema_version="1.1",
            approval_id=req.approval_id,
            session_id=req.session_id,
            decision=decision_kind,
            decided_by="alice",
            decided_at=FROZEN_CLOCK,
        )
    return ApprovalView(request=req, decision=decision, now=now)


def make_all_approval_view_fixtures() -> List[ApprovalView]:
    res = [make_approval_view_fixture(risk) for risk in ALL_4_RISK_LABELS]
    for d_kind in ALL_4_DECISION_KINDS:
        res.append(make_approval_view_fixture(RiskLabel.HIGH, decision_kind=d_kind))
    return res


# 4. ArtifactView factories: markdown/text, CSV, unknown/binary MIME
def make_artifact_view_fixture(kind: str = "markdown") -> ArtifactView:
    if kind == "markdown":
        meta = ArtifactMetadata(
            artifact_id="art-md-001",
            session_id="sess-test-001",
            sha256="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            mime_type="text/markdown",
            size_bytes=12697,  # 12.4 KB
            offered_by="code-scout",
            preview_policy="text_preview",
            created_at=FROZEN_CLOCK,
        )
    elif kind == "csv":
        meta = ArtifactMetadata(
            artifact_id="art-csv-001",
            session_id="sess-test-001",
            sha256="5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
            mime_type="text/csv",
            size_bytes=1048576,  # 1.0 MB
            offered_by="data-cleaner",
            preview_policy="table_preview",
            created_at=FROZEN_CLOCK,
        )
    else:  # binary
        meta = ArtifactMetadata(
            artifact_id="art-bin-001",
            session_id="sess-test-001",
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            mime_type="application/octet-stream",
            size_bytes=512,
            offered_by="code-scout",
            preview_policy="none",
            created_at=FROZEN_CLOCK,
        )
    return ArtifactView.from_metadata(meta)


# 5. RecoverableError factories: relay-unreachable, keychain-unavailable, adapter-crash
def make_recoverable_error_fixture(failure_type: str = "relay") -> RecoverableError:
    if failure_type == "relay":
        return RecoverableError(
            what_happened="Relay server connection lost.",
            impact="Remote peer messaging and external dispatches paused.",
            preserved="Local session state and pending queue saved safely.",
            next_action="Reconnecting automatically in 15 seconds or press 'r' to retry now.",
            technical_detail="ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 8080)",
        )
    elif failure_type == "keychain":
        return RecoverableError(
            what_happened="Keyring backend unavailable.",
            impact="Unable to load stored private keys.",
            preserved="Configuration files on disk remain untouched.",
            next_action="Unlock system keyring or set KIN_TEST_KEYRING_PATH.",
            technical_detail="KeyringLockedError: System keyring is locked by desktop environment.",
        )
    else:  # adapter-crash
        return RecoverableError(
            what_happened="Local command adapter crashed during execution.",
            impact="Turn 4 halted without producing output artifact.",
            preserved="Session history up to turn 3 intact.",
            next_action="Review adapter command config or restart turn.",
            technical_detail="ProcessExitedWithError: Command 'codex' exited with code 139 (SIGSEGV)",
        )


# 6. Default UiState fixture
def make_default_uistate_fixture() -> UiState:
    health = HealthSnapshot(
        keychain_ok=True,
        identity_ok=True,
        relay_reachable=True,
        node_reachable=True,
        pending_inbox_count=0,
    )
    tabs = [
        WorkspaceTab(id="tab-home", kind="home", title="Home", state_glyph="none", closable=False),
        WorkspaceTab(id="tab-sess-1", kind="session", title="Session: Code Review", state_glyph="live", closable=True),
    ]
    sidebar = [
        SidebarItem(id="sb-home", label="Home", section="spaces"),
        SidebarItem(id="sb-agent-1", label="Code Scout", section="agents", availability=AgentAvailability.READY),
    ]
    return UiState(
        profile_health=health,
        workspaces=tabs,
        active_tab_id="tab-home",
        sidebar=sidebar,
    )
