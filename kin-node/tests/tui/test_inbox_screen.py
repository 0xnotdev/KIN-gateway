"""Unit, Policy, Authorization, and Expiry Tests for InboxScreenWidget (§14.6 Phase D & Rework).

Covers:
4.1 DENY reason UI validation gate and DB immutability.
4.2 Owner-only authorization rejection and DB state preservation.
4.3 Quiet hours notification suppression rules vs list visibility.
4.4 No-interrupt active input focus guarantee via Pilot test.
4.5 ISO8601 timestamp boundary comparison test.
"""

from datetime import datetime, timezone
import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from kin.cli import open_profile_db
from kin.identity.storage import get_or_create_vault_key
from kin.policy.persistence import create_pending_approval
from kin.schemas import ActionClass, ApprovalRequest, RiskLabel
from kin.storage.db import create_schema, get_connection
from kin.tui.local_state import decide_pending_approval, get_pending_approvals, parse_iso_utc
from kin.tui.state import ApprovalView, NeedsYouItem
from kin.tui.widgets.inbox_screen import DenyReasonModal, EditConstraintsModal, InboxScreenWidget


def render_widget_to_text(widget: InboxScreenWidget, width: int = 160) -> str:
    console = Console(file=io.StringIO(), width=width)
    console.print(widget.render())
    return console.file.getvalue()


# -----------------------------------------------------------------------------
# 6.5 Inbox — Pending Approvals Render
# -----------------------------------------------------------------------------
def test_inbox_screen_pending_approvals_render(tmp_path: Path):
    """6.5 Pending approvals built via create_pending_approval render in Inbox screen (§14.6 Phase D)."""
    prof_dir = tmp_path / "profiles" / "app_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    db_path = prof_dir / "kin.db"

    conn = open_profile_db(db_path)
    create_schema(conn)

    conn.execute(
        "INSERT INTO sessions (session_id, type, initiator_username, receiver_username, status, created_at, updated_at) VALUES ('sess-abc', 'direct', 'alice', 'bob', 'active', '2026-07-31T00:00:00Z', '2026-07-31T00:00:00Z')"
    )

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="app-12345",
        session_id="sess-abc",
        agent_id="code-bot",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Write patch to src/main.py",
        reason="Write patch to src/main.py",
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
    conn.commit()
    conn.close()

    pending = get_pending_approvals(prof_dir)
    assert len(pending) == 1
    assert pending[0].request.approval_id == "app-12345"

    screen = InboxScreenWidget(profile_dir=prof_dir, approvals=pending)
    rendered = render_widget_to_text(screen)

    assert "APPROVAL QUEUE" in rendered
    assert "code-bot" in rendered


# -----------------------------------------------------------------------------
# 4.1 Inbox — DENY Without a Reason Rejected by UI Gate & DB Unchanged (§4.1)
# -----------------------------------------------------------------------------
class DenyTestApp(App):
    """Test harness App for DenyReasonModal interactive pilot testing (§4.1)."""

    def __init__(self, modal: DenyReasonModal, **kwargs) -> None:
        super().__init__(**kwargs)
        self.modal = modal

    def compose(self) -> ComposeResult:
        yield Static("Main Screen")


@pytest.mark.asyncio
async def test_inbox_screen_deny_without_reason_rejected_by_ui_gate(tmp_path: Path, monkeypatch):
    """4.1 Empty DENY reason is blocked by UI modal validation gate and DB decision remains NULL (§4.1)."""
    prof_dir = tmp_path / "profiles" / "deny_user"
    prof_dir.mkdir(parents=True, exist_ok=True)
    db_path = prof_dir / "kin.db"

    conn = get_connection(db_path)
    create_schema(conn)

    conn.execute(
        "INSERT INTO sessions (session_id, type, initiator_username, receiver_username, status, created_at, updated_at) VALUES ('sess-deny', 'direct', 'alice', 'bob', 'active', '2026-07-31T00:00:00Z', '2026-07-31T00:00:00Z')"
    )
    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="app-deny-123",
        session_id="sess-deny",
        agent_id="scout-bot",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Write file patch",
        reason="Write file patch",
        risk_label=RiskLabel.HIGH,
        requested_scope={},
        expires_at="2026-12-31T23:59:59Z",
    )
    create_pending_approval(conn, b"0" * 32, req, agent_id=req.agent_id, action_class=req.action_class, expires_at=req.expires_at)
    conn.commit()
    conn.close()

    # Spy on decide_pending_approval to assert 0 calls made on empty reason
    spy_decide = MagicMock()
    monkeypatch.setattr("kin.tui.widgets.inbox_screen.decide_pending_approval", spy_decide)

    modal = DenyReasonModal(approval_id="app-deny-123")
    app = DenyTestApp(modal)

    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        # Input whitespace reason in modal input
        inp = modal.query_one("#deny-reason-input", Input)
        inp.value = "   "

        # Attempt to confirm DENY with empty/whitespace reason
        await pilot.click("#btn-confirm")
        await pilot.pause()

        # Assert backend decide_pending_approval was NEVER called
        spy_decide.assert_not_called()

        # Assert modal remains open and error label displays rejection message
        err_label = modal.query_one("#deny-error-label", Static)
        assert "required" in str(err_label.render()).lower()

    # Assert SQLite DB decision column is still NULL
    conn_verify = get_connection(db_path)
    row = conn_verify.execute("SELECT decision FROM approvals WHERE approval_id = 'app-deny-123'").fetchone()
    conn_verify.close()
    assert row is not None
    assert row[0] is None


# -----------------------------------------------------------------------------
# 4.2 Inbox — Owner-Only Authorization Rejection (§4.2)
# -----------------------------------------------------------------------------
def test_inbox_screen_owner_only_authorization_rejection(tmp_path: Path):
    """4.2 Attempting to decide an approval as an unauthorized third party rejects and preserves DB state (§4.2)."""
    prof_dir = tmp_path / "profiles" / "charlie"
    prof_dir.mkdir(parents=True, exist_ok=True)
    db_path = prof_dir / "kin.db"

    conn = get_connection(db_path)
    create_schema(conn)

    # Insert local identity as 'charlie' (neither initiator 'alice' nor receiver 'bob')
    conn.execute("INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES ('charlie', 'pub_charlie', 'key_ref', '1.1')")
    conn.execute("INSERT INTO sessions (session_id, type, initiator_username, receiver_username, status, created_at, updated_at) VALUES ('sess-alice-bob', 'direct', 'alice', 'bob', 'active', '2026-07-31T00:00:00Z', '2026-07-31T00:00:00Z')")

    req = ApprovalRequest(
        schema_version="1.1",
        approval_id="app-alice-100",
        session_id="sess-alice-bob",
        agent_id="bot-a",
        action_class=ActionClass.SHELL_NETWORK_EXTERNAL,
        summary="External curl request",
        reason="External curl request",
        risk_label=RiskLabel.CRITICAL,
        requested_scope={},
        expires_at="2026-12-31T23:59:59Z",
    )
    create_pending_approval(conn, b"0" * 32, req, agent_id=req.agent_id, action_class=req.action_class, expires_at=req.expires_at)
    conn.commit()
    conn.close()

    # Attempt decision as unauthorized identity 'charlie'
    success, err = decide_pending_approval(
        prof_dir,
        profile_name="charlie",
        approval_id="app-alice-100",
        session_id="sess-alice-bob",
        decision="approve_once",
    )

    # ASSERTIONS:
    # (a) Success is False
    assert success is False
    assert err is not None
    # (b) Specific error message reflects authorization rejection from process_owner_command
    assert "Owner command transition rejected" in err.what_happened or "rejected" in err.what_happened.lower()

    # (c) Query approvals table directly afterward and assert decision column is STILL NULL
    conn_v = get_connection(db_path)
    row = conn_v.execute("SELECT decision FROM approvals WHERE approval_id = 'app-alice-100'").fetchone()
    conn_v.close()
    assert row is not None
    assert row[0] is None


# -----------------------------------------------------------------------------
# 4.3 Inbox — Quiet Hours Notification Rules vs List Visibility (§4.3)
# -----------------------------------------------------------------------------
def test_inbox_screen_quiet_hours_non_suppressible_security_items():
    """4.3 Quiet hours suppresses non-critical toasts while critical/near-expiry toasts fire and list renders all items (§4.3)."""
    req_crit = ApprovalRequest(
        schema_version="1.1",
        approval_id="app-crit-99",
        session_id="sess-crit",
        agent_id="sec-bot",
        action_class=ActionClass.SHELL_NETWORK_EXTERNAL,
        summary="Shell execution",
        reason="Shell execution",
        risk_label=RiskLabel.CRITICAL,
        requested_scope={},
        expires_at="2026-12-31T23:59:59Z",
    )
    crit_app = ApprovalView(request=req_crit)

    req_info = ApprovalRequest(
        schema_version="1.1",
        approval_id="app-info-10",
        session_id="sess-info",
        agent_id="info-bot",
        action_class=ActionClass.INFORMATIONAL_RELAY,
        summary="Log status update",
        reason="Log status update",
        risk_label=RiskLabel.LOW,
        requested_scope={},
        expires_at="2026-12-31T23:59:59Z",
    )
    info_app = ApprovalView(request=req_info)

    screen = InboxScreenWidget(
        approvals=[crit_app, info_app],
        quiet_hours_enabled=True,
    )
    rendered = render_widget_to_text(screen)

    # (a) List rendering MUST NEVER hide items from queue during quiet hours
    assert "sec-bot" in rendered
    assert "info-bot" in rendered

    # (b) Non-critical toast IS suppressed during quiet hours
    assert screen.should_suppress_toast(info_app) is True

    # (c) Critical security toast IS NOT suppressed during quiet hours
    assert screen.should_suppress_toast(crit_app) is False


# -----------------------------------------------------------------------------
# 4.4 Inbox — No-Interrupt Active Input Focus Guarantee via Pilot Test (§4.4)
# -----------------------------------------------------------------------------
class InboxTestApp(App):
    """Test harness App for pilot active input focus guarantee (§4.4)."""

    def __init__(self, widget: InboxScreenWidget, **kwargs) -> None:
        super().__init__(**kwargs)
        self.widget = widget

    def compose(self) -> ComposeResult:
        yield self.widget


@pytest.mark.asyncio
async def test_inbox_screen_no_interrupt_active_input():
    """4.4 Injecting items while Input widget has focus preserves focus and typed value (§4.4)."""
    widget = InboxScreenWidget(needs_you_items=[], approvals=[])
    app = InboxTestApp(widget)

    async with app.run_test() as pilot:
        # Open DenyReasonModal overlay on top of Inbox
        modal = DenyReasonModal(approval_id="app-focus-1")
        app.push_screen(modal)
        await pilot.pause()

        # Focus input and type partial content
        inp = modal.query_one("#deny-reason-input", Input)
        inp.focus()
        await pilot.press("p", "a", "r", "t", "i", "a", "l")
        assert inp.value == "partial"
        assert app.focused == inp

        # Inject new item into backing data and refresh widget
        new_item = NeedsYouItem(
            item_id="ny-2",
            session_id="sess-2",
            kind="clarification",
            human_readable_reason="Clarification needed",
            urgency="medium",
            created_at="2026-07-31T00:00:00Z",
        )
        widget._needs_you_override = [new_item]
        widget.refresh()
        await pilot.pause()

        # Assert focus and typed input content are unchanged
        assert app.focused == inp
        assert inp.value == "partial"


# -----------------------------------------------------------------------------
# 4.5 Inbox — ISO8601 Timestamp Boundary Comparison Test (§2)
# -----------------------------------------------------------------------------
def test_inbox_screen_timestamp_iso_boundary_comparison():
    """4.5 ISO8601 timestamps parse and compare correctly across 'Z' and microsecond boundaries (§2)."""
    now_dt = parse_iso_utc("2026-07-31T12:00:00.500000+00:00")
    exp_future_dt = parse_iso_utc("2026-07-31T12:00:01Z")
    exp_past_dt = parse_iso_utc("2026-07-31T12:00:00Z")

    assert exp_future_dt > now_dt  # Correct pending classification
    assert exp_past_dt <= now_dt    # Correct expired classification
