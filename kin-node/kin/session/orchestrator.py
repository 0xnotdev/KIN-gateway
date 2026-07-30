"""Session Orchestrator module per §15.7, §2.3, §2.4."""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.adapters import (
    AdapterActivityEvent,
    AdapterApprovalEvent,
    AdapterRequest,
    AdapterResponse,
    InputItem,
    get_adapter,
    validate_adapter_output,
)
from kin.artifacts.preview import ARCHIVE_MIME_TYPES
from kin.artifacts.vault import ArtifactTooLargeError, load_artifact_bytes, store_artifact
from kin.agent_registry.registry import get_card
from kin.audit.writer import append_session_event, write_audit_event
from kin.policy.evaluator import PolicyResult
from kin.policy.persistence import create_pending_approval, evaluate_action_for_session
from kin.schemas import (
    AgentCard,
    InternalEventKind,
    MessageKind,
    compute_content_hash,
    sign_envelope,
)
from kin.session.reducer import (
    TERMINAL_STATES,
    SessionState,
    process_node_command,
    reconstruct_session_state,
)
from kin.storage.vault import decrypt_field, encrypt_field
from kin.transport.v11 import (
    _apply_node_command_transition,
    _iso_now,
    increment_session_artifact_bytes,
    ingest_envelope,
)


class OrchestratorError(Exception):
    """Base exception for session orchestrator failures."""

    def __init__(self, message: str, code: str = "ORCHESTRATOR_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message


def _execute_node_command(conn: sqlite3.Connection, state: SessionState, command: str) -> Any:
    res = process_node_command(state, command)
    if res.success:
        now_str = _iso_now()
        conn.execute("UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?", (res.new_state.status, now_str, state.session_id))
        conn.commit()
    return res


def _safe_decode_artifact_text(raw_bytes: bytes, mime_type: str | None) -> str | None:
    """Safe UTF-8 text decoding helper reusing Phase 3 preview binary/archive rules."""
    mime = (mime_type or "").strip().lower()
    if mime in ARCHIVE_MIME_TYPES:
        return None
    try:
        text = raw_bytes.decode("utf-8")
        if "\x00" in text:
            return None
        return text
    except UnicodeDecodeError:
        return None


def advance_session_turn(
    conn: sqlite3.Connection,
    vault_key: bytes,
    owner_identity_key: ed25519.Ed25519PrivateKey,
    owner_username: str,
    session_id: str,
    *,
    now: datetime.datetime | None = None,
    get_public_key_fn: Callable[[str], ed25519.Ed25519PublicKey] | None = None,
) -> dict[str, Any]:
    """Advance one turn for the local owner's participating agent (§15.7 build step 4)."""
    now_str = _iso_now(now)

    # 1. Reconstruct state; refuse cleanly if terminal, awaiting approval, or paused
    state = reconstruct_session_state(conn, vault_key, session_id)
    if not state:
        raise OrchestratorError(f"Session '{session_id}' not found.", code="SESSION_NOT_FOUND")

    if state.status in TERMINAL_STATES:
        raise OrchestratorError(f"Cannot advance turn: session is in terminal state '{state.status}'.", code="TERMINAL_STATE")
    if state.status == "awaiting_owner_approval":
        raise OrchestratorError("Cannot advance turn: session is awaiting human owner approval.", code="AWAITING_OWNER_APPROVAL")
    if state.status == "paused":
        raise OrchestratorError("Cannot advance turn: session is paused.", code="SESSION_PAUSED")

    # 2. Determine local agent_id and load AgentCard
    participant_info = state.participants.get(owner_username)
    if not participant_info:
        raise OrchestratorError(f"Owner '{owner_username}' is not a participant in session '{session_id}'.", code="UNAUTHORIZED_PARTICIPANT")

    local_agent_id = participant_info.agent_id
    raw_card_dict = get_card(conn, local_agent_id)
    if not raw_card_dict:
        raise OrchestratorError(f"Agent card for '{local_agent_id}' not found in registry.", code="AGENT_CARD_NOT_FOUND")

    if raw_card_dict.get("local_card_json"):
        card_json_str = decrypt_field(vault_key, raw_card_dict["local_card_json"])
        card = AgentCard.model_validate_json(card_json_str)
    elif raw_card_dict.get("published_card_json"):
        card = AgentCard.model_validate_json(raw_card_dict["published_card_json"])
    else:
        pub_card = raw_card_dict.get("published_card") or raw_card_dict
        card = AgentCard.model_validate(pub_card)

    # 3. Read objective, session_type, and budget fields from sessions table
    cur = conn.cursor()
    cur.execute(
        """\
        SELECT objective, initiator_username, receiver_username, type,
               turn_limit, created_at, runtime_budget_seconds,
               artifact_bytes_budget, cumulative_artifact_bytes,
               cost_budget_estimate, cumulative_cost_estimate
        FROM sessions WHERE session_id = ?
        """,
        (session_id,),
    )
    s_row = cur.fetchone()
    if not s_row:
        raise OrchestratorError(f"Session '{session_id}' not found.", code="SESSION_NOT_FOUND")

    (
        objective_text,
        init_un,
        rec_un,
        sess_type_raw,
        turn_limit,
        created_at_str,
        runtime_budget_seconds,
        artifact_bytes_budget,
        cumulative_artifact_bytes,
        cost_budget_estimate,
        cumulative_cost_estimate,
    ) = s_row

    objective_text = objective_text or ""
    session_type = sess_type_raw or (state.type if hasattr(state, "type") else "ask")
    peer_un = rec_un if owner_username == init_un else init_un
    peer_participant = state.participants.get(peer_un)
    peer_agent_id = peer_participant.agent_id if peer_participant else ""

    # 3.5. AGGREGATE BUDGET EXHAUSTION CHECK BEFORE ADAPTER INVOCATION (§15.8 M5 Phase 6)
    now_dt = now or datetime.datetime.now(datetime.timezone.utc)
    exhausted_dimension: str | None = None
    exhausted_reason: str | None = None

    elapsed_seconds: float | None = None
    if created_at_str:
        created_dt = datetime.datetime.fromisoformat(created_at_str.rstrip("Z")).replace(tzinfo=datetime.timezone.utc)
        elapsed_seconds = (now_dt - created_dt).total_seconds()

    if turn_limit is not None and state.current_turn >= turn_limit:
        exhausted_dimension = "turn_limit"
        exhausted_reason = f"Session budget exhausted: turn_limit ({turn_limit}) reached."
    elif runtime_budget_seconds is not None and elapsed_seconds is not None and elapsed_seconds >= runtime_budget_seconds:
        exhausted_dimension = "runtime_budget_seconds"
        exhausted_reason = f"Session budget exhausted: runtime_budget_seconds ({runtime_budget_seconds}s) reached."
    elif artifact_bytes_budget is not None and cumulative_artifact_bytes >= artifact_bytes_budget:
        exhausted_dimension = "artifact_bytes_budget"
        exhausted_reason = f"Session budget exhausted: artifact_bytes_budget ({artifact_bytes_budget} bytes) reached."
    elif cost_budget_estimate is not None and cumulative_cost_estimate >= cost_budget_estimate:
        exhausted_dimension = "cost_budget_estimate"
        exhausted_reason = f"Session budget exhausted: cost_budget_estimate ({cost_budget_estimate}) reached."

    if exhausted_dimension and exhausted_reason:
        from kin.transport.v11 import pause_session
        pause_session(
            conn,
            vault_key,
            owner_identity_key,
            None,
            owner_username,
            session_id,
            reason=exhausted_reason,
            now=now_dt,
        )
        write_audit_event(
            conn,
            vault_key,
            category="budget_exhausted",
            session_id=session_id,
            actor_username=owner_username,
            summary=exhausted_reason,
            payload={"exhausted_dimension": exhausted_dimension},
        )
        return {
            "status": "paused",
            "reason": exhausted_reason,
            "exhausted_dimension": exhausted_dimension,
        }

    # Build history items from decrypted session events
    history_items = []
    for ev in state.events:
        history_items.append({
            "kind": ev.get("kind", "message"),
            "actor": ev.get("actor_username", ""),
            "content": str(ev.get("payload", {})),
        })

    # Build inputs list: query all stored artifacts belonging to this session
    cur.execute(
        "SELECT artifact_id, mime_type FROM artifacts WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,),
    )
    art_rows = cur.fetchall()
    input_items: list[InputItem] = []

    for art_id, mime_type in art_rows:
        try:
            raw_bytes = load_artifact_bytes(conn, vault_key, art_id)
            decoded_text = _safe_decode_artifact_text(raw_bytes, mime_type)
            input_items.append(
                InputItem(
                    kind="artifact",
                    ref=art_id,
                    content=decoded_text,
                )
            )
        except Exception:
            input_items.append(
                InputItem(
                    kind="artifact",
                    ref=art_id,
                    content=None,
                )
            )

    # Construct AdapterRequest
    local_policy = {
        "filesystem": card.boundaries.filesystem if card.boundaries else "none",
        "network": card.boundaries.network_access if card.boundaries else "none",
        "shell": card.boundaries.shell if card.boundaries else "none",
    }

    adapter_req = AdapterRequest(
        schema_version="1.1",
        protocol_version="1.1",
        session={"id": session_id, "type": session_type, "turn": state.current_turn},
        self_participant={"agent_id": local_agent_id, "card_snapshot": card.model_dump(mode="json")},
        peer={"person": peer_un, "agent_id": peer_agent_id, "card_snapshot": {}},
        objective=objective_text,
        inputs=input_items,
        history=history_items,
        local_policy=local_policy,
    )

    # 4. Call adapter via factory.
    # Cost estimate approximation: incremented by 1.0 per LLM adapter call (estimated adapter call count, not real USD cost).
    conn.execute(
        "UPDATE sessions SET cumulative_cost_estimate = cumulative_cost_estimate + 1.0 WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()

    adapter = get_adapter(card)
    response: AdapterResponse = adapter.invoke(adapter_req, vault_key=vault_key)

    # Handle transient vs hard adapter errors
    if response.error:
        write_audit_event(
            conn,
            vault_key,
            category="adapter_error",
            session_id=session_id,
            actor_username=owner_username,
            summary=f"Adapter error code {response.error.code}: {response.error.message}",
            payload={"code": response.error.code, "message": response.error.message},
        )
        if response.error.code in ("ADAPTER_TIMEOUT", "RATE_LIMITED", "PROCESS_TIMEOUT_KILLED"):
            # Transient error
            return {"status": "retryable_error", "error": response.error.model_dump(mode="json")}
        else:
            # Hard error -> mark session failed
            _apply_node_command_transition(conn, vault_key, session_id, "mark_failed", now=now)
            return {"status": "failed", "error": response.error.model_dump(mode="json")}

    # 5. Run validate_adapter_output
    val_res = validate_adapter_output(response, card, conn, vault_key, session_id)
    if not val_res.valid:
        _apply_node_command_transition(conn, vault_key, session_id, "mark_failed", now=now)
        raise OrchestratorError(f"Adapter output rejected by security validator: {val_res.rejection_reason}", code="SECURITY_REJECTION")

    # 6. Process Activity events (local-only observability)
    for ev in response.events:
        kind_val = getattr(ev, "event_kind", None)
        if kind_val == "activity" or isinstance(ev, AdapterActivityEvent):
            label_val = getattr(ev, "label", str(ev))
            append_session_event(
                conn,
                vault_key,
                session_id=session_id,
                actor_username=owner_username,
                actor_agent_id=local_agent_id,
                kind=InternalEventKind.ACTIVITY.value,
                visibility="local_only",
                payload={"label": label_val},
            )

    # 7. Process Approval Requests & Outbound Policy Check
    from kin.policy.evaluator import PolicyDecision
    for ev in response.events:
        kind_val = getattr(ev, "event_kind", None)
        if kind_val == "approval_request" or isinstance(ev, AdapterApprovalEvent):
            app_req = getattr(ev, "approval_request", None)
            if not app_req:
                continue
            pol_res: PolicyResult = evaluate_action_for_session(
                conn, card, app_req.action_class, {"session_id": session_id}, session_id, now_str
            )
            if pol_res.decision == PolicyDecision.DENY:
                write_audit_event(
                    conn,
                    vault_key,
                    category="security_rejection",
                    session_id=session_id,
                    actor_username=owner_username,
                    summary=f"Action '{app_req.action_class.value}' denied by local policy.",
                    payload={"action_class": app_req.action_class.value},
                )
                continue
            elif pol_res.decision == PolicyDecision.REQUIRES_APPROVAL:
                exp_at = app_req.expires_at or _iso_now((now or datetime.datetime.now(datetime.timezone.utc)) + datetime.timedelta(seconds=86400))
                create_pending_approval(
                    conn, vault_key, app_req, agent_id=local_agent_id, action_class=app_req.action_class, expires_at=exp_at
                )
                _apply_node_command_transition(conn, vault_key, session_id, "mark_awaiting_owner_approval", now=now)
                return {"status": "awaiting_owner_approval", "approval_id": app_req.approval_id}

    if response.message:
        from kin.schemas import ActionClass, ApprovalRequest, RiskLabel
        msg_action_class = ActionClass.INFORMATIONAL_RELAY
        pol_msg_res: PolicyResult = evaluate_action_for_session(
            conn, card, msg_action_class, {"session_id": session_id, "kind": response.message.kind.value}, session_id, now_str
        )
        if pol_msg_res.decision == PolicyDecision.DENY:
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                session_id=session_id,
                actor_username=owner_username,
                summary=f"Outbound message '{response.message.kind.value}' denied by policy.",
                payload={"kind": response.message.kind.value},
            )
            _apply_node_command_transition(conn, vault_key, session_id, "mark_failed", now=now)
            return {"status": "failed", "reason": "Outbound message policy denial"}
        elif pol_msg_res.decision == PolicyDecision.REQUIRES_APPROVAL:
            req_id = f"app_{uuid.uuid4().hex[:12]}"
            exp_at = _iso_now((now or datetime.datetime.now(datetime.timezone.utc)) + datetime.timedelta(seconds=86400))
            app_req = ApprovalRequest(
                schema_version="1.1",
                approval_id=req_id,
                session_id=session_id,
                agent_id=local_agent_id,
                action_class=msg_action_class,
                summary=f"Approve outbound message {response.message.kind.value}",
                reason="Outbound message requires owner approval",
                risk_label=RiskLabel.MEDIUM,
                requested_scope={"content": response.message.content[:100]},
                expires_at=exp_at,
            )
            create_pending_approval(conn, vault_key, app_req, agent_id=local_agent_id, action_class=msg_action_class, expires_at=exp_at)
            _apply_node_command_transition(conn, vault_key, session_id, "mark_awaiting_owner_approval", now=now)
            return {"status": "awaiting_owner_approval", "approval_id": req_id}

    # 8. Process Artifacts (only after all approval gating clears)
    for art in response.artifacts:
        raw_bytes = art.path_or_bytes if isinstance(art.path_or_bytes, bytes) else art.path_or_bytes.encode("utf-8")
        max_bytes = card.boundaries.max_artifact_bytes or 1_048_576
        try:
            store_artifact(
                conn,
                vault_key,
                session_id=session_id,
                raw_bytes=raw_bytes,
                mime_type=art.mime_type,
                offered_by=owner_username,
                preview_policy="auto",
                max_bytes=max_bytes,
                now=now,
            )
            increment_session_artifact_bytes(conn, session_id, len(raw_bytes))
        except ArtifactTooLargeError:
            msg = f"Artifact size {len(raw_bytes)} bytes exceeds card max_artifact_bytes ({max_bytes})."
            write_audit_event(
                conn,
                vault_key,
                category="security_rejection",
                session_id=session_id,
                actor_username=owner_username,
                summary=msg,
                payload={"artifact_size": len(raw_bytes), "max_bytes": max_bytes},
            )
            _apply_node_command_transition(conn, vault_key, session_id, "mark_failed", now=now)
            raise OrchestratorError(msg, code="ARTIFACT_TOO_LARGE")

    # 9. Process Outbound Message if present (only after all approval gating clears)
    if response.message:
        msg = response.message
        cur.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM session_events WHERE session_id = ? AND actor_username = ?", (session_id, owner_username))
        seq = cur.fetchone()[0]

        payload_dict = {"content": msg.content}

        env_dict = {
            "schema_version": "1.1",
            "protocol_version": "1.1",
            "session_id": session_id,
            "sequence": seq,
            "actor_username": owner_username,
            "actor_agent_id": local_agent_id,
            "timestamp": now_str,
            "kind": msg.kind.value,
            "content_hash": compute_content_hash(payload_dict),
            "payload": payload_dict,
        }
        env_dict["signature"] = sign_envelope(env_dict, owner_identity_key)

        def default_get_pubkey(un: str) -> ed25519.Ed25519PublicKey:
            return owner_identity_key.public_key()

        pubkey_fn = get_public_key_fn or default_get_pubkey
        ing_ack = ingest_envelope(conn, vault_key, env_dict, get_public_key_fn=pubkey_fn, now=now)

        # Queue outbound envelope for peer delivery
        env_enc = encrypt_field(vault_key, json.dumps(env_dict))
        queue_id = f"q_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """\
            INSERT INTO outbound_envelope_queue (
                queue_id, session_id, sequence, recipient_username, envelope_kind,
                envelope_json_enc, delivery_state, attempt_count, next_retry_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (queue_id, session_id, seq, peer_un, msg.kind.value, env_enc, now_str, now_str, now_str),
        )
        conn.commit()

        return {"status": ing_ack.status, "sequence": seq, "kind": msg.kind.value}

    return {"status": "advanced"}


def send_status_nudge(
    conn: sqlite3.Connection,
    vault_key: bytes,
    owner_username: str,
    session_id: str,
    message_text: str = "Status check nudge",
    *,
    now: datetime.datetime | None = None,
    rate_limit_seconds: int = 60,
) -> dict[str, Any]:
    """Send a rate-limited status_event nudge per §2.4 (1 nudge per 60 seconds per session per owner)."""
    now_dt = now or datetime.datetime.now(datetime.timezone.utc)

    cur = conn.cursor()
    cur.execute(
        """\
        SELECT created_at FROM session_events
        WHERE session_id = ? AND actor_username = ? AND kind = 'status_event'
        ORDER BY created_at DESC LIMIT 1
        """,
        (session_id, owner_username),
    )
    row = cur.fetchone()
    if row and row[0]:
        try:
            last_dt = datetime.datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            elapsed = (now_dt - last_dt).total_seconds()
            if elapsed < rate_limit_seconds:
                raise OrchestratorError(
                    f"Nudge rate limit exceeded. Please wait {int(rate_limit_seconds - elapsed)} seconds before nudging again.",
                    code="RATE_LIMIT_EXCEEDED",
                )
        except Exception as e:
            if isinstance(e, OrchestratorError):
                raise

    res = append_session_event(
        conn,
        vault_key,
        session_id=session_id,
        actor_username=owner_username,
        actor_agent_id="",
        kind=MessageKind.STATUS_EVENT.value,
        visibility="peer_visible",
        payload={"nudge_message": message_text},
    )
    return {"status": "nudged", "event_id": res.get("event_id")}


def tag_in_handoff(
    conn: sqlite3.Connection,
    vault_key: bytes,
    owner_identity_key: ed25519.Ed25519PrivateKey,
    owner_username: str,
    session_id: str,
    replacement_agent_id: str,
    *,
    now: datetime.datetime | None = None,
    get_public_key_fn: Callable[[str], ed25519.Ed25519PublicKey] | None = None,
) -> dict[str, Any]:
    """Perform a participant tag-in handoff (§2.4)."""
    now_str = _iso_now(now)

    # 1. Verify replacement agent exists and is enabled
    ag = get_card(conn, replacement_agent_id)
    if not ag or not ag.get("enabled"):
        raise OrchestratorError(f"Replacement agent '{replacement_agent_id}' does not exist or is disabled.", code="INVALID_REPLACEMENT_AGENT")

    # 2. Reconstruct session state and build bounded handoff package
    state = reconstruct_session_state(conn, vault_key, session_id)
    if not state:
        raise OrchestratorError(f"Session '{session_id}' not found.", code="SESSION_NOT_FOUND")

    cur = conn.cursor()
    cur.execute("SELECT objective FROM sessions WHERE session_id = ?", (session_id,))
    s_row = cur.fetchone()
    objective_text = s_row[0] if s_row and s_row[0] else ""

    history_summary = []
    open_questions = []
    for ev in state.events:
        ev_kind = ev.get("kind", "")
        if ev_kind not in ("activity", "status_event"):
            payload_data = ev.get("payload", {})
            content_str = payload_data.get("content") if isinstance(payload_data, dict) else str(payload_data)
            history_summary.append({
                "actor": ev.get("actor_username", ""),
                "kind": ev_kind,
                "content": content_str or "",
            })
            if ev_kind == MessageKind.QUESTION.value:
                open_questions.append(content_str)

    handoff_package = {
        "objective": objective_text,
        "open_questions": open_questions,
        "replacement_agent_id": replacement_agent_id,
        "recent_history_summary": history_summary,
    }

    # 3. Update session table with new agent ID
    role = "sender" if owner_username == state.initiator_username else "receiver"
    col_name = "sender_agent_id" if role == "sender" else "receiver_agent_id"

    conn.execute(f"UPDATE sessions SET {col_name} = ? WHERE session_id = ?", (replacement_agent_id, session_id))
    conn.commit()

    # 4. Emit signed PARTICIPANT_CHANGED envelope
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM session_events WHERE session_id = ? AND actor_username = ?", (session_id, owner_username))
    seq = cur.fetchone()[0]

    env_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": session_id,
        "sequence": seq,
        "actor_username": owner_username,
        "actor_agent_id": replacement_agent_id,
        "timestamp": now_str,
        "kind": MessageKind.PARTICIPANT_CHANGED.value,
        "content_hash": compute_content_hash(handoff_package),
        "payload": handoff_package,
    }
    env_dict["signature"] = sign_envelope(env_dict, owner_identity_key)

    def default_get_pubkey(un: str) -> ed25519.Ed25519PublicKey:
        return owner_identity_key.public_key()

    pubkey_fn = get_public_key_fn or default_get_pubkey
    ing_ack = ingest_envelope(conn, vault_key, env_dict, get_public_key_fn=pubkey_fn, now=now)

    return {"status": ing_ack.status, "replacement_agent_id": replacement_agent_id, "sequence": seq}
