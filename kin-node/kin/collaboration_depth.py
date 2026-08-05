"""Real M7 readiness, reservations, playbooks, quality, and budget gauges."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field

from kin.agent_registry.availability import AVAILABILITY_EXPLANATIONS
from kin.schemas import AgentAvailability, PublishedAgentCard
from kin.storage.vault import decrypt_field, decrypt_field_or_plaintext, encrypt_field


def _utc(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _plain_or_decrypted(vault_key: bytes, value: str | None) -> str:
    return decrypt_field_or_plaintext(vault_key, value) or ""


class ReadinessRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    name: str
    availability: AgentAvailability
    recommended: bool
    explanation: str


class AgentReservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_id: str
    agent_id: str
    owner_username: str
    starts_at: str
    ends_at: str
    status: str = "active"


class LocalQualitySignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    completed_sessions: int = Field(ge=0)
    total_sessions: int = Field(ge=0)
    completion_rate: float = Field(ge=0, le=1)
    average_duration_seconds: float | None = Field(default=None, ge=0)


class Playbook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.1"
    playbook_id: str
    name: str
    source_session_id: str | None = None
    session_type: str
    objective_template: str
    required_peer_capabilities: list[str] = Field(default_factory=list)
    turn_limit: int
    runtime_budget_seconds: int | None = None
    artifact_bytes_budget: int | None = None
    cost_budget_estimate: float | None = None
    approval_defaults: dict[str, str] = Field(
        default_factory=lambda: {"consequential_actions": "always_ask"}
    )


class PlaybookDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook_id: str
    session_type: str
    objective: str
    sender_agent_id: str
    peer_username: str
    receiver_agent_id: str
    turn_limit: int
    runtime_budget_seconds: int | None
    artifact_bytes_budget: int | None
    cost_budget_estimate: float | None
    status: str = "draft"
    carried_approval_count: int = 0


class BudgetGaugeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    elapsed_seconds: float = Field(ge=0)
    runtime_limit_seconds: int | None
    runtime_fraction: float | None
    artifact_bytes: int = Field(ge=0)
    artifact_limit_bytes: int | None
    artifact_fraction: float | None
    local_cost_estimate: float | None
    local_cost_limit: float | None
    cost_fraction: float | None
    peer_cost_summary: str | None = None


def reserve_agent(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    owner_username: str,
    starts_at: str,
    ends_at: str,
) -> AgentReservation:
    start, end = _utc(starts_at), _utc(ends_at)
    if end <= start:
        raise ValueError("Reservation end must be after its start.")
    if conn.execute("SELECT 1 FROM agents WHERE agent_id = ?", (agent_id,)).fetchone() is None:
        raise ValueError("The selected agent does not exist.")
    overlap = conn.execute(
        """SELECT 1 FROM agent_reservations
           WHERE agent_id = ? AND status = 'active'
             AND starts_at < ? AND ends_at > ? LIMIT 1""",
        (agent_id, _iso(end), _iso(start)),
    ).fetchone()
    if overlap:
        raise ValueError("The selected agent is already reserved in that time window.")
    reservation = AgentReservation(
        reservation_id=f"res_{uuid.uuid4().hex}",
        agent_id=agent_id,
        owner_username=owner_username,
        starts_at=_iso(start),
        ends_at=_iso(end),
    )
    conn.execute(
        """INSERT INTO agent_reservations
               (reservation_id, agent_id, owner_username, starts_at, ends_at, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'active', ?)""",
        (
            reservation.reservation_id,
            agent_id,
            owner_username,
            reservation.starts_at,
            reservation.ends_at,
            _iso(),
        ),
    )
    conn.commit()
    return reservation


def readiness_recommendations(
    conn: sqlite3.Connection,
    *,
    at: datetime | None = None,
) -> list[ReadinessRecommendation]:
    moment = _iso(at)
    rows = conn.execute(
        "SELECT agent_id, name, availability, enabled FROM agents ORDER BY name, agent_id"
    ).fetchall()
    recommendations: list[ReadinessRecommendation] = []
    for agent_id, name, stored, enabled in rows:
        if not enabled:
            availability = AgentAvailability.POLICY_BLOCKED
        elif conn.execute(
            """SELECT 1 FROM agent_reservations
               WHERE agent_id = ? AND status = 'active' AND starts_at <= ? AND ends_at > ?""",
            (agent_id, moment, moment),
        ).fetchone():
            availability = AgentAvailability.RESERVED
        else:
            try:
                availability = AgentAvailability(stored)
            except ValueError:
                availability = AgentAvailability.OFFLINE
        recommendations.append(
            ReadinessRecommendation(
                agent_id=agent_id,
                name=name,
                availability=availability,
                recommended=availability == AgentAvailability.READY,
                explanation=AVAILABILITY_EXPLANATIONS[availability],
            )
        )
    return sorted(recommendations, key=lambda item: (not item.recommended, item.name, item.agent_id))


def local_quality_signal(conn: sqlite3.Connection, agent_id: str) -> LocalQualitySignal:
    rows = conn.execute(
        """SELECT status, created_at, updated_at FROM sessions
           WHERE sender_agent_id = ? OR receiver_agent_id = ?""",
        (agent_id, agent_id),
    ).fetchall()
    completed = [row for row in rows if row[0] == "completed"]
    durations = [max(0.0, (_utc(row[2]) - _utc(row[1])).total_seconds()) for row in completed]
    return LocalQualitySignal(
        agent_id=agent_id,
        completed_sessions=len(completed),
        total_sessions=len(rows),
        completion_rate=(len(completed) / len(rows)) if rows else 0.0,
        average_duration_seconds=(sum(durations) / len(durations)) if durations else None,
    )


def create_playbook_from_session(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    session_id: str,
    name: str,
) -> Playbook:
    row = conn.execute(
        """SELECT type, status, objective, receiver_username, receiver_agent_id,
                  turn_limit, runtime_budget_seconds, artifact_bytes_budget,
                  cost_budget_estimate
           FROM sessions WHERE session_id = ?""",
        (session_id,),
    ).fetchone()
    if row is None or row[1] != "completed":
        raise ValueError("A playbook can only be created from a completed session.")
    if conn.execute(
        "SELECT 1 FROM session_events WHERE session_id = ? AND kind = 'outcome'",
        (session_id,),
    ).fetchone() is None:
        raise ValueError("A persisted outcome card is required before creating a playbook.")
    peer_card = conn.execute(
        "SELECT card_json FROM peer_agent_cards WHERE peer_username = ? AND agent_id = ?",
        (row[3], row[4]),
    ).fetchone()
    capabilities: list[str] = []
    if peer_card:
        capabilities = PublishedAgentCard.model_validate_json(peer_card[0]).capabilities.tags
    playbook = Playbook(
        playbook_id=f"pb_{uuid.uuid4().hex}",
        name=name.strip() or "Session playbook",
        source_session_id=session_id,
        session_type=row[0],
        objective_template=_plain_or_decrypted(vault_key, row[2]),
        required_peer_capabilities=capabilities,
        turn_limit=row[5],
        runtime_budget_seconds=row[6],
        artifact_bytes_budget=row[7],
        cost_budget_estimate=row[8],
    )
    now = _iso()
    conn.execute(
        """INSERT INTO playbooks
               (playbook_id, name, source_session_id, template_json_enc, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            playbook.playbook_id,
            playbook.name,
            session_id,
            encrypt_field(vault_key, playbook.model_dump_json()),
            now,
            now,
        ),
    )
    conn.commit()
    return playbook


def open_playbook_draft(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    playbook_id: str,
    sender_agent_id: str,
    peer_username: str,
    receiver_agent_id: str,
) -> PlaybookDraft:
    row = conn.execute(
        "SELECT template_json_enc FROM playbooks WHERE playbook_id = ?", (playbook_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Playbook not found.")
    playbook = Playbook.model_validate_json(decrypt_field(vault_key, row[0]) or "{}")
    local = conn.execute(
        "SELECT enabled, availability FROM agents WHERE agent_id = ?", (sender_agent_id,)
    ).fetchone()
    if local is None or not local[0] or local[1] in {"policy_blocked", "offline", "needs_key", "needs_workspace"}:
        raise ValueError("Selected local agent is not compatible with current local policy/readiness.")
    peer = conn.execute(
        """SELECT card_json, status FROM peer_agent_cards
           WHERE peer_username = ? AND agent_id = ?""",
        (peer_username, receiver_agent_id),
    ).fetchone()
    if peer is None:
        raise ValueError("Selected peer agent card is unavailable.")
    if peer[1] == "stale":
        raise ValueError("Selected peer agent card is stale and requires owner review.")
    card = PublishedAgentCard.model_validate_json(peer[0])
    missing = sorted(set(playbook.required_peer_capabilities) - set(card.capabilities.tags))
    if missing:
        raise ValueError("Selected peer agent does not satisfy the playbook capability requirements.")
    return PlaybookDraft(
        playbook_id=playbook_id,
        session_type=playbook.session_type,
        objective=playbook.objective_template,
        sender_agent_id=sender_agent_id,
        peer_username=peer_username,
        receiver_agent_id=receiver_agent_id,
        turn_limit=playbook.turn_limit,
        runtime_budget_seconds=playbook.runtime_budget_seconds,
        artifact_bytes_budget=playbook.artifact_bytes_budget,
        cost_budget_estimate=playbook.cost_budget_estimate,
    )


def budget_gauges(
    conn: sqlite3.Connection,
    vault_key: bytes,
    session_id: str,
    *,
    at: datetime | None = None,
) -> BudgetGaugeSnapshot:
    row = conn.execute(
        """SELECT created_at, updated_at, status, runtime_budget_seconds,
                  artifact_bytes_budget, cumulative_artifact_bytes,
                  cost_budget_estimate, cumulative_cost_estimate
           FROM sessions WHERE session_id = ?""",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Session not found.")
    end = _utc(row[1]) if row[2] in {"completed", "failed", "cancelled", "expired", "declined"} else _utc(at)
    elapsed = max(0.0, (end - _utc(row[0])).total_seconds())
    runtime_fraction = elapsed / row[3] if row[3] else None
    artifact_fraction = row[5] / row[4] if row[4] else None
    local_cost = row[7] if row[7] > 0 else None
    cost_fraction = local_cost / row[6] if local_cost is not None and row[6] else None

    peer_cost_summary = None
    event_rows = conn.execute(
        """SELECT payload_json FROM session_events
           WHERE session_id = ? AND kind = 'final_result' ORDER BY event_order DESC""",
        (session_id,),
    ).fetchall()
    for event_row in event_rows:
        try:
            payload = json.loads(decrypt_field(vault_key, event_row[0]) or "{}")
        except Exception:
            continue
        explicit = payload.get("peer_cost_summary")
        if isinstance(explicit, str) and explicit.strip():
            peer_cost_summary = explicit.strip()
            break
    return BudgetGaugeSnapshot(
        session_id=session_id,
        elapsed_seconds=elapsed,
        runtime_limit_seconds=row[3],
        runtime_fraction=runtime_fraction,
        artifact_bytes=row[5],
        artifact_limit_bytes=row[4],
        artifact_fraction=artifact_fraction,
        local_cost_estimate=local_cost,
        local_cost_limit=row[6],
        cost_fraction=cost_fraction,
        peer_cost_summary=peer_cost_summary,
    )
