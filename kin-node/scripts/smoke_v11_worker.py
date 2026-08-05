#!/usr/bin/env python3
"""Execute one V1.1 operation inside a single profile subprocess.

The two-node smoke harness invokes this helper with a profile-specific HOME.
That keeps Alice and Bob's keys, database access, and transport calls inside
their respective processes while emitting machine-readable evidence.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.identity.storage import (
    get_or_create_vault_key,
    load_private_key,
    load_x25519_private_key,
)
from kin.schemas import MessageKind
from kin.tui.local_state import ensure_profile_db
from kin.transport.v11 import (
    dispatch_session,
    respond_to_session,
    send_session_message,
    sync_peer_cards,
)


def _install_test_keyring_if_requested() -> None:
    if os.environ.get("KIN_UNSAFE_TEST_KEYRING") == "1":
        import keyring

        from kin.testing.insecure_memory_keyring import InMemoryTestKeyring

        keyring.set_keyring(InMemoryTestKeyring())


def _profile_context(profile: str) -> tuple[Any, bytes, ed25519.Ed25519PrivateKey, bytes, str]:
    profile_dir = Path.home() / ".kin" / "profiles" / profile
    conn = ensure_profile_db(profile_dir / "kin.db")
    vault_key = get_or_create_vault_key(profile)
    identity_key = ed25519.Ed25519PrivateKey.from_private_bytes(load_private_key(profile))
    x25519_key = load_x25519_private_key(profile)
    row = conn.execute("SELECT username FROM identity LIMIT 1").fetchone()
    if not row:
        conn.close()
        raise RuntimeError(f"Profile '{profile}' has no identity row")
    return conn, vault_key, identity_key, x25519_key, str(row[0])


def _contact_endpoint(conn: Any, peer_username: str) -> str:
    row = conn.execute(
        "SELECT endpoint FROM contacts WHERE username = ? AND fingerprint_verified_at IS NOT NULL",
        (peer_username,),
    ).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"Verified contact '{peer_username}' has no endpoint")
    return str(row[0])


def _inspect(conn: Any, session_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT session_id, type, initiator_username, receiver_username, status,
               objective, sender_agent_id, receiver_agent_id
        FROM sessions WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if not row:
        return {"session_id": session_id, "found": False, "event_count": 0, "event_kinds": []}
    event_rows = conn.execute(
        """
        SELECT kind, actor_username, sequence
        FROM session_events
        WHERE session_id = ?
        ORDER BY event_order ASC
        """,
        (session_id,),
    ).fetchall()
    return {
        "session_id": row[0],
        "found": True,
        "type": row[1],
        "initiator_username": row[2],
        "receiver_username": row[3],
        "status": row[4],
        "goal": row[5],
        "sender_agent_id": row[6],
        "receiver_agent_id": row[7],
        "event_count": len(event_rows),
        "event_kinds": [event[0] for event in event_rows],
        "event_actors": [event[1] for event in event_rows],
        "event_sequences": [event[2] for event in event_rows],
    }


def main() -> None:
    _install_test_keyring_if_requested()
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    sync_parser = subparsers.add_parser("sync-cards")
    sync_parser.add_argument("--peer", required=True)

    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("--peer", required=True)
    dispatch_parser.add_argument("--sender-agent", required=True)
    dispatch_parser.add_argument("--receiver-agent", required=True)
    dispatch_parser.add_argument("--goal", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--session", required=True)

    respond_parser = subparsers.add_parser("respond")
    respond_parser.add_argument("--session", required=True)
    respond_parser.add_argument("--decision", choices=("accept", "decline", "clarify"), required=True)
    respond_parser.add_argument("--agent")
    respond_parser.add_argument("--text", default="")

    message_parser = subparsers.add_parser("message")
    message_parser.add_argument("--session", required=True)
    message_parser.add_argument("--kind", choices=("question", "answer", "final_result"), required=True)
    message_parser.add_argument("--actor-agent", required=True)
    message_parser.add_argument("--text", required=True)

    args = parser.parse_args()
    conn, vault_key, identity_key, x25519_key, username = _profile_context(args.profile)
    try:
        relay_url = os.environ.get("KIN_RELAY_URL")
        if args.operation == "sync-cards":
            result = sync_peer_cards(
                conn,
                username,
                identity_key,
                args.peer,
                _contact_endpoint(conn, args.peer),
            )
            output = {
                "operation": "sync-cards",
                "profile": args.profile,
                "peer": args.peer,
                "source": result["source"],
                "card_count": len(result["cards"]),
            }
        elif args.operation == "dispatch":
            result = dispatch_session(
                conn=conn,
                vault_key=vault_key,
                sender_identity_key=identity_key,
                sender_x25519_privkey=x25519_key,
                sender_username=username,
                peer_username=args.peer,
                sender_agent_id=args.sender_agent,
                receiver_agent_id=args.receiver_agent,
                collaboration_mode="ask",
                goal=args.goal,
                peer_endpoint=_contact_endpoint(conn, args.peer),
                relay_url=relay_url,
            )
            output = {"operation": "dispatch", "profile": args.profile, **result}
        elif args.operation == "inspect":
            output = {"operation": "inspect", "profile": args.profile, **_inspect(conn, args.session)}
        elif args.operation == "respond":
            result = respond_to_session(
                conn=conn,
                vault_key=vault_key,
                owner_identity_key=identity_key,
                owner_x25519_privkey=x25519_key,
                owner_username=username,
                session_id=args.session,
                decision=args.decision,
                accepting_agent_id=args.agent,
                reason_or_question=args.text or None,
                relay_url=relay_url,
            )
            output = {"operation": "respond", "profile": args.profile, **result}
        else:
            payload_key = "result" if args.kind == "final_result" else args.kind
            payload = {payload_key: args.text, "message": args.text}
            result = send_session_message(
                conn=conn,
                vault_key=vault_key,
                owner_identity_key=identity_key,
                owner_x25519_privkey=x25519_key,
                owner_username=username,
                session_id=args.session,
                kind=MessageKind(args.kind),
                payload=payload,
                actor_agent_id=args.actor_agent,
                relay_url=relay_url,
            )
            output = {"operation": "message", "profile": args.profile, **result}
        print(json.dumps(output, sort_keys=True))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
