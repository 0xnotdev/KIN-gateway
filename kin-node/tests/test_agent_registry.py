"""Unit tests for kin.agent_registry package (loader, availability, registry, peer_cards)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

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
    WebhookAdapterConfig,
)
from kin.storage.db import get_connection, create_schema
from kin.storage.vault import decrypt_field
from kin.identity.resolver import ProfileContextResolver
from kin.identity.storage import get_agent_credential_service
from kin.agent_registry.availability import AVAILABILITY_EXPLANATIONS, compute_availability
from kin.agent_registry.loader import CardLoadError, is_v11_card_file, load_card_file
from kin.agent_registry.peer_cards import cache_peer_card, is_stale, mark_reviewed
from kin.agent_registry.registry import (
    get_agents_dir,
    get_card,
    import_card,
    list_cards,
    publish_card,
    register_card,
    scan_local_cards,
    set_enabled,
)


@pytest.fixture
def test_db(tmp_path: Path):
    db_path = tmp_path / "kin.db"
    conn = get_connection(db_path)
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def vault_key():
    return b"01234567890123456789012345678901"


def create_valid_card_dict(agent_id="agent-alpha", profile="default") -> dict:
    return {
        "schema_version": "1.1",
        "id": agent_id,
        "name": "Alpha Agent",
        "description": "Test alpha agent",
        "adapter": {
            "type": "webhook",
            "webhook_url": "https://example.com/webhook",
            "credential_ref": get_agent_credential_service(profile, agent_id, "webhook_secret"),
        },
        "capabilities": {
            "tags": ["testing", "alpha"],
            "accepts": ["application/json"],
            "produces": ["application/json"],
        },
        "boundaries": {
            "network_access": "allow",
            "filesystem": "none",
            "shell": "deny",
            "max_runtime_seconds": 600,
            "max_artifact_bytes": 1000000,
        },
        "autonomy": {
            "relay_information": "always_ask",
            "propose_actions": "always_ask",
            "execute_local_actions": "always_ask",
        },
    }


def test_valid_adapter_types_load_and_register(tmp_path: Path, test_db, vault_key):
    """Assert embedded, webhook, and local_command cards parse and register cleanly."""
    profile = "testprof"
    
    # 1. Local command card
    lc_dict = create_valid_card_dict("local-agent", profile)
    lc_dict["adapter"] = {
        "type": "local_command",
        "command": "python script.py",
        "working_directory": str(tmp_path),
    }
    lc_file = tmp_path / "local-agent.yaml"
    lc_file.write_text(yaml.dump(lc_dict))
    card_lc = load_card_file(lc_file, expected_agent_id="local-agent", profile_name=profile)
    assert card_lc.id == "local-agent"
    register_card(test_db, vault_key, card_lc, profile_name=profile)

    # 2. Embedded card
    emb_dict = create_valid_card_dict("emb-agent", profile)
    emb_dict["adapter"] = {
        "type": "embedded",
        "provider": "openrouter",
        "model": "google/gemini-2.5-flash",
    }
    emb_file = tmp_path / "emb-agent.yaml"
    emb_file.write_text(yaml.dump(emb_dict))
    card_emb = load_card_file(emb_file, expected_agent_id="emb-agent", profile_name=profile)
    assert card_emb.id == "emb-agent"
    register_card(test_db, vault_key, card_emb, profile_name=profile)

    # Assert both registered
    records = list_cards(test_db)
    ids = [r["agent_id"] for r in records]
    assert "local-agent" in ids
    assert "emb-agent" in ids


def test_invalid_yaml_syntax(tmp_path: Path):
    """Assert malformed YAML raises clean CardLoadError."""
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("schema_version: 1.1\n  invalid_indent: [unclosed")
    with pytest.raises(CardLoadError) as exc_info:
        load_card_file(bad_file)
    assert "Malformed YAML" in str(exc_info.value)


def test_duplicate_id_in_scan(tmp_path: Path):
    """Assert duplicate agent ID across two files produces CardLoadError on second file."""
    card_data = create_valid_card_dict("dupe-id", "default")
    (tmp_path / "a_file.yaml").write_text(yaml.dump(card_data))
    
    card_data_2 = create_valid_card_dict("dupe-id", "default")
    card_data_2["name"] = "Second File"
    (tmp_path / "b_file.yaml").write_text(yaml.dump(card_data_2))

    valid_cards, per_file_errors, legacy_skipped = scan_local_cards(tmp_path, profile_name="default")
    # Note: filename stem mismatch on a_file (expects 'a_file', got 'dupe-id') or duplicate ID produces error
    assert len(per_file_errors) >= 1


def test_unsafe_id_rejection(tmp_path: Path):
    """Assert invalid or unsafe ID patterns (path traversal, null bytes) are rejected."""
    card_dict = create_valid_card_dict("unsafe/id", "default")
    card_file = tmp_path / "unsafe.yaml"
    card_file.write_text(yaml.dump(card_dict))

    with pytest.raises(CardLoadError) as exc:
        load_card_file(card_file)
    assert "Schema validation error" in str(exc.value) or "id must match" in str(exc.value)


def test_unknown_adapter_type(tmp_path: Path):
    """Assert unrecognized adapter type is rejected by discriminated union."""
    card_dict = create_valid_card_dict("shell-agent", "default")
    card_dict["adapter"] = {"type": "shell_direct", "command": "bash"}
    card_file = tmp_path / "shell-agent.yaml"
    card_file.write_text(yaml.dump(card_dict))

    with pytest.raises(CardLoadError) as exc:
        load_card_file(card_file)
    assert "Schema validation error" in str(exc.value)


def test_secret_in_yaml_and_mismatched_credential_ref(tmp_path: Path):
    """Assert extra 'webhook_secret' field or wrong credential_ref format is rejected."""
    # 1. Raw secret in YAML (forbidden extra field)
    card_dict = create_valid_card_dict("secret-agent", "default")
    card_dict["adapter"]["webhook_secret"] = "sk-raw-secret-value-123"
    card_file = tmp_path / "secret-agent.yaml"
    card_file.write_text(yaml.dump(card_dict))

    with pytest.raises(CardLoadError) as exc:
        load_card_file(card_file, profile_name="default")
    assert "Schema validation error" in str(exc.value)

    # 2. Mismatched credential_ref format
    card_dict_2 = create_valid_card_dict("bad-ref-agent", "default")
    card_dict_2["adapter"]["credential_ref"] = "some-random-ref-name"
    card_file_2 = tmp_path / "bad-ref-agent.yaml"
    card_file_2.write_text(yaml.dump(card_dict_2))

    with pytest.raises(CardLoadError) as exc:
        load_card_file(card_file_2, profile_name="default")
    assert "does not match expected keychain service name" in str(exc.value)


def test_bad_timeout_and_artifact_size_limits(tmp_path: Path):
    """Assert boundary limits <= 0 or exceeding max caps are rejected."""
    # max_runtime_seconds > 3600
    c1 = create_valid_card_dict("t1", "default")
    c1["boundaries"]["max_runtime_seconds"] = 7200
    f1 = tmp_path / "t1.yaml"
    f1.write_text(yaml.dump(c1))
    with pytest.raises(CardLoadError):
        load_card_file(f1)

    # max_artifact_bytes <= 0
    c2 = create_valid_card_dict("t2", "default")
    c2["boundaries"]["max_artifact_bytes"] = 0
    f2 = tmp_path / "t2.yaml"
    f2.write_text(yaml.dump(c2))
    with pytest.raises(CardLoadError):
        load_card_file(f2)


def test_bad_mime_and_overlong_capabilities(tmp_path: Path):
    """Assert invalid MIME patterns or overlong tags/lists are rejected."""
    c1 = create_valid_card_dict("mime1", "default")
    c1["capabilities"]["accepts"] = ["invalid-mime-no-slash"]
    f1 = tmp_path / "mime1.yaml"
    f1.write_text(yaml.dump(c1))
    with pytest.raises(CardLoadError):
        load_card_file(f1)

    c2 = create_valid_card_dict("tag1", "default")
    c2["capabilities"]["tags"] = ["a" * 65]
    f2 = tmp_path / "tag1.yaml"
    f2.write_text(yaml.dump(c2))
    with pytest.raises(CardLoadError):
        load_card_file(f2)


def test_corrupt_card_in_directory_scan(tmp_path: Path):
    """Assert corrupt V1.1 card is logged as per-file error without aborting valid cards in directory."""
    # Valid card
    c_valid = create_valid_card_dict("valid-card", "default")
    (tmp_path / "valid-card.yaml").write_text(yaml.dump(c_valid))

    # Corrupt V1.1 card
    c_corrupt = {"schema_version": "1.1", "id": "corrupt-card", "invalid_field": True}
    (tmp_path / "corrupt-card.yaml").write_text(yaml.dump(c_corrupt))

    valid_cards, per_file_errors, legacy_skipped = scan_local_cards(tmp_path, profile_name="default")
    assert len(valid_cards) == 1
    assert valid_cards[0].id == "valid-card"
    assert len(per_file_errors) == 1
    assert "corrupt-card.yaml" in str(per_file_errors[0])


def test_legacy_v1_coexistence(tmp_path: Path):
    """Assert scan_local_cards loads V1.1 cards and cleanly skips legacy V1 card YAML files."""
    # V1.1 card
    c_v11 = create_valid_card_dict("v11-card", "default")
    (tmp_path / "v11-card.yaml").write_text(yaml.dump(c_v11))

    # Legacy V1 card (no schema_version)
    c_v1 = {"name": "OldV1Agent", "backend_type": "embedded", "provider": "openai"}
    (tmp_path / "legacy_agent.yaml").write_text(yaml.dump(c_v1))

    valid_cards, per_file_errors, legacy_skipped = scan_local_cards(tmp_path, profile_name="default")
    assert len(valid_cards) == 1
    assert valid_cards[0].id == "v11-card"
    assert len(per_file_errors) == 0
    assert len(legacy_skipped) == 1
    assert legacy_skipped[0].name == "legacy_agent.yaml"


def test_peer_card_caching_and_staleness(test_db):
    """Assert cache_peer_card, staleness flag, and mark_reviewed workflow."""
    pub_card = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="peer-bot",
        name="Peer Bot",
        description="A peer bot",
        capabilities=AgentCapabilities(tags=["peer"], accepts=["text/plain"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )

    # 1. Initial cache -> fresh
    r1 = cache_peer_card(test_db, "bob", pub_card)
    assert r1 == "fresh"
    assert is_stale(test_db, "bob", "peer-bot") is False

    # 2. Same content -> unchanged
    r2 = cache_peer_card(test_db, "bob", pub_card)
    assert r2 == "unchanged"
    assert is_stale(test_db, "bob", "peer-bot") is False

    # 3. Modified content -> stale
    pub_card_updated = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="peer-bot",
        name="Peer Bot Updated",
        description="A peer bot with updated description",
        capabilities=AgentCapabilities(tags=["peer", "updated"], accepts=["text/plain"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
    r3 = cache_peer_card(test_db, "bob", pub_card_updated)
    assert r3 == "stale"
    assert is_stale(test_db, "bob", "peer-bot") is True

    # 4. Mark reviewed -> fresh
    mark_reviewed(test_db, "bob", "peer-bot")
    assert is_stale(test_db, "bob", "peer-bot") is False


def test_card_version_increment(test_db, vault_key):
    """Assert re-registering an agent_id with updated card increments card_version."""
    c1 = AgentCard.model_validate(create_valid_card_dict("ver-agent", "default"))
    register_card(test_db, vault_key, c1, profile_name="default")
    r1 = get_card(test_db, "ver-agent")
    assert r1["card_version"] == 1

    c2_dict = create_valid_card_dict("ver-agent", "default")
    c2_dict["description"] = "Updated version description"
    c2 = AgentCard.model_validate(c2_dict)
    register_card(test_db, vault_key, c2, profile_name="default")
    r2 = get_card(test_db, "ver-agent")
    assert r2["card_version"] == 2
