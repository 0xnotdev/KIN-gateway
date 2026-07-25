"""Unit tests for orchestrator event ordering (§15.7 and §2.5)."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.agent_registry.registry import register_card
from kin.schemas import (
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    AutonomyLevel,
    EmbeddedAdapterConfig,
)
from kin.session.orchestrator import advance_session_turn
from kin.storage.migrations import run_migrations


def _make_agent_card(agent_id: str, name: str) -> AgentCard:
    return AgentCard(
        schema_version="1.1",
        id=agent_id,
        name=name,
        description=name,
        adapter=EmbeddedAdapterConfig(type="embedded", provider="openai", model="gpt-4o"),
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="none", shell="deny", max_runtime_seconds=30, max_artifact_bytes=1048576),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ALLOW, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )


def test_orchestrator_local_activity_precedes_outbound_message():
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    vault_key = b"test-vault-key-32bytes-long!!!!!"
    alice_priv = ed25519.Ed25519PrivateKey.generate()

    register_card(conn, vault_key, _make_agent_card("alice_agent", "Alice Agent"))
    conn.execute("UPDATE agents SET enabled = 1 WHERE agent_id = 'alice_agent'")

    now_str = "2026-07-22T12:00:00Z"
    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES ('s_order_1', 'ask', 'alice', 'bob', 'active', 'alice_agent', 'bob_agent', 12, ?, ?)
        """,
        (now_str, now_str),
    )
    conn.commit()

    # Mock embedded adapter response
    mock_resp = MagicMock()
    mock_resp.error = None
    mock_resp.events = [MagicMock(event_kind="activity", label="Thinking step 1")]
    mock_resp.message = MagicMock(kind=MagicMock(value="proposal"), content="My proposal text")
    mock_resp.artifacts = []
    mock_resp.terminal = False
    mock_resp.model_dump.return_value = {}

    from unittest.mock import patch
    with patch("kin.session.orchestrator.get_adapter") as mock_get_adapter, \
         patch("kin.session.orchestrator.validate_adapter_output") as mock_val:

        mock_adapter = MagicMock()
        mock_adapter.invoke.return_value = mock_resp
        mock_get_adapter.return_value = mock_adapter

        mock_val_out = MagicMock()
        mock_val_out.valid = True
        mock_val.return_value = mock_val_out

        res = advance_session_turn(conn, vault_key, alice_priv, "alice", "s_order_1")
        assert res["status"] == "delivered"

    # Query events ordered by event_order
    cur = conn.cursor()
    cur.execute("SELECT event_order, kind, visibility FROM session_events WHERE session_id = 's_order_1' ORDER BY event_order ASC")
    events = cur.fetchall()

    assert len(events) >= 2
    # First event must be local_only activity
    assert events[0][1] == "activity"
    assert events[0][2] == "local_only"
    # Second event must be peer_visible proposal
    assert events[1][1] == "proposal"
    assert events[1][2] == "peer_visible"
