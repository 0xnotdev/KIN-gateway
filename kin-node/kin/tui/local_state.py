"""Shared local state query layer for KIN V1.1 TUI.

Provides shared, reusable queries for identity, local agent cards, SQLite profile DB contacts,
and relay reachability. Used by First Flight and Home Screen (§14.6 Phase B).
"""

from datetime import datetime, timezone
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from kin.agent_registry.loader import load_card_file
from kin.agent_registry.registry import scan_local_cards
from kin.cli import DEFAULT_RELAY_URL, open_profile_db
from kin.identity.fingerprint import compute_fingerprint
from kin.identity.storage import load_private_key
from kin.schemas import ActionClass, ApprovalRequest, RiskLabel
from kin.storage.db import create_schema
from kin.tui.state import AgentCardView, ApprovalView, ContactSummary, HealthSnapshot, NeedsYouItem, RecoverableError


def ensure_profile_db(db_path: Path) -> sqlite3.Connection:
    """Open and initialize schema for a profile SQLite database."""
    conn = open_profile_db(db_path)
    create_schema(conn)
    return conn


def get_local_identity_info(profile_name: str, profile_dir: Path) -> Tuple[bool, Optional[str], Optional[str]]:
    """Query local identity state. Returns (has_identity, username, public_key_hex)."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, None, None

    conn = ensure_profile_db(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT username, public_key FROM identity LIMIT 1")
        row = cursor.fetchone()
        if row:
            username, pubkey_hex = row[0], row[1]
            try:
                load_private_key(profile_name)
                return True, username, pubkey_hex
            except Exception:
                return False, username, pubkey_hex
        return False, None, None
    finally:
        conn.close()


def get_local_agents_summaries(profile_dir: Path, profile_name: str = "default") -> List[AgentCardView]:
    """Query local agent registry YAML cards and SQLite agents for UI projection (§A1)."""
    from kin.agent_registry.availability import AVAILABILITY_EXPLANATIONS, compute_availability
    from kin.schemas import AgentAvailability

    agents_dir = profile_dir / "agents"
    local_cards, _, _ = scan_local_cards(agents_dir)
    views: List[AgentCardView] = []

    # Read enabled / availability status from SQLite agents table if present
    db_status: Dict[str, Tuple[bool, AgentAvailability]] = {}
    db_path = profile_dir / "kin.db"
    if db_path.exists():
        conn = ensure_profile_db(db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT agent_id, enabled, availability FROM agents")
            for row in cur.fetchall():
                a_id, en, av = row
                try:
                    av_enum = AgentAvailability(av)
                except Exception:
                    av_enum = AgentAvailability.READY
                db_status[a_id] = (bool(en), av_enum)
        except Exception:
            pass
        finally:
            conn.close()

    for card in local_cards:
        enabled_flag, stored_avail = db_status.get(card.id, (True, AgentAvailability.READY))
        computed_avail = compute_availability(card, profile_name, stored_availability=stored_avail, enabled=enabled_flag)
        reason = AVAILABILITY_EXPLANATIONS.get(computed_avail, "Status computed.")
        views.append(AgentCardView.from_local_card(card, availability=computed_avail, readiness_reason=reason))
    return views


def get_all_agent_summaries(profile_dir: Path, profile_name: str = "default") -> Tuple[List[AgentCardView], List[AgentCardView]]:
    """Query local agent cards and cached peer agent cards. Returns (local_agents, peer_agents)."""
    from kin.schemas import AgentAvailability

    local_agents = get_local_agents_summaries(profile_dir, profile_name)
    peer_agents: List[AgentCardView] = []

    db_path = profile_dir / "kin.db"
    if db_path.exists():
        conn = ensure_profile_db(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT peer_username, agent_id, card_json, status FROM peer_agent_cards ORDER BY agent_id ASC"
            )
            for row in cursor.fetchall():
                p_user, a_id, c_json, p_status = row
                try:
                    import json
                    data = json.loads(c_json)
                    name = data.get("name", a_id)
                    desc = data.get("description", "")
                    caps = data.get("capabilities", {}).get("tags", [])
                    stale_mark = " (Stale)" if p_status == "stale" else ""
                    av_enum = AgentAvailability.READY if p_status != "stale" else AgentAvailability.OFFLINE
                    reason = "Peer card updated - owner review required" if p_status == "stale" else "Ready to accept work."
                    peer_agents.append(
                        AgentCardView(
                            agent_id=a_id,
                            name=f"{name}{stale_mark}",
                            description=desc,
                            availability=av_enum,
                            readiness_reason=reason,
                            is_peer=True,
                            capabilities_tags=caps,
                            adapter_kind=f"Peer • {av_enum.value}",
                            boundary_summary="Owner-controlled; reviewed on acceptance",
                            peer_username=p_user,
                        )
                    )
                except Exception:
                    pass
        finally:
            conn.close()

    return local_agents, peer_agents


def toggle_local_agent_enabled(
    profile_dir: Path, agent_id: str, enabled: bool, profile_name: str = "default"
) -> Tuple[bool, Optional[RecoverableError]]:
    """Enable or disable a local agent using kin.agent_registry.set_enabled."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened=f"Database for profile '{profile_name}' not found.",
            impact="Cannot toggle agent status.",
            preserved="Local files intact.",
            next_action="Run First Flight setup first.",
        )

    conn = ensure_profile_db(db_path)
    try:
        from kin.agent_registry.registry import set_enabled
        from kin.identity.storage import get_or_create_vault_key
        vault_key = get_or_create_vault_key(profile_name)
        set_enabled(conn, agent_id, enabled, profile_name=profile_name, vault_key=vault_key)
        return True, None
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to toggle agent '{agent_id}': {exc}",
            impact="Agent availability state unchanged.",
            preserved="Agent card definition safe.",
            next_action="Check keyring status or vault key access.",
        )
    finally:
        conn.close()


def review_peer_card_staleness(
    profile_dir: Path, peer_username: str, agent_id: str
) -> bool:
    """Mark a peer agent card as reviewed, clearing its stale status in SQLite."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False

    conn = ensure_profile_db(db_path)
    try:
        from kin.agent_registry.peer_cards import mark_reviewed
        mark_reviewed(conn, peer_username, agent_id)
        return True
    finally:
        conn.close()


def get_local_contacts_summaries(profile_dir: Path, profile_name: str = "default") -> List[ContactSummary]:
    """Query SQLite contacts table for paired trusted contacts."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return []

    conn = ensure_profile_db(db_path)
    contacts: List[ContactSummary] = []
    try:
        # Fetch local public key for fingerprint calculation
        cursor = conn.cursor()
        cursor.execute("SELECT public_key FROM identity LIMIT 1")
        row = cursor.fetchone()
        our_pub_bytes = bytes.fromhex(row[0]) if row and row[0] else b""

        cursor.execute(
            """
            SELECT username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at
            FROM contacts ORDER BY username ASC
            """
        )
        for r in cursor.fetchall():
            c_username, c_display, c_pub, c_x25519, c_ep, c_autonomy, c_verified = r
            fingerprint = None
            if our_pub_bytes and c_pub:
                try:
                    contact_pub_bytes = bytes.fromhex(c_pub)
                    fingerprint = compute_fingerprint(our_pub_bytes, contact_pub_bytes)
                except Exception:
                    fingerprint = None

            contacts.append(
                ContactSummary(
                    username=c_username,
                    display_name=c_display or c_username,
                    public_key=c_pub,
                    x25519_public_key=c_x25519,
                    endpoint=c_ep,
                    autonomy_level=c_autonomy or "always_ask",
                    fingerprint=fingerprint,
                    verified_at=c_verified,
                )
            )
        return contacts
    finally:
        conn.close()


def check_relay_reachability_status(
    relay_url: str, client: Optional[httpx.Client] = None
) -> Tuple[bool, Optional[RecoverableError]]:
    """Verify reachability of the relay server.

    Probes the directory lookup endpoint. A 404 response for a non-existent probe user
    proves the relay HTTP daemon is online and routing requests.
    """
    probe_url = f"{relay_url}/directory/lookup/__health_probe__"
    try:
        if client:
            resp = client.get(probe_url)
        else:
            resp = httpx.get(probe_url, timeout=3.0)

        if resp.status_code in (200, 204, 404):
            return True, None
        else:
            err = RecoverableError(
                what_happened=f"Relay daemon error (HTTP status {resp.status_code}).",
                impact="Peer discovery and relay routing unavailable.",
                preserved="Local identity and agent registry remain functional.",
                next_action="Check relay daemon logs or press [Skip] to work offline.",
            )
            return False, err
    except Exception as exc:
        err = RecoverableError(
            what_happened=f"Relay unreachable at '{relay_url}': {exc}",
            impact="Peer messaging operating in offline mode.",
            preserved="Local storage unaffected.",
            next_action="Start local relay or press [Skip] to proceed.",
        )
        return False, err


def get_peer_capabilities_recency(profile_dir: Path, peer_username: str) -> Optional[str]:
    """Query cached peer_capabilities recency timestamp for a contact (§14.6 Phase D)."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return None
    conn = ensure_profile_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT fetched_at FROM peer_capabilities WHERE peer_username = ?", (peer_username,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def get_stale_peer_card_count(profile_dir: Path, peer_username: str) -> int:
    """Query count of stale peer agent cards for a contact (§14.6 Phase D)."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return 0
    conn = ensure_profile_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM peer_agent_cards WHERE peer_username = ? AND status = 'stale'",
            (peer_username,),
        )
        row = cur.fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_needs_you_items(profile_dir: Path, profile_name: str = "default") -> List[NeedsYouItem]:
    """Query active sessions requiring human owner attention per §5.8 and §14.6 Phase D."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return []

    _, local_username, _ = get_local_identity_info(profile_name, profile_dir)
    conn = ensure_profile_db(db_path)
    items: List[NeedsYouItem] = []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT session_id, initiator_username, receiver_username, status, created_at
            FROM sessions
            WHERE status IN ('peer_review', 'needs_clarification', 'awaiting_owner_approval')
            ORDER BY created_at DESC
            """
        )
        for row in cur.fetchall():
            s_id, init_user, recv_user, s_status, created_at = row
            # Attribution Check (§1a & Code Citation)
            if s_status == "peer_review" and local_username == recv_user:
                items.append(
                    NeedsYouItem(
                        item_id=f"ny-{s_id[:8]}",
                        session_id=s_id,
                        kind="session_acceptance",
                        human_readable_reason=f"Waiting for you to accept {init_user}'s session request",
                        urgency="medium",
                        created_at=created_at,
                    )
                )
            elif s_status == "needs_clarification" and local_username == init_user:
                items.append(
                    NeedsYouItem(
                        item_id=f"ny-{s_id[:8]}",
                        session_id=s_id,
                        kind="clarification",
                        human_readable_reason=f"{recv_user} requested clarification on session parameters",
                        urgency="medium",
                        created_at=created_at,
                    )
                )
            elif s_status == "awaiting_owner_approval" and (local_username in (init_user, recv_user) or not local_username):
                items.append(
                    NeedsYouItem(
                        item_id=f"ny-{s_id[:8]}",
                        session_id=s_id,
                        kind="approval",
                        human_readable_reason=f"Policy gate paused session {s_id[:8]} pending owner decision",
                        urgency="high",
                        created_at=created_at,
                    )
                )
        return items
    finally:
        conn.close()


def parse_iso_utc(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO8601 string (handling 'Z' or offset) into timezone-aware UTC datetime."""
    if not ts_str:
        return None
    try:
        clean_ts = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def get_pending_approvals(profile_dir: Path, profile_name: str = "default") -> List[ApprovalView]:
    """Query SQLite approvals table for pending or expired approval requests (§14.6 Phase D)."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return []

    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.isoformat()
    conn = ensure_profile_db(db_path)
    views: List[ApprovalView] = []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT approval_id, session_id, agent_id, action_class, request_json, expires_at, decision
            FROM approvals
            ORDER BY approval_id DESC
            """
        )
        for row in cur.fetchall():
            app_id, sess_id, agent_id, act_class, req_json, exp_at, dec = row
            exp_dt = parse_iso_utc(exp_at)

            # Accurate datetime-aware comparison preventing ISO 'Z' vs microsecond string sorting bugs (§2)
            if exp_dt is not None:
                is_pending = (dec is None and exp_dt > now_dt)
                is_expired = (dec is None and exp_dt <= now_dt)
            else:
                is_pending = (dec is None and exp_at > now_str)
                is_expired = (dec is None and exp_at <= now_str)

            if not is_pending and not is_expired:
                continue

            # Safe deserialization wrapping extra="forbid" Pydantic models
            req_obj = None
            if req_json:
                try:
                    req_obj = ApprovalRequest.model_validate_json(req_json)
                except Exception:
                    req_obj = None

            if req_obj:
                views.append(ApprovalView(request=req_obj, decision=dec))
            else:
                try:
                    req_fallback = ApprovalRequest(
                        schema_version="1.1",
                        approval_id=app_id,
                        session_id=sess_id,
                        agent_id=agent_id,
                        action_class=ActionClass(act_class) if act_class else ActionClass.INFORMATIONAL_RELAY,
                        summary=f"Approval request {app_id[:8]}",
                        reason=f"Approval request {app_id[:8]}",
                        risk_label=RiskLabel.MEDIUM,
                        requested_scope={},
                        expires_at=exp_at or now_str,
                    )
                    views.append(ApprovalView(request=req_fallback, decision=dec))
                except Exception:
                    pass
        return views
    finally:
        conn.close()


def dispatch_session_owner_decision(
    profile_dir: Path,
    profile_name: str,
    *,
    session_id: str,
    approval_id: str,
    decision: str,
    reason: Optional[str] = None,
    constraints: Optional[dict] = None,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Convenience wrapper for recording an approval decision."""
    return decide_pending_approval(
        profile_dir,
        profile_name,
        approval_id=approval_id,
        session_id=session_id,
        decision=decision,
        reason=reason,
        constraints=constraints,
    )


def decide_pending_approval(
    profile_dir: Path,
    profile_name: str = "default",
    *,
    approval_id: str,
    session_id: str,
    decision: str,
    reason: Optional[str] = None,
    constraints: Optional[dict] = None,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Record owner decision via kin.policy.persistence.decide_approval (§3.2 & §14.6 Phase D)."""
    from datetime import datetime, timezone
    from kin.identity.storage import get_or_create_vault_key
    from kin.policy.persistence import (
        ApprovalAlreadyDecidedError,
        ApprovalExpiredError,
        ApprovalNotFoundError,
        InvalidDecisionValueError,
        decide_approval,
    )

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database file not found.",
            impact="Cannot record approval decision.",
            preserved="Local state unchanged.",
            next_action="Initialize profile first.",
        )

    _, local_username, _ = get_local_identity_info(profile_name, profile_dir)
    owner_user = local_username or "default_user"
    now_str = datetime.now(timezone.utc).isoformat()
    vault_key = get_or_create_vault_key(profile_name)

    conn = ensure_profile_db(db_path)
    try:
        decide_approval(
            conn,
            vault_key,
            approval_id=approval_id,
            session_id=session_id,
            decision=decision,
            owner_username=owner_user,
            now=now_str,
            reason=reason,
            constraints=constraints,
        )
        return True, None
    except ApprovalNotFoundError as exc:
        return False, RecoverableError(
            what_happened=f"Approval request '{approval_id}' not found.",
            impact="Decision not applied.",
            preserved="Database intact.",
            next_action="Refresh Inbox screen queue.",
        )
    except ApprovalAlreadyDecidedError as exc:
        return False, RecoverableError(
            what_happened=f"Approval '{approval_id}' has already been decided.",
            impact="Duplicate decision rejected.",
            preserved="Existing decision retained.",
            next_action="Review decided approvals list.",
        )
    except ApprovalExpiredError as exc:
        return False, RecoverableError(
            what_happened=f"Approval '{approval_id}' has expired.",
            impact="Expired approval cannot be approved.",
            preserved="Audit trail updated.",
            next_action="Re-initiate action request if required.",
        )
    except InvalidDecisionValueError as exc:
        return False, RecoverableError(
            what_happened=f"Invalid decision parameters: {exc}",
            impact="Decision rejected by policy engine.",
            preserved="No database changes made.",
            next_action="Provide mandatory non-empty reason/constraints.",
        )
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to record decision: {exc}",
            impact="Approval state unchanged.",
            preserved="Local database safe.",
            next_action="Check policy configuration.",
        )
    finally:
        conn.close()


def dispatch_new_session(
    profile_dir: Path,
    profile_name: str = "default",
    *,
    peer_username: str,
    sender_agent_id: str,
    receiver_agent_id: str,
    session_type: str,
    goal: str,
    max_turns: Optional[int] = None,
    http_client: Optional[httpx.Client] = None,
) -> Tuple[bool, Optional[dict], Optional[RecoverableError]]:
    """Dispatch a new session using kin.transport.v11.dispatch_session (§A4)."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from kin.identity.storage import get_or_create_vault_key, load_private_key, load_x25519_private_key
    from kin.transport.v11 import CapabilityMismatchError, StalePeerCardError, dispatch_session

    # Enforce peer is in verified contacts list
    contacts = get_local_contacts_summaries(profile_dir, profile_name)
    contact_usernames = {c.username for c in contacts}
    if peer_username not in contact_usernames:
        return False, None, RecoverableError(
            what_happened=f"Peer '{peer_username}' is not a verified contact.",
            impact="Cannot dispatch session to an unverified contact.",
            preserved="Draft session state preserved.",
            next_action="Verify peer identity via Network tab or kin pair first.",
        )

    ok, own_username, _ = get_local_identity_info(profile_name, profile_dir)
    if not ok or not own_username:
        return False, None, RecoverableError(
            what_happened="Local identity key not initialized.",
            impact="Cannot sign outbound session request.",
            preserved="Draft session state preserved.",
            next_action="Run First Flight setup to generate identity key.",
        )

    try:
        vault_key = get_or_create_vault_key(profile_name)
        raw_ed_bytes = load_private_key(profile_name)
        ed_priv = ed25519.Ed25519PrivateKey.from_private_bytes(raw_ed_bytes)
        x255_priv = load_x25519_private_key(profile_name)
    except Exception as exc:
        return False, None, RecoverableError(
            what_happened="Failed to load private identity keys.",
            impact="Cannot encrypt or sign dispatch payload.",
            preserved="Draft session state preserved.",
            next_action="Check profile permissions and vault key.",
            technical_detail=str(exc),
        )

    db_path = profile_dir / "kin.db"
    conn = ensure_profile_db(db_path)
    try:
        result = dispatch_session(
            conn=conn,
            vault_key=vault_key,
            sender_identity_key=ed_priv,
            sender_x25519_privkey=x255_priv,
            sender_username=own_username,
            peer_username=peer_username,
            sender_agent_id=sender_agent_id,
            receiver_agent_id=receiver_agent_id,
            collaboration_mode=session_type,
            goal=goal,
            max_turns=max_turns,
            http_client=http_client,
        )
        return True, result, None
    except CapabilityMismatchError as exc:
        return False, None, RecoverableError(
            what_happened=f"Capability mismatch with agent '{receiver_agent_id}'.",
            impact="Session dispatch declined by agent capability rules.",
            preserved="Draft session state preserved.",
            next_action="Select a compatible agent or review agent capabilities.",
            technical_detail=str(exc),
        )
    except StalePeerCardError as exc:
        return False, None, RecoverableError(
            what_happened=f"Peer card for '{peer_username}' is stale.",
            impact="Session dispatch blocked until peer card is reviewed.",
            preserved="Draft session state preserved.",
            next_action="Review the peer card in Network before retrying.",
            technical_detail=str(exc),
        )
    except ValueError as exc:
        return False, None, RecoverableError(
            what_happened=f"Invalid session parameter: {exc}",
            impact="Session request failed validation.",
            preserved="Draft session state preserved.",
            next_action="Check collaboration type and turn limit parameters.",
            technical_detail=str(exc),
        )
    except Exception as exc:
        return False, None, RecoverableError(
            what_happened="Unexpected error during session dispatch.",
            impact="Outbound dispatch failed.",
            preserved="Draft session state preserved.",
            next_action="Check connection and try again.",
            technical_detail=str(exc),
        )
    finally:
        conn.close()


def query_health_snapshot(
    profile_name: str = "default",
    profile_dir: Optional[Path] = None,
    relay_url: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> HealthSnapshot:
    """Build a real HealthSnapshot based on local identity, keychain, and real pending inbox counts (§14.6 Phase D)."""
    p_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)
    r_url = relay_url or os.environ.get("KIN_RELAY_URL", DEFAULT_RELAY_URL)

    has_identity, username, _ = get_local_identity_info(profile_name, p_dir)
    relay_ok, _ = check_relay_reachability_status(r_url, client=client)

    # Real pending inbox count (§5 Integration Requirement)
    needs_you_count = len(get_needs_you_items(p_dir, profile_name))
    pending_app_count = len(get_pending_approvals(p_dir, profile_name))
    total_pending = needs_you_count + pending_app_count

    degraded_reason = None
    if not has_identity:
        degraded_reason = "No local identity initialized • Run First Flight setup"
    elif not relay_ok:
        degraded_reason = f"Profile '{username or profile_name}' local only • Relay offline"

    return HealthSnapshot(
        keychain_ok=has_identity,
        identity_ok=has_identity,
        relay_reachable=relay_ok,
        node_reachable=True,
        pending_inbox_count=total_pending,
        degraded_reason=degraded_reason,
    )
