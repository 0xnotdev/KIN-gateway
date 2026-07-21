"""Tests for the agent roster loading, selection, and webhook backend."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml
from typer.testing import CliRunner
import httpx
from unittest.mock import MagicMock, patch

from kin.agent_roster.loader import load_agent_roster, AgentLoadingError, AgentConfig
from kin.agent_backend.webhook_backend import WebhookAgentBackend
from kin.agent_backend.factory import get_agent_backend
from kin.agent_backend.base import AgentBackendRequest, AgentBackendResponse
from kin.cli import app as cli_app
from kin.storage.db import get_connection, create_schema


@pytest.fixture
def temp_home_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def temp_profile_dir(temp_home_dir: Path) -> Path:
    profile_dir = temp_home_dir / ".kin" / "profiles" / "test-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


@pytest.fixture
def agents_dir(temp_profile_dir: Path) -> Path:
    d = temp_profile_dir / "agents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_roster_loading_success(agents_dir: Path, temp_home_dir: Path) -> None:
    # 1. Write valid yaml configs
    agent_1 = {
        "name": "EmbeddedAgent",
        "backend_type": "embedded",
        "provider": "openrouter",
        "model": "openrouter/google/gemini-2.5-flash:free",
        "personality": "Sassy and fast",
        "tools": ["read_calendar"],
        "boundaries": {"max_hourly_rate": 50}
    }
    agent_2 = {
        "name": "WebhookAgent",
        "backend_type": "webhook",
        "webhook_url": "http://localhost:9000/agent",
        "webhook_secret": "secret123",
        "personality": "Helpful bot"
    }

    with open(agents_dir / "agent1.yaml", "w") as f:
        yaml.dump(agent_1, f)
    with open(agents_dir / "agent2.yaml", "w") as f:
        yaml.dump(agent_2, f)

    # Load roster
    profile_name = "test-profile"
    with patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir):
        roster = load_agent_roster(profile_name)

    assert len(roster) == 2
    assert "EmbeddedAgent" in roster
    assert "WebhookAgent" in roster
    assert roster["EmbeddedAgent"].backend_type == "embedded"
    assert roster["WebhookAgent"].backend_type == "webhook"
    assert roster["EmbeddedAgent"].tools == ["read_calendar"]
    assert roster["EmbeddedAgent"].boundaries == {"max_hourly_rate": 50}


def test_roster_loading_missing_or_empty(temp_profile_dir: Path, temp_home_dir: Path) -> None:
    profile_name = "test-profile"
    # Ensure agents directory is missing
    agents_dir = temp_profile_dir / "agents"
    if agents_dir.exists():
        import shutil
        shutil.rmtree(agents_dir)

    with patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir):
        # Path doesn't exist
        roster = load_agent_roster(profile_name)
        assert roster == {}

        # Path is empty
        agents_dir.mkdir(parents=True, exist_ok=True)
        roster = load_agent_roster(profile_name)
        assert roster == {}


def test_roster_loading_malformed_yaml(agents_dir: Path, temp_home_dir: Path) -> None:
    with open(agents_dir / "bad.yaml", "w") as f:
        f.write("{invalid yaml structure:::")

    profile_name = "test-profile"
    with patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir):
        with pytest.raises(AgentLoadingError) as exc_info:
            load_agent_roster(profile_name)
        assert "Malformed YAML in bad.yaml" in str(exc_info.value)


def test_roster_loading_missing_name(agents_dir: Path, temp_home_dir: Path) -> None:
    agent_data = {
        "backend_type": "embedded",
        "provider": "openrouter",
        "model": "openrouter/google/gemini"
    }
    with open(agents_dir / "noname.yaml", "w") as f:
        yaml.dump(agent_data, f)

    profile_name = "test-profile"
    with patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir):
        with pytest.raises(AgentLoadingError) as exc_info:
            load_agent_roster(profile_name)
        assert "Missing 'name' in noname.yaml" in str(exc_info.value)


def test_roster_loading_validation_embedded(agents_dir: Path, temp_home_dir: Path) -> None:
    # Missing model
    agent_data = {
        "name": "BadEmbedded",
        "backend_type": "embedded",
        "provider": "openrouter"
    }
    with open(agents_dir / "bad_embedded.yaml", "w") as f:
        yaml.dump(agent_data, f)

    profile_name = "test-profile"
    with patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir):
        with pytest.raises(AgentLoadingError) as exc_info:
            load_agent_roster(profile_name)
        assert "model" in str(exc_info.value)


def test_roster_loading_validation_webhook(agents_dir: Path, temp_home_dir: Path) -> None:
    # Missing secret
    agent_data = {
        "name": "BadWebhook",
        "backend_type": "webhook",
        "webhook_url": "http://localhost:9000/agent"
    }
    with open(agents_dir / "bad_webhook.yaml", "w") as f:
        yaml.dump(agent_data, f)

    profile_name = "test-profile"
    with patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir):
        with pytest.raises(AgentLoadingError) as exc_info:
            load_agent_roster(profile_name)
        assert "webhook_secret" in str(exc_info.value)


def test_webhook_backend_success() -> None:
    backend = WebhookAgentBackend("http://localhost:9000/agent", "secret123")
    req = AgentBackendRequest(
        task_goal="Write a test",
        context={"foo": "bar"},
        conversation_history=["user: Hello"]
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"reply": "This is a response", "message_type": "proposal"}

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        res = backend.generate_response(req)
        assert res.reply == "This is a response"
        assert res.message_type == "proposal"
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer secret123"


def test_webhook_backend_retry_on_conn_failure() -> None:
    backend = WebhookAgentBackend("http://localhost:9000/agent", "secret123")
    req = AgentBackendRequest(
        task_goal="Write a test",
        context={"foo": "bar"},
        conversation_history=["user: Hello"]
    )

    # Connection failure on first attempt, success on second
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"reply": "Success after retry", "message_type": "answer"}

    with patch("httpx.Client.post", side_effect=[httpx.ConnectError("refused"), mock_resp]) as mock_post:
        res = backend.generate_response(req)
        assert res.reply == "Success after retry"
        assert mock_post.call_count == 2


def test_webhook_backend_failure_after_one_retry() -> None:
    backend = WebhookAgentBackend("http://localhost:9000/agent", "secret123")
    req = AgentBackendRequest(
        task_goal="Write a test",
        context={"foo": "bar"},
        conversation_history=["user: Hello"]
    )

    # Fails twice
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("refused")) as mock_post:
        with pytest.raises(httpx.ConnectError):
            backend.generate_response(req)
        assert mock_post.call_count == 2


def test_webhook_backend_no_retry_on_http_error() -> None:
    backend = WebhookAgentBackend("http://localhost:9000/agent", "secret123")
    req = AgentBackendRequest(
        task_goal="Write a test",
        context={"foo": "bar"},
        conversation_history=["user: Hello"]
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("server error", request=MagicMock(), response=mock_resp)

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        with pytest.raises(httpx.HTTPStatusError):
            backend.generate_response(req)
        assert mock_post.call_count == 1  # No retry for HTTP error codes


def test_webhook_backend_malformed_response() -> None:
    backend = WebhookAgentBackend("http://localhost:9000/agent", "secret123")
    req = AgentBackendRequest(
        task_goal="Write a test",
        context={"foo": "bar"},
        conversation_history=["user: Hello"]
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"invalid": "response"}  # missing reply & message_type

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(Exception):
            backend.generate_response(req)


@pytest.fixture
def mock_db(temp_profile_dir: Path) -> Path:
    db_path = temp_profile_dir / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO identity VALUES (?, ?, ?, ?)",
        ("alice", "pubkey-alice", "keychain-ref", "0.1.0"),
    )
    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, endpoint, autonomy_level, fingerprint_verified_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("bob", "Bob", "pubkey-bob", "http://localhost:8321", "always_ask", "2026-07-17T12:00:00Z"),
    )
    conn.commit()
    conn.close()
    return db_path


def test_cli_ask_zero_agents(mock_db: Path, temp_profile_dir: Path, temp_home_dir: Path) -> None:
    # Zero agents -> should proceed exactly as today without any prompt
    runner = CliRunner()
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"task_id": "test-task-1234", "status": "input-required"}

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir),
        patch("httpx.post", return_value=mock_res) as mock_post,
        patch("kin.cli.load_private_key", return_value=bytes.fromhex("01" * 32))
    ):
        result = runner.invoke(cli_app, ["--profile", "test-profile", "ask", "bob", "Question"])
        assert result.exit_code == 0
        assert "Task created successfully!" in result.stdout
        mock_post.assert_called_once()


def test_cli_ask_one_agent(mock_db: Path, temp_profile_dir: Path, temp_home_dir: Path) -> None:
    # One agent -> silently auto-selects without prompt
    agents_dir = temp_profile_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent = {
        "name": "OnlyAgent",
        "backend_type": "embedded",
        "provider": "openrouter",
        "model": "openrouter/google/gemini"
    }
    with open(agents_dir / "agent.yaml", "w") as f:
        yaml.dump(agent, f)

    runner = CliRunner()
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"task_id": "test-task-1234", "status": "input-required"}

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir),
        patch("httpx.post", return_value=mock_res),
        patch("kin.cli.load_private_key", return_value=bytes.fromhex("01" * 32))
    ):
        result = runner.invoke(cli_app, ["--profile", "test-profile", "ask", "bob", "Question"])
        assert result.exit_code == 0
        assert "Select an agent" not in result.stdout  # No prompt shown
        assert "Task created successfully!" in result.stdout

        # Verify agent name is stored in DB
        conn = get_connection(mock_db)
        cursor = conn.cursor()
        cursor.execute("SELECT agent_name FROM tasks WHERE task_id = 'test-task-1234'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "OnlyAgent"
        conn.close()


def test_cli_ask_multiple_agents_selection(mock_db: Path, temp_profile_dir: Path, temp_home_dir: Path) -> None:
    # Multiple agents -> prompts user, stores chosen agent in DB
    agents_dir = temp_profile_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_a = {
        "name": "AgentA",
        "backend_type": "embedded",
        "provider": "openrouter",
        "model": "openrouter/google/gemini"
    }
    agent_b = {
        "name": "AgentB",
        "backend_type": "embedded",
        "provider": "openrouter",
        "model": "openrouter/google/gemini"
    }
    with open(agents_dir / "agentA.yaml", "w") as f:
        yaml.dump(agent_a, f)
    with open(agents_dir / "agentB.yaml", "w") as f:
        yaml.dump(agent_b, f)

    runner = CliRunner()
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"task_id": "test-task-multiple", "status": "input-required"}

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir),
        patch("httpx.post", return_value=mock_res),
        patch("kin.cli.load_private_key", return_value=bytes.fromhex("01" * 32))
    ):
        # We select option 2 (AgentB)
        result = runner.invoke(cli_app, ["--profile", "test-profile", "ask", "bob", "Question"], input="2\n")
        assert result.exit_code == 0
        assert "Select an agent" in result.stdout
        assert "AgentA" in result.stdout
        assert "AgentB" in result.stdout

        # Verify agent name is stored in DB
        conn = get_connection(mock_db)
        cursor = conn.cursor()
        cursor.execute("SELECT agent_name FROM tasks WHERE task_id = 'test-task-multiple'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "AgentB"
        conn.close()


def test_cli_ask_option_agent_valid(mock_db: Path, temp_profile_dir: Path, temp_home_dir: Path) -> None:
    # --agent AgentB passes selection without prompt
    agents_dir = temp_profile_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_a = {
        "name": "AgentA",
        "backend_type": "embedded",
        "provider": "openrouter",
        "model": "openrouter/google/gemini"
    }
    agent_b = {
        "name": "AgentB",
        "backend_type": "embedded",
        "provider": "openrouter",
        "model": "openrouter/google/gemini"
    }
    with open(agents_dir / "agentA.yaml", "w") as f:
        yaml.dump(agent_a, f)
    with open(agents_dir / "agentB.yaml", "w") as f:
        yaml.dump(agent_b, f)

    runner = CliRunner()
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"task_id": "test-task-opt", "status": "input-required"}

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir),
        patch("httpx.post", return_value=mock_res),
        patch("kin.cli.load_private_key", return_value=bytes.fromhex("01" * 32))
    ):
        result = runner.invoke(cli_app, ["--profile", "test-profile", "ask", "bob", "Question", "--agent", "AgentB"])
        assert result.exit_code == 0
        assert "Select an agent" not in result.stdout  # Prompts bypassed

        # Verify agent name is stored in DB
        conn = get_connection(mock_db)
        cursor = conn.cursor()
        cursor.execute("SELECT agent_name FROM tasks WHERE task_id = 'test-task-opt'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "AgentB"
        conn.close()


def test_cli_ask_option_agent_invalid(mock_db: Path, temp_profile_dir: Path, temp_home_dir: Path) -> None:
    # --agent InvalidAgent fails clearly listing valid options
    agents_dir = temp_profile_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_a = {
        "name": "AgentA",
        "backend_type": "embedded",
        "provider": "openrouter",
        "model": "openrouter/google/gemini"
    }
    with open(agents_dir / "agentA.yaml", "w") as f:
        yaml.dump(agent_a, f)

    runner = CliRunner()

    with (
        patch("kin.cli.get_profile_dir", return_value=temp_profile_dir),
        patch("kin.agent_roster.loader.Path.home", return_value=temp_home_dir),
    ):
        result = runner.invoke(cli_app, ["--profile", "test-profile", "ask", "bob", "Question", "--agent", "InvalidAgent"])
        assert result.exit_code == 1
        assert "Error: Agent 'InvalidAgent' not found in roster. Available agents: AgentA" in result.stderr
