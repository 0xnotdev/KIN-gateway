"""V1.1 Pydantic models, RFC 8785 JCS canonicalization, and envelope verification pipeline."""

from __future__ import annotations

import base64
import hashlib
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Enforce mandatory rfc8785 package for 100% RFC 8785 JCS compliance
try:
    import rfc8785
except ImportError:
    raise RuntimeError("rfc8785 package is required for RFC 8785 JCS canonicalization")


def canonical_jcs(data: dict[str, Any]) -> bytes:
    """Serialize dictionary to RFC 8785 JCS canonical bytes (UTF-16 code-unit key sorting, ECMAScript numbers)."""
    return rfc8785.dumps(data)


def base64url_encode(data: bytes) -> str:
    """Encode bytes to URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def base64url_decode(encoded: str) -> bytes:
    """Decode URL-safe base64 string with or without padding."""
    padded = encoded + "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def validate_json_primitives(val: Any) -> None:
    """Recursively validate that val contains only valid JSON primitives (no NaNs, Infinities, sets, or custom objects)."""
    if val is None or isinstance(val, (str, bool)):
        return
    elif isinstance(val, int):
        return
    elif isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Invalid float value '{val}' (NaN and Infinity are forbidden in JSON).")
        return
    elif isinstance(val, list):
        for item in val:
            validate_json_primitives(item)
    elif isinstance(val, dict):
        for k, v in val.items():
            if not isinstance(k, str):
                raise ValueError(f"JSON dict keys must be strings, got {type(k).__name__}.")
            validate_json_primitives(v)
    else:
        raise ValueError(f"Unsupported non-JSON type '{type(val).__name__}' in payload.")


def compute_content_hash(payload: dict[str, Any]) -> str:
    """Compute base64url-encoded SHA-256 hash over canonical JCS payload bytes."""
    validate_json_primitives(payload)
    jcs_bytes = canonical_jcs(payload)
    digest = hashlib.sha256(jcs_bytes).digest()
    return base64url_encode(digest)


# Enums
class MessageKind(str, Enum):
    TASK_REQUEST = "task_request"
    ACCEPTANCE = "acceptance"
    DECLINE = "decline"
    CLARIFICATION = "clarification"
    PLAN = "plan"
    PROPOSAL = "proposal"
    COUNTERPROPOSAL = "counterproposal"
    FINDING = "finding"
    QUESTION = "question"
    ANSWER = "answer"
    ARTIFACT_OFFER = "artifact_offer"
    ARTIFACT_ACCEPT = "artifact_accept"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_DECISION = "approval_decision"
    STATUS_EVENT = "status_event"
    FINAL_RESULT = "final_result"
    CANCEL = "cancel"
    PARTICIPANT_CHANGED = "participant_changed"


class ActionClass(str, Enum):
    INFORMATIONAL_RELAY = "informational_relay"
    SESSION_PARTICIPATION = "session_participation"
    ARTIFACT_RECEIPT = "artifact_receipt"
    WORKSPACE_READ = "workspace_read"
    WORKSPACE_WRITE = "workspace_write"
    SHELL_NETWORK_EXTERNAL = "shell_network_external"


class RiskLabel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionKind(str, Enum):
    APPROVE_ONCE = "approve_once"
    DENY = "deny"
    EDIT_CONSTRAINTS = "edit_constraints"
    ALWAYS_ALLOW_BOUNDED = "always_allow_bounded"


class AgentAvailability(str, Enum):
    READY = "ready"
    BUSY = "busy"
    RESERVED = "reserved"
    NEEDS_KEY = "needs_key"
    NEEDS_WORKSPACE = "needs_workspace"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    OFFLINE = "offline"
    POLICY_BLOCKED = "policy_blocked"


# Validation Regexes
TIMESTAMP_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
CONTENT_HASH_REGEX = re.compile(r"^[a-zA-Z0-9_-]{43}$")


# Agent Cards
class AgentCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    id: str
    name: str
    description: str
    adapter: dict[str, Any]
    capabilities: dict[str, Any]
    boundaries: dict[str, Any]
    autonomy: dict[str, Any]
    presentation: dict[str, Any] | None = None


class PublishedAgentCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    agent_id: str
    name: str
    description: str
    capabilities: dict[str, Any]
    availability: AgentAvailability
    requires_owner_acceptance: bool
    protocol_version: Literal["1.1"]


# Wire Envelope
class SessionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    protocol_version: Literal["1.1"]
    session_id: str
    sequence: int
    actor_username: str
    actor_agent_id: str
    timestamp: str
    kind: MessageKind
    content_hash: str
    payload: dict[str, Any]
    signature: str | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def validate_kind_enum(cls, v: Any) -> MessageKind:
        if isinstance(v, MessageKind):
            return v
        if isinstance(v, str):
            try:
                return MessageKind(v)
            except ValueError:
                raise ValueError(f"Invalid MessageKind '{v}'")
        raise ValueError(f"MessageKind must be a string or MessageKind enum, got {type(v).__name__}")

    @field_validator("sequence", mode="before")
    @classmethod
    def validate_strict_int_sequence(cls, v: Any) -> int:
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("sequence must be a strict integer")
        if v < 1:
            raise ValueError("sequence must be >= 1")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_format(cls, v: str) -> str:
        if not TIMESTAMP_REGEX.match(v):
            raise ValueError("timestamp must be ISO 8601 UTC format ending in 'Z'")
        return v

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash_format(cls, v: str) -> str:
        if not CONTENT_HASH_REGEX.match(v):
            raise ValueError("content_hash must be a 43-character URL-safe Base64 SHA-256 string")
        return v

    @field_validator("payload")
    @classmethod
    def validate_payload_primitives(cls, v: dict[str, Any]) -> dict[str, Any]:
        validate_json_primitives(v)
        return v


def sign_envelope(envelope_dict: dict[str, Any], private_key: ed25519.Ed25519PrivateKey) -> str:
    """Compute base64url Ed25519 signature over canonical JCS envelope (excluding signature)."""
    dict_to_sign = {k: v for k, v in envelope_dict.items() if k != "signature"}
    jcs_bytes = canonical_jcs(dict_to_sign)
    sig_bytes = private_key.sign(jcs_bytes)
    return base64url_encode(sig_bytes)


def verify_envelope_signature(envelope_dict: dict[str, Any], public_key: ed25519.Ed25519PublicKey) -> bool:
    """Verify base64url Ed25519 signature over canonical JCS envelope."""
    sig_str = envelope_dict.get("signature")
    if not sig_str:
        return False
    try:
        sig_bytes = base64url_decode(sig_str)
        dict_to_sign = {k: v for k, v in envelope_dict.items() if k != "signature"}
        jcs_bytes = canonical_jcs(dict_to_sign)
        public_key.verify(sig_bytes, jcs_bytes)
        return True
    except (InvalidSignature, Exception):
        return False


# Wire Objects
class ArtifactOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    artifact_id: str
    session_id: str
    sha256: str
    mime_type: str
    size_bytes: int = Field(..., ge=0)
    offered_by: str
    preview_policy: str


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    approval_id: str
    session_id: str
    agent_id: str
    action_class: ActionClass
    summary: str
    reason: str
    risk_label: RiskLabel
    requested_scope: dict[str, Any]
    expires_at: str

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at_format(cls, v: str) -> str:
        if not TIMESTAMP_REGEX.match(v):
            raise ValueError("expires_at must be ISO 8601 UTC format ending in 'Z'")
        return v


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    approval_id: str
    session_id: str
    decision: DecisionKind
    decided_by: str
    decided_at: str
    constraints: dict[str, Any] | None = None

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at_format(cls, v: str) -> str:
        if not TIMESTAMP_REGEX.match(v):
            raise ValueError("decided_at must be ISO 8601 UTC format ending in 'Z'")
        return v


class TransportAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    envelope_session_id: str
    envelope_sequence: int = Field(..., ge=1)
    status: Literal["delivered", "queued", "rejected"]
    received_at: str
    verified_hash: str

    @field_validator("received_at")
    @classmethod
    def validate_received_at_format(cls, v: str) -> str:
        if not TIMESTAMP_REGEX.match(v):
            raise ValueError("received_at must be ISO 8601 UTC format ending in 'Z'")
        return v


class CapabilityAdvertisement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: str  # Kept as str to allow negotiation to inspect non-1.1 versions cleanly
    supported_features: list[str]
    max_turn_limit: int = Field(..., ge=1)


class InternalEventKind(str, Enum):
    MESSAGE = "message"
    ENVELOPE_RECEIVED = "envelope_received"
    PUBLIC_MSG = "public_msg"
    PRIVATE_NOTE = "private_note"
    OUTBOUND_ENVELOPE_QUEUED = "outbound_envelope_queued"


class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    protocol_version: Literal["1.1"]
    event_id: str
    session_id: str
    event_order: int = Field(..., ge=0)
    sequence: int | None = None
    actor_username: str
    actor_agent_id: str | None = None
    kind: MessageKind | InternalEventKind
    visibility: Literal["peer_visible", "local_only"]
    payload: dict[str, Any]
    signature: str | None = None
    created_at: str

    @field_validator("kind", mode="before")
    @classmethod
    def validate_kind_enum(cls, v: Any) -> MessageKind | InternalEventKind:
        if isinstance(v, (MessageKind, InternalEventKind)):
            return v
        if isinstance(v, str):
            try:
                return MessageKind(v)
            except ValueError:
                pass
            try:
                return InternalEventKind(v)
            except ValueError:
                pass
            raise ValueError(
                f"Invalid event kind '{v}'. Must be a recognized MessageKind or InternalEventKind."
            )
        raise ValueError(f"kind must be a string, MessageKind, or InternalEventKind enum, got {type(v).__name__}")

    @field_validator("sequence", mode="before")
    @classmethod
    def validate_sequence(cls, v: Any) -> int | None:
        if v is None:
            return None
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("sequence must be a strict integer or None")
        if v < 1:
            raise ValueError("sequence must be >= 1")
        return v

    @field_validator("created_at")
    @classmethod
    def validate_created_at_format(cls, v: str) -> str:
        if not TIMESTAMP_REGEX.match(v) and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+00:00|Z)$", v):
            raise ValueError("created_at must be ISO 8601 UTC format")
        return v

    @field_validator("payload")
    @classmethod
    def validate_payload_primitives(cls, v: dict[str, Any]) -> dict[str, Any]:
        validate_json_primitives(v)
        return v


# Verified Envelope Pipeline
@dataclass(frozen=True)
class VerifiedEnvelope:
    envelope: SessionEnvelope
    actor_public_key: ed25519.Ed25519PublicKey
    verified_at: str


class VerificationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    verified_envelope: VerifiedEnvelope | None = None
    error_code: str | None = None
    error_message: str | None = None


def verify_and_build_envelope(
    raw_dict: dict[str, Any],
    get_public_key_fn: Callable[[str], ed25519.Ed25519PublicKey | None],
    active_session_id: str,
    participant_map: dict[str, str],  # username -> agent_id
) -> VerificationResult:
    """Run full 6-stage verification pipeline to produce a VerifiedEnvelope."""
    # 1. Structural Schema Validation
    try:
        envelope = SessionEnvelope.model_validate(raw_dict)
    except Exception as e:
        return VerificationResult(
            success=False, error_code="STRUCTURAL_SCHEMA_INVALID", error_message=str(e)
        )

    # 2. Session ID Match Check
    if envelope.session_id != active_session_id:
        return VerificationResult(
            success=False,
            error_code="SESSION_ID_MISMATCH",
            error_message=f"Envelope session_id '{envelope.session_id}' does not match active session '{active_session_id}'.",
        )

    # 3. Canonical Payload Hash Verification
    try:
        expected_hash = compute_content_hash(envelope.payload)
        if envelope.content_hash != expected_hash:
            return VerificationResult(
                success=False,
                error_code="CONTENT_HASH_MISMATCH",
                error_message=f"Payload hash mismatch. Envelope: '{envelope.content_hash}', Computed: '{expected_hash}'.",
            )
    except Exception as e:
        return VerificationResult(
            success=False, error_code="PAYLOAD_CANONICALIZATION_FAILED", error_message=str(e)
        )

    # 4. Participant Authorization (Username & Agent ID)
    if envelope.actor_username not in participant_map:
        return VerificationResult(
            success=False,
            error_code="UNAUTHORIZED_ACTOR",
            error_message=f"Actor '{envelope.actor_username}' is not a registered session participant.",
        )

    expected_agent_id = participant_map[envelope.actor_username]
    if envelope.actor_agent_id != expected_agent_id:
        return VerificationResult(
            success=False,
            error_code="UNAUTHORIZED_AGENT",
            error_message=f"Actor agent ID '{envelope.actor_agent_id}' does not match registered agent '{expected_agent_id}'.",
        )

    # 5. Public Key Resolution
    pub_key = get_public_key_fn(envelope.actor_username)
    if not pub_key:
        return VerificationResult(
            success=False,
            error_code="PUBLIC_KEY_NOT_FOUND",
            error_message=f"Public key for trusted contact '{envelope.actor_username}' not found.",
        )

    # 6. Cryptographic Signature Verification
    if not envelope.signature or not verify_envelope_signature(raw_dict, pub_key):
        return VerificationResult(
            success=False,
            error_code="INVALID_SIGNATURE",
            error_message=f"Ed25519 signature verification failed for actor '{envelope.actor_username}'.",
        )

    verified = VerifiedEnvelope(
        envelope=envelope,
        actor_public_key=pub_key,
        verified_at=envelope.timestamp,
    )
    return VerificationResult(success=True, verified_envelope=verified)
