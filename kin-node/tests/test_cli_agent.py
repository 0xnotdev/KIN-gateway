"""CLI smoke tests for kin agent command group (list, inspect, validate, enable, disable, import, publish)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml
from typer.testing import CliRunner

from kin.cli import app
from kin.schemas import AgentAvailability, AgentCard
from kin.agent_registry.availability import AVAILABILITY_EXPLANATIONS
from kin.identity.storage import get_agent_credential_service

runner = CliRunner()


def parse_json_output(result) -> dict | list:
    """Helper to parse JSON from CliRunner output, stripping stderr warnings."""
    lines = [line for line in result.output.splitlines() if not line.startswith("WARNING:")]
    return json.loads("\n".join(lines))


@pytest.fixture
def cli_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("KIN_UNSAFE_TEST_KEYRING", "1")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    profile_dir = tmp_path / ".kin" / "profiles" / "testprofile"
    agents_dir = profile_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


def create_agent_yaml(agent_id: str, adapter_type: str = "embedded", profile_name: str = "testprofile", wdir: str = "/tmp") -> dict:
    cred_ref = get_agent_credential_service(profile_name, agent_id, "webhook_secret")
    adapter_dict = {
        "embedded": {"type": "embedded", "provider": "openrouter", "model": "google/gemini-2.5-flash"},
        "webhook": {"type": "webhook", "webhook_url": "https://example.com/webhook", "credential_ref": cred_ref},
        "local_command": {"type": "local_command", "command": "python test.py", "working_directory": wdir},
    }[adapter_type]

    return {
        "schema_version": "1.1",
        "id": agent_id,
        "name": f"Agent {agent_id}",
        "description": f"Description for {agent_id}",
        "adapter": adapter_dict,
        "capabilities": {"tags": ["test"], "accepts": ["text/plain"], "produces": ["text/plain"]},
        "boundaries": {"network_access": "deny", "filesystem": "none", "shell": "deny", "max_runtime_seconds": 600, "max_artifact_bytes": 1000000},
        "autonomy": {"relay_information": "always_ask", "propose_actions": "always_ask", "execute_local_actions": "always_ask"},
    }


def test_cli_agent_validate_success_and_failure(cli_home: Path, tmp_path: Path):
    """Assert kin agent validate against standalone path works cleanly for valid cards and fails for invalid cards."""
    # Valid card (standalone filename draft.yaml is permitted for validate)
    v_dict = create_agent_yaml("my-draft-agent", "embedded")
    v_path = tmp_path / "draft.yaml"
    v_path.write_text(yaml.dump(v_dict))

    r_valid = runner.invoke(app, ["--profile", "testprofile", "agent", "validate", str(v_path)])
    assert r_valid.exit_code == 0
    assert "is valid" in r_valid.output

    # Invalid card
    bad_dict = {"schema_version": "1.1", "id": "bad-agent"}
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text(yaml.dump(bad_dict))

    r_bad = runner.invoke(app, ["--profile", "testprofile", "agent", "validate", str(bad_path)])
    assert r_bad.exit_code != 0
    assert "validation failed" in r_bad.output or "validation failed" in str(r_bad.stderr)


def test_cli_agent_import_and_list(cli_home: Path, tmp_path: Path):
    """Assert kin agent import copies card into agents_dir and registers it."""
    card_dict = create_agent_yaml("import-agent", "embedded")
    src_file = tmp_path / "import-source.yaml"
    src_file.write_text(yaml.dump(card_dict))

    # 1. Import
    r_imp = runner.invoke(app, ["--profile", "testprofile", "agent", "import", str(src_file)])
    assert r_imp.exit_code == 0
    assert "imported and registered" in r_imp.output

    # Assert copied to agents_dir as import-agent.yaml
    agents_dir = cli_home / ".kin" / "profiles" / "testprofile" / "agents"
    assert (agents_dir / "import-agent.yaml").exists()

    # 2. List (human)
    r_list = runner.invoke(app, ["--profile", "testprofile", "agent", "list"])
    assert r_list.exit_code == 0
    assert "import-agent" in r_list.output

    # 3. List (--json)
    r_list_json = runner.invoke(app, ["--profile", "testprofile", "agent", "list", "--json"])
    assert r_list_json.exit_code == 0
    cards_json = parse_json_output(r_list_json)
    assert len(cards_json) == 1
    assert cards_json[0]["agent_id"] == "import-agent"
    assert cards_json[0]["availability"] == "ready"
    assert cards_json[0]["availability_reason"] == "Ready to accept work."


def test_cli_agent_inspect_and_publish(cli_home: Path, tmp_path: Path):
    """Assert kin agent inspect and publish commands emit expected human and JSON outputs."""
    card_dict = create_agent_yaml("pub-agent", "embedded")
    src_file = tmp_path / "pub-agent.yaml"
    src_file.write_text(yaml.dump(card_dict))

    runner.invoke(app, ["--profile", "testprofile", "agent", "import", str(src_file)])

    # Inspect human
    r_insp = runner.invoke(app, ["--profile", "testprofile", "agent", "inspect", "pub-agent"])
    assert r_insp.exit_code == 0
    assert "Agent ID: pub-agent" in r_insp.output

    # Inspect --json (published projection ONLY)
    r_insp_json = runner.invoke(app, ["--profile", "testprofile", "agent", "inspect", "pub-agent", "--json"])
    assert r_insp_json.exit_code == 0
    insp_json = parse_json_output(r_insp_json)
    assert insp_json["agent_id"] == "pub-agent"
    assert "adapter" not in insp_json
    assert "boundaries" not in insp_json

    # Publish human
    r_pub = runner.invoke(app, ["--profile", "testprofile", "agent", "publish", "pub-agent"])
    assert r_pub.exit_code == 0
    assert "PUBLISHED AGENT CARD PROJECTION" in r_pub.output
    assert "No transport transmission was performed" in r_pub.output

    # Publish --json
    r_pub_json = runner.invoke(app, ["--profile", "testprofile", "agent", "publish", "pub-agent", "--json"])
    assert r_pub_json.exit_code == 0
    pub_json = parse_json_output(r_pub_json)
    assert pub_json["agent_id"] == "pub-agent"
    assert pub_json["requires_owner_acceptance"] is True


def test_cli_agent_enable_disable(cli_home: Path, tmp_path: Path):
    """Assert kin agent disable and enable update registered agent status and availability."""
    card_dict = create_agent_yaml("toggle-agent", "embedded")
    src_file = tmp_path / "toggle-agent.yaml"
    src_file.write_text(yaml.dump(card_dict))

    runner.invoke(app, ["--profile", "testprofile", "agent", "import", str(src_file)])

    # Disable
    r_dis = runner.invoke(app, ["--profile", "testprofile", "agent", "disable", "toggle-agent"])
    assert r_dis.exit_code == 0
    assert "disabled" in r_dis.output

    r_list = runner.invoke(app, ["--profile", "testprofile", "agent", "list", "--json"])
    data = parse_json_output(r_list)
    assert data[0]["enabled"] is False
    assert data[0]["availability"] == "policy_blocked"

    # Disabled agent cannot be published
    r_pub_fail = runner.invoke(app, ["--profile", "testprofile", "agent", "publish", "toggle-agent"])
    assert r_pub_fail.exit_code != 0
    assert "disabled" in r_pub_fail.output or "disabled" in str(r_pub_fail.stderr)

    # Enable
    r_en = runner.invoke(app, ["--profile", "testprofile", "agent", "enable", "toggle-agent"])
    assert r_en.exit_code == 0
    assert "enabled" in r_en.output

    r_list2 = runner.invoke(app, ["--profile", "testprofile", "agent", "list", "--json"])
    data2 = parse_json_output(r_list2)
    assert data2[0]["enabled"] is True
    assert data2[0]["availability"] == "ready"


def test_all_availability_reasons_in_cli_output(cli_home: Path, tmp_path: Path):
    """Assert all availability reasons from AVAILABILITY_EXPLANATIONS can be produced and displayed."""
    profile = "testprofile"

    # 1. NEEDS_KEY: Webhook adapter without password set in keyring
    wh_dict = create_agent_yaml("wh-key-agent", "webhook", profile)
    wh_file = tmp_path / "wh-key-agent.yaml"
    wh_file.write_text(yaml.dump(wh_dict))
    runner.invoke(app, ["--profile", profile, "agent", "import", str(wh_file)])

    r1 = runner.invoke(app, ["--profile", profile, "agent", "inspect", "wh-key-agent", "--json"])
    data1 = parse_json_output(r1)
    assert data1["availability"] == "needs_key"
    assert data1["availability_reason"] == AVAILABILITY_EXPLANATIONS[AgentAvailability.NEEDS_KEY]

    # 2. NEEDS_WORKSPACE: Local command adapter with non-existent directory
    lc_dict = create_agent_yaml("lc-ws-agent", "local_command", profile, wdir=str(tmp_path / "non_existent_dir_12345"))
    lc_file = tmp_path / "lc-ws-agent.yaml"
    lc_file.write_text(yaml.dump(lc_dict))
    runner.invoke(app, ["--profile", profile, "agent", "import", str(lc_file)])

    r2 = runner.invoke(app, ["--profile", profile, "agent", "inspect", "lc-ws-agent", "--json"])
    data2 = parse_json_output(r2)
    assert data2["availability"] == "needs_workspace"
    assert data2["availability_reason"] == AVAILABILITY_EXPLANATIONS[AgentAvailability.NEEDS_WORKSPACE]

    # 3. READY: Embedded adapter
    emb_dict = create_agent_yaml("emb-ready-agent", "embedded", profile)
    emb_file = tmp_path / "emb-ready-agent.yaml"
    emb_file.write_text(yaml.dump(emb_dict))
    runner.invoke(app, ["--profile", profile, "agent", "import", str(emb_file)])

    r3 = runner.invoke(app, ["--profile", profile, "agent", "inspect", "emb-ready-agent", "--json"])
    data3 = parse_json_output(r3)
    assert data3["availability"] == "ready"
    assert data3["availability_reason"] == AVAILABILITY_EXPLANATIONS[AgentAvailability.READY]

    # 4. POLICY_BLOCKED: Disabled agent
    runner.invoke(app, ["--profile", profile, "agent", "disable", "emb-ready-agent"])
    r4 = runner.invoke(app, ["--profile", profile, "agent", "inspect", "emb-ready-agent", "--json"])
    data4 = parse_json_output(r4)
    assert data4["availability"] == "policy_blocked"
    assert data4["availability_reason"] == AVAILABILITY_EXPLANATIONS[AgentAvailability.POLICY_BLOCKED]
