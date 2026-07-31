"""Unit tests for agent availability computation engine in get_local_agents_summaries (§A1).

Proves that:
1. Disabled agent reports POLICY_BLOCKED.
2. Webhook agent with no stored credential reports NEEDS_KEY.
3. Local-command agent with missing working directory reports NEEDS_WORKSPACE.
4. get_local_agents_summaries never returns the literal string 'active'.
"""

import io
from pathlib import Path

import pytest
import yaml

from kin.schemas import AgentAvailability
from kin.tui.local_state import get_local_agents_summaries, ensure_profile_db


# -----------------------------------------------------------------------------
# A1. Local State Agent Availability Engine Tests
# -----------------------------------------------------------------------------
def test_local_state_availability_disabled_agent(tmp_path: Path):
    """1. Disabled agent in SQLite database reports POLICY_BLOCKED (§A1)."""
    prof_dir = tmp_path / "profiles" / "avail_user"
    agents_dir = prof_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    db_path = prof_dir / "kin.db"

    card_yaml = {
        "schema_version": "1.1",
        "id": "disabled-bot",
        "name": "Disabled Bot",
        "description": "Bot disabled by policy",
        "adapter": {"type": "local_command", "command": "echo hello", "working_directory": str(tmp_path.resolve())},
        "capabilities": {"tags": ["test"], "accepts": ["text/plain"], "produces": ["text/plain"]},
        "boundaries": {"filesystem": "workspace_read", "shell": "deny", "max_runtime_seconds": 300, "max_artifact_bytes": 1048576},
        "autonomy": {"relay_information": "always_ask", "propose_actions": "always_ask", "execute_local_actions": "always_ask"},
    }
    (agents_dir / "disabled-bot.yaml").write_text(yaml.dump(card_yaml), encoding="utf-8")

    # Insert into SQLite as disabled (enabled = 0)
    conn = ensure_profile_db(db_path)
    conn.execute(
        """
        INSERT INTO agents (agent_id, name, adapter_type, local_card_json, published_card_json, enabled, availability, created_at, updated_at, card_version)
        VALUES ('disabled-bot', 'Disabled Bot', 'local_command', '{}', '{}', 0, 'ready', '2026-07-31T00:00:00Z', '2026-07-31T00:00:00Z', '1.1')
        """
    )
    conn.commit()
    conn.close()

    summaries = get_local_agents_summaries(prof_dir, "avail_user")
    assert len(summaries) == 1
    assert summaries[0].availability == AgentAvailability.POLICY_BLOCKED
    assert "policy" in summaries[0].readiness_reason.lower()


def test_local_state_availability_webhook_missing_key(tmp_path: Path):
    """2. Webhook agent with no stored credential reports NEEDS_KEY (§A1)."""
    prof_dir = tmp_path / "profiles" / "webhook_user"
    agents_dir = prof_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    card_yaml = {
        "schema_version": "1.1",
        "id": "webhook-bot",
        "name": "Webhook Bot",
        "description": "Webhook bot without key",
        "adapter": {
            "type": "webhook",
            "webhook_url": "http://127.0.0.1:9000/webhook",
            "credential_ref": "kin-webhook_user-agent-webhook-bot-webhook_secret",
        },
        "capabilities": {"tags": ["webhook"], "accepts": ["text/plain"], "produces": ["text/plain"]},
        "boundaries": {"filesystem": "workspace_read", "shell": "deny", "max_runtime_seconds": 300, "max_artifact_bytes": 1048576},
        "autonomy": {"relay_information": "always_ask", "propose_actions": "always_ask", "execute_local_actions": "always_ask"},
    }
    (agents_dir / "webhook-bot.yaml").write_text(yaml.dump(card_yaml), encoding="utf-8")

    summaries = get_local_agents_summaries(prof_dir, "webhook_user")
    assert len(summaries) == 1
    assert summaries[0].availability == AgentAvailability.NEEDS_KEY
    assert "credential" in summaries[0].readiness_reason.lower() or "key" in summaries[0].readiness_reason.lower()


def test_local_state_availability_missing_workspace_dir(tmp_path: Path):
    """3. Local command agent with missing working directory reports NEEDS_WORKSPACE (§A1)."""
    prof_dir = tmp_path / "profiles" / "missing_dir_user"
    agents_dir = prof_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    missing_dir = tmp_path.resolve() / "nonexistent_directory_xyz"

    card_yaml = {
        "schema_version": "1.1",
        "id": "missing-dir-bot",
        "name": "Missing Dir Bot",
        "description": "Bot with missing working directory",
        "adapter": {"type": "local_command", "command": "echo test", "working_directory": str(missing_dir)},
        "capabilities": {"tags": ["local"], "accepts": ["text/plain"], "produces": ["text/plain"]},
        "boundaries": {"filesystem": "workspace_read", "shell": "deny", "max_runtime_seconds": 300, "max_artifact_bytes": 1048576},
        "autonomy": {"relay_information": "always_ask", "propose_actions": "always_ask", "execute_local_actions": "always_ask"},
    }
    (agents_dir / "missing-dir-bot.yaml").write_text(yaml.dump(card_yaml), encoding="utf-8")

    summaries = get_local_agents_summaries(prof_dir, "missing_dir_user")
    assert len(summaries) == 1
    assert summaries[0].availability == AgentAvailability.NEEDS_WORKSPACE
    assert "working directory" in summaries[0].readiness_reason.lower() or "workspace" in summaries[0].readiness_reason.lower()


def test_local_state_availability_never_returns_active_literal(tmp_path: Path):
    """4. Assert get_local_agents_summaries never returns the invalid string 'active' (§A1)."""
    prof_dir = tmp_path / "profiles" / "ready_user"
    agents_dir = prof_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    card_yaml = {
        "schema_version": "1.1",
        "id": "ready-bot",
        "name": "Ready Bot",
        "description": "Valid ready bot",
        "adapter": {"type": "local_command", "command": "echo ready", "working_directory": str(tmp_path.resolve())},
        "capabilities": {"tags": ["ready"], "accepts": ["text/plain"], "produces": ["text/plain"]},
        "boundaries": {"filesystem": "workspace_read", "shell": "deny", "max_runtime_seconds": 300, "max_artifact_bytes": 1048576},
        "autonomy": {"relay_information": "always_ask", "propose_actions": "always_ask", "execute_local_actions": "always_ask"},
    }
    (agents_dir / "ready-bot.yaml").write_text(yaml.dump(card_yaml), encoding="utf-8")

    summaries = get_local_agents_summaries(prof_dir, "ready_user")
    assert len(summaries) == 1
    assert summaries[0].availability != "active"
    assert summaries[0].availability == AgentAvailability.READY
