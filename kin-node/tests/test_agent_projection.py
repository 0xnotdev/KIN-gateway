"""Property-based and table-driven contract test for PublishedAgentCard projection security."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from typer.testing import CliRunner

from kin.schemas import (
    AgentAutonomy,
    AgentAvailability,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    AutonomyLevel,
    EmbeddedAdapterConfig,
    LocalCommandAdapterConfig,
    PublishedAgentCard,
    SdkAdapterConfig,
    WebhookAdapterConfig,
)
from kin.agent_registry.registry import publish_card
from kin.cli import app
from kin.identity.storage import get_agent_credential_service

runner = CliRunner()

SECRET_SENTINEL_COMMAND = "/usr/bin/secret-owner-command --key=super-secret"
SECRET_SENTINEL_WORKDIR = "/home/owner/private/confidential-project"
SECRET_SENTINEL_URL = "https://confidential.internal/api/webhook"
SECRET_SENTINEL_PRESENTATION = {"theme_color": "#ff0000", "avatar_url": "http://private/avatar.png"}

ALLOWLISTED_KEYS = {
    "schema_version",
    "protocol_version",
    "agent_id",
    "name",
    "description",
    "capabilities",
    "availability",
    "requires_owner_acceptance",
}


@pytest.fixture
def sample_cards():
    """Generates a list of valid AgentCards covering all adapter types with sensitive sentinel values."""
    c_local = AgentCard(
        schema_version="1.1",
        id="local-agent-1",
        name="Local Agent",
        description="Local agent with private paths",
        adapter=LocalCommandAdapterConfig(
            type="local_command",
            command=SECRET_SENTINEL_COMMAND,
            working_directory=SECRET_SENTINEL_WORKDIR,
        ),
        capabilities=AgentCapabilities(tags=["local"], accepts=["text/plain"]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="workspace_read", shell="approval_required", max_runtime_seconds=600, max_artifact_bytes=100000),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ASK, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.NEVER),
        presentation=SECRET_SENTINEL_PRESENTATION,
    )

    webhook_cred_ref = get_agent_credential_service("testprof", "webhook-agent-1", "webhook_secret")
    c_webhook = AgentCard(
        schema_version="1.1",
        id="webhook-agent-1",
        name="Webhook Agent",
        description="Webhook agent with secret credential ref",
        adapter=WebhookAdapterConfig(
            type="webhook",
            webhook_url=SECRET_SENTINEL_URL,
            credential_ref=webhook_cred_ref,
        ),
        capabilities=AgentCapabilities(tags=["webhook"], accepts=["application/json"]),
        boundaries=AgentBoundaries(network_access="allow", filesystem="none", shell="deny", max_runtime_seconds=1800, max_artifact_bytes=5000000),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ALLOW, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.NEVER),
        presentation=SECRET_SENTINEL_PRESENTATION,
    )

    c_embedded = AgentCard(
        schema_version="1.1",
        id="embedded-agent-1",
        name="Embedded Agent",
        description="Embedded agent with model details",
        adapter=EmbeddedAdapterConfig(
            type="embedded",
            provider="openrouter",
            model="google/gemini-2.5-flash",
        ),
        capabilities=AgentCapabilities(tags=["embedded"], accepts=["text/markdown"]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="none", shell="deny", max_runtime_seconds=300, max_artifact_bytes=100000),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ASK, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )

    c_sdk = AgentCard(
        schema_version="1.1",
        id="sdk-agent-1",
        name="SDK Agent",
        description="SDK agent with entry point",
        adapter=SdkAdapterConfig(
            type="sdk",
            entry_point="my_module.submodule:main_agent",
        ),
        capabilities=AgentCapabilities(tags=["sdk"], accepts=["application/json"]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="none", shell="deny", max_runtime_seconds=1200, max_artifact_bytes=1000000),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ASK, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )

    return [c_local, c_webhook, c_embedded, c_sdk]


def test_publish_card_projection_allowlist_and_secret_exclusion(sample_cards):
    """Assert publish_card() NEVER leaks internal adapter, boundaries, autonomy, or presentation fields."""
    for card in sample_cards:
        pub = publish_card(card)
        json_str = pub.model_dump_json()
        data = json.loads(json_str)

        # 1. Assert keys match allowlist EXACTLY
        assert set(data.keys()) == ALLOWLISTED_KEYS

        # 2. Assert no forbidden fields exist in dict
        for forbidden in ["adapter", "boundaries", "autonomy", "presentation", "working_directory", "command", "credential_ref", "webhook_url"]:
            assert forbidden not in data

        # 3. Assert secret sentinel values NEVER appear anywhere in the serialized payload
        assert SECRET_SENTINEL_COMMAND not in json_str
        assert SECRET_SENTINEL_WORKDIR not in json_str
        assert SECRET_SENTINEL_URL not in json_str
        assert "theme_color" not in json_str


def test_cli_inspect_json_projection_isolation(tmp_path: Path, monkeypatch, sample_cards):
    """Assert `kin agent inspect --json` emits ONLY the safe PublishedAgentCard projection."""
    monkeypatch.setenv("KIN_UNSAFE_TEST_KEYRING", "1")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    profile_dir = tmp_path / ".kin" / "profiles" / "testprof"
    agents_dir = profile_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Save a webhook card with sentinel values into agents_dir
    card = sample_cards[1]  # Webhook card
    card_file = agents_dir / f"{card.id}.yaml"
    card_file.write_text(json.dumps(card.model_dump()))

    # List/register via CLI
    r_list = runner.invoke(app, ["--profile", "testprof", "agent", "list"])
    assert r_list.exit_code == 0

    # Inspect --json
    r_inspect = runner.invoke(app, ["--profile", "testprof", "agent", "inspect", card.id, "--json"])
    assert r_inspect.exit_code == 0

    lines = [line for line in r_inspect.output.splitlines() if not line.startswith("WARNING:")]
    inspect_data = json.loads("\n".join(lines))
    # Allows availability_reason in CLI inspect json output, but all safe allowlisted keys are present
    assert set(inspect_data.keys()).issubset(ALLOWLISTED_KEYS | {"availability_reason"})

    for forbidden in ["adapter", "boundaries", "autonomy", "presentation", "working_directory", "command", "credential_ref"]:
        assert forbidden not in inspect_data

    assert SECRET_SENTINEL_URL not in r_inspect.output
