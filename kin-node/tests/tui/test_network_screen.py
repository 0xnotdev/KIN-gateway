"""Unit, Redaction, and Network Isolation Tests for NetworkScreenWidget (§14.6 Phase D).

Covers adversarial public key redaction/truncation, empty/unpaired state rendering,
zero live HTTP calls on render, and peer-card freshness alert navigation signals.
"""

import io
from pathlib import Path

import pytest
from rich.console import Console

from kin.agent_registry.peer_cards import cache_peer_card
from kin.cli import open_profile_db
from kin.schemas import AgentAvailability, AgentCapabilities, PublishedAgentCard
from kin.storage.db import create_schema
from kin.tui.state import ContactSummary
from kin.tui.widgets.network_screen import NetworkScreenWidget


def render_widget_to_text(widget: NetworkScreenWidget, width: int = 160) -> str:
    console = Console(file=io.StringIO(), width=width)
    console.print(widget.render())
    return console.file.getvalue()


# -----------------------------------------------------------------------------
# 6.1 Network — Adversarial Redaction & Truncation Test
# -----------------------------------------------------------------------------
def test_network_screen_adversarial_redaction_and_truncation():
    """6.1 Assert full public_key/x25519_public_key never appears unredacted/untruncated (§14.6 Phase D)."""
    full_pub_key = "a1b2c3d4e5f60718293a4b5c6d7e8f901234567890abcdef1234567890abcdef"
    full_x25519_key = "f9e8d7c6b5a403928170655443322110fedcba0987654321fedcba0987654321"

    c = ContactSummary(
        username="alice",
        display_name="Alice Smith",
        public_key=full_pub_key,
        x25519_public_key=full_x25519_key,
        endpoint="http://127.0.0.1:8321",
        autonomy_level="always_ask",
        fingerprint="word-apple-banana-cherry",
        verified_at="2026-07-31T00:00:00Z",
    )

    screen = NetworkScreenWidget(contacts=[c])
    rendered = render_widget_to_text(screen)

    # Invariants: full 64-char key strings MUST NOT render
    assert full_pub_key not in rendered
    assert full_x25519_key not in rendered
    assert "word-apple-banana-cherry" in rendered
    assert "Alice Smith" in rendered


# -----------------------------------------------------------------------------
# 6.2 Network — Empty / Unpaired State Renders Next Action
# -----------------------------------------------------------------------------
def test_network_screen_empty_unpaired_state():
    """6.2 Assert empty/unpaired state renders next action with zero pairing forms (§14.6 Phase D)."""
    screen = NetworkScreenWidget(contacts=[])
    rendered = render_widget_to_text(screen)

    assert "ZERO PAIRED TRUSTED CONTACTS" in rendered
    assert "kin pair <code>" in rendered
    assert "search directory" not in rendered.lower()


# -----------------------------------------------------------------------------
# 6.3 Network — Zero Live HTTP Calls on Render
# -----------------------------------------------------------------------------
def test_network_screen_zero_live_http_calls_on_render(monkeypatch):
    """6.3 Assert NetworkScreenWidget render() issues ZERO live HTTP calls (§14.6 Phase D)."""
    import httpx

    calls: list[str] = []

    def guard_http(url, *args, **kwargs):
        calls.append(str(url))
        raise RuntimeError("Forbidden live HTTP call during render!")

    monkeypatch.setattr(httpx, "get", guard_http)
    monkeypatch.setattr(httpx.Client, "get", guard_http)

    c = ContactSummary(
        username="bob",
        display_name="Bob Builder",
        public_key="12345678",
        x25519_public_key="87654321",
        endpoint="http://127.0.0.1:8321",
        autonomy_level="always_ask",
    )

    screen = NetworkScreenWidget(contacts=[c])
    rendered = render_widget_to_text(screen)

    assert len(calls) == 0
    assert "Bob Builder" in rendered


# -----------------------------------------------------------------------------
# 6.4 Network — Stale Peer-Card Freshness Alert Navigation Signal
# -----------------------------------------------------------------------------
def test_network_screen_stale_card_count_alert_navigation_signal(tmp_path: Path):
    """6.4 Stale peer-card count displays alert navigation trigger (§14.6 Phase D)."""
    prof_dir = tmp_path / "profiles" / "stale_net_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    db_path = prof_dir / "kin.db"

    conn = open_profile_db(db_path)
    create_schema(conn)

    card1 = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="bot1",
        name="Bot 1",
        description="Initial",
        capabilities=AgentCapabilities(tags=["test"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
    card2 = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id="bot1",
        name="Bot 1 Updated",
        description="Updated",
        capabilities=AgentCapabilities(tags=["test", "v2"]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )

    cache_peer_card(conn, "charlie", card1)
    cache_peer_card(conn, "charlie", card2)  # Stale
    conn.close()

    c = ContactSummary(
        username="charlie",
        display_name="Charlie Peer",
        public_key="abcdef123456",
        x25519_public_key="654321fedcba",
        endpoint="http://127.0.0.1:8321",
        autonomy_level="always_ask",
    )

    screen = NetworkScreenWidget(profile_dir=prof_dir, contacts=[c])
    rendered = render_widget_to_text(screen)

    assert "1 card(s) need review" in rendered
