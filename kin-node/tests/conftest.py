"""Pytest fixtures for KIN V1.1 test harness."""

from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.schemas import (
    AgentAutonomy,
    AgentAvailability,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    AutonomyLevel,
    LocalCommandAdapterConfig,
    PublishedAgentCard,
)


@pytest.fixture
def alice_keys():
    seed = b"alice-test-key-seed-32bytes-long"
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    return {"private_key": priv, "public_key": priv.public_key()}


@pytest.fixture
def bob_keys():
    seed = b"bob-test-key-seed-32bytes-longer"
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    return {"private_key": priv, "public_key": priv.public_key()}


@pytest.fixture
def alice_profile_root(tmp_path: Path) -> Path:
    p = tmp_path / "profiles" / "alice"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def bob_profile_root(tmp_path: Path) -> Path:
    p = tmp_path / "profiles" / "bob"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def frozen_clock():
    return "2026-07-22T12:00:00.000Z"


@pytest.fixture
def sample_agent_card():
    return AgentCard(
        schema_version="1.1",
        id="code-scout",
        name="Code Scout",
        description="Reviews repository diffs and proposes patch fixes.",
        adapter=LocalCommandAdapterConfig(type="local_command", command="codex", working_directory="/work/code"),
        capabilities=AgentCapabilities(tags=["code-review", "patch-proposal"], accepts=["text/x-diff"]),
        boundaries=AgentBoundaries(network_access="deny", filesystem="none", shell="deny", max_runtime_seconds=900, max_artifact_bytes=10_000_000),
        autonomy=AgentAutonomy(relay_information=AutonomyLevel.ALWAYS_ASK, propose_actions=AutonomyLevel.ALWAYS_ASK, execute_local_actions=AutonomyLevel.ALWAYS_ASK),
    )


@pytest.fixture
def sample_published_card():
    return PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="data-cleaner",
        name="Data Cleaner",
        description="Converts raw tabular data into validated CSV artifacts.",
        capabilities=AgentCapabilities(tags=["data-cleaning", "csv"], accepts=["text/csv"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
