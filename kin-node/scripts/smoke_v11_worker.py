#!/usr/bin/env python3
"""Execute one V1.1 operation inside a single profile subprocess.

The two-node smoke harness invokes this helper with a profile-specific HOME.
That keeps Alice and Bob's keys, database access, and transport calls inside
their respective processes while emitting machine-readable evidence.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.artifacts.vault import get_artifact_metadata, load_artifact_bytes, store_artifact
from kin.identity.storage import (
    get_or_create_vault_key,
    load_private_key,
    load_x25519_private_key,
)
from kin.policy.persistence import create_pending_approval
from kin.schemas import ActionClass, ApprovalRequest, CapabilityAdvertisement, MessageKind, RiskLabel
from kin.session.reducer import reconstruct_session_state
from kin.tui.local_state import decide_pending_approval, ensure_profile_db
from kin.transport.v11 import (
    _apply_node_command_transition,
    _relay_auth_headers,
    cache_peer_capabilities,
    dispatch_session,
    poll_relay_and_process,
    respond_to_session,
    send_artifact_offer,
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


def _contact_public_key(conn: Any, peer_username: str) -> ed25519.Ed25519PublicKey | None:
    row = conn.execute(
        "SELECT public_key FROM contacts WHERE username = ? AND fingerprint_verified_at IS NOT NULL",
        (peer_username,),
    ).fetchone()
    if not row or not row[0]:
        return None
    return ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(str(row[0])))


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
        SELECT event_id, kind, actor_username, sequence
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
        "event_ids": [event[0] for event in event_rows],
        "event_kinds": [event[1] for event in event_rows],
        "event_actors": [event[2] for event in event_rows],
        "event_sequences": [event[3] for event in event_rows],
    }


def main() -> None:
    _install_test_keyring_if_requested()
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    sync_parser = subparsers.add_parser("sync-cards")
    sync_parser.add_argument("--peer", required=True)

    capability_parser = subparsers.add_parser("sync-capabilities")
    capability_parser.add_argument("--peer", required=True)

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

    relay_inbox_parser = subparsers.add_parser("relay-inbox")
    relay_inbox_parser.add_argument("--relay-url")

    poll_parser = subparsers.add_parser("poll-relay")
    poll_parser.add_argument("--relay-url")

    reconstruct_parser = subparsers.add_parser("reconstruct")
    reconstruct_parser.add_argument("--session", required=True)

    approval_parser = subparsers.add_parser("create-expiring-approval")
    approval_parser.add_argument("--session", required=True)
    approval_parser.add_argument("--agent", required=True)
    approval_parser.add_argument("--expiry-seconds", required=True, type=float)

    decide_parser = subparsers.add_parser("decide-approval")
    decide_parser.add_argument("--session", required=True)
    decide_parser.add_argument("--approval", required=True)
    decide_parser.add_argument("--decision", default="approve_once")

    artifact_parser = subparsers.add_parser("artifact-offer")
    artifact_parser.add_argument("--session", required=True)
    artifact_parser.add_argument("--text", required=True)
    artifact_parser.add_argument("--mime-type", default="text/plain")

    inspect_artifact_parser = subparsers.add_parser("inspect-artifact")
    inspect_artifact_parser.add_argument("--artifact", required=True)

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
        elif args.operation == "sync-capabilities":
            response = httpx.get(
                f"{_contact_endpoint(conn, args.peer).rstrip('/')}/v1.1/capabilities",
                timeout=10.0,
            )
            response.raise_for_status()
            advertisement = CapabilityAdvertisement.model_validate(response.json())
            cache_peer_capabilities(conn, args.peer, advertisement)
            output = {
                "operation": "sync-capabilities",
                "profile": args.profile,
                "peer": args.peer,
                "protocol_version": advertisement.protocol_version,
                "features": advertisement.supported_features,
                "source": "network",
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
        elif args.operation == "message":
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
        elif args.operation == "relay-inbox":
            target_relay = args.relay_url or relay_url
            if not target_relay:
                raise RuntimeError("relay-inbox requires KIN_RELAY_URL or --relay-url")
            response = httpx.get(
                f"{target_relay.rstrip('/')}/relay/inbox",
                headers=_relay_auth_headers(username, identity_key),
                timeout=10.0,
            )
            response.raise_for_status()
            messages = response.json().get("messages", [])
            output = {
                "operation": "relay-inbox",
                "profile": args.profile,
                "message_count": len(messages),
                "message_ids": [message.get("message_id") for message in messages],
                "senders": [message.get("sender_username") for message in messages],
            }
        elif args.operation == "poll-relay":
            target_relay = args.relay_url or relay_url
            if not target_relay:
                raise RuntimeError("poll-relay requires KIN_RELAY_URL or --relay-url")
            processed = poll_relay_and_process(
                conn=conn,
                vault_key=vault_key,
                my_username=username,
                my_private_key=identity_key,
                my_x25519_privkey=x25519_key,
                relay_url=target_relay,
                get_public_key_fn=lambda peer: _contact_public_key(conn, peer),
            )
            output = {
                "operation": "poll-relay",
                "profile": args.profile,
                "processed_count": processed,
            }
        elif args.operation == "reconstruct":
            state = reconstruct_session_state(conn, vault_key, args.session)
            output = {
                "operation": "reconstruct",
                "profile": args.profile,
                "session_id": args.session,
                "found": state is not None,
                "status": state.status if state else None,
                "event_count": _inspect(conn, args.session)["event_count"],
                "actor_sequences": state.actor_sequences if state else {},
            }
        elif args.operation == "create-expiring-approval":
            now = datetime.datetime.now(datetime.timezone.utc)
            expires = now + datetime.timedelta(seconds=args.expiry_seconds)
            approval_id = f"app_smoke_{os.urandom(6).hex()}"
            expires_at = expires.isoformat().replace("+00:00", "Z")
            request = ApprovalRequest(
                schema_version="1.1",
                approval_id=approval_id,
                session_id=args.session,
                agent_id=args.agent,
                action_class=ActionClass.INFORMATIONAL_RELAY,
                summary="Short-lived Phase B approval",
                reason="Verify real approval expiry rejection",
                risk_label=RiskLabel.MEDIUM,
                requested_scope={"test_only_expiry_seconds": args.expiry_seconds},
                expires_at=expires_at,
            )
            create_pending_approval(
                conn,
                vault_key,
                request,
                agent_id=args.agent,
                action_class=ActionClass.INFORMATIONAL_RELAY,
                expires_at=expires_at,
            )
            state = _apply_node_command_transition(
                conn,
                vault_key,
                args.session,
                "mark_awaiting_owner_approval",
                now=now,
            )
            if state is None or state.status != "awaiting_owner_approval":
                raise RuntimeError("Failed to move real session into awaiting_owner_approval")
            output = {
                "operation": "create-expiring-approval",
                "profile": args.profile,
                "session_id": args.session,
                "approval_id": approval_id,
                "expires_at": expires_at,
                "status": state.status,
            }
        elif args.operation == "decide-approval":
            success, error = decide_pending_approval(
                Path.home() / ".kin" / "profiles" / args.profile,
                args.profile,
                approval_id=args.approval,
                session_id=args.session,
                decision=args.decision,
            )
            row = conn.execute(
                "SELECT decision FROM approvals WHERE approval_id = ?",
                (args.approval,),
            ).fetchone()
            output = {
                "operation": "decide-approval",
                "profile": args.profile,
                "session_id": args.session,
                "approval_id": args.approval,
                "success": success,
                "error": error.what_happened if error else None,
                "decision": row[0] if row else None,
            }
        elif args.operation == "artifact-offer":
            raw_bytes = args.text.encode("utf-8")
            metadata = store_artifact(
                conn,
                vault_key,
                session_id=args.session,
                raw_bytes=raw_bytes,
                mime_type=args.mime_type,
                offered_by=username,
                preview_policy="text",
                max_bytes=1_000_000,
                source="adapter_output",
            )
            result = send_artifact_offer(
                conn=conn,
                vault_key=vault_key,
                owner_identity_key=identity_key,
                owner_x25519_privkey=x25519_key,
                owner_username=username,
                session_id=args.session,
                artifact_id=metadata.artifact_id,
                relay_url=relay_url,
            )
            output = {
                "operation": "artifact-offer",
                "profile": args.profile,
                **result,
                "sha256": metadata.sha256,
                "offered_by": metadata.offered_by,
                "size_bytes": metadata.size_bytes,
            }
        else:
            metadata = get_artifact_metadata(conn, args.artifact)
            raw_bytes = load_artifact_bytes(conn, vault_key, args.artifact)
            output = {
                "operation": "inspect-artifact",
                "profile": args.profile,
                "artifact_id": metadata.artifact_id,
                "session_id": metadata.session_id,
                "sha256": metadata.sha256,
                "computed_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "offered_by": metadata.offered_by,
                "source": metadata.source,
                "mime_type": metadata.mime_type,
                "size_bytes": metadata.size_bytes,
                "content": raw_bytes.decode("utf-8", errors="replace"),
            }
        print(json.dumps(output, sort_keys=True))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
