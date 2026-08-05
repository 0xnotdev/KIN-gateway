"""M7 Slice 2 persistence, replay, outcome, and fresh-authority proofs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kin.audit.writer import append_session_event
from kin.policy.evaluator import PolicyDecision
from kin.policy.persistence import evaluate_action_for_session
from kin.schemas import (
    ActionClass,
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    AutonomyLevel,
    EmbeddedAdapterConfig,
)
from kin.session.history import (
    create_checkpoint,
    create_decision,
    create_fresh_authority_rerun,
    create_outcome_card,
    get_outcome_card,
    replay_session,
)
from kin.storage.db import create_schema, get_connection


VAULT_KEY = b"\x17" * 32


def _seed_session(conn: sqlite3.Connection, session_id: str = "sess_m7_history") -> None:
    conn.execute(
        """INSERT INTO sessions (
               session_id, type, initiator_username, receiver_username, status,
               objective, sender_agent_id, receiver_agent_id,
               participant_snapshot_json, turn_limit, runtime_budget_seconds,
               artifact_bytes_budget, cumulative_artifact_bytes,
               cost_budget_estimate, cumulative_cost_estimate, created_at, updated_at
           ) VALUES (?, 'ask', 'alice', 'bob', 'active', ?, 'ag_alice', 'ag_bob',
                     ?, 20, 90, 4096, 100, 2.5, 0.75, ?, ?)""",
        (
            session_id,
            "Review the release evidence",
            '{"alice":"ag_alice","bob":"ag_bob"}',
            "2026-08-05T10:00:00Z",
            "2026-08-05T10:00:00Z",
        ),
    )
    conn.commit()
    append_session_event(
        conn,
        VAULT_KEY,
        session_id=session_id,
        actor_username="alice",
        actor_agent_id="ag_alice",
        kind="task_request",
        visibility="peer_visible",
        payload={"goal": "Review the release evidence"},
        signature="real-persisted-signature-evidence",
        sequence=1,
    )


def _approval_card() -> AgentCard:
    return AgentCard(
        schema_version="1.1",
        id="ag_alice",
        name="Alice Agent",
        description="Approval isolation test card",
        adapter=EmbeddedAdapterConfig(type="embedded", provider="local", model="test"),
        capabilities=AgentCapabilities(tags=["test"], accepts=["text/plain"], produces=["text/plain"]),
        boundaries=AgentBoundaries(
            network_access="allow",
            filesystem="workspace_read_write_with_approval",
            shell="approval_required",
            max_runtime_seconds=300,
            max_artifact_bytes=1_000_000,
        ),
        autonomy=AgentAutonomy(
            relay_information=AutonomyLevel.ALWAYS_ASK,
            propose_actions=AutonomyLevel.ALWAYS_ASK,
            execute_local_actions=AutonomyLevel.ALWAYS_ASK,
        ),
    )


def test_checkpoints_decisions_and_replay_survive_database_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)
    _seed_session(conn)

    checkpoint = create_checkpoint(
        conn,
        VAULT_KEY,
        session_id="sess_m7_history",
        created_by="alice",
        label="Inputs reviewed",
        snapshot={"reviewed": ["brief.md"]},
    )
    decision = create_decision(
        conn,
        VAULT_KEY,
        session_id="sess_m7_history",
        decided_by="alice",
        summary="Ship only after the gate passes",
        rationale="The release gate is authoritative",
        checkpoint_id=checkpoint.checkpoint_id,
    )
    append_session_event(
        conn,
        VAULT_KEY,
        session_id="sess_m7_history",
        actor_username="alice",
        actor_agent_id=None,
        kind="private_note",
        visibility="local_only",
        payload={"content": "must never enter deterministic reviewed replay"},
        signature=None,
        sequence=None,
    )
    first = replay_session(conn, VAULT_KEY, "sess_m7_history")
    conn.close()

    reopened = get_connection(db_path)
    second = replay_session(reopened, VAULT_KEY, "sess_m7_history")
    assert second.model_dump() == first.model_dump()
    assert second.digest == first.digest
    assert checkpoint.event_order < decision.event_order
    assert [event["kind"] for event in second.events] == [
        "task_request",
        "checkpoint",
        "decision",
    ]
    assert all("must never enter" not in str(event) for event in second.events)
    local_rows = reopened.execute(
        "SELECT kind, visibility FROM session_events WHERE kind IN ('checkpoint', 'decision') ORDER BY event_order"
    ).fetchall()
    assert local_rows == [("checkpoint", "local_only"), ("decision", "local_only")]
    reopened.close()


def test_outcome_card_requires_and_reflects_real_terminal_state(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "kin.db")
    create_schema(conn)
    _seed_session(conn)

    with pytest.raises(ValueError, match="require a terminal session"):
        create_outcome_card(conn, VAULT_KEY, session_id="sess_m7_history", summary="Too early")

    conn.execute(
        "UPDATE sessions SET status = 'completed', updated_at = ? WHERE session_id = ?",
        ("2026-08-05T10:30:00Z", "sess_m7_history"),
    )
    conn.commit()
    evidence = replay_session(conn, VAULT_KEY, "sess_m7_history")
    outcome = create_outcome_card(
        conn,
        VAULT_KEY,
        session_id="sess_m7_history",
        summary="Release evidence accepted",
    )
    persisted = get_outcome_card(conn, VAULT_KEY, "sess_m7_history")

    assert persisted == outcome
    assert outcome.status == "completed"
    assert outcome.summary == "Release evidence accepted"
    assert outcome.evidence_event_count == evidence.event_count
    assert outcome.replay_digest == evidence.digest
    assert create_outcome_card(
        conn,
        VAULT_KEY,
        session_id="sess_m7_history",
        summary="A duplicate must not replace the result",
    ) == outcome
    assert conn.execute(
        "SELECT COUNT(*) FROM session_events WHERE session_id = ? AND kind = 'outcome'",
        ("sess_m7_history",),
    ).fetchone()[0] == 1
    conn.close()


def test_fresh_authority_rerun_copies_limits_but_no_authority_or_history(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "kin.db")
    create_schema(conn)
    _seed_session(conn)
    create_checkpoint(
        conn,
        VAULT_KEY,
        session_id="sess_m7_history",
        created_by="alice",
        label="Source-only checkpoint",
    )
    conn.execute(
        """INSERT INTO approvals (
               approval_id, session_id, agent_id, action_class, request_json,
               decision, decided_at, expires_at, consumed_at
           ) VALUES ('approval_source', ?, 'ag_alice', 'workspace_write', '{}',
                     'approve_once', '2026-08-05T10:10:00Z', '2026-08-06T10:10:00Z', NULL)""",
        ("sess_m7_history",),
    )
    conn.commit()

    rerun = create_fresh_authority_rerun(
        conn,
        VAULT_KEY,
        source_session_id="sess_m7_history",
        created_by="alice",
        rerun_session_id="sess_m7_fresh",
    )
    row = conn.execute(
        """SELECT status, objective, turn_limit, runtime_budget_seconds,
                  artifact_bytes_budget, cumulative_artifact_bytes,
                  cost_budget_estimate, cumulative_cost_estimate
           FROM sessions WHERE session_id = ?""",
        (rerun.rerun_session_id,),
    ).fetchone()
    assert row == (
        "draft",
        "Review the release evidence",
        20,
        90,
        4096,
        0,
        2.5,
        0.0,
    )
    assert rerun.carried_approval_count == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM approvals WHERE session_id = ?", (rerun.rerun_session_id,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT kind FROM session_events WHERE session_id = ? ORDER BY event_order",
        (rerun.rerun_session_id,),
    ).fetchall() == [("rerun_created",)]

    policy = evaluate_action_for_session(
        conn,
        _approval_card(),
        ActionClass.WORKSPACE_WRITE,
        {},
        rerun.rerun_session_id,
        "2026-08-05T11:00:00Z",
    )
    assert policy.decision == PolicyDecision.REQUIRES_APPROVAL
    conn.close()
