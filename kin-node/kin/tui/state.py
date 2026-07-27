"""Typed View Models for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §3.4, §4.1, §5.8, §7.2, §10.3, §14.1, §14.6

Note: These are UI PROJECTIONS, not sources of truth.
They import read-only from kin.schemas and kin.artifacts.vault.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar, Union

from kin.artifacts.vault import ArtifactMetadata
from kin.schemas import (
    AgentAvailability,
    AgentCard,
    ApprovalDecision,
    ApprovalRequest,
    InternalEventKind,
    MessageKind,
    PublishedAgentCard,
    SessionEvent,
)

T = TypeVar("T")

WorkspaceKind = Literal["home", "session", "dispatch", "agents", "network", "inbox", "search"]
StateGlyph = Literal["live", "needs_you", "error", "none"]
SidebarSection = Literal["spaces", "agents", "network", "needs_you"]
PresentationClass = Literal[
    "message", "activity", "checkpoint", "artifact", "approval", "state_transition", "security"
]

# Explicit, exhaustive mapping of every MessageKind and InternalEventKind member
# to its UI presentation class (§7.2).
EVENT_KIND_MAPPING: Dict[Union[MessageKind, InternalEventKind], PresentationClass] = {
    # MessageKind members (18 total)
    MessageKind.TASK_REQUEST: "message",
    MessageKind.ACCEPTANCE: "state_transition",
    MessageKind.DECLINE: "state_transition",
    MessageKind.CLARIFICATION: "message",
    MessageKind.PLAN: "activity",
    MessageKind.PROPOSAL: "message",
    MessageKind.COUNTERPROPOSAL: "message",
    MessageKind.FINDING: "activity",
    MessageKind.QUESTION: "message",
    MessageKind.ANSWER: "message",
    MessageKind.ARTIFACT_OFFER: "artifact",
    MessageKind.ARTIFACT_ACCEPT: "artifact",
    MessageKind.APPROVAL_REQUEST: "approval",
    MessageKind.APPROVAL_DECISION: "approval",
    MessageKind.STATUS_EVENT: "activity",  # Non-transitional status updates (matches PEER_KIND_TRANSITION_MAP: None)
    MessageKind.FINAL_RESULT: "state_transition",
    MessageKind.CANCEL: "state_transition",
    MessageKind.PARTICIPANT_CHANGED: "state_transition",
    # InternalEventKind members (7 total)
    InternalEventKind.MESSAGE: "message",
    InternalEventKind.ENVELOPE_RECEIVED: "activity",
    InternalEventKind.PUBLIC_MSG: "message",
    InternalEventKind.PRIVATE_NOTE: "activity",
    InternalEventKind.OUTBOUND_ENVELOPE_QUEUED: "activity",
    InternalEventKind.ACTIVITY: "activity",
    InternalEventKind.ADAPTER_ERROR: "security",  # Crucial: errors mapped to security so they are never lost in activity noise
}


def map_event_kind_to_presentation_class(
    kind: Union[MessageKind, InternalEventKind, str]
) -> PresentationClass:
    """Map SessionEvent kind (MessageKind or InternalEventKind) to UI presentation class.

    Switches strictly on real schema enum members. Raises ValueError for unrecognized kinds
    so new schema additions break loudly rather than silently defaulting.
    """
    enum_val: Optional[Union[MessageKind, InternalEventKind]] = None

    if isinstance(kind, (MessageKind, InternalEventKind)):
        enum_val = kind
    elif isinstance(kind, str):
        # Attempt conversion to MessageKind first, then InternalEventKind
        try:
            enum_val = MessageKind(kind)
        except ValueError:
            try:
                enum_val = InternalEventKind(kind)
            except ValueError:
                pass

    if enum_val is None or enum_val not in EVENT_KIND_MAPPING:
        raise ValueError(
            f"Unrecognized event kind '{kind}'. Must be a valid MessageKind or InternalEventKind enum member."
        )

    return EVENT_KIND_MAPPING[enum_val]


@dataclass
class HealthSnapshot:
    """Health status snapshot mirroring kin doctor report."""

    keychain_ok: bool
    identity_ok: bool
    relay_reachable: bool
    node_reachable: bool
    pending_inbox_count: int
    degraded_reason: Optional[str] = None


@dataclass
class WorkspaceTab:
    """Workspace tab representation per TUI spec §4.1."""

    id: str
    kind: WorkspaceKind
    title: str
    state_glyph: StateGlyph = "none"
    closable: bool = True

    def __post_init__(self) -> None:
        if self.kind == "home":
            self.closable = False


@dataclass
class SidebarItem:
    """Recursive/nested sidebar item."""

    id: str
    label: str
    section: SidebarSection
    count: Optional[int] = None
    availability: Optional[AgentAvailability] = None
    collapsed: bool = False
    children: List["SidebarItem"] = field(default_factory=list)


@dataclass
class SessionSummary:
    """Lightweight UI summary of a SessionState for list/row rendering."""

    session_id: str
    status: str
    participant_display_names: List[str]
    current_turn: int
    max_turns: int
    last_activity_at: str


@dataclass
class UiEvent:
    """Presentation wrapper around kin.schemas.SessionEvent."""

    event_id: str
    session_id: str
    kind: str
    created_at: str
    actor_username: Optional[str]
    presentation_class: PresentationClass

    @classmethod
    def from_session_event(cls, event: SessionEvent) -> "UiEvent":
        p_class = map_event_kind_to_presentation_class(event.kind)
        return cls(
            event_id=event.event_id,
            session_id=event.session_id,
            kind=str(event.kind),
            created_at=event.created_at,
            actor_username=event.actor_username,
            presentation_class=p_class,
        )


@dataclass
class ArtifactView:
    """UI projection wrapping kin.artifacts.vault.ArtifactMetadata."""

    metadata: ArtifactMetadata
    display_size: str
    preview_available: bool

    @classmethod
    def from_metadata(cls, metadata: ArtifactMetadata) -> "ArtifactView":
        size_bytes = metadata.size_bytes
        if size_bytes < 1024:
            disp_size = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            disp_size = f"{size_bytes / 1024:.1f} KB"
        else:
            disp_size = f"{size_bytes / (1024 * 1024):.1f} MB"

        policy = str(metadata.preview_policy).lower()
        mime = str(metadata.mime_type).lower()
        is_previewable = policy not in ("none", "disabled", "false") and (
            mime.startswith("text/")
            or mime in ("application/json", "application/csv", "text/csv", "application/yaml", "text/markdown")
        )

        return cls(
            metadata=metadata,
            display_size=disp_size,
            preview_available=is_previewable,
        )


@dataclass
class ApprovalView:
    """UI projection wrapping kin.schemas.ApprovalRequest and optional ApprovalDecision.

    Supports an injectable `now` timestamp (datetime or ISO string) for deterministic testing.
    """

    request: ApprovalRequest
    decision: Optional[ApprovalDecision] = None
    time_remaining: Optional[float] = None
    now: Optional[Union[datetime, str]] = None

    def __post_init__(self) -> None:
        if self.request.expires_at and not self.decision:
            try:
                exp_dt = datetime.fromisoformat(self.request.expires_at.replace("Z", "+00:00"))
                if self.now is None:
                    current_time = datetime.now(timezone.utc)
                elif isinstance(self.now, str):
                    current_time = datetime.fromisoformat(self.now.replace("Z", "+00:00"))
                else:
                    current_time = self.now

                if current_time.tzinfo is None:
                    current_time = current_time.replace(tzinfo=timezone.utc)

                diff = (exp_dt - current_time).total_seconds()
                self.time_remaining = max(0.0, diff)
            except (ValueError, TypeError):
                self.time_remaining = None


@dataclass
class AgentCardView:
    """UI projection wrapping local AgentCard or peer PublishedAgentCard."""

    agent_id: str
    name: str
    description: str
    availability: AgentAvailability
    readiness_reason: str
    is_peer: bool
    # Only populated if local card
    capabilities_tags: List[str] = field(default_factory=list)

    @classmethod
    def from_local_card(
        cls, card: AgentCard, availability: AgentAvailability, readiness_reason: str
    ) -> "AgentCardView":
        return cls(
            agent_id=card.id,
            name=card.name,
            description=card.description,
            availability=availability,
            readiness_reason=readiness_reason,
            is_peer=False,
            capabilities_tags=list(card.capabilities.tags) if card.capabilities else [],
        )

    @classmethod
    def from_published_card(cls, card: PublishedAgentCard, readiness_reason: str) -> "AgentCardView":
        return cls(
            agent_id=card.agent_id,
            name=card.name,
            description=card.description,
            availability=card.availability,
            readiness_reason=readiness_reason,
            is_peer=True,
            capabilities_tags=list(card.capabilities.tags) if card.capabilities else [],
        )


@dataclass
class CommandResult(Generic[T]):
    """Generic outcome wrapper matching ReducerResult / VerificationResult shape."""

    success: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    data: Optional[T] = None


@dataclass
class RecoverableError:
    """Structured operational error card per TUI spec §10.3."""

    what_happened: str
    impact: str
    preserved: str
    next_action: str
    technical_detail: Optional[str] = None


@dataclass
class UiState:
    """Root UI state container."""

    profile_health: HealthSnapshot
    workspaces: List[WorkspaceTab] = field(default_factory=list)
    active_tab_id: Optional[str] = None
    sidebar: List[SidebarItem] = field(default_factory=list)
    node_snapshot: dict = field(default_factory=dict)
    overlays: List[dict] = field(default_factory=list)
    toasts: List[dict] = field(default_factory=list)
    workspace_focus_scroll: dict = field(default_factory=dict)
