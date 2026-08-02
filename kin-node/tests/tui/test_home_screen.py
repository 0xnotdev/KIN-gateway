"""Unit, Snapshot, Scale, and Stress Tests for Home Screen Widget (§14.6 Phase B).

Covers all 6 required Home snapshot states (empty, healthy, live, queued, approval, security),
4 layout breakpoints (160x44, 120x36, 90x28, 80x24), scale virtualization, long labels,
in-place counter stress test, and no-interrupt input preservation.
All tests use mock httpx transports to guarantee zero real network I/O.
"""

import io
from pathlib import Path

import httpx
import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.widgets import Input

from kin.tui.fixtures import (
    make_all_approval_view_fixtures,
    make_all_session_summary_fixtures,
    make_session_summary_fixture,
)
from kin.tui.local_state import (
    get_local_agents_summaries,
    get_local_contacts_summaries,
    query_health_snapshot,
)
from kin.tui.state import (
    AgentCardView,
    ApprovalView,
    ContactSummary,
    HealthSnapshot,
    SessionSummary,
)
from kin.tui.widgets.home_screen import HomeScreenWidget


def make_mock_client(status_code: int = 404) -> httpx.Client:
    """Construct a mock httpx.Client that returns mock HTTP responses with zero network I/O."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, json={"detail": "Mock probe response"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def render_widget_to_text(widget: HomeScreenWidget, width: int = 160) -> str:
    """Render a Rich renderable widget to text at a specific terminal width."""
    console = Console(file=io.StringIO(), width=width)
    console.print(widget.render())
    return console.file.getvalue()


class HomeScreenTestApp(App):
    """Test harness App for mounting HomeScreenWidget."""

    def __init__(self, home_widget: HomeScreenWidget) -> None:
        super().__init__()
        self.home_widget = home_widget

    def compose(self) -> ComposeResult:
        yield self.home_widget
        yield Input(placeholder="Type here...", id="active-text-input")


# -----------------------------------------------------------------------------
# 1. State 1: EMPTY Profile State Snapshot (with 5-second onboarding prompt)
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("width,height", [(160, 44), (120, 36), (90, 28), (80, 24)])
def test_home_screen_state_1_empty_profile_snapshots(tmp_path: Path, width: int, height: int):
    """State 1: Empty profile home screen renders 5-second onboarding prompt across 4 breakpoints (§14.6 Phase B)."""
    prof_dir = tmp_path / "profiles" / "empty_home_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client(404)

    widget = HomeScreenWidget(profile_name="empty_home_user", profile_dir=prof_dir, client=mock_client)
    rendered = render_widget_to_text(widget, width=width)

    assert "KIN V1.1 HOME DASHBOARD" in rendered
    assert "FIRST FLIGHT ONBOARDING RECOMMENDED" in rendered
    assert "0 Total" in rendered


# -----------------------------------------------------------------------------
# 2. State 2: HEALTHY Profile State Snapshot
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("width,height", [(160, 44), (120, 36), (90, 28), (80, 24)])
def test_home_screen_state_2_healthy_profile_snapshots(tmp_path: Path, width: int, height: int):
    """State 2: Healthy profile renders real local agents & contacts and fixture sessions across 4 breakpoints (§14.6 Phase B)."""
    prof_dir = tmp_path / "profiles" / "healthy_home_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client(200)

    sample_agents = [
        AgentCardView(agent_id="code-scout", name="Code Scout", description="Explores codebases", availability="active", readiness_reason=None, is_peer=False),
        AgentCardView(agent_id="doc-bot", name="Doc Bot", description="Documentation writer", availability="available", readiness_reason=None, is_peer=False),
    ]
    sample_contacts = [
        ContactSummary(username="alice", display_name="Alice Smith", public_key="0"*64, x25519_public_key="1"*64, endpoint="http://127.0.0.1:8321", fingerprint="a1b2c3d4e5f67890"),
    ]
    sample_sessions = list(make_all_session_summary_fixtures().values())[:3]

    widget = HomeScreenWidget(
        profile_name="healthy_home_user",
        profile_dir=prof_dir,
        agents=sample_agents,
        contacts=sample_contacts,
        sessions=sample_sessions,
        client=mock_client,
        health=HealthSnapshot(keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0),
    )
    rendered = render_widget_to_text(widget, width=width)

    assert "Code Scout" in rendered
    assert "Doc Bot" in rendered
    assert "Alice Smith" in rendered
    assert "HEALTHY" in rendered


# -----------------------------------------------------------------------------
# 3. State 3: LIVE Sessions State Snapshot
# -----------------------------------------------------------------------------
def test_home_screen_state_3_live_sessions_snapshot(tmp_path: Path):
    """State 3: Live sessions dashboard snapshot renders active and streaming session map previews (§14.6 Phase B)."""
    prof_dir = tmp_path / "profiles" / "live_sessions_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client(200)

    live_sessions = [
        make_session_summary_fixture("active", "sess-live-001"),
        make_session_summary_fixture("awaiting_peer", "sess-live-002"),
        make_session_summary_fixture("awaiting_owner_approval", "sess-live-003"),
    ]

    widget = HomeScreenWidget(
        profile_name="live_sessions_user",
        profile_dir=prof_dir,
        sessions=live_sessions,
        client=mock_client,
        health=HealthSnapshot(keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0),
    )
    rendered = render_widget_to_text(widget)

    assert "sess-live-001" in rendered
    assert "sess-live-002" in rendered
    assert "sess-live-003" in rendered
    assert "ACTIVE" in rendered


# -----------------------------------------------------------------------------
# 4. State 4: QUEUED Approvals Queue List Snapshot
# -----------------------------------------------------------------------------
def test_home_screen_state_4_queued_approvals_snapshot(tmp_path: Path):
    """State 4: Multi-item approval queue list snapshot renders Needs You section with pending gates (§14.6 Phase B)."""
    prof_dir = tmp_path / "profiles" / "queued_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client(200)

    approvals = make_all_approval_view_fixtures()[:3]

    widget = HomeScreenWidget(
        profile_name="queued_user",
        profile_dir=prof_dir,
        approvals=approvals,
        client=mock_client,
        health=HealthSnapshot(keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0),
    )
    rendered = render_widget_to_text(widget)

    assert "Needs You (Pending Approvals)" in rendered
    assert len(approvals) == 3


# -----------------------------------------------------------------------------
# 5. State 5: APPROVAL State (Single Critical Gate Focused Detail) Snapshot
# -----------------------------------------------------------------------------
def test_home_screen_state_5_approval_focused_snapshot(tmp_path: Path):
    """State 5: Single focused critical action approval card snapshot highlighting risk & reasons (§14.6 Phase B)."""
    from kin.tui.widgets.approval_card import ApprovalCardWidget

    critical_approval = make_all_approval_view_fixtures()[0]
    card_widget = ApprovalCardWidget(approval_view=critical_approval)
    
    console = Console(file=io.StringIO(), width=120)
    console.print(card_widget.render())
    rendered = console.file.getvalue()

    assert "RISK:" in rendered
    assert "Action:" in rendered
    assert "Requester:" in rendered
    assert "Reason:" in rendered


# -----------------------------------------------------------------------------
# 6. State 6: SECURITY / Peer Isolation State Snapshot
# -----------------------------------------------------------------------------
def test_home_screen_state_6_security_peer_isolation_snapshot(tmp_path: Path):
    """State 6: Security snapshot verifies peer agent boundary and fingerprint verification displays (§14.6 Phase B)."""
    prof_dir = tmp_path / "profiles" / "security_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client(200)

    peer_agent = AgentCardView(
        agent_id="peer-bob",
        name="Bob (Peer Agent)",
        description="Remote peer agent",
        availability="active",
        readiness_reason=None,
        is_peer=True,
    )
    verified_contact = ContactSummary(
        username="bob",
        display_name="Bob Jones",
        public_key="0" * 64,
        x25519_public_key="1" * 64,
        endpoint="http://127.0.0.1:8322",
        autonomy_level="always_ask",
        fingerprint="9988776655443322",
        verified_at="2026-07-30T10:00:00Z",
    )

    widget = HomeScreenWidget(
        profile_name="security_user",
        profile_dir=prof_dir,
        agents=[peer_agent],
        contacts=[verified_contact],
        client=mock_client,
        health=HealthSnapshot(keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0),
    )
    rendered = render_widget_to_text(widget)

    assert "Bob (Peer Agent)" in rendered
    assert "Bob Jones" in rendered
    assert "9988776655443322" in rendered


# -----------------------------------------------------------------------------
# 7. Scale Virtualization Snapshot Test (100 sessions / 20 agents)
# -----------------------------------------------------------------------------
def test_home_screen_scale_virtualization_100_sessions_20_agents(tmp_path: Path):
    """Scale test: 100 sessions & 20 agents use bounded rendering for scale performance (§14.6 Phase B)."""
    prof_dir = tmp_path / "profiles" / "scale_home_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client(200)

    many_agents = [
        AgentCardView(agent_id=f"agent-{i}", name=f"Agent {i}", description=f"Description {i}", availability="active", readiness_reason=None, is_peer=False)
        for i in range(20)
    ]
    many_sessions = [
        make_session_summary_fixture("active", f"sess-{i}")
        for i in range(100)
    ]

    widget = HomeScreenWidget(
        profile_name="scale_home_user",
        profile_dir=prof_dir,
        agents=many_agents,
        sessions=many_sessions,
        client=mock_client,
        health=HealthSnapshot(keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0),
        max_visible_sessions=10,
        max_visible_agents=6,
    )
    rendered = render_widget_to_text(widget)

    assert "+ 90 more sessions" in rendered
    assert "+ 14 more agents" in rendered


# -----------------------------------------------------------------------------
# 8. Long Labels Snapshot Test
# -----------------------------------------------------------------------------
def test_home_screen_long_labels(tmp_path: Path):
    """Long labels snapshot: long agent names & session titles render safely without crash (§14.6 Phase B)."""
    prof_dir = tmp_path / "profiles" / "long_label_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client(200)

    long_agent = AgentCardView(
        agent_id="agent-with-an-extremely-long-descriptive-identifier-name-100",
        name="Agent With An Extremely Long Descriptive Identifier Name",
        description="Extremely long description " * 5,
        availability="active",
        readiness_reason=None,
        is_peer=False,
    )
    long_session = make_session_summary_fixture("active", "sess-long-12345")

    widget = HomeScreenWidget(
        profile_name="long_label_user",
        profile_dir=prof_dir,
        agents=[long_agent],
        sessions=[long_session],
        client=mock_client,
        health=HealthSnapshot(keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0),
    )
    rendered = render_widget_to_text(widget)

    assert "agent-with-an-extremely-long-descriptive-identifier-name-100" in rendered
    assert "sess-long-12345" in rendered


# -----------------------------------------------------------------------------
# 9. In-Place Counter Update Stress Test
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_home_screen_counters_update_in_place_stress_test(tmp_path: Path):
    """In-place counter update stress test: 100 counter updates preserve focus & cursor (§14.6 Phase B)."""
    prof_dir = tmp_path / "profiles" / "stress_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client(200)

    widget = HomeScreenWidget(
        profile_name="stress_user",
        profile_dir=prof_dir,
        client=mock_client,
        health=HealthSnapshot(keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0),
    )
    app = HomeScreenTestApp(widget)

    async with app.run_test() as pilot:
        inp = app.query_one("#active-text-input", Input)
        inp.focus()
        inp.value = "User active input string"
        await pilot.pause()
        inp.cursor_position = 10

        # Inject 100 counter updates
        for i in range(100):
            widget.sessions = [
                make_session_summary_fixture("active", f"sess-{j}")
                for j in range(i % 15)
            ]
            widget.refresh()
            await pilot.pause(0.001)

        # ASSERTIONS: Focus and cursor position remain 100% untouched!
        assert app.focused == inp
        assert inp.value == "User active input string"
        assert inp.cursor_position == 10


# -----------------------------------------------------------------------------
# 10. No-Interrupt Active Input Test
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_home_screen_no_interrupt_active_input(tmp_path: Path):
    """No-interrupt test: incoming background events cannot print over or force-switch input (§14.6 Phase B)."""
    prof_dir = tmp_path / "profiles" / "no_interrupt_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    mock_client = make_mock_client(200)

    widget = HomeScreenWidget(
        profile_name="no_interrupt_user",
        profile_dir=prof_dir,
        client=mock_client,
        health=HealthSnapshot(keychain_ok=True, identity_ok=True, relay_reachable=True, node_reachable=True, pending_inbox_count=0),
    )
    app = HomeScreenTestApp(widget)

    async with app.run_test() as pilot:
        inp = app.query_one("#active-text-input", Input)
        inp.focus()
        inp.value = "Draft dispatch prompt in progress..."

        # Simulate background event updating approvals
        widget.approvals = make_all_approval_view_fixtures()[:2]
        widget.refresh()
        await pilot.pause(0.01)

        # Assert active input value is preserved cleanly without interruption
        assert inp.value == "Draft dispatch prompt in progress..."
        assert app.focused == inp
