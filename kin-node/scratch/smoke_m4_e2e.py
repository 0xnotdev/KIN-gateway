"""Smoke test script demonstrating a complete end-to-end two-fixture-profile agent-to-agent bounded collaboration (§15.7 and §2.6)."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.agent_registry.registry import register_card
from kin.session.orchestrator import advance_session_turn
from kin.session.reducer import reconstruct_session_state
from kin.storage.migrations import run_migrations
from kin.schemas import (
    AgentCard,
    AgentCapabilities,
    AgentBoundaries,
    AgentAutonomy,
    AutonomyLevel,
    EmbeddedAdapterConfig,
)


def _make_card(agent_id: str, name: str, owner: str) -> AgentCard:
    return AgentCard(
        schema_version="1.1",
        id=agent_id,
        name=name,
        description=name,
        adapter=EmbeddedAdapterConfig(type="embedded", provider="openai", model="gpt-4o"),
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="none", shell="deny", max_runtime_seconds=900, max_artifact_bytes=10000000),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ALLOW, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )


def run_smoke_test():
    print("=== KIN V1.1 Milestone M4 Smoke Test ===")
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    vault_key = b"smoke-vault-key-32bytes-long!!!!"
    alice_priv = ed25519.Ed25519PrivateKey.generate()

    register_card(conn, vault_key, _make_card("alice_agent", "Alice Agent", "alice"))
    register_card(conn, vault_key, _make_card("bob_agent", "Bob Agent", "bob"))
    conn.execute("UPDATE agents SET enabled = 1")
    conn.commit()

    now_str = "2026-07-22T12:00:00Z"
    sess_id = "sess_smoke_m4"

    # Insert active session
    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES (?, 'ask', 'alice', 'bob', 'active', 'Analyze repository metrics', 'alice_agent', 'bob_agent', 12, ?, ?)
        """,
        (sess_id, now_str, now_str),
    )
    conn.commit()

    # Mock adapter responses
    mock_resp = MagicMock()
    mock_resp.error = None
    mock_resp.events = [MagicMock(event_kind="activity", label="Analyzing repository files...")]
    mock_resp.message = MagicMock(kind=MagicMock(value="proposal"), content="Here is the metric summary.")
    mock_resp.artifacts = []
    mock_resp.terminal = False
    mock_resp.model_dump.return_value = {}

    with patch("kin.session.orchestrator.get_adapter") as mock_get_adapter, \
         patch("kin.session.orchestrator.validate_adapter_output") as mock_val:

        mock_adapter = MagicMock()
        mock_adapter.invoke.return_value = mock_resp
        mock_get_adapter.return_value = mock_adapter

        mock_val_out = MagicMock()
        mock_val_out.valid = True
        mock_val.return_value = mock_val_out

        res = advance_session_turn(conn, vault_key, alice_priv, "alice", sess_id)
        print(f"[1] Turn advanced result: {res}")

    state = reconstruct_session_state(conn, vault_key, sess_id)
    print(f"[2] Reconstructed SessionState status: {state.status}, current_turn: {state.current_turn}")

    cur = conn.cursor()
    cur.execute("SELECT kind, visibility, payload_json FROM session_events WHERE session_id = ?", (sess_id,))
    events = cur.fetchall()
    print(f"[3] Total persisted session events: {len(events)}")
    for ev in events:
        print(f"    - Event kind={ev[0]}, visibility={ev[1]}")

    print("=== Smoke Test Completed Successfully! ===")


if __name__ == "__main__":
    run_smoke_test()
