"""FastAPI route implementations for the kin-relay service."""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from kin_relay.db import get_connection
from kin_relay.models import (
    InboxMessage,
    InboxAckRequest,
    InboxResponse,
    LookupResponse,
    MailboxDeliverRequest,
    RegisterRequest,
)

router = APIRouter()


def get_db(request: Request):
    """Dependency that yields a database connection based on app config."""
    db_path = getattr(request.app.state, "db_path", "relay.db")
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


@router.post("/directory/register")
async def register_endpoint(
    body: RegisterRequest, conn: sqlite3.Connection = Depends(get_db)
) -> JSONResponse:
    """Register or update a username's endpoint and public key.

    Enforces that usernames are permanent and cannot be reassigned to a
    different public key.
    """
    cursor = conn.cursor()
    # Check if username is already registered
    cursor.execute(
        "SELECT public_key FROM directory_entries WHERE username = ?",
        (body.username,),
    )
    row = cursor.fetchone()

    if row is not None:
        existing_pubkey = row[0]
        if existing_pubkey != body.public_key:
            raise HTTPException(
                status_code=409,
                detail="Username is already registered to a different key.",
            )
        # Idempotent update of endpoint and x25519_public_key for same public key
        cursor.execute(
            "UPDATE directory_entries SET endpoint = ?, x25519_public_key = ? WHERE username = ?",
            (body.endpoint, body.x25519_public_key, body.username),
        )
    else:
        # First-time registration
        cursor.execute(
            "INSERT INTO directory_entries (username, public_key, x25519_public_key, endpoint) VALUES (?, ?, ?, ?)",
            (body.username, body.public_key, body.x25519_public_key, body.endpoint),
        )

    conn.commit()
    return JSONResponse(status_code=200, content={"status": "registered"})


@router.get("/directory/lookup/{username}", response_model=LookupResponse)
async def lookup_endpoint(
    username: str, conn: sqlite3.Connection = Depends(get_db)
) -> LookupResponse:
    """Look up a registered username's public key and endpoint."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT public_key, x25519_public_key, endpoint FROM directory_entries WHERE username = ?",
        (username,),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Username '{username}' not found in directory.",
        )
    return LookupResponse(public_key=row[0], x25519_public_key=row[1], endpoint=row[2])


@router.post("/relay/mailbox/{username}")
async def deliver_to_mailbox(
    username: str,
    body: MailboxDeliverRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    """Deliver an encrypted message blob to the target username's mailbox.

    Fails if the target username does not exist in the directory.
    """
    cursor = conn.cursor()
    # Ensure target recipient is registered
    cursor.execute(
        "SELECT 1 FROM directory_entries WHERE username = ?",
        (username,),
    )
    if cursor.fetchone() is None:
        raise HTTPException(
            status_code=404,
            detail=f"Recipient username '{username}' is not registered.",
        )

    # Compute expires_at (7 days from now)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=7)).isoformat()
    received_at = now.isoformat()

    cursor.execute(
        "INSERT INTO mailbox (username, sender_username, encrypted_blob, received_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (username, body.sender_username, body.encrypted_blob, received_at, expires_at),
    )
    conn.commit()

    return JSONResponse(status_code=200, content={"status": "queued"})


# Named constant for replay prevention window (5 minutes)
REPLAY_WINDOW_MINUTES = 5


def _authenticate_inbox_request(
    x_username: str | None,
    x_signature: str | None,
    x_timestamp: str | None,
    conn: sqlite3.Connection,
    signed_message: bytes | None = None,
) -> str:
    """Authenticate a mailbox owner and return its username."""
    if x_username is None:
        raise HTTPException(status_code=400, detail="Missing X-Username header for authentication.")
    if x_signature is None:
        raise HTTPException(status_code=400, detail="Missing X-Signature header for authentication.")
    if x_timestamp is None:
        raise HTTPException(status_code=400, detail="Missing X-Timestamp header for authentication.")

    try:
        timestamp = datetime.fromisoformat(x_timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid X-Timestamp format. Must be ISO 8601.") from exc
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    if abs((datetime.now(timezone.utc) - timestamp).total_seconds()) > REPLAY_WINDOW_MINUTES * 60:
        raise HTTPException(status_code=401, detail="X-Timestamp is outside the allowed 5-minute window.")

    row = conn.execute("SELECT public_key FROM directory_entries WHERE username = ?", (x_username,)).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found in directory.")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ed25519

        ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(row[0])).verify(
            bytes.fromhex(x_signature), signed_message or f"{x_username}:{x_timestamp}".encode("utf-8")
        )
    except (InvalidSignature, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid signature.") from exc
    return x_username


@router.get("/relay/inbox", response_model=InboxResponse)
async def fetch_inbox(
    x_username: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> InboxResponse:
    """Fetch waiting messages for the authenticated user.

    Requires username, signature, and timestamp verification.
    """
    x_username = _authenticate_inbox_request(x_username, x_signature, x_timestamp, conn)

    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).isoformat()

    # 1. Clean up expired messages in the background/on fetch
    cursor.execute(
        "DELETE FROM mailbox WHERE username = ? AND expires_at < ?",
        (x_username, now_str),
    )

    # 2. Fetch all current non-expired messages
    # sender_username here is an unauthenticated routing hint only — actual sender authenticity is established after decryption via the existing Ed25519 signature on the underlying task/message payload. A false sender_username only causes decryption to fail (wrong key), never a successful impersonation.
    cursor.execute(
        "SELECT message_id, sender_username, encrypted_blob FROM mailbox WHERE username = ? AND expires_at >= ? ORDER BY received_at ASC",
        (x_username, now_str),
    )
    rows = cursor.fetchall()

    if not rows:
        return InboxResponse(messages=[])

    messages = [InboxMessage(message_id=row[0], sender_username=row[1], encrypted_blob=row[2]) for row in rows]
    conn.commit()

    return InboxResponse(messages=messages)


@router.post("/relay/inbox/ack")
async def acknowledge_inbox(
    body: InboxAckRequest,
    x_username: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    """Delete messages only after their recipient has processed them locally.

    Authentication intentionally mirrors inbox retrieval: only the mailbox owner can
    acknowledge messages, and stale captured requests are bounded by the same replay window.
    """
    # Bind the acknowledgement body into the signature, so a captured inbox
    # signature cannot be replayed to delete an arbitrary mailbox message.
    ack_payload = json.dumps({"message_ids": body.message_ids}, separators=(",", ":"))
    x_username = _authenticate_inbox_request(
        x_username,
        x_signature,
        x_timestamp,
        conn,
        f"{x_username}:{x_timestamp}:{ack_payload}".encode("utf-8"),
    )
    if not body.message_ids:
        return JSONResponse(status_code=200, content={"status": "acknowledged", "count": 0})

    placeholders = ",".join("?" for _ in body.message_ids)
    cursor = conn.cursor()
    cursor.execute(
        f"DELETE FROM mailbox WHERE username = ? AND message_id IN ({placeholders})",
        (x_username, *body.message_ids),
    )
    conn.commit()
    return JSONResponse(status_code=200, content={"status": "acknowledged", "count": cursor.rowcount})
