"""Real routes per system-design-v1.md section 4.1 and 4.4."""

from __future__ import annotations

import sqlite3
import json
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, Header, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
import litellm
import openai
import httpx

from kin.node.models import CreateTaskRequest, SendMessageRequest
from kin.storage.db import get_connection, get_setting
from kin.identity.keys import encrypt_for_recipient, sign_message, verify_signature
from kin.identity.storage import SecretNotFoundError, load_private_key, load_x25519_private_key
from kin.agent_backend.base import AgentBackendRequest
from kin.agent_backend.llm_backend import LLMAgentBackend

router = APIRouter()

PROTOCOL_VERSION = "0.1.0"

# FR11: hard round limit on negotiation exchanges
MAX_TASK_MESSAGES = 10


async def auto_relay_information_response(
    conn: sqlite3.Connection,
    profile_name: str,
    task_id: str,
    contact_username: str,
    endpoint: str,
    contact_x25519_public_key: str | None,
    content: str,
) -> str | None:
    """Deliver a narrow factual answer under ``auto_relay_info`` policy.

    This is deliberately stricter than the policy name: only a backend-produced
    ``answer`` to an incoming ``question`` may move without human review. Proposals,
    counter-proposals, confirmations, and every finalization always remain drafts.
    Returns the new local task status, or ``None`` when review should remain required.
    """
    identity = conn.execute("SELECT username FROM identity LIMIT 1").fetchone()
    task = conn.execute("SELECT origin_ref_id, peer_task_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if identity is None or task is None:
        return None
    own_username = identity[0]
    origin_ref_id, peer_task_id = task
    target_task_id = peer_task_id or task_id
    payload = {"from_username": own_username, "content": content, "message_type": "answer"}
    if origin_ref_id:
        payload["origin_ref_id"] = origin_ref_id
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    try:
        signature = sign_message(load_private_key(profile_name), payload_bytes).hex()
    except Exception:
        return None

    now = datetime.now(timezone.utc).isoformat()
    status: str | None = None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{endpoint.rstrip('/')}/tasks/{target_task_id}/messages",
                content=payload_bytes,
                headers={"Content-Type": "application/json", "X-Signature": signature},
            )
            response.raise_for_status()
            status = response.json()["status"]
    except httpx.RequestError:
        if not contact_x25519_public_key:
            return None
        try:
            envelope = {
                "type": "send_message",
                "task_id": target_task_id,
                "payload_bytes": payload_bytes.hex(),
                "signature": signature,
            }
            encrypted = encrypt_for_recipient(
                load_x25519_private_key(profile_name),
                bytes.fromhex(contact_x25519_public_key),
                json.dumps(envelope, separators=(",", ":")).encode("utf-8"),
            )
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{os.environ.get('KIN_RELAY_URL', 'http://localhost:8000').rstrip('/')}/relay/mailbox/{contact_username}",
                    json={"sender_username": own_username, "encrypted_blob": encrypted.hex()},
                )
                response.raise_for_status()
            status = "queued-relay"
        except (ValueError, SecretNotFoundError, httpx.HTTPError):
            return None
    except (KeyError, ValueError, httpx.HTTPError):
        return None

    conn.execute(
        "INSERT INTO messages (message_id, task_id, from_username, content, message_type, created_at, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), task_id, own_username, content, "answer", now, signature),
    )
    conn.execute(
        "UPDATE tasks SET status = ?, draft_content = NULL, draft_message_type = NULL, updated_at = ? WHERE task_id = ?",
        (status, now, task_id),
    )
    conn.commit()
    return status


def get_db(request: Request):
    """Dependency that yields a database connection based on app config."""
    default_db = Path.home() / ".kin" / "profiles" / "default" / "kin.db"
    db_path = getattr(request.app.state, "db_path", default_db)
    # Ensure parent directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Section 4.1 — Agent Card (discovery)
# ---------------------------------------------------------------------------

@router.get("/.well-known/agent-card.json")
async def get_agent_card(conn: sqlite3.Connection = Depends(get_db)) -> JSONResponse:
    """Expose the public capability document used during first contact."""
    row = conn.execute("SELECT username, public_key, protocol_version FROM identity LIMIT 1").fetchone()
    if row is None:
        return JSONResponse(status_code=404, content={"detail": "KIN identity is not initialized."})
    username, public_key, protocol_version = row
    return JSONResponse(
        status_code=200,
        content={
            "name": username,
            "username": username,
            "public_key": public_key,
            "endpoint": get_setting(conn, "public_endpoint", "http://127.0.0.1:8321"),
            "capabilities": ["info_request", "negotiation"],
            "protocol_version": protocol_version or PROTOCOL_VERSION,
        },
    )


# ---------------------------------------------------------------------------
# Section 4.4 — Create a task
# ---------------------------------------------------------------------------

async def process_create_task(
    body: CreateTaskRequest,
    raw_body: bytes,
    x_signature: str | None,
    conn: sqlite3.Connection,
    profile_name: str,
    local_ref_id: str | None = None,
) -> tuple[int, dict]:
    """Shared helper to process task creation from direct HTTP or CLI fetch."""
    if not x_signature:
        return 401, {"detail": "Missing X-Signature header"}

    # Decode signature hex
    try:
        sig_bytes = bytes.fromhex(x_signature)
    except ValueError:
        return 401, {"detail": "Invalid signature hex format"}

    # Look up the requester contact in database
    cursor = conn.cursor()
    cursor.execute(
        "SELECT public_key, fingerprint_verified_at, autonomy_level, endpoint, x25519_public_key FROM contacts WHERE username = ?",
        (body.requester_username,),
    )
    row = cursor.fetchone()
    if row is None or row[1] is None:
        return 403, {"detail": f"Requester '{body.requester_username}' is not a verified contact."}

    contact_pubkey_hex, _, autonomy_level, contact_endpoint, contact_x25519_public_key = row
    contact_pubkey_bytes = bytes.fromhex(contact_pubkey_hex)

    # Verify signature over raw body bytes
    if not verify_signature(contact_pubkey_bytes, raw_body, sig_bytes):
        return 401, {"detail": "Invalid signature"}

    task_id = str(uuid.uuid4())
    now_str = datetime.now(timezone.utc).isoformat()
    context_str = json.dumps(body.context)

    # Resolve default/first agent name if agents are configured
    from kin.agent_roster.loader import load_agent_roster, AgentLoadingError
    selected_agent_name = None
    try:
        roster = load_agent_roster(profile_name)
        if roster:
            if len(roster) == 1:
                selected_agent_name = next(iter(roster.keys()))
            else:
                selected_agent_name = sorted(roster.keys())[0]
    except AgentLoadingError:
        pass

    context_str = json.dumps(body.context) if body.context else "{}"

    peer_agent_name = body.context.get("peer_agent_name") if body.context else None

    # Save initial task to DB (status="submitted") and the initial goal message in one transaction
    cursor.execute(
        """
        INSERT INTO tasks (task_id, contact_username, goal, context_json, status, created_at, updated_at, result_json, draft_content, draft_message_type, agent_name, peer_agent_name, origin_ref_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, body.requester_username, body.goal, context_str, "submitted", now_str, now_str, None, None, None, selected_agent_name, peer_agent_name, local_ref_id),
    )

    # Derive initial message type from context if provided, otherwise default to "question"
    init_msg_type = body.context.get("message_type", "question") if body.context else "question"
    init_msg_id = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO messages (message_id, task_id, from_username, content, message_type, created_at, signature)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (init_msg_id, task_id, body.requester_username, body.goal, init_msg_type, now_str, x_signature),
    )
    conn.commit()

    # Trigger LLM auto-draft generation asynchronously (avoiding event loop block)
    from kin.agent_backend.factory import get_agent_backend
    backend = get_agent_backend(profile_name, selected_agent_name)
    conversation_history = [f"{body.requester_username} ({init_msg_type}): {body.goal}"]
    agent_req = AgentBackendRequest(
        task_goal=body.goal,
        context=body.context,
        conversation_history=conversation_history
    )

    try:
        agent_res = await backend.generate_response_async(agent_req)
        # Update task with successful draft
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, draft_content = ?, draft_message_type = ?, updated_at = ?
            WHERE task_id = ?
            """,
            ("input-required", agent_res.reply, agent_res.message_type, now_str, task_id)
        )
        conn.commit()
        final_status = "input-required"
        if autonomy_level == "auto_relay_info" and init_msg_type == "question" and agent_res.message_type == "answer":
            auto_status = await auto_relay_information_response(
                conn,
                profile_name,
                task_id,
                body.requester_username,
                contact_endpoint,
                contact_x25519_public_key,
                agent_res.reply,
            )
            if auto_status is not None:
                final_status = auto_status
    except (SecretNotFoundError, json.JSONDecodeError, ValidationError, openai.OpenAIError) as e:
        # Wrap failure details inside result_json and mark task status as failed
        err_payload = {
            "error": "backend error",
            "detail": str(e)
        }
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, result_json = ?, updated_at = ?
            WHERE task_id = ?
            """,
            ("failed", json.dumps(err_payload), now_str, task_id)
        )
        conn.commit()
        final_status = "failed"
    except Exception as e:
        # Safety-net catch-all for unexpected/unhandled exceptions to avoid leaving task stuck
        err_payload = {
            "error": f"unhandled exception: {type(e).__name__}",
            "detail": str(e)
        }
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, result_json = ?, updated_at = ?
            WHERE task_id = ?
            """,
            ("failed", json.dumps(err_payload), now_str, task_id)
        )
        conn.commit()
        final_status = "failed"

    return 200, {"task_id": task_id, "status": final_status}


async def process_send_message(
    task_id: str,
    body: SendMessageRequest,
    raw_body: bytes,
    x_signature: str | None,
    conn: sqlite3.Connection,
    profile_name: str,
) -> tuple[int, dict]:
    """Shared helper to process message delivery inside a task from direct HTTP or CLI fetch."""
    # Look up the task (try task_id or peer_task_id first)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status, goal, context_json, agent_name, task_id, contact_username FROM tasks WHERE task_id = ? OR peer_task_id = ?",
        (task_id, task_id),
    )
    row = cursor.fetchone()
    if row is None and body.origin_ref_id:
        # Retry lookup matching task_id = body.origin_ref_id (the local-queued- row)
        cursor.execute(
            "SELECT status, goal, context_json, agent_name, task_id, contact_username FROM tasks WHERE task_id = ?",
            (body.origin_ref_id,),
        )
        row = cursor.fetchone()
        if row is not None:
            # Reconciliation: Record peer_task_id = path task_id on the local-queued- row
            # HARD CONSTRAINT: Primary key task_id is NEVER mutated!
            cursor.execute(
                "UPDATE tasks SET peer_task_id = ? WHERE task_id = ?",
                (task_id, body.origin_ref_id),
            )
            conn.commit()

    if row is None:
        return 404, {"detail": f"Task with ID '{task_id}' not found."}

    task_status, task_goal, context_json, agent_name, target_task_id, contact_username = row
    task_id = target_task_id  # Use local primary key for message storage and status updates

    # Reject if the task is already closed (completed or failed)
    if task_status in ("completed", "failed"):
        return 409, {"detail": f"Task with ID '{task_id}' is closed (status: {task_status})."}

    if not x_signature:
        return 401, {"detail": "Missing X-Signature header"}

    # Decode signature hex
    try:
        sig_bytes = bytes.fromhex(x_signature)
    except ValueError:
        return 401, {"detail": "Invalid signature hex format"}

    # Verify sender contact exists and is verified
    cursor.execute(
        "SELECT public_key, fingerprint_verified_at FROM contacts WHERE username = ?",
        (body.from_username,),
    )
    contact_row = cursor.fetchone()
    if contact_row is None or contact_row[1] is None:
        return 403, {"detail": f"Sender '{body.from_username}' is not a verified contact."}

    contact_pubkey_hex, _ = contact_row
    contact_pubkey_bytes = bytes.fromhex(contact_pubkey_hex)

    # Verify signature over raw body bytes
    if not verify_signature(contact_pubkey_bytes, raw_body, sig_bytes):
        return 401, {"detail": "Invalid signature"}

    now_str = datetime.now(timezone.utc).isoformat()

    # Count existing rows in the messages table for this task_id.
    cursor.execute("SELECT COUNT(*) FROM messages WHERE task_id = ?", (task_id,))
    msg_count = cursor.fetchone()[0]

    # Note: Round-limit check fires BEFORE any message_type branching or tool_name allowlist checks.
    if msg_count >= MAX_TASK_MESSAGES:
        # Round limit reached: update task status to failed and store the reason
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, result_json = ?, updated_at = ?
            WHERE task_id = ?
            """,
            ("failed", json.dumps({"reason": "round_limit_reached", "round_count": msg_count}), now_str, task_id)
        )
        conn.commit()
        return 200, {"status": "failed"}

    # Insert the new message
    new_msg_id = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO messages (message_id, task_id, from_username, content, message_type, created_at, signature)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (new_msg_id, task_id, body.from_username, body.content, body.message_type, now_str, x_signature),
    )

    # Handle protocol message branching
    if body.message_type == "finalize_accept":
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, draft_content = NULL, draft_message_type = NULL, result_json = ?, updated_at = ?
            WHERE task_id = ?
            """,
            ("completed", json.dumps({"outcome": body.content, "finalized_by": body.from_username}), now_str, task_id)
        )
        conn.commit()
        return 200, {"status": "completed"}

    elif body.message_type == "finalize_proposal":
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, draft_content = ?, draft_message_type = ?, updated_at = ?
            WHERE task_id = ?
            """,
            ("input-required", body.content, "finalize_proposal", now_str, task_id)
        )
        conn.commit()
        return 200, {"status": "input-required"}

    # Update status to working during LLM generation for ordinary message types
    cursor.execute(
        "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
        ("working", now_str, task_id)
    )
    conn.commit()

    # Retrieve full conversation history for LLM prompt context
    cursor.execute(
        "SELECT from_username, message_type, content FROM messages WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,),
    )
    history_rows = cursor.fetchall()
    conversation_history = [
        f"{r[0]} ({r[1]}): {r[2]}" for r in history_rows
    ]

    task_context = json.loads(context_json) if context_json else {}

    # Trigger LLM auto-draft generation asynchronously
    from kin.agent_backend.factory import get_agent_backend
    backend = get_agent_backend(profile_name, agent_name)
    agent_req = AgentBackendRequest(
        task_goal=task_goal,
        context=task_context,
        conversation_history=conversation_history
    )

    try:
        agent_res = await backend.generate_response_async(agent_req)
        # Save successful draft
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, draft_content = ?, draft_message_type = ?, updated_at = ?
            WHERE task_id = ?
            """,
            ("input-required", agent_res.reply, agent_res.message_type, now_str, task_id)
        )
        conn.commit()
        final_status = "input-required"
        contact_policy = conn.execute(
            "SELECT autonomy_level, endpoint, x25519_public_key FROM contacts WHERE username = ?",
            (contact_username,),
        ).fetchone()
        if (
            body.message_type == "question"
            and agent_res.message_type == "answer"
            and contact_policy is not None
            and contact_policy[0] == "auto_relay_info"
        ):
            auto_status = await auto_relay_information_response(
                conn,
                profile_name,
                task_id,
                contact_username,
                contact_policy[1],
                contact_policy[2],
                agent_res.reply,
            )
            if auto_status is not None:
                final_status = auto_status
    except (SecretNotFoundError, json.JSONDecodeError, ValidationError, openai.OpenAIError) as e:
        # Save backend error
        err_payload = {
            "error": "backend error",
            "detail": str(e)
        }
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, result_json = ?, updated_at = ?
            WHERE task_id = ?
            """,
            ("failed", json.dumps(err_payload), now_str, task_id)
        )
        conn.commit()
        final_status = "failed"
    except Exception as e:
        # Safety-net catch-all for unexpected/unhandled exceptions to avoid leaving task stuck
        err_payload = {
            "error": f"unhandled exception: {type(e).__name__}",
            "detail": str(e)
        }
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, result_json = ?, updated_at = ?
            WHERE task_id = ?
            """,
            ("failed", json.dumps(err_payload), now_str, task_id)
        )
        conn.commit()
        final_status = "failed"

    return 200, {"status": final_status}


@router.post("/tasks")
async def create_task(
    request: Request,
    body: CreateTaskRequest,
    x_signature: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    """Create a task requested by another KIN node."""
    raw_body = await request.body()
    profile_name = getattr(request.app.state, "profile_name", "default")
    status_code, content = await process_create_task(body, raw_body, x_signature, conn, profile_name)
    return JSONResponse(status_code=status_code, content=content)


@router.post("/tasks/{task_id}/messages")
async def send_message(
    request: Request,
    task_id: str,
    body: SendMessageRequest,
    x_signature: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    """Send a message within an existing task."""
    raw_body = await request.body()
    profile_name = getattr(request.app.state, "profile_name", "default")
    status_code, content = await process_send_message(task_id, body, raw_body, x_signature, conn, profile_name)
    return JSONResponse(status_code=status_code, content=content)


# ---------------------------------------------------------------------------
# Section 4.4 — Check task status
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    """Retrieve task status, draft, and history from local storage."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status, result_json, draft_content, draft_message_type, task_id FROM tasks WHERE task_id = ? OR peer_task_id = ?",
        (task_id, task_id),
    )
    row = cursor.fetchone()
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Task with ID '{task_id}' not found."},
        )

    status, result_json, draft_content, draft_message_type, internal_task_id = row
    result = json.loads(result_json) if result_json else None

    draft = None
    if draft_content and draft_message_type:
        draft = {
            "content": draft_content,
            "message_type": draft_message_type,
        }

    # Fetch messages/history in ascending chronological order
    cursor.execute(
        "SELECT from_username, content, message_type, created_at FROM messages WHERE task_id = ? ORDER BY created_at ASC",
        (internal_task_id,),
    )
    msg_rows = cursor.fetchall()
    history = [
        {
            "from_username": r[0],
            "content": r[1],
            "message_type": r[2],
            "created_at": r[3]
        }
        for r in msg_rows
    ]

    return JSONResponse(
        status_code=200,
        content={
            "status": status,
            "history": history,
            "result": result,
            "draft": draft,
        },
    )


# ---------------------------------------------------------------------------
# V1.1 Transport Routes (Milestone M3)
# ---------------------------------------------------------------------------

@router.get("/v1.1/capabilities")
async def get_v11_capabilities() -> JSONResponse:
    from kin.schemas import CapabilityAdvertisement
    ad = CapabilityAdvertisement(
        protocol_version="1.1",
        supported_features=["session_v1", "jcs_signatures", "vault_gcm", "direct_transport", "relay_fallback"],
        max_turn_limit=12,
    )
    return JSONResponse(status_code=200, content=ad.model_dump(mode="json"))


@router.get("/v1.1/agents/cards")
async def get_published_agent_cards(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    from kin.identity.auth import verify_signed_auth_headers
    from kin.agent_registry.registry import list_cards

    def get_contact_pubkey(un: str) -> ed25519.Ed25519PublicKey | None:
        cur = conn.cursor()
        cur.execute("SELECT public_key, fingerprint_verified_at FROM contacts WHERE username = ?", (un,))
        row = cur.fetchone()
        if row and row[0] and row[1]:
            return ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(row[0]))
        return None

    ok, auth_username, err_msg = verify_signed_auth_headers(dict(request.headers), get_contact_pubkey)
    if not ok:
        return JSONResponse(status_code=403, content={"detail": err_msg or "Unauthorized agent card request"})

    cur = conn.cursor()
    cur.execute("SELECT username FROM identity LIMIT 1")
    owner_row = cur.fetchone()
    owner_username = owner_row[0] if owner_row else "unknown"

    cards = list_cards(conn, include_disabled=False)
    pub_cards = []
    for c in cards:
        if c.get("published_card_json"):
            pub_cards.append(json.loads(c["published_card_json"]))

    return JSONResponse(status_code=200, content={"schema_version": "1.1", "owner_username": owner_username, "cards": pub_cards})


@router.post("/v1.1/sessions")
async def process_v11_session_envelope(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    from kin.transport.v11 import ingest_envelope
    from kin.storage.vault import get_or_create_vault_key

    raw_body = await request.json()
    profile_name = getattr(request.app.state, "profile_name", "default")

    try:
        vault_key = get_or_create_vault_key(profile_name)
    except Exception:
        vault_key = b"0" * 32

    def get_contact_pubkey(un: str) -> ed25519.Ed25519PublicKey | None:
        cur = conn.cursor()
        cur.execute("SELECT public_key FROM identity WHERE username = ?", (un,))
        row = cur.fetchone()
        if row and row[0]:
            return ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(row[0]))
        cur.execute("SELECT public_key, fingerprint_verified_at FROM contacts WHERE username = ?", (un,))
        row = cur.fetchone()
        if row and row[0] and row[1]:
            return ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(row[0]))
        return None

    ack = ingest_envelope(conn, vault_key, raw_body, get_contact_pubkey)

    if ack.status == "rejected":
        code = ack.error_code
        status_code = 400
        if code in ("INVALID_SIGNATURE", "PUBLIC_KEY_NOT_FOUND"):
            status_code = 401
        elif code in ("UNPAIRED_SENDER", "UNAUTHORIZED_ACTOR", "UNAUTHORIZED_AGENT", "UNAUTHORIZED_ROLE_ACTION"):
            status_code = 403
        elif code in ("DUPLICATE_SEQUENCE", "OUT_OF_ORDER_SEQUENCE", "INVALID_STATE_TRANSITION", "TERMINAL_STATE_IMMUTABLE"):
            status_code = 409

        return JSONResponse(status_code=status_code, content=ack.model_dump(mode="json"))

    return JSONResponse(status_code=200, content=ack.model_dump(mode="json"))

