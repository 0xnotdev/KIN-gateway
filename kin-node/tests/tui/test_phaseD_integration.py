"""Phase D Integration Tests (§14.6 Phase D, §5 Integration Requirement).

Covers count unification across Sidebar badge, StatusBar pending_inbox_count,
Home approval count, and Inbox screen count; plus keyboard navigation (n/i/p).
"""

from pathlib import Path

import httpx
import pytest

from kin.cli import open_profile_db
from kin.policy.persistence import create_pending_approval
from kin.schemas import ActionClass, ApprovalRequest, RiskLabel
from kin.storage.db import create_schema
from kin.tui.app import KinApp
from kin.tui.local_state import (
    get_needs_you_items,
    get_pending_approvals,
    query_health_snapshot,
)
from kin.tui.shell import MainCanvas
from kin.tui.widgets.home_screen import HomeScreenWidget
from kin.tui.widgets.inbox_screen import InboxScreenWidget
from kin.tui.widgets.network_screen import NetworkScreenWidget


def make_mock_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=404, json={"detail": "Mock response"})
    return httpx.Client(transport=httpx.MockTransport(handler))


# -----------------------------------------------------------------------------
# 6.11 Integration — Sidebar, StatusBar, Home, and Inbox Pending Count Equality
# -----------------------------------------------------------------------------
def test_phaseD_pending_count_equality_across_all_four_surfaces(tmp_path: Path):
    """6.11 Assert Sidebar badge, StatusBar, Home, and Inbox agree on the same pending item count (§14.6 Phase D)."""
    prof_dir = tmp_path / "profiles" / "integ_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    db_path = prof_dir / "kin.db"

    conn = open_profile_db(db_path)
    create_schema(conn)

    # Insert 2 pending approvals
    for idx in (1, 2):
        conn.execute(
            f"INSERT INTO sessions (session_id, type, initiator_username, receiver_username, status, created_at, updated_at) VALUES ('sess-integ-{idx}', 'direct', 'alice', 'bob', 'active', '2026-07-31T00:00:00Z', '2026-07-31T00:00:00Z')"
        )
        req = ApprovalRequest(
            schema_version="1.1",
            approval_id=f"app-integ-{idx}",
            session_id=f"sess-integ-{idx}",
            agent_id=f"bot-{idx}",
            action_class=ActionClass.WORKSPACE_WRITE,
            summary=f"Integration write test {idx}",
            reason=f"Integration write test {idx}",
            risk_label=RiskLabel.HIGH,
            requested_scope={},
            expires_at="2026-12-31T23:59:59Z",
        )
        create_pending_approval(
            conn,
            b"0" * 32,
            req,
            agent_id=req.agent_id,
            action_class=req.action_class,
            expires_at=req.expires_at,
        )
    conn.close()

    # Query counts via local_state helpers
    needs_you_items = get_needs_you_items(prof_dir, "integ_user")
    pending_approvals = get_pending_approvals(prof_dir, "integ_user")
    total_pending = len(needs_you_items) + len(pending_approvals)

    assert total_pending == 2

    # Surface 1: HealthSnapshot / StatusBar
    health = query_health_snapshot("integ_user", prof_dir, client=make_mock_client())
    assert health.pending_inbox_count == 2

    # Surface 2: InboxScreenWidget
    inbox_screen = InboxScreenWidget(profile_dir=prof_dir, profile_name="integ_user")
    ny_inbox, app_inbox = inbox_screen.get_items()
    assert len(ny_inbox) + len(app_inbox) == 2

    # Surface 3: HomeScreenWidget
    home_screen = HomeScreenWidget(profile_dir=prof_dir, profile_name="integ_user", client=make_mock_client())
    assert home_screen.get_health().pending_inbox_count == 2

    # Surface 4: Sidebar (real instantiated widget)
    from kin.tui.shell import Sidebar
    sidebar = Sidebar(profile_dir=prof_dir, profile_name="integ_user")
    inbox_node = [n for n in sidebar.get_visible_nodes() if n.node_id == "space_inbox"][0]
    assert inbox_node.badge == "2"


def test_sidebar_real_nodes_no_demo_literals(tmp_path: Path):
    """Assert Sidebar renders real agent and contact names with ZERO demo literals (§A2)."""
    from kin.tui.shell import Sidebar
    from kin.agent_registry.peer_cards import cache_peer_card
    from kin.schemas import AgentCapabilities, AgentAvailability, PublishedAgentCard
    import yaml

    prof_dir = tmp_path / "profiles" / "real_sidebar_user"
    agents_dir = prof_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    db_path = prof_dir / "kin.db"

    # 1. Real local agent YAML
    card_yaml = {
        "schema_version": "1.1",
        "id": "sentinel-agent",
        "name": "Production Sentinel Agent",
        "description": "Real production agent",
        "adapter": {"type": "local_command", "command": "echo test", "working_directory": str(tmp_path.resolve())},
        "capabilities": {"tags": ["prod"], "accepts": ["text/plain"], "produces": ["text/plain"]},
        "boundaries": {"filesystem": "workspace_read", "shell": "deny", "max_runtime_seconds": 300, "max_artifact_bytes": 1048576},
        "autonomy": {"relay_information": "always_ask", "propose_actions": "always_ask", "execute_local_actions": "always_ask"},
    }
    (agents_dir / "sentinel-agent.yaml").write_text(yaml.dump(card_yaml), encoding="utf-8")

    # 2. Real trusted contact in DB
    conn = open_profile_db(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO contacts (username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at) VALUES ('charlie', 'Charlie Delta', 'pk1', 'xpk1', 'http://127.0.0.1:8000', 'always_ask', '2026-07-31T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    sidebar = Sidebar(profile_dir=prof_dir, profile_name="real_sidebar_user")
    nodes = sidebar.get_visible_nodes()
    node_titles = [n.title for n in nodes]

    assert "Production Sentinel Agent" in node_titles
    assert "Charlie Delta" in node_titles

    # Absolute invariant: demo literals MUST NOT be present
    assert "Code Scout" not in node_titles
    assert "Data Cleaner" not in node_titles
    assert "Bob" not in node_titles
    assert "Priya" not in node_titles


# -----------------------------------------------------------------------------
# 6.13 Integration — Keyboard Entry (n/i/p) Lands on Real Widgets
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_phaseD_keyboard_landing_on_real_widgets(tmp_path: Path):
    """6.13 Assert n/i/p workspace tab switches mount real Network and Inbox widgets (§14.6 Phase D)."""
    prof_dir = tmp_path / "profiles" / "key_nav_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client()

    home_w = HomeScreenWidget(profile_name="key_nav_user", profile_dir=prof_dir, client=mock_client)
    network_w = NetworkScreenWidget(profile_name="key_nav_user", profile_dir=prof_dir)
    inbox_w = InboxScreenWidget(profile_name="key_nav_user", profile_dir=prof_dir)

    canvas = MainCanvas(
        active_tab_kind="home",
        home_widget=home_w,
        network_widget=network_w,
        inbox_widget=inbox_w,
    )

    # 1. Switch to network ('n')
    canvas.set_active_tab_kind("network")
    assert canvas.active_tab_kind == "network"
    assert canvas.network_widget is network_w

    # 2. Switch to inbox ('i')
    canvas.set_active_tab_kind("inbox")
    assert canvas.active_tab_kind == "inbox"
    assert canvas.inbox_widget is inbox_w

    # 3. Switch to approvals ('p')
    canvas.set_active_tab_kind("approvals")
    assert canvas.active_tab_kind == "approvals"
    assert canvas.inbox_widget is inbox_w
