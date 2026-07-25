"""End-to-end integration tests for Session Orchestrator (§15.7 and §2.5)."""

from __future__ import annotations

import sqlite3

import pytest
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
from kin.session.orchestrator import (
    OrchestratorError,
    advance_session_turn,
    send_status_nudge,
    tag_in_handoff,
)
from kin.session.reducer import reconstruct_session_state
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


@pytest.fixture
def node_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    run_migrations(conn)
    vault_key = b"test-vault-key-32bytes-long!!!!!"
    alice_priv = ed25519.Ed25519PrivateKey.generate()

    register_card(conn, vault_key, _make_agent_card("alice_agent", "Alice Agent"))
    register_card(conn, vault_key, _make_agent_card("alice_scout", "Alice Scout"))
    conn.execute("UPDATE agents SET enabled = 1")
    conn.commit()

    return {"conn": conn, "vault_key": vault_key, "priv": alice_priv}


def test_status_nudge_rate_limiting(node_db):
    conn = node_db["conn"]
    vault_key = node_db["vault_key"]
    now_str = "2026-07-22T12:00:00Z"

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES ('s_nudge_1', 'ask', 'alice', 'bob', 'active', 'alice_agent', 'bob_agent', 12, ?, ?)
        """,
        (now_str, now_str),
    )
    conn.commit()

    # First nudge -> succeeds
    res1 = send_status_nudge(conn, vault_key, "alice", "s_nudge_1", "First nudge")
    assert res1["status"] == "nudged"

    # Immediate second nudge within 60s -> MUST fail with RATE_LIMIT_EXCEEDED
    with pytest.raises(OrchestratorError, match="Nudge rate limit exceeded"):
        send_status_nudge(conn, vault_key, "alice", "s_nudge_1", "Second nudge")


def test_tag_in_handoff_workflow(node_db):
    from kin.storage.vault import decrypt_field
    import json

    conn = node_db["conn"]
    vault_key = node_db["vault_key"]
    alice_priv = node_db["priv"]
    now_str = "2026-07-22T12:00:00Z"
    expected_obj = "Perform deep research on quantum state algorithms"

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, objective, initiator_username, receiver_username, status,
            sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES ('s_tag_1', 'research', ?, 'alice', 'bob', 'active', 'alice_agent', 'bob_agent', 12, ?, ?)
        """,
        (expected_obj, now_str, now_str),
    )
    conn.commit()

    res = tag_in_handoff(conn, vault_key, alice_priv, "alice", "s_tag_1", "alice_scout")
    assert res["status"] == "delivered"
    assert res["replacement_agent_id"] == "alice_scout"

    cur = conn.cursor()
    cur.execute("SELECT sender_agent_id FROM sessions WHERE session_id = 's_tag_1'")
    assert cur.fetchone()[0] == "alice_scout"

    # Verify decrypted handoff_package payload in session_events
    cur.execute("SELECT payload_json FROM session_events WHERE session_id = 's_tag_1' AND kind = 'participant_changed'")
    payload_enc = cur.fetchone()[0]
    payload = json.loads(decrypt_field(vault_key, payload_enc))

    assert payload["objective"] == expected_obj
    assert payload["replacement_agent_id"] == "alice_scout"


def test_orchestrator_restart_recovery(node_db):
    conn = node_db["conn"]
    vault_key = node_db["vault_key"]
    now_str = "2026-07-22T12:00:00Z"

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES ('s_rec_1', 'ask', 'alice', 'bob', 'active', 'alice_agent', 'bob_agent', 12, ?, ?)
        """,
        (now_str, now_str),
    )
    conn.commit()

    # Reconstruct state from SQLite
    state = reconstruct_session_state(conn, vault_key, "s_rec_1")
    assert state.status == "active"
    assert state.initiator_username == "alice"
    assert state.receiver_username == "bob"


def test_orchestrator_multi_turn_history_persistence(node_db):
    """Test Defect 1 fix: multi-turn turn 2 receives non-empty history from turn 1."""
    from unittest.mock import MagicMock, patch

    conn = node_db["conn"]
    vault_key = node_db["vault_key"]
    alice_priv = node_db["priv"]
    now_str = "2026-07-22T12:00:00Z"
    sess_id = "s_history_multi_turn"

    conn.execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES (?, 'research', 'alice', 'bob', 'active', 'alice_agent', 'bob_agent', 12, ?, ?)
        """,
        (sess_id, now_str, now_str),
    )
    conn.commit()

    captured_requests = []

    def mock_invoke(req, vault_key=None):
        captured_requests.append(req)
        return MagicMock(
            error=None,
            events=[],
            message=MagicMock(kind=MagicMock(value="proposal"), content=f"Turn {len(captured_requests)} response"),
            artifacts=[],
            terminal=False,
        )

    with patch("kin.session.orchestrator.get_adapter") as mock_get_adapter, \
         patch("kin.session.orchestrator.validate_adapter_output") as mock_val:

        mock_adapter = MagicMock()
        mock_adapter.invoke.side_effect = mock_invoke
        mock_get_adapter.return_value = mock_adapter

        mock_val_out = MagicMock()
        mock_val_out.valid = True
        mock_val.return_value = mock_val_out

        # Turn 1
        res1 = advance_session_turn(conn, vault_key, alice_priv, "alice", sess_id)
        assert res1["status"] == "delivered"
        assert len(captured_requests[0].history) == 0

        # Turn 2
        res2 = advance_session_turn(conn, vault_key, alice_priv, "alice", sess_id)
        assert res2["status"] == "delivered"
        # Turn 2 history MUST contain turn 1's event!
        assert len(captured_requests[1].history) >= 1
        assert captured_requests[1].session["type"] == "research"
