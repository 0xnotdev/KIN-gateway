"""Shared local state query layer for KIN V1.1 TUI.

Provides shared, reusable queries for identity, local agent cards, SQLite profile DB contacts,
and relay reachability. Used by First Flight and Home Screen (§14.6 Phase B).
"""

from datetime import datetime, timezone
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

import httpx

from kin.agent_registry.loader import load_card_file
from kin.agent_registry.registry import scan_local_cards
from kin.cli import DEFAULT_RELAY_URL, open_profile_db
from kin.context_pantry import PantryValidationError, build_reviewed_context_pack
from kin.identity.fingerprint import compute_fingerprint
from kin.identity.storage import get_or_create_vault_key, load_private_key
from kin.schemas import ActionClass, ApprovalRequest, InternalEventKind, MessageKind, RiskLabel
from kin.storage.db import create_schema
from kin.storage.vault import decrypt_field_or_plaintext
from kin.tui.state import (
    AgentCardView,
    ApprovalView,
    ArtifactView,
    ContactSummary,
    HealthSnapshot,
    NeedsYouItem,
    PrivateNoteView,
    RecoverableError,
    SessionSummary,
    UiEvent,
    map_event_kind_to_presentation_class,
)


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
            from kin.collaboration_depth import readiness_recommendations

            recommendations = {
                item.agent_id: item.availability
                for item in readiness_recommendations(conn)
            }
            cur = conn.cursor()
            cur.execute("SELECT agent_id, enabled, availability FROM agents")
            for row in cur.fetchall():
                a_id, en, av = row
                try:
                    av_enum = AgentAvailability(av)
                except Exception:
                    av_enum = AgentAvailability.READY
                db_status[a_id] = (bool(en), recommendations.get(a_id, av_enum))
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

        # 2. Query session_events for security-class events (§10.1 persistent red card + Needs-you)
        try:
            cur.execute(
                """
                SELECT event_id, session_id, kind, created_at, actor_username
                FROM session_events
                ORDER BY created_at DESC
                """
            )
            for row in cur.fetchall():
                e_id, s_id, e_kind, created_at, actor = row
                try:
                    p_class = map_event_kind_to_presentation_class(e_kind)
                except ValueError as exc:
                    logger.warning("Unrecognized event kind '%s' during Needs-You classification; defaulting to 'security' (safe/visible): %s", e_kind, exc)
                    p_class = "security"

                if p_class == "security":
                    items.append(
                        NeedsYouItem(
                            item_id=f"sec-{e_id[:8]}",
                            session_id=s_id or "",
                            kind="security",
                            human_readable_reason=f"SECURITY ALERT [{e_kind}]: Security violation recorded for actor @{actor or 'unknown'}",
                            urgency="high",
                            created_at=created_at or "",
                        )
                    )
        except Exception as exc:
            from kin.tui.errors import log_exception_to_diagnostics
            log_exception_to_diagnostics(exc, profile_dir)
            logger.warning("Failed to query security events for Needs-You queue: %s", exc, exc_info=True)

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
    vault_key = get_or_create_vault_key(profile_name)
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
                    req_obj = ApprovalRequest.model_validate_json(
                        decrypt_field_or_plaintext(vault_key, req_json)
                    )
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
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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


def create_private_note(
    profile_dir: Path,
    profile_name: str,
    session_id: str,
    actor_username: str,
    note_text: str,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Append an encrypted owner-only scratch note without signing or transport."""
    from kin.audit.writer import append_session_event
    from kin.identity.storage import get_or_create_vault_key

    if not note_text or not note_text.strip():
        return False, RecoverableError(
            what_happened="Private note text cannot be empty.",
            impact="No private note was created.",
            preserved="Session history remains unchanged.",
            next_action="Enter note text and save again.",
        )
    if not actor_username or not actor_username.strip():
        return False, RecoverableError(
            what_happened="Private note author is unavailable.",
            impact="No private note was created.",
            preserved="Session history remains unchanged.",
            next_action="Initialize the local profile identity first.",
        )

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database file not found.",
            impact="Cannot save private note.",
            preserved="No local state changed.",
            next_action="Initialize profile first.",
        )

    try:
        vault_key = get_or_create_vault_key(profile_name)
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to access private-note encryption key: {exc}",
            impact="Private note was not recorded.",
            preserved="Existing session history remains intact.",
            next_action="Unlock the profile keychain and retry.",
        )
    conn = ensure_profile_db(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return False, RecoverableError(
                what_happened=f"Session '{session_id}' not found.",
                impact="Private note was not saved.",
                preserved="Local database remains unchanged.",
                next_action="Select a valid session.",
            )

        result = append_session_event(
            conn,
            vault_key,
            session_id=session_id,
            actor_username=actor_username.strip(),
            actor_agent_id=None,
            kind=InternalEventKind.PRIVATE_NOTE.value,
            visibility="local_only",
            payload={"content": note_text.strip()},
            signature=None,
            sequence=None,
        )
        if result.get("status") != "appended":
            raise RuntimeError(f"Unexpected private-note append status: {result.get('status')}")
        return True, None
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to save private note: {exc}",
            impact="Private note was not recorded.",
            preserved="Existing session history remains intact.",
            next_action="Retry saving the note.",
        )
    finally:
        conn.close()


def pause_session(
    profile_dir: Path,
    profile_name: str = "default",
    *,
    session_id: str,
    reason: Optional[str] = None,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Pause an active session (§14.8 Phase D)."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.transport.v11 import pause_session as _transport_pause

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database file not found.",
            impact="Cannot pause session.",
            preserved="Local state unchanged.",
            next_action="Initialize profile first.",
        )

    _, local_username, _ = get_local_identity_info(profile_name, profile_dir)
    owner_user = local_username or "owner"
    now_dt = datetime.now(timezone.utc)
    vault_key = get_or_create_vault_key(profile_name)

    conn = ensure_profile_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,))
        row = cur.fetchone()
        if row is None:
            return False, RecoverableError(
                what_happened=f"Session '{session_id}' not found.",
                impact="Pause action rejected.",
                preserved="Database intact.",
                next_action="Verify session ID.",
            )
        status = row[0]
        if status in ("completed", "cancelled", "failed", "rejected"):
            return False, RecoverableError(
                what_happened=f"Session '{session_id}' is already in terminal state '{status}'.",
                impact="Pause action rejected.",
                preserved="Terminal session state retained.",
                next_action="No further state changes possible.",
            )

        _transport_pause(
            conn,
            vault_key,
            owner_identity_key=None,
            sender_x25519_privkey=None,
            owner_username=owner_user,
            session_id=session_id,
            reason=reason or "Paused by owner via TUI Arena",
            now=now_dt,
        )
        return True, None
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to pause session: {exc}",
            impact="Session state transition failed.",
            preserved="Local database intact.",
            next_action="Retry pause operation.",
        )
    finally:
        conn.close()


def resume_session(
    profile_dir: Path,
    profile_name: str = "default",
    *,
    session_id: str,
    reason: Optional[str] = None,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Resume a paused session (§14.8 Phase D)."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.transport.v11 import resume_session as _transport_resume

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database file not found.",
            impact="Cannot resume session.",
            preserved="Local state unchanged.",
            next_action="Initialize profile first.",
        )

    _, local_username, _ = get_local_identity_info(profile_name, profile_dir)
    owner_user = local_username or "owner"
    now_dt = datetime.now(timezone.utc)
    vault_key = get_or_create_vault_key(profile_name)

    conn = ensure_profile_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,))
        row = cur.fetchone()
        if row is None:
            return False, RecoverableError(
                what_happened=f"Session '{session_id}' not found.",
                impact="Resume action rejected.",
                preserved="Database intact.",
                next_action="Verify session ID.",
            )
        status = row[0]
        if status in ("completed", "cancelled", "failed", "rejected"):
            return False, RecoverableError(
                what_happened=f"Session '{session_id}' is already in terminal state '{status}'.",
                impact="Resume action rejected.",
                preserved="Terminal session state retained.",
                next_action="No further state changes possible.",
            )

        _transport_resume(
            conn,
            vault_key,
            owner_identity_key=None,
            sender_x25519_privkey=None,
            owner_username=owner_user,
            session_id=session_id,
            reason=reason or "Resumed by owner via TUI Arena",
            now=now_dt,
        )
        return True, None
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to resume session: {exc}",
            impact="Session state transition failed.",
            preserved="Local database intact.",
            next_action="Retry resume operation.",
        )
    finally:
        conn.close()


def cancel_session_command(
    profile_dir: Path,
    profile_name: str = "default",
    *,
    session_id: str,
    reason: Optional[str] = None,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Cancel an active or paused session (§14.8 Phase D)."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.transport.v11 import cancel_session as _transport_cancel

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database file not found.",
            impact="Cannot cancel session.",
            preserved="Local state unchanged.",
            next_action="Initialize profile first.",
        )

    _, local_username, _ = get_local_identity_info(profile_name, profile_dir)
    owner_user = local_username or "owner"
    now_dt = datetime.now(timezone.utc)
    vault_key = get_or_create_vault_key(profile_name)

    conn = ensure_profile_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,))
        row = cur.fetchone()
        if row is None:
            return False, RecoverableError(
                what_happened=f"Session '{session_id}' not found.",
                impact="Cancel action rejected.",
                preserved="Database intact.",
                next_action="Verify session ID.",
            )
        status = row[0]
        if status in ("completed", "cancelled", "failed", "rejected"):
            return False, RecoverableError(
                what_happened=f"Session '{session_id}' is already in terminal state '{status}'.",
                impact="Cancel action rejected.",
                preserved="Terminal session state retained.",
                next_action="No further state changes possible.",
            )

        _transport_cancel(
            conn,
            vault_key,
            owner_identity_key=None,
            sender_x25519_privkey=None,
            owner_username=owner_user,
            session_id=session_id,
            reason=reason or "Cancelled by owner via TUI Arena",
            now=now_dt,
        )
        return True, None
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to cancel session: {exc}",
            impact="Session state transition failed.",
            preserved="Local database intact.",
            next_action="Retry cancel operation.",
        )
    finally:
        conn.close()


def tag_in_session_agent(
    profile_dir: Path,
    profile_name: str,
    *,
    session_id: str,
    replacement_agent_id: str,
    relay_url: Optional[str] = None,
    http_client: Optional[httpx.Client] = None,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[dict[str, Any]], Optional[RecoverableError]]:
    """Sign, persist, and deliver an owner-confirmed participant tag-in."""
    ok, owner_username, _ = get_local_identity_info(profile_name, profile_dir)
    if not ok or not owner_username:
        return False, None, RecoverableError(
            what_happened="Local identity key not initialized.",
            impact="Cannot sign the participant change.",
            preserved="The current session participant remains unchanged.",
            next_action="Complete First Flight identity setup, then retry.",
        )

    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from kin.identity.storage import get_or_create_vault_key, load_x25519_private_key
        from kin.session.orchestrator import tag_in_handoff

        owner_key = ed25519.Ed25519PrivateKey.from_private_bytes(load_private_key(profile_name))
        owner_x25519 = load_x25519_private_key(profile_name)
        vault_key = get_or_create_vault_key(profile_name)
    except Exception as exc:
        return False, None, RecoverableError(
            what_happened="Failed to load private identity keys.",
            impact="Cannot sign or encrypt the participant change.",
            preserved="The current session participant remains unchanged.",
            next_action="Check profile permissions and keychain access.",
            technical_detail=str(exc),
        )

    conn = ensure_profile_db(profile_dir / "kin.db")
    try:
        result = tag_in_handoff(
            conn,
            vault_key,
            owner_key,
            owner_username,
            session_id,
            replacement_agent_id,
            owner_x25519_privkey=owner_x25519,
            relay_url=relay_url or os.environ.get("KIN_RELAY_URL", DEFAULT_RELAY_URL),
            http_client=http_client,
            now=now,
        )
        return True, result, None
    except Exception as exc:
        return False, None, RecoverableError(
            what_happened=f"Failed to hand the session to '{replacement_agent_id}'.",
            impact="The participant change was not completed.",
            preserved="Existing session history and current participant are retained.",
            next_action="Review the replacement agent and connectivity, then retry.",
            technical_detail=str(exc),
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
    pantry_items: Optional[list] = None,
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
        context_pack = build_reviewed_context_pack(
            conn,
            vault_key,
            pantry_items or [],
        )
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
            context_pack=context_pack,
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
    except PantryValidationError as exc:
        return False, None, RecoverableError(
            what_happened=str(exc),
            impact="Session was not dispatched with unreviewed or expired context.",
            preserved="The draft and local references remain local.",
            next_action="Review each shared context item, remove expired items, and retry.",
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


def send_human_message_to_session_action(
    profile_name: str,
    session_id: str,
    message_text: str,
    profile_dir: Optional[Path] = None,
    relay_url: Optional[str] = None,
    http_client: Optional[httpx.Client] = None,
    now: Optional[datetime] = None,
) -> tuple[bool, Optional[dict[str, Any]], Optional[RecoverableError]]:
    """Compose and transmit a human-authored message to a session peer (§14.8 Step 5/6).
    
    1. Loads real owner identity keys (Ed25519 and X25519) from vault/keychain via load_private_key/load_x25519_private_key.
       Fails with clear RecoverableError if keys are unavailable (NO synthetic key fallbacks).
    2. Opens kin.db.
    3. Checks session status:
       - If status is 'needs_clarification' or 'peer_review', routes through respond_to_session(decision="clarify").
       - If status is 'active', routes through send_session_message(kind=MessageKind.QUESTION).
    4. Cryptographically signs envelope, ingests locally, and delivers directly via HTTP or queues to Relay Mailbox.
    """
    if not message_text or not message_text.strip():
        return False, None, RecoverableError(
            what_happened="Message text cannot be empty.",
            impact="Compose action cancelled.",
            preserved="No changes made.",
            next_action="Enter message content before sending.",
        )

    p_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)
    ok, own_username, _ = get_local_identity_info(profile_name, p_dir)
    if not ok or not own_username:
        return False, None, RecoverableError(
            what_happened="Local identity key not initialized.",
            impact="Cannot sign outbound session message.",
            preserved="Draft content preserved in modal.",
            next_action="Run First Flight setup to generate identity key.",
        )

    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from kin.identity.storage import get_or_create_vault_key, load_private_key, load_x25519_private_key
        vault_key = get_or_create_vault_key(profile_name)
        raw_ed_bytes = load_private_key(profile_name)
        ed_priv = ed25519.Ed25519PrivateKey.from_private_bytes(raw_ed_bytes)
        x255_priv = load_x25519_private_key(profile_name)
    except Exception as exc:
        return False, None, RecoverableError(
            what_happened="Failed to load private identity keys.",
            impact="Cannot encrypt or sign outbound message.",
            preserved="Draft content preserved in modal.",
            next_action="Check profile permissions and vault key.",
            technical_detail=str(exc),
        )

    db_path = p_dir / "kin.db"
    conn = ensure_profile_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,))
        row = cur.fetchone()
        if not row:
            return False, None, RecoverableError(
                what_happened=f"Session '{session_id}' not found.",
                impact="Cannot send message to non-existent session.",
                preserved="No changes made.",
                next_action="Select a valid active session.",
            )
        status = row[0]

        r_url = relay_url or os.environ.get("KIN_RELAY_URL", DEFAULT_RELAY_URL)
        from kin.transport.v11 import respond_to_session, send_session_message

        if status in ("peer_review", "needs_clarification"):
            res = respond_to_session(
                conn=conn,
                vault_key=vault_key,
                owner_identity_key=ed_priv,
                owner_x25519_privkey=x255_priv,
                owner_username=own_username,
                session_id=session_id,
                decision="clarify",
                reason_or_question=message_text.strip(),
                relay_url=r_url,
                now=now,
                http_client=http_client,
            )
        else:
            payload = {"message": message_text.strip(), "question": message_text.strip()}
            res = send_session_message(
                conn=conn,
                vault_key=vault_key,
                owner_identity_key=ed_priv,
                owner_x25519_privkey=x255_priv,
                owner_username=own_username,
                session_id=session_id,
                kind=MessageKind.QUESTION,
                payload=payload,
                relay_url=r_url,
                now=now,
                http_client=http_client,
            )

        if res.get("status") == "failed":
            return False, None, RecoverableError(
                what_happened="Failed to deliver message to peer.",
                impact="Outbound message delivery failed (peer endpoint unreachable & relay queue failed).",
                preserved="Message saved locally in draft state.",
                next_action="Check network connectivity and peer endpoint.",
            )

        return True, res, None
    except Exception as exc:
        return False, None, RecoverableError(
            what_happened="Error sending session message.",
            impact="Outbound message failed.",
            preserved="Draft content preserved.",
            next_action="Check logs and try again.",
            technical_detail=str(exc),
        )
    finally:
        conn.close()


def promote_private_note_to_peer_visible(
    profile_dir: Path,
    profile_name: str,
    session_id: str,
    note_event_id: str,
    *,
    relay_url: Optional[str] = None,
    http_client: Optional[httpx.Client] = None,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Promote one local note through the canonical signed message transport."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.storage.vault import decrypt_field

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database file not found.",
            impact="Cannot promote private note.",
            preserved="The note remains local-only.",
            next_action="Initialize profile first.",
        )

    try:
        vault_key = get_or_create_vault_key(profile_name)
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to access private-note encryption key: {exc}",
            impact="Nothing was sent to the peer.",
            preserved="The original note remains local-only.",
            next_action="Unlock the profile keychain and retry promotion.",
        )
    conn = ensure_profile_db(db_path)
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM session_events
            WHERE event_id = ? AND session_id = ? AND kind = ? AND visibility = 'local_only'
            """,
            (note_event_id, session_id, InternalEventKind.PRIVATE_NOTE.value),
        ).fetchone()
        if row is None:
            return False, RecoverableError(
                what_happened=f"Private note '{note_event_id}' not found.",
                impact="Nothing was sent to the peer.",
                preserved="Local session history remains unchanged.",
                next_action="Refresh the Notes lane and select an existing note.",
            )

        decrypted = decrypt_field(vault_key, row[0])
        payload = json.loads(decrypted) if decrypted else {}
        note_text = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(note_text, str) or not note_text.strip():
            return False, RecoverableError(
                what_happened=f"Private note '{note_event_id}' has no promotable text.",
                impact="Nothing was sent to the peer.",
                preserved="The note remains local-only.",
                next_action="Create a new non-empty private note.",
            )
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to read private note: {exc}",
            impact="Nothing was sent to the peer.",
            preserved="The note remains local-only.",
            next_action="Refresh the Notes lane and retry.",
        )
    finally:
        conn.close()

    ok, _result, error = send_human_message_to_session_action(
        profile_name=profile_name,
        session_id=session_id,
        message_text=note_text.strip(),
        profile_dir=profile_dir,
        relay_url=relay_url,
        http_client=http_client,
        now=now,
    )
    if not ok:
        return False, error or RecoverableError(
            what_happened="Failed to promote private note.",
            impact="Nothing was sent to the peer.",
            preserved="The original note remains local-only.",
            next_action="Check connectivity and retry promotion.",
        )
    return True, None


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


# -----------------------------------------------------------------------------
# Session Arena Data Layer Accessors (§14.8 Phase A)
# -----------------------------------------------------------------------------

def get_session_list(
    profile_dir: Path, profile_name: str = "default"
) -> List[SessionSummary]:
    """Query all sessions from the sessions table (§14.8 Phase A)."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return []

    conn = ensure_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)
    sessions: List[SessionSummary] = []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT session_id, type, status, initiator_username, receiver_username,
                   objective, turn_limit, created_at, updated_at
            FROM sessions
            ORDER BY updated_at DESC
            """
        )
        for row in cur.fetchall():
            s_id, s_type, s_stat, init_user, recv_user, obj, t_lim, c_at, u_at = row
            sessions.append(
                SessionSummary(
                    session_id=s_id,
                    status=s_stat,
                    type=s_type,
                    initiator_username=init_user or "",
                    receiver_username=recv_user or "",
                    objective=decrypt_field_or_plaintext(vault_key, obj) or "",
                    turn_limit=t_lim or 12,
                    created_at=c_at or "",
                    updated_at=u_at or "",
                )
            )
        return sessions
    finally:
        conn.close()


def get_session_detail(
    profile_dir: Path, session_id: str, profile_name: str = "default"
) -> Optional[SessionSummary]:
    """Query a single SessionSummary by session_id (§14.8 Phase A)."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return None

    conn = ensure_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT session_id, type, status, initiator_username, receiver_username,
                   objective, turn_limit, created_at, updated_at
            FROM sessions
            WHERE session_id = ?
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        s_id, s_type, s_stat, init_user, recv_user, obj, t_lim, c_at, u_at = row
        return SessionSummary(
            session_id=s_id,
            status=s_stat,
            type=s_type,
            initiator_username=init_user or "",
            receiver_username=recv_user or "",
            objective=decrypt_field_or_plaintext(vault_key, obj) or "",
            turn_limit=t_lim or 12,
            created_at=c_at or "",
            updated_at=u_at or "",
        )
    finally:
        conn.close()


def _parse_payload_content(payload_json_val: Optional[str], vault_key: Optional[bytes] = None) -> Optional[str]:
    """Parse and decrypt payload_json, extracting human-readable message text and redacting it (§14.8 Step 5/6)."""
    if not payload_json_val:
        return None

    raw_json_str = payload_json_val
    if vault_key:
        try:
            from kin.storage.vault import decrypt_field
            decrypted = decrypt_field(vault_key, payload_json_val)
            if decrypted:
                raw_json_str = decrypted
        except Exception:
            pass

    try:
        import json
        data = json.loads(raw_json_str)
        raw_text = None
        if isinstance(data, dict):
            raw_text = (
                data.get("message")
                or data.get("question")
                or data.get("reason")
                or data.get("content")
                or data.get("goal")
                or data.get("outcome")
            )
        elif isinstance(data, str):
            raw_text = data

        if raw_text and isinstance(raw_text, str):
            from kin.tui.redaction import redact_ui_text
            return redact_ui_text(raw_text)
    except Exception:
        pass

    return None


def get_session_events(
    profile_dir: Path,
    session_id: str,
    profile_name: str = "default",
    seen_event_ids: Optional[Set[str]] = None,
    after_event_order: Optional[int] = None,
    after_created_at: Optional[str] = None,
) -> List[UiEvent]:
    """Fetch session_events and audit_events into chronologically ordered UiEvent list with incremental cursor filtering (§14.8 Phase A, C2 Round 2)."""
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return []

    conn = ensure_profile_db(db_path)
    events: List[UiEvent] = []
    seen = seen_event_ids or set()
    
    vault_key = None
    try:
        from kin.identity.storage import get_or_create_vault_key
        vault_key = get_or_create_vault_key(profile_name)
    except Exception:
        pass

    try:
        cur = conn.cursor()

        # 1. Query session_events table using event_order cursor if provided
        if after_event_order is not None:
            cur.execute(
                """
                SELECT event_id, session_id, kind, created_at, actor_username, event_order, payload_json
                FROM session_events
                WHERE session_id = ? AND event_order > ?
                  AND COALESCE(visibility, 'peer_visible') != 'local_only'
                ORDER BY event_order ASC
                """,
                (session_id, after_event_order),
            )
        else:
            cur.execute(
                """
                SELECT event_id, session_id, kind, created_at, actor_username, event_order, payload_json
                FROM session_events
                WHERE session_id = ?
                  AND COALESCE(visibility, 'peer_visible') != 'local_only'
                ORDER BY event_order ASC
                """,
                (session_id,),
            )
        for row in cur.fetchall():
            e_id, s_id, kind_str, c_at, actor, e_ord, p_json = row
            if e_id in seen:
                continue

            try:
                p_class = map_event_kind_to_presentation_class(kind_str)
            except ValueError:
                # Unrecognized event kind fallback: surface safely under security presentation class rather than dropping
                p_class = "security"

            content_str = _parse_payload_content(p_json, vault_key)

            events.append(
                UiEvent(
                    event_id=e_id,
                    session_id=s_id,
                    kind=kind_str,
                    created_at=c_at,
                    actor_username=actor,
                    presentation_class=p_class,
                    event_order=e_ord,
                    content=content_str,
                )
            )

        # 2. Query audit_events table for session_id using created_at cursor if provided
        if after_created_at is not None:
            cur.execute(
                """
                SELECT audit_id, session_id, category, created_at, actor_username, summary
                FROM audit_events
                WHERE session_id = ? AND created_at >= ?
                """,
                (session_id, after_created_at),
            )
        else:
            cur.execute(
                """
                SELECT audit_id, session_id, category, created_at, actor_username, summary
                FROM audit_events
                WHERE session_id = ?
                """,
                (session_id,),
            )
        for row in cur.fetchall():
            a_id, s_id, cat, c_at, actor, summ = row
            if cat.startswith("session_event_"):
                # Skip mirror rows to prevent double-counting session_events
                continue
            if a_id in seen:
                continue

            try:
                evt = UiEvent.from_audit_event(
                    audit_id=a_id,
                    session_id=s_id or session_id,
                    category=cat,
                    created_at=c_at,
                    actor_username=actor,
                    summary=summ or "",
                )
            except ValueError:
                # Unrecognized audit category fallback: surface safely under security presentation class
                evt = UiEvent(
                    event_id=a_id,
                    session_id=s_id or session_id,
                    kind=cat,
                    created_at=c_at,
                    actor_username=actor,
                    presentation_class="security",
                )
            events.append(evt)

        # Sort combined events strictly by ISO created_at timestamp
        events.sort(key=lambda e: e.created_at)
        return events
    finally:
        conn.close()


def get_session_events_page(
    profile_dir: Path,
    session_id: str,
    profile_name: str = "default",
    *,
    page_size: int = 500,
    before_event_order: Optional[int] = None,
) -> Tuple[List[UiEvent], bool]:
    """Return one newest-first SQL page, presented in stable ascending order.

    The extra fetched row is used only to report whether an older page exists.
    Local-only events are excluded at the query boundary.
    """
    if not 1 <= page_size <= 2_000:
        raise ValueError("page_size must be between 1 and 2000")
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return [], False
    conn = ensure_profile_db(db_path)
    vault_key = None
    try:
        try:
            from kin.identity.storage import get_or_create_vault_key
            vault_key = get_or_create_vault_key(profile_name)
        except Exception:
            pass
        if before_event_order is not None:
            rows = conn.execute(
                """SELECT event_id, session_id, kind, created_at, actor_username,
                          event_order, payload_json
                   FROM session_events
                   WHERE session_id = ? AND event_order < ?
                     AND COALESCE(visibility, 'peer_visible') != 'local_only'
                   ORDER BY event_order DESC
                   LIMIT ?""",
                (session_id, before_event_order, page_size + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT event_id, session_id, kind, created_at, actor_username,
                          event_order, payload_json
                   FROM session_events
                   WHERE session_id = ?
                     AND COALESCE(visibility, 'peer_visible') != 'local_only'
                   ORDER BY event_order DESC
                   LIMIT ?""",
                (session_id, page_size + 1),
            ).fetchall()
        has_older = len(rows) > page_size
        rows = rows[:page_size]
        events: List[UiEvent] = []
        for e_id, s_id, kind_str, created_at, actor, event_order, payload_json in reversed(rows):
            try:
                presentation_class = map_event_kind_to_presentation_class(kind_str)
            except ValueError:
                presentation_class = "security"
            events.append(
                UiEvent(
                    event_id=e_id,
                    session_id=s_id,
                    kind=kind_str,
                    created_at=created_at,
                    actor_username=actor,
                    presentation_class=presentation_class,
                    event_order=event_order,
                    content=_parse_payload_content(payload_json, vault_key),
                )
            )
        return events, has_older
    finally:
        conn.close()


def get_private_notes(
    profile_dir: Path,
    session_id: str,
    profile_name: str = "default",
) -> List[PrivateNoteView]:
    """Return decrypted owner-only notes without projecting them as timeline events."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.storage.vault import decrypt_field

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return []

    try:
        vault_key = get_or_create_vault_key(profile_name)
    except Exception:
        return []
    conn = ensure_profile_db(db_path)
    notes: List[PrivateNoteView] = []
    try:
        rows = conn.execute(
            """
            SELECT event_id, session_id, actor_username, payload_json, created_at, event_order
            FROM session_events
            WHERE session_id = ? AND kind = ? AND visibility = 'local_only'
            ORDER BY event_order ASC
            """,
            (session_id, InternalEventKind.PRIVATE_NOTE.value),
        ).fetchall()
        for event_id, stored_session_id, actor, encrypted_payload, created_at, event_order in rows:
            try:
                decrypted = decrypt_field(vault_key, encrypted_payload)
                payload = json.loads(decrypted) if decrypted else {}
            except Exception:
                continue
            note_text = payload.get("content") if isinstance(payload, dict) else None
            if not isinstance(note_text, str):
                continue
            notes.append(
                PrivateNoteView(
                    event_id=event_id,
                    session_id=stored_session_id,
                    actor_username=actor,
                    note_text=note_text,
                    created_at=created_at,
                    event_order=event_order,
                )
            )
        return notes
    finally:
        conn.close()


def get_session_history_events(
    profile_dir: Path,
    session_id: str,
    profile_name: str = "default",
) -> List[UiEvent]:
    """Project owner-local checkpoints, decisions, and outcomes into Arena lanes."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.storage.vault import decrypt_field

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return []
    try:
        vault_key = get_or_create_vault_key(profile_name)
    except Exception:
        return []
    conn = ensure_profile_db(db_path)
    events: List[UiEvent] = []
    try:
        rows = conn.execute(
            """SELECT event_id, kind, created_at, actor_username, event_order, payload_json
               FROM session_events
               WHERE session_id = ? AND visibility = 'local_only'
                 AND kind IN (?, ?, ?)
               ORDER BY event_order ASC""",
            (
                session_id,
                InternalEventKind.CHECKPOINT.value,
                InternalEventKind.DECISION.value,
                InternalEventKind.OUTCOME.value,
            ),
        ).fetchall()
        for event_id, kind, created_at, actor, event_order, encrypted_payload in rows:
            try:
                payload = json.loads(decrypt_field(vault_key, encrypted_payload) or "{}")
            except Exception:
                continue
            content = (
                payload.get("content")
                or payload.get("summary")
                or payload.get("label")
                or ""
            )
            events.append(
                UiEvent(
                    event_id=event_id,
                    session_id=session_id,
                    kind=kind,
                    created_at=created_at,
                    actor_username=actor,
                    presentation_class=map_event_kind_to_presentation_class(kind),
                    event_order=event_order,
                    content=content,
                )
            )
        return events
    finally:
        conn.close()


def get_session_outcome_card(
    profile_dir: Path,
    session_id: str,
    profile_name: str = "default",
):
    """Load the real persisted OutcomeCard backend object for Arena."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.session.history import get_outcome_card

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return None
    try:
        vault_key = get_or_create_vault_key(profile_name)
    except Exception:
        return None
    conn = ensure_profile_db(db_path)
    try:
        return get_outcome_card(conn, vault_key, session_id)
    finally:
        conn.close()


def create_session_checkpoint(
    profile_dir: Path,
    profile_name: str,
    session_id: str,
    created_by: str,
    label: str,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Persist an owner-local checkpoint through the M7 history backend."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.session.history import create_checkpoint

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database file not found.",
            impact="Checkpoint was not created.",
            preserved="Session history remains unchanged.",
            next_action="Initialize the profile first.",
        )
    conn = ensure_profile_db(db_path)
    try:
        create_checkpoint(
            conn,
            get_or_create_vault_key(profile_name),
            session_id=session_id,
            created_by=created_by,
            label=label,
        )
        return True, None
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to create checkpoint: {exc}",
            impact="No checkpoint was added.",
            preserved="Existing session evidence remains intact.",
            next_action="Refresh the Arena and retry.",
        )
    finally:
        conn.close()


def create_session_decision(
    profile_dir: Path,
    profile_name: str,
    session_id: str,
    decided_by: str,
    summary: str,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Persist an ordered owner-local decision through the M7 history backend."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.session.history import create_decision

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database file not found.",
            impact="Decision was not recorded.",
            preserved="Session history remains unchanged.",
            next_action="Initialize the profile first.",
        )
    conn = ensure_profile_db(db_path)
    try:
        create_decision(
            conn,
            get_or_create_vault_key(profile_name),
            session_id=session_id,
            decided_by=decided_by,
            summary=summary,
        )
        return True, None
    except Exception as exc:
        return False, RecoverableError(
            what_happened=f"Failed to record decision: {exc}",
            impact="No decision was added.",
            preserved="Existing session evidence remains intact.",
            next_action="Refresh the Arena and retry.",
        )
    finally:
        conn.close()


def create_fresh_session_rerun(
    profile_dir: Path,
    profile_name: str,
    source_session_id: str,
    created_by: str,
) -> Tuple[bool, Optional[str], Optional[RecoverableError]]:
    """Create a fresh-authority draft with no copied approval rows."""
    from kin.identity.storage import get_or_create_vault_key
    from kin.session.history import create_fresh_authority_rerun

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, None, RecoverableError(
            what_happened="Database file not found.",
            impact="Rerun draft was not created.",
            preserved="Source session remains unchanged.",
            next_action="Initialize the profile first.",
        )
    conn = ensure_profile_db(db_path)
    try:
        rerun = create_fresh_authority_rerun(
            conn,
            get_or_create_vault_key(profile_name),
            source_session_id=source_session_id,
            created_by=created_by,
        )
        return True, rerun.rerun_session_id, None
    except Exception as exc:
        return False, None, RecoverableError(
            what_happened=f"Failed to create fresh-authority rerun: {exc}",
            impact="No rerun draft was created.",
            preserved="Source session and approvals remain unchanged.",
            next_action="Refresh the Arena and retry.",
        )
    finally:
        conn.close()


def get_session_budget_gauges(
    profile_dir: Path,
    profile_name: str,
    session_id: str,
):
    """Load informative gauges from the same persisted budgets enforced by orchestration."""
    from kin.collaboration_depth import budget_gauges
    from kin.identity.storage import get_or_create_vault_key

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return None
    conn = ensure_profile_db(db_path)
    try:
        return budget_gauges(conn, get_or_create_vault_key(profile_name), session_id)
    except Exception:
        return None
    finally:
        conn.close()


def create_session_playbook(
    profile_dir: Path,
    profile_name: str,
    session_id: str,
    name: str,
) -> Tuple[bool, Optional[str], Optional[RecoverableError]]:
    """Create an encrypted local playbook from a persisted completed outcome."""
    from kin.collaboration_depth import create_playbook_from_session
    from kin.identity.storage import get_or_create_vault_key

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, None, RecoverableError(
            what_happened="Database file not found.",
            impact="Playbook was not created.",
            preserved="Session outcome remains unchanged.",
            next_action="Initialize the profile first.",
        )
    conn = ensure_profile_db(db_path)
    try:
        playbook = create_playbook_from_session(
            conn,
            get_or_create_vault_key(profile_name),
            session_id=session_id,
            name=name,
        )
        return True, playbook.playbook_id, None
    except Exception as exc:
        return False, None, RecoverableError(
            what_happened=f"Playbook creation failed: {exc}",
            impact="No reusable template was created.",
            preserved="Session history and authority remain unchanged.",
            next_action="Create a playbook only after a completed outcome is available.",
        )
    finally:
        conn.close()


def get_artifacts_for_session(
    profile_dir: Path, session_id: str, profile_name: str = "default"
) -> List[ArtifactView]:
    """Query artifacts table for a session and map to List[ArtifactView] (§14.8 Phase A)."""
    from kin.artifacts.vault import ArtifactMetadata

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return []

    conn = ensure_profile_db(db_path)
    views: List[ArtifactView] = []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT artifact_id, sha256, mime_type, metadata_json, offered_by, created_at, LENGTH(COALESCE(bytes_encrypted, ''))
            FROM artifacts
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        for row in cur.fetchall():
            art_id, sha, mime, meta_json, off_by, c_at, sz_bytes = row
            meta_obj = None
            if meta_json:
                try:
                    import json
                    m_data = json.loads(meta_json)
                    meta_obj = ArtifactMetadata(
                        artifact_id=m_data.get("artifact_id", art_id),
                        session_id=m_data.get("session_id", session_id),
                        sha256=m_data.get("sha256", sha),
                        mime_type=m_data.get("mime_type", mime),
                        size_bytes=m_data.get("size_bytes", sz_bytes),
                        offered_by=m_data.get("offered_by", off_by),
                        preview_policy=m_data.get("preview_policy", "text"),
                        created_at=m_data.get("created_at", c_at),
                        source=m_data.get("source", "adapter_output"),
                    )
                except Exception:
                    meta_obj = None

            if not meta_obj:
                meta_obj = ArtifactMetadata(
                    artifact_id=art_id,
                    session_id=session_id,
                    sha256=sha,
                    mime_type=mime,
                    size_bytes=sz_bytes,
                    offered_by=off_by,
                    preview_policy="text",
                    created_at=c_at,
                    source="adapter_output",
                )
            views.append(ArtifactView.from_metadata(meta_obj))
        return views
    finally:
        conn.close()


def get_approvals_for_session(
    profile_dir: Path, session_id: str, profile_name: str = "default"
) -> List[ApprovalView]:
    """Query approvals table for session history, INCLUDING decided approvals (§14.8 Phase A)."""
    from kin.schemas import ActionClass, ApprovalDecision, ApprovalRequest, DecisionKind, RiskLabel

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return []

    conn = ensure_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)
    views: List[ApprovalView] = []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT approval_id, agent_id, action_class, request_json, expires_at, decision, decided_at
            FROM approvals
            WHERE session_id = ?
            ORDER BY expires_at ASC
            """,
            (session_id,),
        )
        for row in cur.fetchall():
            app_id, agent_id, act_class, req_json, exp_at, dec_str, dec_at = row
            req_obj = None
            if req_json:
                try:
                    req_obj = ApprovalRequest.model_validate_json(
                        decrypt_field_or_plaintext(vault_key, req_json)
                    )
                except Exception:
                    req_obj = None

            if not req_obj:
                try:
                    try:
                        act_enum = ActionClass(act_class) if act_class else ActionClass.WORKSPACE_WRITE
                    except Exception:
                        act_enum = ActionClass.WORKSPACE_WRITE

                    req_obj = ApprovalRequest(
                        schema_version="1.1",
                        approval_id=app_id,
                        session_id=session_id,
                        agent_id=agent_id or "agent-unknown",
                        action_class=act_enum,
                        summary=f"Approval request {app_id[:8]}",
                        reason=f"Approval request {app_id[:8]}",
                        risk_label=RiskLabel.MEDIUM,
                        requested_scope={},
                        expires_at=exp_at if (exp_at and exp_at.endswith("Z")) else "2026-08-01T00:00:00Z",
                    )
                except Exception:
                    continue

            dec_obj: Optional[ApprovalDecision] = None
            if dec_str:
                try:
                    d_kind = DecisionKind(dec_str)
                except ValueError:
                    d_kind = DecisionKind.DENY if "deny" in str(dec_str).lower() else DecisionKind.APPROVE_ONCE

                dec_obj = ApprovalDecision(
                    schema_version="1.1",
                    approval_id=app_id,
                    session_id=session_id,
                    decision=d_kind,
                    decided_at=dec_at if (dec_at and dec_at.endswith("Z")) else (exp_at if (exp_at and exp_at.endswith("Z")) else "2026-08-01T00:00:00Z"),
                    decided_by="owner",
                )

            views.append(ApprovalView(request=req_obj, decision=dec_obj))
        return views
    finally:
        conn.close()


def get_agent_card_by_id(profile_dir: Path, agent_id: str, profile_name: str = "default") -> Optional[Any]:
    """Load AgentCard by agent_id from profile's agents directory."""
    from kin.agent_registry.registry import scan_local_cards
    agents_dir = profile_dir / "agents"
    valid_cards, _, _ = scan_local_cards(agents_dir, profile_name=profile_name)
    for card in valid_cards:
        if card.id == agent_id:
            return card
    return None


def import_artifact_action(
    profile_dir: Path,
    profile_name: str = "default",
    *,
    session_id: str,
    artifact_id: str,
    relative_target_path: str,
    workspace_root: Optional[Union[str, Path]] = None,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Import raw artifact bytes into the workspace target path with owner permission check (§14.8 Phase D)."""
    from kin.artifacts.workspace import (
        import_artifact_to_workspace,
        UnsafeWorkspacePathError,
        WorkspaceNotConfiguredError,
        WorkspaceWritePermissionDeniedError,
        InvalidPatchArtifactError,
    )
    from kin.identity.storage import get_or_create_vault_key
    from kin.tui.errors import convert_exception_to_recoverable_error

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database not found",
            impact="Cannot verify artifact session ownership.",
            preserved="No workspace files modified.",
            next_action="Ensure profile database exists.",
        )

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT session_id, offered_by FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        row = cur.fetchone()
        if not row or row[0] != session_id:
            return False, RecoverableError(
                what_happened=f"Artifact ownership mismatch: '{artifact_id}' does not belong to session '{session_id}'.",
                impact="Import rejected for session boundary security.",
                preserved="No workspace files modified.",
                next_action="Select an artifact belonging to the active session.",
            )

        offered_by_agent_id = row[1] or "unknown_agent"
        card = get_agent_card_by_id(profile_dir, offered_by_agent_id, profile_name=profile_name)
        if not card:
            return False, RecoverableError(
                what_happened=f"Agent card not found for offering agent '{offered_by_agent_id}'.",
                impact="Cannot confirm this action is authorized.",
                preserved="No workspace files modified.",
                next_action=f"Ensure the offering agent's card for '{offered_by_agent_id}' is registered in profile agents directory.",
            )

        vault_key = get_or_create_vault_key(profile_name)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        target_root = workspace_root or (profile_dir / "workspace")

        import_artifact_to_workspace(
            conn,
            vault_key,
            card,
            session_id,
            artifact_id,
            target_root,
            relative_target_path,
            now_iso,
        )
        return True, None

    except UnsafeWorkspacePathError as exc:
        return False, RecoverableError(
            what_happened=f"Unsafe Workspace Path Error: {exc}",
            impact="Import halted to prevent path traversal.",
            preserved="Target workspace remains intact.",
            next_action="Provide a valid relative target path inside the workspace root.",
        )
    except WorkspaceNotConfiguredError as exc:
        return False, RecoverableError(
            what_happened=f"Workspace Not Configured Error: {exc}",
            impact="Import halted because agent adapter has no workspace working directory.",
            preserved="Target workspace remains intact.",
            next_action="Configure local_command adapter working_directory.",
        )
    except WorkspaceWritePermissionDeniedError as exc:
        return False, RecoverableError(
            what_happened=f"Workspace Write Permission Denied: {exc}",
            impact="Import action requires prior owner approval.",
            preserved="Target workspace remains intact.",
            next_action="Submit an approval decision in the Needs-You queue first.",
        )
    except InvalidPatchArtifactError as exc:
        return False, RecoverableError(
            what_happened=f"Invalid Patch Artifact Error: {exc}",
            impact="Artifact file format invalid.",
            preserved="Target workspace remains intact.",
            next_action="Verify artifact content.",
        )
    except Exception as exc:
        rec_err = convert_exception_to_recoverable_error(exc, profile_dir)
        return False, rec_err
    finally:
        conn.close()


def apply_patch_action(
    profile_dir: Path,
    profile_name: str = "default",
    *,
    session_id: str,
    artifact_id: str,
    relative_target_path: str,
    workspace_root: Optional[Union[str, Path]] = None,
) -> Tuple[bool, Optional[RecoverableError]]:
    """Apply a unified diff patch artifact to a workspace target file with owner permission check (§14.8 Phase D)."""
    from kin.artifacts.workspace import (
        apply_patch_to_workspace,
        UnsafeWorkspacePathError,
        WorkspaceNotConfiguredError,
        WorkspaceWritePermissionDeniedError,
        InvalidPatchArtifactError,
    )
    from kin.identity.storage import get_or_create_vault_key
    from kin.tui.errors import convert_exception_to_recoverable_error

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return False, RecoverableError(
            what_happened="Database not found",
            impact="Cannot verify artifact session ownership.",
            preserved="No workspace files modified.",
            next_action="Ensure profile database exists.",
        )

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT session_id, offered_by FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        row = cur.fetchone()
        if not row or row[0] != session_id:
            return False, RecoverableError(
                what_happened=f"Artifact ownership mismatch: '{artifact_id}' does not belong to session '{session_id}'.",
                impact="Patch apply rejected for session boundary security.",
                preserved="No workspace files modified.",
                next_action="Select an artifact belonging to the active session.",
            )

        offered_by_agent_id = row[1] or "unknown_agent"
        card = get_agent_card_by_id(profile_dir, offered_by_agent_id, profile_name=profile_name)
        if not card:
            return False, RecoverableError(
                what_happened=f"Agent card not found for offering agent '{offered_by_agent_id}'.",
                impact="Cannot confirm this action is authorized.",
                preserved="No workspace files modified.",
                next_action=f"Ensure the offering agent's card for '{offered_by_agent_id}' is registered in profile agents directory.",
            )

        vault_key = get_or_create_vault_key(profile_name)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        target_root = workspace_root or (profile_dir / "workspace")

        apply_patch_to_workspace(
            conn,
            vault_key,
            card,
            session_id,
            artifact_id,
            target_root,
            relative_target_path,
            now_iso,
        )
        return True, None

    except UnsafeWorkspacePathError as exc:
        return False, RecoverableError(
            what_happened=f"Unsafe Workspace Path Error: {exc}",
            impact="Patch application halted to prevent path traversal.",
            preserved="Target workspace remains intact.",
            next_action="Provide a valid relative target path inside the workspace root.",
        )
    except WorkspaceNotConfiguredError as exc:
        return False, RecoverableError(
            what_happened=f"Workspace Not Configured Error: {exc}",
            impact="Patch application halted because agent adapter has no workspace working directory.",
            preserved="Target workspace remains intact.",
            next_action="Configure local_command adapter working_directory.",
        )
    except WorkspaceWritePermissionDeniedError as exc:
        return False, RecoverableError(
            what_happened=f"Workspace Write Permission Denied: {exc}",
            impact="Patch application action requires prior owner approval.",
            preserved="Target workspace remains intact.",
            next_action="Submit an approval decision in the Needs-You queue first.",
        )
    except InvalidPatchArtifactError as exc:
        return False, RecoverableError(
            what_happened=f"Invalid Patch Artifact Error: {exc}",
            impact="Target file content does not match patch context or deletion lines.",
            preserved="Target workspace remains intact.",
            next_action="Ensure target file is not stale or drifted.",
        )
    except Exception as exc:
        rec_err = convert_exception_to_recoverable_error(exc, profile_dir)
        return False, rec_err
    finally:
        conn.close()


def preview_patch_action(
    profile_dir: Path,
    profile_name: str = "default",
    *,
    artifact_id: str,
    relative_target_path: str,
    workspace_root: Optional[Union[str, Path]] = None,
) -> Tuple[Optional[Any], Optional[RecoverableError]]:
    """Generate read-only preview of patch application without modifying disk (§14.8 Phase D)."""
    from kin.artifacts.workspace import preview_patch_apply, InvalidPatchArtifactError, UnsafeWorkspacePathError
    from kin.identity.storage import get_or_create_vault_key

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        return None, RecoverableError(
            what_happened="Database not found",
            impact="Cannot load artifact.",
            preserved="No workspace files modified.",
            next_action="Ensure profile DB exists.",
        )

    conn = sqlite3.connect(db_path)
    try:
        vault_key = get_or_create_vault_key(profile_name)
        target_root = workspace_root or (profile_dir / "workspace")
        preview = preview_patch_apply(conn, vault_key, artifact_id, target_root, relative_target_path)
        return preview, None
    except Exception as exc:
        return None, RecoverableError(
            what_happened=f"Patch preview error: {exc}",
            impact="Cannot generate patch preview.",
            preserved="No workspace files modified.",
            next_action="Check patch artifact format.",
        )
    finally:
        conn.close()
