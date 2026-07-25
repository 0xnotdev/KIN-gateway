"""Subprocess security unit tests for LocalCommandAdapter (§15.7 and §2.2)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from kin.adapters.base import AdapterRequest
from kin.adapters.local_command import LocalCommandAdapter
from kin.schemas import (
    AgentAutonomy,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    AutonomyLevel,
    LocalCommandAdapterConfig,
)


def _make_local_cmd_card(cmd: str, work_dir: str = "/tmp", max_runtime: int = 2, max_bytes: int = 1024) -> AgentCard:
    return AgentCard(
        schema_version="1.1",
        id="local_cmd_ag",
        name="Local Cmd Agent",
        description="Local Cmd Agent Description",
        adapter=LocalCommandAdapterConfig(type="local_command", command=cmd, working_directory=work_dir),
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="workspace_read_write_with_approval", shell="approval_required", max_runtime_seconds=max_runtime, max_artifact_bytes=max_bytes),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ALLOW, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )


def test_local_command_env_isolation(tmp_path):
    # Inject sentinel env var into parent process
    os.environ["SENTINEL_SECRET_TOKEN"] = "SECRET_12345_FORBIDDEN"

    try:
        # Command prints environment variables
        if sys.platform == "win32":
            cmd = "cmd.exe /c set"
        else:
            cmd = "env"

        card = _make_local_cmd_card(cmd, work_dir=str(tmp_path))
        adapter = LocalCommandAdapter(card)

        req = AdapterRequest(
            session={"id": "s1", "type": "ask", "turn": 1},
            self_participant={"agent_id": "local_cmd_ag", "card_snapshot": {}},
            peer={"person": "bob", "agent_id": "b1", "card_snapshot": {}},
            objective="Env test",
        )

        res = adapter.invoke(req)
        assert res.message is not None
        # Assert parent's sentinel env var was NOT inherited by subprocess
        assert "SENTINEL_SECRET_TOKEN" not in res.message.content
        assert "SECRET_12345_FORBIDDEN" not in res.message.content
    finally:
        os.environ.pop("SENTINEL_SECRET_TOKEN", None)


def test_local_command_timeout_process_tree_kill(tmp_path):
    # Command spawns a long sleep
    if sys.platform == "win32":
        cmd = "powershell.exe -Command Start-Sleep -Seconds 10"
    else:
        cmd = "sleep 10"

    card = _make_local_cmd_card(cmd, work_dir=str(tmp_path), max_runtime=1)
    adapter = LocalCommandAdapter(card)

    req = AdapterRequest(
        session={"id": "s1", "type": "ask", "turn": 1},
        self_participant={"agent_id": "local_cmd_ag", "card_snapshot": {}},
        peer={"person": "bob", "agent_id": "b1", "card_snapshot": {}},
        objective="Timeout test",
    )

    res = adapter.invoke(req)
    assert res.error is not None
    assert res.error.code == "PROCESS_TIMEOUT_KILLED"


def test_local_command_output_bounding(tmp_path):
    # Command prints a huge string (2000 bytes)
    huge_str = "A" * 2000
    if sys.platform == "win32":
        cmd = f"cmd.exe /c echo {huge_str}"
    else:
        cmd = f"echo {huge_str}"

    card = _make_local_cmd_card(cmd, work_dir=str(tmp_path), max_bytes=100)
    adapter = LocalCommandAdapter(card)

    req = AdapterRequest(
        session={"id": "s1", "type": "ask", "turn": 1},
        self_participant={"agent_id": "local_cmd_ag", "card_snapshot": {}},
        peer={"person": "bob", "agent_id": "b1", "card_snapshot": {}},
        objective="Bounding test",
    )

    res = adapter.invoke(req)
    assert any("Output truncated" in ev.label for ev in res.events if hasattr(ev, "label"))
