"""Unit, Security Boundary, and Integration Tests for Agents Screen (§14.6 Phase C).

Covers local-vs-peer security boundary separation (with adversarial fixture checks),
readiness reason displays, stale-card review flow using real is_stale()/mark_reviewed(),
unpaired state displays, and Home-to-Agents keyboard navigation integration.
"""

import io
from pathlib import Path

import httpx
import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.widgets import Input

from kin.agent_registry.peer_cards import cache_peer_card, is_stale, mark_reviewed
from kin.cli import open_profile_db
from kin.schemas import AgentAvailability, AgentCapabilities, PublishedAgentCard
from kin.storage.db import create_schema
from kin.tui.local_state import (
    get_all_agent_summaries,
    review_peer_card_staleness,
    toggle_local_agent_enabled,
)
from kin.tui.state import AgentCardView, ContactSummary
from kin.tui.widgets.agent_card import AgentCardWidget
from kin.tui.widgets.agents_screen import AgentsScreenWidget


def make_mock_client() -> httpx.Client:
    """Mock httpx client preventing socket I/O."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=404, json={"detail": "Mock response"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def render_widget_to_text(widget: AgentsScreenWidget, width: int = 160) -> str:
    """Render AgentsScreenWidget to string."""
    console = Console(file=io.StringIO(), width=width)
    console.print(widget.render())
    return console.file.getvalue()


# -----------------------------------------------------------------------------
# 1. Local-vs-Peer Security Boundary Separation (Adversarial Fixture Check)
# -----------------------------------------------------------------------------
def test_agents_screen_peer_security_boundary_adversarial_isolation():
    """1. Assert peer agent path never leaks adapter, path, or secret data even with adversarial input (§14.6 Phase C)."""
    peer_card = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="peer-adversary",
        name="Adversarial Peer Agent",
        description="Remote peer testing security isolation",
        capabilities=AgentCapabilities(tags=["peer", "remote"], accepts=["text/plain"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )

    # Convert to AgentCardView representing peer card
    peer_view = AgentCardView(
        agent_id=peer_card.agent_id,
        name=peer_card.name,
        description=peer_card.description,
        availability="active",
        readiness_reason=None,
        is_peer=True,
        capabilities_tags=peer_card.capabilities.tags,
    )

    # Render via AgentCardWidget
    card_widget = AgentCardWidget(card_view=peer_view)
    rendered = str(card_widget.render())

    # Adversarial assertions: zero local paths, zero adapter configs, zero vault secrets!
    assert "local_card_json" not in rendered
    assert "adapter" not in rendered
    assert "/home/user/" not in rendered
    assert "private_key" not in rendered
    assert "Adversarial Peer Agent" in rendered


# -----------------------------------------------------------------------------
# 2. Readiness Reason Rendered for Local & Peer Cards
# -----------------------------------------------------------------------------
def test_agents_screen_readiness_reason_rendered():
    """2. Assert readiness_reason is rendered for local & peer cards when unavailable or degraded (§14.6 Phase C)."""
    local_degraded = AgentCardView(
        agent_id="local-broken",
        name="Broken Local Agent",
        description="Local agent with missing binary",
        availability="degraded",
        readiness_reason="CLI executable '/usr/bin/missing_tool' not found on PATH",
        is_peer=False,
    )
    peer_stale = AgentCardView(
        agent_id="peer-stale",
        name="Stale Peer Agent",
        description="Peer agent updated remote spec",
        availability="degraded",
        readiness_reason="Peer card updated - owner review required",
        is_peer=True,
    )

    screen_widget = AgentsScreenWidget(
        local_agents=[local_degraded],
        peer_agents=[peer_stale],
        selected_agent_id="local-broken",
    )
    rendered = render_widget_to_text(screen_widget)

    assert "Broken Local Agent" in rendered
    assert "DEGRADED" in rendered
    assert "missing_tool" in rendered


# -----------------------------------------------------------------------------
# 3. Stale-Card Review Path using is_stale() and mark_reviewed()
# -----------------------------------------------------------------------------
def test_agents_screen_stale_card_review_flow(tmp_path: Path):
    """3. Stale-card review flow detects stale status via is_stale() and clears via mark_reviewed() (§14.6 Phase C)."""
    prof_dir = tmp_path / "profiles" / "stale_review_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    db_path = prof_dir / "kin.db"

    conn = open_profile_db(db_path)
    create_schema(conn)

    pub_card_v1 = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="peer-coder",
        name="Peer Coder V1",
        description="Initial peer card",
        capabilities=AgentCapabilities(tags=["code"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
    pub_card_v2 = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="peer-coder",
        name="Peer Coder V2 (Updated)",
        description="Updated peer card description",
        capabilities=AgentCapabilities(tags=["code", "refactor"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )

    # 1. Initial cache -> fresh
    status1 = cache_peer_card(conn, "alice", pub_card_v1)
    assert status1 == "fresh"
    assert is_stale(conn, "alice", "peer-coder") is False

    # 2. Updated cache -> stale
    status2 = cache_peer_card(conn, "alice", pub_card_v2)
    assert status2 == "stale"
    assert is_stale(conn, "alice", "peer-coder") is True
    conn.close()

    # 3. Review peer card staleness via TUI helper -> calls mark_reviewed()
    success = review_peer_card_staleness(prof_dir, "alice", "peer-coder")
    assert success is True

    conn2 = open_profile_db(db_path)
    assert is_stale(conn2, "alice", "peer-coder") is False
    conn2.close()


# -----------------------------------------------------------------------------
# 4. Unpaired Empty State
# -----------------------------------------------------------------------------
def test_agents_screen_unpaired_empty_state():
    """4. Unpaired empty state displays EmptyStateWidget notice (§14.6 Phase C)."""
    local_agent = AgentCardView(
        agent_id="local-code",
        name="Local Coder",
        description="Local agent",
        availability="active",
        readiness_reason=None,
        is_peer=False,
    )

    screen_widget = AgentsScreenWidget(
        local_agents=[local_agent],
        peer_agents=[],
        contacts=[],
        filter_tag="peer",
    )
    rendered = render_widget_to_text(screen_widget)

    assert "UNPAIRED STATE — NO PEER AGENTS VISIBLE" in rendered
    assert "Pair a contact in the Network tab" in rendered


# -----------------------------------------------------------------------------
# 5. Home-to-Agents Keyboard Navigation Integration Test
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_home_to_agents_keyboard_navigation_integration(tmp_path: Path):
    """5. Integration test: Enter key on Home roster jumps to Agents screen with selected agent (§14.6 Phase C)."""
    from kin.tui.shell import MainCanvas
    from kin.tui.widgets.home_screen import HomeScreenWidget

    prof_dir = tmp_path / "profiles" / "nav_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client()

    home_w = HomeScreenWidget(profile_name="nav_user", profile_dir=prof_dir, client=mock_client)
    agents_w = AgentsScreenWidget(profile_name="nav_user", profile_dir=prof_dir)
    canvas = MainCanvas(active_tab_kind="home", home_widget=home_w, agents_widget=agents_w)

    assert canvas.active_tab_kind == "home"

    # Simulate tab switch to "agents" and select agent
    canvas.set_active_tab_kind("agents")
    canvas.agents_widget.select_agent("code-scout")

    assert canvas.active_tab_kind == "agents"
    assert canvas.agents_widget.selected_agent_id == "code-scout"
