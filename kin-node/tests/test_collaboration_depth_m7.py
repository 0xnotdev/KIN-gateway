"""M7 Slice 4 tests over real readiness, playbook, and budget primitives."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

import pytest

from kin.agent_registry.peer_cards import cache_peer_card
from kin.audit.writer import append_session_event
from kin.collaboration_depth import (
    budget_gauges,
    create_playbook_from_session,
    local_quality_signal,
    open_playbook_draft,
    readiness_recommendations,
    reserve_agent,
)
from kin.schemas import AgentAvailability, AgentCapabilities, PublishedAgentCard
from kin.session.history import create_outcome_card
from kin.storage.migrations import run_migrations


VAULT_KEY = b"\x41" * 32


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    now = "2026-08-05T09:00:00Z"
    conn.executemany(
        """INSERT INTO agents
               (agent_id, name, adapter_type, enabled, availability, created_at, updated_at)
           VALUES (?, ?, 'embedded', ?, ?, ?, ?)""",
        [
            ("ag_ready", "Ready Agent", 1, "ready", now, now),
            ("ag_disabled", "Disabled Agent", 0, "ready", now, now),
        ],
    )
    conn.commit()
    return conn


def _peer_card(tags: list[str]) -> PublishedAgentCard:
    return PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="ag_peer",
        name="Peer Reviewer",
        description="Reviews release evidence",
        capabilities=AgentCapabilities(tags=tags, accepts=["text/plain"], produces=["text/markdown"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )


def _completed_session(conn: sqlite3.Connection, session_id: str = "sess_depth") -> None:
    conn.execute(
        """INSERT INTO sessions (
               session_id, type, initiator_username, receiver_username, status,
               objective, sender_agent_id, receiver_agent_id, turn_limit,
               runtime_budget_seconds, artifact_bytes_budget, cumulative_artifact_bytes,
               cost_budget_estimate, cumulative_cost_estimate, created_at, updated_at
           ) VALUES (?, 'review', 'alice', 'bob', 'completed', ?, 'ag_ready', 'ag_peer',
                     8, 3600, 10000, 2500, 4.0, 1.25, ?, ?)""",
        (
            session_id,
            "Repeat the reviewed release gate",
            "2026-08-05T09:00:00Z",
            "2026-08-05T09:10:00Z",
        ),
    )
    conn.commit()
    append_session_event(
        conn,
        VAULT_KEY,
        session_id=session_id,
        actor_username="bob",
        actor_agent_id="ag_peer",
        kind="final_result",
        visibility="peer_visible",
        payload={"content": "Gate passed"},
        signature="persisted-peer-signature",
        sequence=1,
    )
    create_outcome_card(conn, VAULT_KEY, session_id=session_id, summary="Gate passed")


def test_reservation_changes_real_readiness_with_one_sentence_explanation() -> None:
    conn = _db()
    at = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    reserve_agent(
        conn,
        agent_id="ag_ready",
        owner_username="alice",
        starts_at="2026-08-05T11:00:00Z",
        ends_at="2026-08-05T13:00:00Z",
    )
    recommendations = readiness_recommendations(conn, at=at)
    by_id = {item.agent_id: item for item in recommendations}

    assert by_id["ag_ready"].availability == AgentAvailability.RESERVED
    assert by_id["ag_ready"].recommended is False
    assert by_id["ag_ready"].explanation == "Reserved for a planned collaboration."
    assert by_id["ag_disabled"].availability == AgentAvailability.POLICY_BLOCKED
    assert by_id["ag_disabled"].explanation.endswith(".")
    with pytest.raises(ValueError, match="already reserved"):
        reserve_agent(
            conn,
            agent_id="ag_ready",
            owner_username="alice",
            starts_at="2026-08-05T12:30:00Z",
            ends_at="2026-08-05T13:30:00Z",
        )
    conn.close()


def test_local_quality_signal_is_derived_locally_and_never_published() -> None:
    conn = _db()
    _completed_session(conn)
    conn.execute(
        """INSERT INTO sessions
               (session_id, type, initiator_username, receiver_username, status,
                sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at)
           VALUES ('sess_failed', 'ask', 'alice', 'bob', 'failed',
                   'ag_ready', 'ag_peer', 4, '2026-08-05T10:00:00Z', '2026-08-05T10:02:00Z')"""
    )
    conn.commit()
    signal = local_quality_signal(conn, "ag_ready")
    assert signal.total_sessions == 2
    assert signal.completed_sessions == 1
    assert signal.completion_rate == 0.5
    assert signal.average_duration_seconds == 600.0
    assert "quality" not in _peer_card(["review"]).model_dump()
    conn.close()


def test_playbook_requires_fresh_compatible_cards_and_current_local_policy() -> None:
    conn = _db()
    cache_peer_card(conn, "bob", _peer_card(["review", "release-gate"]))
    _completed_session(conn)
    playbook = create_playbook_from_session(
        conn,
        VAULT_KEY,
        session_id="sess_depth",
        name="Reviewed release gate",
    )

    assert playbook.required_peer_capabilities == ["review", "release-gate"]
    assert "peer_username" not in type(playbook).model_fields
    assert "sender_agent_id" not in type(playbook).model_fields
    assert playbook.approval_defaults == {"consequential_actions": "always_ask"}

    conn.execute(
        "UPDATE peer_agent_cards SET status = 'stale' WHERE peer_username = 'bob' AND agent_id = 'ag_peer'"
    )
    conn.commit()
    with pytest.raises(ValueError, match="stale"):
        open_playbook_draft(
            conn,
            VAULT_KEY,
            playbook_id=playbook.playbook_id,
            sender_agent_id="ag_ready",
            peer_username="bob",
            receiver_agent_id="ag_peer",
        )

    conn.execute(
        "UPDATE peer_agent_cards SET status = 'fresh' WHERE peer_username = 'bob' AND agent_id = 'ag_peer'"
    )
    conn.execute("UPDATE agents SET enabled = 0 WHERE agent_id = 'ag_ready'")
    conn.commit()
    with pytest.raises(ValueError, match="local policy/readiness"):
        open_playbook_draft(
            conn,
            VAULT_KEY,
            playbook_id=playbook.playbook_id,
            sender_agent_id="ag_ready",
            peer_username="bob",
            receiver_agent_id="ag_peer",
        )

    conn.execute("UPDATE agents SET enabled = 1 WHERE agent_id = 'ag_ready'")
    conn.commit()
    draft = open_playbook_draft(
        conn,
        VAULT_KEY,
        playbook_id=playbook.playbook_id,
        sender_agent_id="ag_ready",
        peer_username="bob",
        receiver_agent_id="ag_peer",
    )
    assert draft.status == "draft"
    assert draft.carried_approval_count == 0
    assert draft.sender_agent_id == "ag_ready"
    assert draft.receiver_agent_id == "ag_peer"
    conn.close()


def test_budget_gauges_show_reported_local_estimate_and_hide_peer_cost_by_default() -> None:
    conn = _db()
    _completed_session(conn)
    gauges = budget_gauges(conn, VAULT_KEY, "sess_depth")
    assert gauges.elapsed_seconds == 600.0
    assert gauges.runtime_fraction == pytest.approx(1 / 6)
    assert gauges.artifact_fraction == 0.25
    assert gauges.local_cost_estimate == 1.25
    assert gauges.cost_fraction == 0.3125
    assert gauges.peer_cost_summary is None

    append_session_event(
        conn,
        VAULT_KEY,
        session_id="sess_depth",
        actor_username="bob",
        actor_agent_id="ag_peer",
        kind="final_result",
        visibility="peer_visible",
        payload={"content": "Explicit summary", "peer_cost_summary": "Approx. 900 tokens"},
        signature="persisted-peer-signature-2",
        sequence=2,
    )
    assert budget_gauges(conn, VAULT_KEY, "sess_depth").peer_cost_summary == "Approx. 900 tokens"

    conn.execute(
        "UPDATE sessions SET cumulative_cost_estimate = 0 WHERE session_id = 'sess_depth'"
    )
    conn.commit()
    unreported = budget_gauges(conn, VAULT_KEY, "sess_depth")
    assert unreported.local_cost_estimate is None
    assert unreported.cost_fraction is None
    conn.close()
