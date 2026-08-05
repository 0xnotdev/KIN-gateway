"""V1.1 Transport Layer: Ingestion, Symmetric Self-Processing, Delivery, Retry Queue, and Relay Synchronization."""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.agent_registry.peer_cards import cache_peer_card, is_stale
from kin.agent_registry.registry import get_card
from kin.artifacts.vault import (
    ArtifactIdConflictError,
    ArtifactNotFoundError,
    ArtifactTooLargeError,
    get_artifact_metadata,
    load_artifact_bytes,
    store_artifact,
)
from kin.audit.writer import append_session_event, check_sequence_conflict, write_audit_event
from kin.identity.auth import create_signed_auth_headers
from kin.identity.keys import decrypt_from_sender, encrypt_for_recipient
from kin.schemas import (
    AgentAvailability,
    ArtifactOffer,
    CapabilityAdvertisement,
    MessageKind,
    PublishedAgentCard,
    SessionType,
    TransportAcknowledgement,
    compute_content_hash,
    sign_envelope,
    verify_and_build_envelope,
)

DEFAULT_BUILD_RUNTIME_BUDGET = 86400  # 24 hours
DEFAULT_BUILD_ARTIFACT_BYTES_BUDGET = 50_000_000  # 50 MB
DEFAULT_BUILD_COST_BUDGET_ESTIMATE = 100.0  # 100 estimated adapter calls
from kin.session.compatibility import negotiate_capability
from kin.session.reducer import (
    ParticipantInfo,
    SessionState,
    process_node_command,
    process_owner_command,
    process_peer_envelope,
    reconstruct_session_state,
)
from kin.session.transition_matrix import TERMINAL_STATES

DEFAULT_EXPIRY_TTL_SECONDS = 604800  # 7 days


@dataclass(frozen=True)
class OwnerCredentials:
    identity_key: ed25519.Ed25519PrivateKey
    x25519_privkey: bytes
    username: str


@dataclass(frozen=True)
class PeerEndpointConfig:
    endpoint: str | None = None
    relay_url: str | None = None
    recipient_x25519_pubkey: bytes | None = None


class TransportError(Exception):
    """Base exception for transport failures."""
    pass


class CapabilityMismatchError(TransportError):
    """Raised when a peer's capabilities or protocol version do not meet V1.1 requirements."""
    pass


class StalePeerCardError(TransportError):
    """Raised when attempting to dispatch to a peer agent whose card is stale and unreviewed."""
    pass


def _iso_now(now: datetime.datetime | None = None) -> str:
    dt = now or datetime.datetime.now(datetime.timezone.utc)
    res = dt.isoformat()
    if res.endswith("+00:00"):
        res = res[:-6] + "Z"
    elif not res.endswith("Z"):
        res = res + "Z"
    return res


def _queue_relay_envelope(
    client: httpx.Client,
    relay_url: str,
    recipient_username: str,
    sender_username: str,
    encrypted_payload: bytes,
) -> httpx.Response:
    """Queue one encrypted V1.1 envelope using the relay's real HTTP contract."""
    return client.post(
        f"{relay_url.rstrip('/')}/relay/mailbox/{recipient_username}",
        json={
            "sender_username": sender_username,
            "encrypted_blob": encrypted_payload.hex(),
        },
    )


def _relay_auth_headers(
    username: str,
    private_key: ed25519.Ed25519PrivateKey,
    *,
    now: datetime.datetime | None = None,
    acknowledgement_body: str | None = None,
) -> dict[str, str]:
    """Build relay-compatible hex signatures for inbox reads and bound ACKs."""
    timestamp = _iso_now(now)
    canonical = f"{username}:{timestamp}"
    if acknowledgement_body is not None:
        canonical = f"{canonical}:{acknowledgement_body}"
    return {
        "X-Username": username,
        "X-Timestamp": timestamp,
        "X-Signature": private_key.sign(canonical.encode("utf-8")).hex(),
    }


def _resolve_peer_contact_info(
    conn: sqlite3.Connection, peer_username: str
) -> tuple[str | None, bytes | None, ed25519.Ed25519PublicKey | None]:
    """Resolve endpoint URL, X25519 pubkey, and Ed25519 pubkey for a peer contact."""
    cur = conn.cursor()
    cur.execute(
        "SELECT endpoint, x25519_public_key, public_key, fingerprint_verified_at FROM contacts WHERE username = ?",
        (peer_username,),
    )
    row = cur.fetchone()
    if not row or not row[3]:
        return None, None, None

    endpoint = row[0]
    x25519_hex = row[1]
    pubkey_hex = row[2]

    x25519_bytes = bytes.fromhex(x25519_hex) if x25519_hex else None
    ed_pubkey = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex)) if pubkey_hex else None

    return endpoint, x25519_bytes, ed_pubkey


def cache_peer_capabilities(
    conn: sqlite3.Connection,
    peer_username: str,
    capability_ad: CapabilityAdvertisement,
    now: datetime.datetime | None = None,
) -> None:
    """Cache peer's CapabilityAdvertisement projection in peer_capabilities table."""
    now_str = _iso_now(now)
    cap_json = capability_ad.model_dump_json()
    conn.execute(
        """\
        INSERT INTO peer_capabilities (peer_username, capability_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(peer_username) DO UPDATE SET
            capability_json = excluded.capability_json,
            fetched_at = excluded.fetched_at
        """,
        (peer_username, cap_json, now_str),
    )
    conn.commit()


def get_cached_peer_capabilities(
    conn: sqlite3.Connection,
    peer_username: str,
    max_age_hours: int = 72,
    now: datetime.datetime | None = None,
) -> CapabilityAdvertisement | None:
    """Retrieve cached peer CapabilityAdvertisement if present and not expired."""
    now_dt = now or datetime.datetime.now(datetime.timezone.utc)
    cur = conn.cursor()
    cur.execute(
        "SELECT capability_json, fetched_at FROM peer_capabilities WHERE peer_username = ?",
        (peer_username,),
    )
    row = cur.fetchone()
    if not row:
        return None

    cap_json, fetched_str = row
    fetched_dt = datetime.datetime.fromisoformat(fetched_str.rstrip("Z")).replace(tzinfo=datetime.timezone.utc)
    if (now_dt - fetched_dt).total_seconds() > max_age_hours * 3600:
        return None

    try:
        return CapabilityAdvertisement.model_validate_json(cap_json)
    except Exception:
        return None


def _apply_node_command_transition(
    conn: sqlite3.Connection,
    vault_key: bytes,
    session_id: str,
    command_name: str,
    now: datetime.datetime | None = None,
) -> SessionState | None:
    """Reconstruct SessionState, execute process_node_command, persist new status, and log audit event.

    Ensures state machine transitions follow valid transition rules and terminal immutability.
    """
    now_str = _iso_now(now)
    state = reconstruct_session_state(conn, vault_key, session_id)
    if not state:
        return None

    res = process_node_command(state, command_name)
    if not res.success:
        write_audit_event(
            conn,
            vault_key,
            category="session_status_rejected",
            session_id=session_id,
            summary=f"Node command transition '{command_name}' rejected on state '{state.status}': {res.error_message}",
        )
        return None

    new_state = res.new_state
    conn.execute(
        "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
        (new_state.status, now_str, session_id),
    )
    write_audit_event(
        conn,
        vault_key,
        category="session_status_updated",
        session_id=session_id,
        summary=f"Session status updated to '{new_state.status}' via command '{command_name}'",
        payload={"previous_status": state.status, "new_status": new_state.status, "command": command_name},
        correlation_id=session_id,
    )
    conn.commit()
    return new_state


def _apply_owner_command_transition(
    conn: sqlite3.Connection,
    vault_key: bytes,
    session_id: str,
    owner_username: str,
    action: str,
    payload: dict[str, Any] | None = None,
    now: datetime.datetime | None = None,
) -> SessionState | None:
    """Reconstruct SessionState, execute process_owner_command, persist new status, and log audit event.

    Ensures state machine transitions follow valid transition rules and owner authorization.
    """
    from kin.session.reducer import process_owner_command

    now_str = _iso_now(now)
    state = reconstruct_session_state(conn, vault_key, session_id)
    if not state:
        return None

    res = process_owner_command(state, owner_username, action, payload)
    if not res.success:
        write_audit_event(
            conn,
            vault_key,
            category="session_status_rejected",
            session_id=session_id,
            summary=f"Owner command transition '{action}' rejected on state '{state.status}': {res.error_message}",
        )
        return None

    new_state = res.new_state
    conn.execute(
        "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
        (new_state.status, now_str, session_id),
    )
    write_audit_event(
        conn,
        vault_key,
        category="session_status_updated",
        session_id=session_id,
        summary=f"Session status updated to '{new_state.status}' via owner action '{action}'",
        payload={"previous_status": state.status, "new_status": new_state.status, "action": action},
        correlation_id=session_id,
    )
    conn.commit()
    return new_state


def ingest_envelope(
    conn: sqlite3.Connection,
    vault_key: bytes,
    raw_body: dict[str, Any],
    get_public_key_fn: Callable[[str], ed25519.Ed25519PublicKey | None],
    now: datetime.datetime | None = None,
    recipient_x25519_privkey: bytes | None = None,
    owner_identity_key: ed25519.Ed25519PrivateKey | None = None,
    relay_url: str | None = None,
    http_client: httpx.Client | None = None,
) -> TransportAcknowledgement:
    """Core 6-stage envelope ingestion pipeline with symmetric self-processing and agent-id locking."""
    now_dt = now or datetime.datetime.now(datetime.timezone.utc)
    now_str = _iso_now(now_dt)

    session_id = raw_body.get("session_id", "")
    actor_username = raw_body.get("actor_username", "")
    actor_agent_id = raw_body.get("actor_agent_id", "")
    sequence = raw_body.get("sequence", 0)

    cur = conn.cursor()
    cur.execute(
        "SELECT initiator_username, receiver_username, sender_agent_id, receiver_agent_id, status, expires_at FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    sess_row = cur.fetchone()

    participant_map: dict[str, str] = {}
    if sess_row is None:
        kind_str = raw_body.get("kind", "")
        # Bootstrap check for initial TASK_REQUEST
        if kind_str != MessageKind.TASK_REQUEST.value:
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="rejected",
                received_at=now_str,
                verified_hash=raw_body.get("content_hash", ""),
                error_code="SESSION_NOT_FOUND",
                error_message=f"Session '{session_id}' does not exist for non-bootstrap envelope '{kind_str}'.",
            )

        # Verify actor is a paired contact (or local self)
        pub_key = get_public_key_fn(actor_username)
        if not pub_key:
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="rejected",
                received_at=now_str,
                verified_hash=raw_body.get("content_hash", ""),
                error_code="UNPAIRED_SENDER",
                error_message=f"Actor '{actor_username}' is not a verified contact.",
            )

        participant_map = {actor_username: actor_agent_id}
    else:
        init_un, rec_un, sender_ag_id, receiver_ag_id, sess_status, expires_at_str = sess_row

        # Lazy expiration check using process_node_command helper (GAP S)
        if expires_at_str:
            exp_dt = datetime.datetime.fromisoformat(expires_at_str.rstrip("Z")).replace(tzinfo=datetime.timezone.utc)
            if now_dt >= exp_dt and sess_status not in TERMINAL_STATES:
                exp_state = _apply_node_command_transition(conn, vault_key, session_id, "mark_expired", now=now_dt)
                if exp_state:
                    sess_status = exp_state.status

        kind_str = raw_body.get("kind", "")
        participant_map = {}
        if sender_ag_id:
            participant_map[init_un] = sender_ag_id
        if receiver_ag_id and (kind_str != MessageKind.ACCEPTANCE.value or actor_username == init_un):
            participant_map[rec_un] = receiver_ag_id
        if actor_username not in participant_map:
            participant_map[actor_username] = actor_agent_id

    # 1. Run 6-stage verification pipeline
    ver_res = verify_and_build_envelope(raw_body, get_public_key_fn, active_session_id=session_id, participant_map=participant_map)
    if not ver_res.success or not ver_res.verified_envelope:
        return TransportAcknowledgement(
            schema_version="1.1",
            envelope_session_id=session_id,
            envelope_sequence=sequence,
            status="rejected",
            received_at=now_str,
            verified_hash=raw_body.get("content_hash", ""),
            error_code=ver_res.error_code,
            error_message=ver_res.error_message,
        )

    verified_env = ver_res.verified_envelope
    env = verified_env.envelope

    # 2. Check for duplicate/conflict sequence BEFORE reducer (GAP K & O)
    status_kind, existing_event_id = check_sequence_conflict(
        conn,
        vault_key,
        session_id=session_id,
        actor_username=env.actor_username,
        sequence=env.sequence,
        payload=env.payload,
    )
    if status_kind == "duplicate":
        return TransportAcknowledgement(
            schema_version="1.1",
            envelope_session_id=session_id,
            envelope_sequence=env.sequence,
            status="delivered",
            received_at=now_str,
            verified_hash=env.content_hash,
        )
    elif status_kind == "conflict":
        return TransportAcknowledgement(
            schema_version="1.1",
            envelope_session_id=session_id,
            envelope_sequence=env.sequence,
            status="rejected",
            received_at=now_str,
            verified_hash=env.content_hash,
            error_code="SEQUENCE_REUSE_MISMATCH",
            error_message="Sequence reuse mismatch: sequence number re-used with different content hash.",
        )

    # 3. Reconstruct or initialize state
    if sess_row is None:
        payload = env.payload or {}
        requested_agent_id = payload.get("requested_agent_id", "")
        collaboration_mode_raw = payload.get("collaboration_mode", "ask")

        try:
            st = SessionType(collaboration_mode_raw)
        except ValueError:
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=env.sequence,
                status="rejected",
                received_at=now_str,
                verified_hash=env.content_hash,
                error_code="INVALID_SESSION_TYPE",
                error_message=f"Invalid collaboration_mode '{collaboration_mode_raw}'. Must be a valid SessionType.",
            )

        cur.execute("SELECT username FROM identity LIMIT 1")
        my_identity_row = cur.fetchone()
        my_username = my_identity_row[0] if my_identity_row else ""

        if actor_username == my_username:
            peer_username = payload.get("peer_username", "")
            initiator_username = actor_username
            receiver_username = peer_username
        else:
            peer_username = my_username
            initiator_username = actor_username
            receiver_username = peer_username

        raw_max_turns = payload.get("max_turns", 12)
        turn_limit = raw_max_turns if isinstance(raw_max_turns, int) and 1 <= raw_max_turns <= 12 else 12

        if st in (SessionType.BUILD_PIPELINE, SessionType.DELEGATE_SUBTASK):
            runtime_budget = payload.get("runtime_budget_seconds", DEFAULT_BUILD_RUNTIME_BUDGET)
            artifact_budget = payload.get("artifact_bytes_budget", DEFAULT_BUILD_ARTIFACT_BYTES_BUDGET)
            cost_budget = payload.get("cost_budget_estimate", DEFAULT_BUILD_COST_BUDGET_ESTIMATE)
        else:
            runtime_budget = payload.get("runtime_budget_seconds")
            artifact_budget = payload.get("artifact_bytes_budget")
            cost_budget = payload.get("cost_budget_estimate")

        exp_str = (now_dt + datetime.timedelta(seconds=DEFAULT_EXPIRY_TTL_SECONDS)).isoformat()
        if not exp_str.endswith("Z"):
            exp_str = exp_str.split("+")[0] + "Z"

        conn.execute(
            """\
            INSERT INTO sessions (
                session_id, type, initiator_username, receiver_username, status,
                objective, sender_agent_id, receiver_agent_id, turn_limit,
                runtime_budget_seconds, artifact_bytes_budget, cumulative_artifact_bytes,
                cost_budget_estimate, cumulative_cost_estimate,
                created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, 0, ?, 0.0, ?, ?, ?)
            """,
            (
                session_id,
                st.value,
                initiator_username,
                receiver_username,
                payload.get("goal", ""),
                actor_agent_id,  # Lock sender_agent_id immediately
                requested_agent_id if requested_agent_id else None,
                turn_limit,
                runtime_budget,
                artifact_budget,
                cost_budget,
                now_str,
                now_str,
                exp_str,
            ),
        )
        conn.commit()

        state = SessionState(
            session_id=session_id,
            initiator_username=initiator_username,
            receiver_username=receiver_username,
            status="draft",
            max_turns=turn_limit,
            participants={
                actor_username: ParticipantInfo(agent_id=actor_agent_id, role="owner")
            },
        )
    else:
        state = reconstruct_session_state(conn, vault_key, session_id)
        if not state:
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="rejected",
                received_at=now_str,
                verified_hash=env.content_hash,
                error_code="SESSION_STATE_LOAD_FAILED",
                error_message=f"Failed to reconstruct state for session '{session_id}'.",
            )

    # If state is in 'queued' or 'delivered' and incoming envelope is ACCEPTANCE, DECLINE, or CLARIFICATION, advance state to 'peer_review'
    if state.status in ("queued", "delivered") and env.kind in (MessageKind.ACCEPTANCE, MessageKind.DECLINE, MessageKind.CLARIFICATION):
        if state.status == "queued":
            del_res = process_node_command(state, "mark_delivered")
            if del_res.success:
                state = del_res.new_state
        pr_res = process_node_command(state, "mark_peer_review")
        if pr_res.success:
            state = pr_res.new_state

    # 4. Process through reducer
    red_res = process_peer_envelope(state, verified_env)
    if not red_res.success:
        return TransportAcknowledgement(
            schema_version="1.1",
            envelope_session_id=session_id,
            envelope_sequence=sequence,
            status="rejected",
            received_at=now_str,
            verified_hash=env.content_hash,
            error_code=red_res.error_code,
            error_message=red_res.error_message,
        )

    # Special handling for ACCEPTANCE envelope
    if env.kind == MessageKind.ACCEPTANCE:
        accepting_agent_id = env.payload.get("accepting_agent_id") or env.payload.get("receiver_agent_id") or env.actor_agent_id
        if accepting_agent_id:
            conn.execute(
                "UPDATE sessions SET receiver_agent_id = ? WHERE session_id = ?",
                (accepting_agent_id, session_id),
            )
            conn.commit()

    # 5. Append event to database
    app_res = append_session_event(
        conn,
        vault_key,
        session_id=session_id,
        actor_username=env.actor_username,
        actor_agent_id=env.actor_agent_id,
        kind=env.kind.value,
        visibility="peer_visible",
        payload=env.payload,
        signature=env.signature,
        sequence=env.sequence,
    )

    if app_res.get("status") == "rejected":
        return TransportAcknowledgement(
            schema_version="1.1",
            envelope_session_id=session_id,
            envelope_sequence=sequence,
            status="rejected",
            received_at=now_str,
            verified_hash=env.content_hash,
            error_code=app_res.get("error_code", "REJECTION_FAILED"),
            error_message="Session event append was rejected.",
        )

    cur.execute("SELECT username FROM identity LIMIT 1")
    my_id_row = cur.fetchone()
    my_username = my_id_row[0] if my_id_row else ""

    final_state = red_res.new_state
    if final_state.status == "sent" and env.actor_username != my_username:
        deliv_res = process_node_command(final_state, "mark_delivered")
        if deliv_res.success:
            final_state = deliv_res.new_state
            if env.kind == MessageKind.TASK_REQUEST:
                pr_res = process_node_command(final_state, "mark_peer_review")
                if pr_res.success:
                    final_state = pr_res.new_state

    if final_state.status == "accepted" and env.actor_username != my_username:
        act_res = process_node_command(final_state, "mark_active")
        if act_res.success:
            final_state = act_res.new_state

    # Update session status
    conn.execute(
        "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
        (final_state.status, now_str, session_id),
    )
    conn.commit()

    if env.kind == MessageKind.FINAL_RESULT:
        try:
            from kin.session.history import create_outcome_card

            final_payload = env.payload or {}
            outcome_summary = (
                final_payload.get("outcome")
                or final_payload.get("message")
                or final_payload.get("content")
                or "Session completed with a signed final result."
            )
            create_outcome_card(
                conn,
                vault_key,
                session_id=session_id,
                summary=str(outcome_summary),
            )
        except Exception as exc:
            write_audit_event(
                conn,
                vault_key,
                category="outcome_card_error",
                session_id=session_id,
                summary=f"Failed to derive local outcome card: {exc}",
                correlation_id=session_id,
            )

    # Kind-specific handling for ARTIFACT_OFFER on receiving side
    if env.kind == MessageKind.ARTIFACT_OFFER and env.actor_username != my_username:
        payload_dict = env.payload or {}
        try:
            meta_subset = {
                "schema_version": payload_dict.get("schema_version", "1.1"),
                "artifact_id": payload_dict.get("artifact_id"),
                "session_id": payload_dict.get("session_id"),
                "sha256": payload_dict.get("sha256"),
                "mime_type": payload_dict.get("mime_type"),
                "size_bytes": payload_dict.get("size_bytes"),
                "offered_by": payload_dict.get("offered_by"),
                "preview_policy": payload_dict.get("preview_policy"),
            }
            offer = ArtifactOffer.model_validate(meta_subset)
        except Exception as exc:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                actor_username=env.actor_username,
                actor_agent_id=env.actor_agent_id,
                summary=f"Invalid ARTIFACT_OFFER metadata payload: {exc}",
                session_id=session_id,
            )
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="delivered",
                received_at=now_str,
                verified_hash=env.content_hash,
            )

        # Receiver agent card boundary lookup (Directive 2)
        rec_ag_id = sess_row[3] if my_username == sess_row[1] else sess_row[2]
        receiver_max_bytes = 1_048_576
        if rec_ag_id:
            raw_card_dict = get_card(conn, rec_ag_id)
            if raw_card_dict and isinstance(raw_card_dict, dict):
                try:
                    local_json = raw_card_dict.get("local_card_json")
                    pub_json = raw_card_dict.get("published_card_json")
                    if local_json:
                        from kin.storage.vault import decrypt_field
                        card_json_str = decrypt_field(vault_key, local_json)
                        from kin.schemas import AgentCard
                        card = AgentCard.model_validate_json(card_json_str)
                    elif pub_json:
                        from kin.schemas import AgentCard
                        card = AgentCard.model_validate_json(pub_json)
                    else:
                        card = None
                    if card and card.boundaries and card.boundaries.max_artifact_bytes is not None:
                        receiver_max_bytes = card.boundaries.max_artifact_bytes
                except Exception:
                    pass

        # Early short-circuit size check (Directive 5)
        if offer.size_bytes > receiver_max_bytes:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                actor_username=env.actor_username,
                summary=f"Offered artifact size {offer.size_bytes} bytes exceeds receiving card max_artifact_bytes ({receiver_max_bytes}).",
                session_id=session_id,
            )
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="delivered",
                received_at=now_str,
                verified_hash=env.content_hash,
            )

        # Wire decryption & verification
        enc_b64 = payload_dict.get("encrypted_bytes_b64")
        if not enc_b64:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                actor_username=env.actor_username,
                summary="ARTIFACT_OFFER payload missing encrypted_bytes_b64 field.",
                session_id=session_id,
            )
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="delivered",
                received_at=now_str,
                verified_hash=env.content_hash,
            )

        try:
            wire_ciphertext = base64.b64decode(enc_b64)
            _, sender_x255_bytes, _ = _resolve_peer_contact_info(conn, env.actor_username)

            recip_x255_priv = recipient_x25519_privkey
            if not recip_x255_priv:
                try:
                    from kin.identity.storage import load_x25519_private_key
                    cur.execute("SELECT username FROM identity LIMIT 1")
                    id_row = cur.fetchone()
                    if id_row and id_row[0]:
                        recip_x255_priv = load_x25519_private_key(id_row[0])
                except Exception:
                    pass

            if not sender_x255_bytes or not recip_x255_priv:
                raise ValueError("Missing X25519 key for wire decryption.")

            decrypted_bytes = decrypt_from_sender(recip_x255_priv, sender_x255_bytes, wire_ciphertext)
        except Exception as exc:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                actor_username=env.actor_username,
                summary=f"ARTIFACT_OFFER wire decryption failed: {exc}",
                session_id=session_id,
            )
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="delivered",
                received_at=now_str,
                verified_hash=env.content_hash,
            )

        # SHA-256 Claim Verification against peer's claimed sha256
        computed_sha = hashlib.sha256(decrypted_bytes).hexdigest()
        if computed_sha != offer.sha256:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                actor_username=env.actor_username,
                summary=f"Claimed sha256 '{offer.sha256}' does not match computed payload hash '{computed_sha}'.",
                session_id=session_id,
            )
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="delivered",
                received_at=now_str,
                verified_hash=env.content_hash,
            )

        # Decrypted Size Check against receiver boundary
        if len(decrypted_bytes) > receiver_max_bytes:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                actor_username=env.actor_username,
                summary=f"Decrypted artifact size {len(decrypted_bytes)} bytes exceeds receiving card max_artifact_bytes ({receiver_max_bytes}).",
                session_id=session_id,
            )
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="delivered",
                received_at=now_str,
                verified_hash=env.content_hash,
            )

        # Persist to local vault under offer's artifact_id
        try:
            store_artifact(
                conn,
                vault_key,
                session_id=session_id,
                raw_bytes=decrypted_bytes,
                mime_type=offer.mime_type,
                offered_by=offer.offered_by,
                preview_policy=offer.preview_policy,
                max_bytes=receiver_max_bytes,
                source="peer_received",
                now=now_dt,
                artifact_id=offer.artifact_id,
            )
            increment_session_artifact_bytes(conn, session_id, len(decrypted_bytes))
        except (ArtifactTooLargeError, ArtifactIdConflictError) as err:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                actor_username=env.actor_username,
                summary=f"Vault storage of offered artifact rejected: {err}",
                session_id=session_id,
            )
            return TransportAcknowledgement(
                schema_version="1.1",
                envelope_session_id=session_id,
                envelope_sequence=sequence,
                status="delivered",
                received_at=now_str,
                verified_hash=env.content_hash,
            )

        # Send ARTIFACT_ACCEPT back to sender
        accept_payload = {
            "schema_version": "1.1",
            "artifact_id": offer.artifact_id,
            "session_id": session_id,
            "status": "accepted",
        }
        accept_hash = compute_content_hash(accept_payload)
        cur.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM session_events WHERE session_id = ? AND actor_username = ?",
            (session_id, my_username),
        )
        accept_seq = cur.fetchone()[0]

        accept_env_dict = {
            "schema_version": "1.1",
            "protocol_version": "1.1",
            "session_id": session_id,
            "sequence": accept_seq,
            "actor_username": my_username,
            "actor_agent_id": rec_ag_id or my_username,
            "timestamp": now_str,
            "kind": MessageKind.ARTIFACT_ACCEPT.value,
            "content_hash": accept_hash,
            "payload": accept_payload,
        }

        local_ed_priv = owner_identity_key
        if not local_ed_priv:
            try:
                from kin.identity.storage import load_private_key
                priv_bytes = load_private_key(my_username)
                local_ed_priv = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
            except Exception:
                pass

        if local_ed_priv:
            accept_env_dict["signature"] = sign_envelope(accept_env_dict, local_ed_priv)

            def get_accept_pubkey(un: str) -> ed25519.Ed25519PublicKey | None:
                if un == my_username:
                    return local_ed_priv.public_key()
                _, _, sender_ed = _resolve_peer_contact_info(conn, un)
                return sender_ed

            ingest_envelope(
                conn,
                vault_key,
                accept_env_dict,
                get_public_key_fn=get_accept_pubkey,
                now=now_dt,
                recipient_x25519_privkey=recip_x255_priv,
                owner_identity_key=local_ed_priv,
            )

            resolved_ep, sender_x255_bytes, _ = _resolve_peer_contact_info(conn, env.actor_username)
            delivered_accept = False
            cli = http_client or httpx.Client(timeout=10.0)
            if resolved_ep:
                try:
                    resp = cli.post(f"{resolved_ep.rstrip('/')}/v1.1/sessions", json=accept_env_dict)
                    if resp.status_code == 200:
                        delivered_accept = True
                except Exception:
                    pass
            if not delivered_accept and relay_url and sender_x255_bytes and recip_x255_priv:
                try:
                    raw_bytes = json.dumps(accept_env_dict, sort_keys=True).encode("utf-8")
                    enc_payload = encrypt_for_recipient(recip_x255_priv, sender_x255_bytes, raw_bytes)
                    _queue_relay_envelope(
                        cli,
                        relay_url,
                        env.actor_username,
                        my_username,
                        enc_payload,
                    )
                except Exception:
                    pass

    return TransportAcknowledgement(
        schema_version="1.1",
        envelope_session_id=session_id,
        envelope_sequence=sequence,
        status="delivered",
        received_at=now_str,
        verified_hash=env.content_hash,
    )


def dispatch_session(
    conn: sqlite3.Connection,
    vault_key: bytes,
    sender_identity_key: ed25519.Ed25519PrivateKey,
    sender_x25519_privkey: bytes,
    sender_username: str,
    peer_username: str,
    sender_agent_id: str,
    receiver_agent_id: str,
    collaboration_mode: str | SessionType,
    goal: str,
    peer_endpoint: str | None = None,
    relay_url: str | None = None,
    recipient_x25519_pubkey: bytes | None = None,
    max_turns: int | None = None,
    runtime_budget_seconds: int | None = None,
    artifact_bytes_budget: int | None = None,
    cost_budget_estimate: float | None = None,
    now: datetime.datetime | None = None,
    http_client: httpx.Client | None = None,
    context_pack: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Initiate a new V1.1 session, run capability check (Step 1), stale card check (Step 2), symmetric self-processing, and deliver."""
    mode_str = collaboration_mode.value if isinstance(collaboration_mode, SessionType) else str(collaboration_mode)
    try:
        session_type_enum = SessionType(mode_str)
    except ValueError:
        raise ValueError(
            f"Invalid collaboration_mode '{collaboration_mode}'. Must be one of {[t.value for t in SessionType]}."
        )

    eff_max_turns = max_turns if max_turns is not None else 12
    if not isinstance(eff_max_turns, int) or eff_max_turns < 1 or eff_max_turns > 12:
        raise ValueError(
            f"Invalid max_turns: {eff_max_turns}. max_turns must be an integer between 1 and 12."
        )

    if session_type_enum in (SessionType.BUILD_PIPELINE, SessionType.DELEGATE_SUBTASK):
        eff_runtime_budget = runtime_budget_seconds if runtime_budget_seconds is not None else DEFAULT_BUILD_RUNTIME_BUDGET
        eff_artifact_budget = artifact_bytes_budget if artifact_bytes_budget is not None else DEFAULT_BUILD_ARTIFACT_BYTES_BUDGET
        eff_cost_budget = cost_budget_estimate if cost_budget_estimate is not None else DEFAULT_BUILD_COST_BUDGET_ESTIMATE
    else:
        eff_runtime_budget = runtime_budget_seconds
        eff_artifact_budget = artifact_bytes_budget
        eff_cost_budget = cost_budget_estimate

    now_str = _iso_now(now)
    client = http_client or httpx.Client(timeout=10.0)

    # 1. Resolve contact endpoint / keys if None (Step 0)
    resolved_ep, resolved_x255, resolved_ed_pub = _resolve_peer_contact_info(conn, peer_username)
    endpoint = peer_endpoint or resolved_ep
    recip_x255 = recipient_x25519_pubkey or resolved_x255

    # 2. Step 1: Peer Capability Negotiation (GAP T, U, W)
    if endpoint:
        try:
            cap_resp = client.get(f"{endpoint.rstrip('/')}/v1.1/capabilities")
            if cap_resp.status_code == 200:
                cap_ad = CapabilityAdvertisement.model_validate(cap_resp.json())
                negotiation = negotiate_capability(cap_ad, required_features=["session_v1", "jcs_signatures"])
                if not negotiation.compatible:
                    raise CapabilityMismatchError(negotiation.reason)
                # Cache successful capability negotiation (GAP W)
                cache_peer_capabilities(conn, peer_username, cap_ad, now=now)
            else:
                raise CapabilityMismatchError(f"Peer capability endpoint returned status {cap_resp.status_code}.")
        except httpx.RequestError as e:
            # Direct fetch failed - check for a fresh cached capability advertisement (GAP W)
            cached_ad = get_cached_peer_capabilities(conn, peer_username, max_age_hours=72, now=now)
            if cached_ad:
                negotiation = negotiate_capability(cached_ad, required_features=["session_v1", "jcs_signatures"])
                if not negotiation.compatible:
                    raise CapabilityMismatchError(f"Cached capability mismatch: {negotiation.reason}")
            else:
                raise CapabilityMismatchError(
                    f"Failed to reach peer capabilities endpoint at {endpoint} and no fresh cached capabilities exist: {e}"
                )

    # 3. Step 2: Stale Peer Card Check (GAP T)
    if is_stale(conn, peer_username, receiver_agent_id):
        raise StalePeerCardError(
            f"Peer agent card for '{receiver_agent_id}' of user '{peer_username}' is stale and requires owner review prior to dispatch."
        )

    # 4. Construct envelope
    session_id = f"sess_{uuid.uuid4().hex[:16]}"
    payload = {
        "collaboration_mode": session_type_enum.value,
        "goal": goal,
        "requested_agent_id": receiver_agent_id,
        "peer_username": peer_username,
        "max_turns": eff_max_turns,
        "runtime_budget_seconds": eff_runtime_budget,
        "artifact_bytes_budget": eff_artifact_budget,
        "cost_budget_estimate": eff_cost_budget,
        "context_pack": context_pack or [],
    }
    content_hash = compute_content_hash(payload)

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": 1,
        "actor_username": sender_username,
        "actor_agent_id": sender_agent_id,
        "timestamp": now_str,
        "kind": MessageKind.TASK_REQUEST.value,
        "content_hash": content_hash,
        "payload": payload,
    }
    env_dict["signature"] = sign_envelope(env_dict, sender_identity_key)

    # 5. Symmetric self-processing pass
    def get_my_pubkey(un: str) -> ed25519.Ed25519PublicKey | None:
        if un == sender_username:
            return sender_identity_key.public_key()
        return resolved_ed_pub

    ack = ingest_envelope(conn, vault_key, env_dict, get_public_key_fn=get_my_pubkey, now=now)
    if ack.status == "rejected":
        raise TransportError(f"Self-processing of initial TASK_REQUEST rejected: {ack.error_message}")

    # 6. Attempt network transmission (Direct -> Relay -> Local Queue)
    delivered = False
    queued_at_relay = False

    if endpoint:
        try:
            resp = client.post(f"{endpoint.rstrip('/')}/v1.1/sessions", json=env_dict)
            if resp.status_code == 200:
                rec_ack = TransportAcknowledgement.model_validate(resp.json())
                if rec_ack.status == "delivered":
                    delivered = True
                    _apply_node_command_transition(conn, vault_key, session_id, "mark_delivered", now=now)
            elif isinstance(resp.status_code, int) and 400 <= resp.status_code < 500:
                _apply_node_command_transition(conn, vault_key, session_id, "mark_failed", now=now)
                return {"session_id": session_id, "status": "failed", "error": f"Peer rejected envelope: {resp.text}"}
        except httpx.RequestError:
            pass

    if not delivered and relay_url and recip_x255:
        try:
            raw_bytes = json.dumps(env_dict, sort_keys=True).encode("utf-8")
            enc_payload = encrypt_for_recipient(sender_x25519_privkey, recip_x255, raw_bytes)
            relay_resp = _queue_relay_envelope(
                client,
                relay_url,
                peer_username,
                sender_username,
                enc_payload,
            )
            if relay_resp.status_code == 200:
                queued_at_relay = True
                _apply_node_command_transition(conn, vault_key, session_id, "mark_queued", now=now)
        except httpx.RequestError:
            pass

    if not delivered and not queued_at_relay:
        # Local outbound queueing
        queue_id = str(uuid.uuid4())
        raw_json = json.dumps(env_dict, sort_keys=True)
        from kin.storage.vault import encrypt_field
        enc_envelope = encrypt_field(vault_key, raw_json)
        conn.execute(
            """\
            INSERT INTO outbound_envelope_queue (
                queue_id, session_id, sequence, recipient_username,
                envelope_kind, envelope_json_enc, delivery_state, attempt_count,
                next_retry_at, created_at, updated_at
            ) VALUES (?, ?, 1, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (queue_id, session_id, peer_username, MessageKind.TASK_REQUEST.value, enc_envelope, now_str, now_str, now_str),
        )
        conn.commit()

    return {"session_id": session_id, "status": "delivered" if delivered else ("queued" if queued_at_relay else "sent")}


def send_session_message(
    conn: sqlite3.Connection,
    vault_key: bytes,
    owner_identity_key: ed25519.Ed25519PrivateKey,
    owner_x25519_privkey: bytes,
    owner_username: str,
    session_id: str,
    kind: MessageKind,
    payload: dict[str, Any],
    actor_agent_id: str | None = None,
    peer_endpoint: str | None = None,
    relay_url: str | None = None,
    recipient_x25519_pubkey: bytes | None = None,
    now: datetime.datetime | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Construct, cryptographically sign, self-ingest, and deliver an envelope to a session peer (§14.8 Step 5/6)."""
    now_str = _iso_now(now)

    cur = conn.cursor()
    cur.execute("SELECT initiator_username, receiver_username FROM sessions WHERE session_id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        raise TransportError(f"Session '{session_id}' not found.")
    init_un, rec_un = row
    peer_username = rec_un if owner_username == init_un else init_un

    cur.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM session_events WHERE session_id = ? AND actor_username = ?", (session_id, owner_username))
    seq = cur.fetchone()[0]

    content_hash = compute_content_hash(payload)
    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": seq,
        "actor_username": owner_username,
        "actor_agent_id": actor_agent_id or owner_username,
        "timestamp": now_str,
        "kind": kind.value if isinstance(kind, MessageKind) else str(kind),
        "content_hash": content_hash,
        "payload": payload,
    }
    env_dict["signature"] = sign_envelope(env_dict, owner_identity_key)

    resolved_ep, resolved_x255, resolved_ed_pub = _resolve_peer_contact_info(conn, peer_username)
    def get_pubkey(un: str) -> ed25519.Ed25519PublicKey | None:
        if un == owner_username:
            return owner_identity_key.public_key()
        return resolved_ed_pub

    ack = ingest_envelope(conn, vault_key, env_dict, get_public_key_fn=get_pubkey, now=now)
    if ack.status == "rejected":
        raise TransportError(f"Self-processing of envelope rejected: {ack.error_message}")

    delivered = False
    queued_at_relay = False

    endpoint = peer_endpoint or resolved_ep
    recip_x255 = recipient_x25519_pubkey or resolved_x255
    client = http_client or httpx.Client(timeout=10.0)

    if endpoint:
        try:
            resp = client.post(f"{endpoint.rstrip('/')}/v1.1/sessions", json=env_dict)
            if resp.status_code == 200:
                delivered = True
        except httpx.RequestError:
            pass

    if not delivered and relay_url and recip_x255:
        try:
            raw_bytes = json.dumps(env_dict, sort_keys=True).encode("utf-8")
            enc_payload = encrypt_for_recipient(owner_x25519_privkey, recip_x255, raw_bytes)
            relay_resp = _queue_relay_envelope(
                client,
                relay_url,
                peer_username,
                owner_username,
                enc_payload,
            )
            if relay_resp.status_code == 200:
                queued_at_relay = True
        except httpx.RequestError:
            pass

    return {
        "session_id": session_id,
        "status": "delivered" if delivered else ("queued" if queued_at_relay else "failed"),
        "kind": kind.value if isinstance(kind, MessageKind) else str(kind),
        "delivered": delivered,
        "queued_at_relay": queued_at_relay,
    }


def respond_to_session(
    conn: sqlite3.Connection,
    vault_key: bytes,
    owner_identity_key: ed25519.Ed25519PrivateKey,
    owner_x25519_privkey: bytes,
    owner_username: str,
    session_id: str,
    decision: Literal["accept", "decline", "clarify"],
    accepting_agent_id: str | None = None,
    reason_or_question: str | None = None,
    peer_endpoint: str | None = None,
    relay_url: str | None = None,
    recipient_x25519_pubkey: bytes | None = None,
    now: datetime.datetime | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Respond to a session proposal (ACCEPTANCE, DECLINE, CLARIFICATION)."""
    if decision == "accept":
        if not accepting_agent_id:
            raise ValueError("accepting_agent_id is required when accepting a session.")
        ag = get_card(conn, accepting_agent_id)
        if not ag or not ag.get("enabled"):
            raise ValueError(f"Agent '{accepting_agent_id}' does not exist or is disabled.")
        if ag.get("availability") == AgentAvailability.POLICY_BLOCKED.value:
            raise ValueError(f"Agent '{accepting_agent_id}' is policy blocked.")

        kind = MessageKind.ACCEPTANCE
        payload = {"accepting_agent_id": accepting_agent_id, "reason": reason_or_question or "Accepted"}
    elif decision == "decline":
        kind = MessageKind.DECLINE
        payload = {"reason": reason_or_question or "Declined"}
    elif decision == "clarify":
        kind = MessageKind.CLARIFICATION
        payload = {"question": reason_or_question or "Clarification requested"}
    else:
        raise ValueError(f"Unknown decision '{decision}'.")

    res = send_session_message(
        conn=conn,
        vault_key=vault_key,
        owner_identity_key=owner_identity_key,
        owner_x25519_privkey=owner_x25519_privkey,
        owner_username=owner_username,
        session_id=session_id,
        kind=kind,
        payload=payload,
        actor_agent_id=accepting_agent_id or owner_username,
        peer_endpoint=peer_endpoint,
        relay_url=relay_url,
        recipient_x25519_pubkey=recipient_x25519_pubkey,
        now=now,
        http_client=http_client,
    )
    return {
        "session_id": session_id,
        "status": "queued" if res.get("queued_at_relay") else "processed",
        "kind": kind.value,
    }


def cancel_session(
    conn: sqlite3.Connection,
    vault_key: bytes,
    owner_identity_key: ed25519.Ed25519PrivateKey,
    owner_x25519_privkey: bytes,
    owner_username: str,
    session_id: str,
    reason: str = "User cancelled session",
    peer_endpoint: str | None = None,
    relay_url: str | None = None,
    recipient_x25519_pubkey: bytes | None = None,
    now: datetime.datetime | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Cancel an active or pending session."""
    now_str = _iso_now(now)
    cur = conn.cursor()
    cur.execute("SELECT initiator_username, receiver_username, sender_agent_id FROM sessions WHERE session_id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        raise TransportError(f"Session '{session_id}' not found.")
    init_un, rec_un, sender_ag_id = row
    peer_username = rec_un if owner_username == init_un else init_un

    cur.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM session_events WHERE session_id = ? AND actor_username = ?", (session_id, owner_username))
    seq = cur.fetchone()[0]

    payload = {"reason": reason}
    content_hash = compute_content_hash(payload)
    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": seq,
        "actor_username": owner_username,
        "actor_agent_id": sender_ag_id or owner_username,
        "timestamp": now_str,
        "kind": MessageKind.CANCEL.value,
        "content_hash": content_hash,
        "payload": payload,
    }
    env_dict["signature"] = sign_envelope(env_dict, owner_identity_key)

    resolved_ep, resolved_x255, resolved_ed_pub = _resolve_peer_contact_info(conn, peer_username)
    def get_pubkey(un: str) -> ed25519.Ed25519PublicKey | None:
        if un == owner_username:
            return owner_identity_key.public_key()
        return resolved_ed_pub

    ack = ingest_envelope(conn, vault_key, env_dict, get_public_key_fn=get_pubkey, now=now)
    if ack.status == "rejected":
        raise TransportError(f"Self-processing of CANCEL envelope rejected: {ack.error_message}")

    return {"session_id": session_id, "status": "cancelled"}


def increment_session_artifact_bytes(conn: sqlite3.Connection, session_id: str, byte_count: int) -> None:
    """Increment cumulative_artifact_bytes in the sessions table for the specified session."""
    if byte_count <= 0:
        return
    conn.execute(
        "UPDATE sessions SET cumulative_artifact_bytes = cumulative_artifact_bytes + ? WHERE session_id = ?",
        (byte_count, session_id),
    )
    conn.commit()


def pause_session(
    conn: sqlite3.Connection,
    vault_key: bytes,
    owner_identity_key: ed25519.Ed25519PrivateKey,
    owner_x25519_privkey: bytes | None = None,
    owner_username: str = "",
    session_id: str = "",
    reason: str = "Owner paused participation",
    peer_endpoint: str | None = None,
    relay_url: str | None = None,
    recipient_x25519_pubkey: bytes | None = None,
    now: datetime.datetime | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Pause local participation and transmit a STATUS_EVENT to peer."""
    now_str = _iso_now(now)
    state = reconstruct_session_state(conn, vault_key, session_id)
    if not state:
        raise TransportError(f"Session '{session_id}' not found.")

    red_res = process_owner_command(state, owner_username, "owner_pause")
    if not red_res.success:
        raise TransportError(f"Owner pause failed: {red_res.error_message}")

    conn.execute("UPDATE sessions SET status = 'paused', updated_at = ? WHERE session_id = ?", (now_str, session_id))
    write_audit_event(
        conn,
        vault_key,
        category="session_status_updated",
        session_id=session_id,
        summary="Session status updated to 'paused' via owner_pause command",
        payload={"previous_status": state.status, "new_status": "paused", "command": "owner_pause"},
        correlation_id=session_id,
    )
    conn.commit()

    payload = {"status_event": "owner_paused", "reason": reason}
    content_hash = compute_content_hash(payload)
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM session_events WHERE session_id = ? AND actor_username = ?", (session_id, owner_username))
    seq = cur.fetchone()[0]

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": seq,
        "actor_username": owner_username,
        "actor_agent_id": state.participants.get(owner_username, ParticipantInfo(agent_id=owner_username, role="owner")).agent_id,
        "timestamp": now_str,
        "kind": MessageKind.STATUS_EVENT.value,
        "content_hash": content_hash,
        "payload": payload,
    }
    env_dict["signature"] = sign_envelope(env_dict, owner_identity_key)

    peer_username = state.receiver_username if owner_username == state.initiator_username else state.initiator_username
    resolved_ep, resolved_x255, resolved_ed_pub = _resolve_peer_contact_info(conn, peer_username)
    def get_pubkey(un: str) -> ed25519.Ed25519PublicKey | None:
        if un == owner_username:
            return owner_identity_key.public_key()
        return resolved_ed_pub

    ingest_envelope(conn, vault_key, env_dict, get_public_key_fn=get_pubkey, now=now)
    return {"session_id": session_id, "status": "paused"}


def resume_session(
    conn: sqlite3.Connection,
    vault_key: bytes,
    owner_identity_key: ed25519.Ed25519PrivateKey,
    owner_x25519_privkey: bytes,
    owner_username: str,
    session_id: str,
    reason: str = "Owner resumed participation",
    peer_endpoint: str | None = None,
    relay_url: str | None = None,
    recipient_x25519_pubkey: bytes | None = None,
    now: datetime.datetime | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Resume local participation and transmit a STATUS_EVENT to peer."""
    now_str = _iso_now(now)
    state = reconstruct_session_state(conn, vault_key, session_id)
    if not state:
        raise TransportError(f"Session '{session_id}' not found.")

    red_res = process_owner_command(state, owner_username, "owner_resume")
    if not red_res.success:
        raise TransportError(f"Owner resume failed: {red_res.error_message}")

    conn.execute("UPDATE sessions SET status = 'active', updated_at = ? WHERE session_id = ?", (now_str, session_id))
    write_audit_event(
        conn,
        vault_key,
        category="session_status_updated",
        session_id=session_id,
        summary="Session status updated to 'active' via owner_resume command",
        payload={"previous_status": state.status, "new_status": "active", "command": "owner_resume"},
        correlation_id=session_id,
    )
    conn.commit()

    payload = {"status_event": "owner_resumed", "reason": reason}
    content_hash = compute_content_hash(payload)
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM session_events WHERE session_id = ? AND actor_username = ?", (session_id, owner_username))
    seq = cur.fetchone()[0]

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": seq,
        "actor_username": owner_username,
        "actor_agent_id": state.participants.get(owner_username, ParticipantInfo(agent_id=owner_username, role="owner")).agent_id,
        "timestamp": now_str,
        "kind": MessageKind.STATUS_EVENT.value,
        "content_hash": content_hash,
        "payload": payload,
    }
    env_dict["signature"] = sign_envelope(env_dict, owner_identity_key)

    peer_username = state.receiver_username if owner_username == state.initiator_username else state.initiator_username
    resolved_ep, resolved_x255, resolved_ed_pub = _resolve_peer_contact_info(conn, peer_username)
    def get_pubkey(un: str) -> ed25519.Ed25519PublicKey | None:
        if un == owner_username:
            return owner_identity_key.public_key()
        return resolved_ed_pub

    ingest_envelope(conn, vault_key, env_dict, get_public_key_fn=get_pubkey, now=now)
    return {"session_id": session_id, "status": "active"}


def retry_outbound_queue(
    conn: sqlite3.Connection,
    vault_key: bytes,
    now: datetime.datetime | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, int]:
    """Sweep and retry pending outbound queue items using exponential backoff aligned with session expires_at."""
    now_str = _iso_now(now)
    now_dt = datetime.datetime.fromisoformat(now_str.rstrip("Z")).replace(tzinfo=datetime.timezone.utc)
    client = http_client or httpx.Client(timeout=10.0)

    cur = conn.cursor()
    cur.execute(
        """\
        SELECT queue_id, q.session_id, q.sequence, q.recipient_username,
               envelope_json_enc, attempt_count, s.expires_at
        FROM outbound_envelope_queue q
        JOIN sessions s ON q.session_id = s.session_id
        WHERE delivery_state = 'pending' AND next_retry_at <= ?
        """,
        (now_str,),
    )
    rows = cur.fetchall()

    delivered_count = 0
    failed_count = 0

    from kin.storage.vault import decrypt_field

    for queue_id, session_id, seq, recipient_un, enc_json, attempts, exp_str in rows:
        # GAP L & S: Check if session has reached terminal status
        cur.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,))
        sess_status_row = cur.fetchone()
        if sess_status_row and sess_status_row[0] in TERMINAL_STATES:
            conn.execute("UPDATE outbound_envelope_queue SET delivery_state = 'abandoned', updated_at = ? WHERE queue_id = ?", (now_str, queue_id))
            conn.commit()
            continue

        # Check session expiry using reducer transition helper (GAP S)
        if exp_str:
            exp_dt = datetime.datetime.fromisoformat(exp_str.rstrip("Z")).replace(tzinfo=datetime.timezone.utc)
            if now_dt >= exp_dt:
                conn.execute("UPDATE outbound_envelope_queue SET delivery_state = 'expired', updated_at = ? WHERE queue_id = ?", (now_str, queue_id))
                _apply_node_command_transition(conn, vault_key, session_id, "mark_expired", now=now)
                continue

        dec_json = decrypt_field(vault_key, enc_json)
        env_dict = json.loads(dec_json)

        endpoint, recip_x255, recip_ed = _resolve_peer_contact_info(conn, recipient_un)

        delivered = False
        if endpoint:
            try:
                resp = client.post(f"{endpoint.rstrip('/')}/v1.1/sessions", json=env_dict)
                if resp.status_code == 200:
                    delivered = True
                    conn.execute("UPDATE outbound_envelope_queue SET delivery_state = 'delivered', updated_at = ? WHERE queue_id = ?", (now_str, queue_id))
                    _apply_node_command_transition(conn, vault_key, session_id, "mark_delivered", now=now)
                    delivered_count += 1
                elif isinstance(resp.status_code, int) and 400 <= resp.status_code < 500:
                    conn.execute("UPDATE outbound_envelope_queue SET delivery_state = 'failed', last_error = ?, updated_at = ? WHERE queue_id = ?", (resp.text, now_str, queue_id))
                    _apply_node_command_transition(conn, vault_key, session_id, "mark_failed", now=now)
                    failed_count += 1
                    continue
            except httpx.RequestError as e:
                conn.execute("UPDATE outbound_envelope_queue SET last_error = ?, updated_at = ? WHERE queue_id = ?", (str(e), now_str, queue_id))

        if not delivered:
            new_attempts = attempts + 1
            # Corrected backoff formula for 10s initial delay (new_attempts=1 -> 10 * 2^0 = 10s)
            backoff_sec = min(3600, 10 * (2 ** (new_attempts - 1)))
            next_retry = (now_dt + datetime.timedelta(seconds=backoff_sec)).isoformat()
            if not next_retry.endswith("Z"):
                next_retry = next_retry.split("+")[0] + "Z"

            conn.execute(
                """\
                UPDATE outbound_envelope_queue
                SET attempt_count = ?, next_retry_at = ?, updated_at = ?
                WHERE queue_id = ?
                """,
                (new_attempts, next_retry, now_str, queue_id),
            )
            conn.commit()

    return {"delivered": delivered_count, "failed": failed_count}


def poll_relay_and_process(
    conn: sqlite3.Connection,
    vault_key: bytes,
    my_username: str,
    my_private_key: ed25519.Ed25519PrivateKey,
    my_x25519_privkey: bytes,
    relay_url: str,
    get_public_key_fn: Callable[[str], ed25519.Ed25519PublicKey | None],
    now: datetime.datetime | None = None,
    http_client: httpx.Client | None = None,
) -> int:
    """Fetch relay inbox, decrypt, ingest envelopes, and ACK only after successful processing."""
    client = http_client or httpx.Client(timeout=10.0)
    auth_headers = _relay_auth_headers(my_username, my_private_key, now=now)

    resp = client.get(f"{relay_url.rstrip('/')}/relay/inbox", headers=auth_headers)
    if resp.status_code != 200:
        return 0

    messages = resp.json().get("messages", [])
    processed_count = 0

    for msg in messages:
        msg_id = msg.get("message_id")
        sender_un = msg.get("sender_username")
        payload_hex = msg.get("encrypted_blob", "")

        try:
            cipher_bytes = bytes.fromhex(payload_hex)
            sender_ep, sender_x255, sender_ed = _resolve_peer_contact_info(conn, sender_un)
            if not sender_x255:
                continue

            dec_bytes = decrypt_from_sender(my_x25519_privkey, sender_x255, cipher_bytes)
            env_dict = json.loads(dec_bytes.decode("utf-8"))

            ack = ingest_envelope(conn, vault_key, env_dict, get_public_key_fn=get_public_key_fn, now=now)
            # GAP V: check_sequence_conflict resolves duplicate sequence numbers to status="delivered" upstream
            if ack.status in ("delivered", "queued"):
                # Send ACK to relay after successful ingestion
                ack_body = json.dumps({"message_ids": [msg_id]}, separators=(",", ":"))
                ack_headers = _relay_auth_headers(
                    my_username,
                    my_private_key,
                    now=now,
                    acknowledgement_body=ack_body,
                )
                ack_response = client.post(
                    f"{relay_url.rstrip('/')}/relay/inbox/ack",
                    content=ack_body,
                    headers={"Content-Type": "application/json", **ack_headers},
                )
                if ack_response.status_code == 200:
                    processed_count += 1
        except Exception as e:
            write_audit_event(
                conn,
                vault_key,
                category="relay_poll_error",
                summary=f"Failed to process relay message {msg_id}: {e}",
            )

    return processed_count


def sync_peer_cards(
    conn: sqlite3.Connection,
    my_username: str,
    my_private_key: ed25519.Ed25519PrivateKey,
    peer_username: str,
    peer_endpoint: str,
    http_client: httpx.Client | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Fetch peer agent cards from endpoint or fall back to cached cards with provenance disclosure."""
    client = http_client or httpx.Client(timeout=10.0)
    auth_headers = create_signed_auth_headers(my_username, my_private_key, now=now)

    try:
        resp = client.get(f"{peer_endpoint.rstrip('/')}/v1.1/agents/cards", headers=auth_headers)
        if resp.status_code == 200:
            data = resp.json()
            cards = data.get("cards", [])
            for c in cards:
                card_obj = PublishedAgentCard.model_validate(c) if isinstance(c, dict) else c
                cache_peer_card(conn, peer_username, card_obj)
            return {"source": "network", "cards": cards}
    except httpx.RequestError:
        pass

    # Fallback to local cached peer cards
    cur = conn.cursor()
    cur.execute("SELECT card_json FROM peer_agent_cards WHERE peer_username = ?", (peer_username,))
    cached = [json.loads(r[0]) for r in cur.fetchall()]
    return {"source": "cache_fallback", "cards": cached}


def send_artifact_offer(
    conn: sqlite3.Connection,
    vault_key: bytes,
    owner_identity_key: ed25519.Ed25519PrivateKey,
    owner_x25519_privkey: bytes,
    owner_username: str,
    session_id: str,
    artifact_id: str,
    peer_endpoint: str | None = None,
    relay_url: str | None = None,
    recipient_x25519_pubkey: bytes | None = None,
    now: datetime.datetime | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Construct, sign, self-ingest, and transmit an ARTIFACT_OFFER envelope to peer (direct HTTP with relay fallback)."""
    now_str = _iso_now(now)
    client = http_client or httpx.Client(timeout=10.0)

    # 1. Verify session exists
    state = reconstruct_session_state(conn, vault_key, session_id)
    if not state:
        raise TransportError(f"Session '{session_id}' not found.")

    peer_username = state.receiver_username if owner_username == state.initiator_username else state.initiator_username

    # 2. Retrieve metadata (raises ArtifactNotFoundError if artifact_id missing)
    meta = get_artifact_metadata(conn, artifact_id)

    # 3. Validate artifact session ownership (Directive 4)
    if meta.session_id != session_id:
        raise ValueError(f"Artifact '{artifact_id}' belongs to session '{meta.session_id}', not '{session_id}'.")

    # 4. Load raw bytes
    raw_bytes = load_artifact_bytes(conn, vault_key, artifact_id)

    # 5. Resolve contact endpoint / keys if None
    resolved_ep, resolved_x255, resolved_ed_pub = _resolve_peer_contact_info(conn, peer_username)
    endpoint = peer_endpoint or resolved_ep
    recip_x255 = recipient_x25519_pubkey or resolved_x255

    if not recip_x255:
        raise TransportError(f"Recipient X25519 public key not found for peer '{peer_username}'.")

    # 6. Perform X25519 ECDH + ChaCha20Poly1305 wire encryption
    wire_ciphertext = encrypt_for_recipient(owner_x25519_privkey, recip_x255, raw_bytes)
    enc_b64 = base64.b64encode(wire_ciphertext).decode("ascii")

    # 7. Construct payload dictionary
    payload = {
        "schema_version": "1.1",
        "artifact_id": meta.artifact_id,
        "session_id": session_id,
        "sha256": meta.sha256,
        "mime_type": meta.mime_type,
        "size_bytes": meta.size_bytes,
        "offered_by": owner_username,
        "preview_policy": meta.preview_policy,
        "encrypted_bytes_b64": enc_b64,
    }

    content_hash = compute_content_hash(payload)
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM session_events WHERE session_id = ? AND actor_username = ?",
        (session_id, owner_username),
    )
    seq = cur.fetchone()[0]

    actor_ag_id = state.participants.get(owner_username, ParticipantInfo(agent_id=owner_username, role="owner")).agent_id

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": seq,
        "actor_username": owner_username,
        "actor_agent_id": actor_ag_id,
        "timestamp": now_str,
        "kind": MessageKind.ARTIFACT_OFFER.value,
        "content_hash": content_hash,
        "payload": payload,
    }
    env_dict["signature"] = sign_envelope(env_dict, owner_identity_key)

    # 8. Symmetric self-processing pass
    def get_pubkey(un: str) -> ed25519.Ed25519PublicKey | None:
        if un == owner_username:
            return owner_identity_key.public_key()
        return resolved_ed_pub

    ack = ingest_envelope(
        conn,
        vault_key,
        env_dict,
        get_public_key_fn=get_pubkey,
        now=now,
        recipient_x25519_privkey=owner_x25519_privkey,
        owner_identity_key=owner_identity_key,
        relay_url=relay_url,
        http_client=client,
    )
    if ack.status == "rejected":
        raise TransportError(f"Self-processing of ARTIFACT_OFFER envelope rejected: {ack.error_message}")

    # 9. Attempt network delivery (Direct -> Relay -> Local Queue)
    delivered = False
    queued_at_relay = False

    if endpoint:
        try:
            resp = client.post(f"{endpoint.rstrip('/')}/v1.1/sessions", json=env_dict)
            if resp.status_code == 200:
                rec_ack = TransportAcknowledgement.model_validate(resp.json())
                if rec_ack.status == "delivered":
                    delivered = True
        except httpx.RequestError:
            pass

    if not delivered and relay_url and recip_x255:
        try:
            raw_env_bytes = json.dumps(env_dict, sort_keys=True).encode("utf-8")
            enc_payload = encrypt_for_recipient(owner_x25519_privkey, recip_x255, raw_env_bytes)
            relay_resp = _queue_relay_envelope(
                client,
                relay_url,
                peer_username,
                owner_username,
                enc_payload,
            )
            if relay_resp.status_code == 200:
                queued_at_relay = True
        except httpx.RequestError:
            pass

    delivery_status = "direct" if delivered else ("relay" if queued_at_relay else "local-only")
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "status": "offered",
        "delivery": delivery_status,
    }
