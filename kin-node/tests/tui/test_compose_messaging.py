"""Dual-profile cross-node integration tests for human message composition (§14.8 Step 5/6, Line 227)."""

import json
import pytest
from kin.schemas import MessageKind
from kin.tui.local_state import send_human_message_to_session_action
from kin.tui.state import UiEvent
from kin.tui.widgets.compose_modal import ComposeMessageModal
from kin.tui.widgets.session_arena import SessionArenaWidget


@pytest.fixture
def dual_profile_setup(tmp_path):
    """Set up Alice and Bob isolated local profiles with real Ed25519/X25519 keys and a shared session."""
    from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
    from cryptography.hazmat.primitives import serialization
    from kin.identity.storage import save_private_key, save_x25519_private_key
    from kin.tui.local_state import ensure_profile_db
    from kin.storage.db import get_connection

    alice_dir = tmp_path / "alice"
    bob_dir = tmp_path / "bob"
    alice_dir.mkdir()
    bob_dir.mkdir()

    # 1. Alice keys & DB
    alice_ed_priv = ed25519.Ed25519PrivateKey.generate()
    alice_ed_pub = alice_ed_priv.public_key()
    alice_x_priv = x25519.X25519PrivateKey.generate()
    alice_x_pub = alice_x_priv.public_key()

    alice_ed_raw = alice_ed_priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    alice_ed_pub_raw = alice_ed_pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    alice_x_raw = alice_x_priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    alice_x_pub_raw = alice_x_pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    save_private_key("alice", alice_ed_raw)
    save_x25519_private_key("alice", alice_x_raw)

    alice_conn = ensure_profile_db(alice_dir / "kin.db")
    alice_cur = alice_conn.cursor()
    alice_cur.execute("INSERT OR REPLACE INTO identity (username, public_key) VALUES ('alice', ?)", (alice_ed_pub_raw.hex(),))
    alice_cur.execute(
        "INSERT INTO sessions (session_id, initiator_username, receiver_username, status, type, created_at, updated_at) VALUES ('sess-comp-1', 'alice', 'bob', 'active', 'research', '2026-08-01T12:00:00Z', '2026-08-01T12:00:00Z')"
    )
    alice_conn.commit()

    # 2. Bob keys & DB
    bob_ed_priv = ed25519.Ed25519PrivateKey.generate()
    bob_ed_pub = bob_ed_priv.public_key()
    bob_x_priv = x25519.X25519PrivateKey.generate()
    bob_x_pub = bob_x_priv.public_key()

    bob_ed_raw = bob_ed_priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    bob_ed_pub_raw = bob_ed_pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    bob_x_raw = bob_x_priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    bob_x_pub_raw = bob_x_pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    save_private_key("bob", bob_ed_raw)
    save_x25519_private_key("bob", bob_x_raw)

    bob_conn = ensure_profile_db(bob_dir / "kin.db")
    bob_cur = bob_conn.cursor()
    bob_cur.execute("INSERT OR REPLACE INTO identity (username, public_key) VALUES ('bob', ?)", (bob_ed_pub_raw.hex(),))
    bob_cur.execute(
        "INSERT INTO sessions (session_id, initiator_username, receiver_username, status, type, created_at, updated_at) VALUES ('sess-comp-1', 'alice', 'bob', 'active', 'research', '2026-08-01T12:00:00Z', '2026-08-01T12:00:00Z')"
    )
    bob_conn.commit()

    # Add contacts
    alice_cur.execute("INSERT OR REPLACE INTO contacts (username, endpoint, public_key, x25519_public_key, fingerprint_verified_at) VALUES ('bob', 'http://127.0.0.1:9999', ?, ?, '2026-08-01T12:00:00Z')", (bob_ed_pub_raw.hex(), bob_x_pub_raw.hex()))
    bob_cur.execute("INSERT OR REPLACE INTO contacts (username, endpoint, public_key, x25519_public_key, fingerprint_verified_at) VALUES ('alice', 'http://127.0.0.1:9998', ?, ?, '2026-08-01T12:00:00Z')", (alice_ed_pub_raw.hex(), alice_x_pub_raw.hex()))
    alice_conn.commit()
    bob_conn.commit()

    alice_conn.close()
    bob_conn.close()

    return {
        "alice_dir": alice_dir,
        "bob_dir": bob_dir,
        "alice_ed_pub": alice_ed_pub,
    }


def test_compose_human_message_end_to_end_transmission(dual_profile_setup, monkeypatch):
    """Assert Alice composes a message, signs envelope, self-ingests, and delivers to Bob's node end-to-end (§14.8 Line 227)."""
    import httpx
    from kin.transport.v11 import ingest_envelope

    alice_dir = dual_profile_setup["alice_dir"]
    bob_dir = dual_profile_setup["bob_dir"]
    alice_ed_pub = dual_profile_setup["alice_ed_pub"]

    # Mock HTTP client to route direct transport post from Alice to Bob's ingest_envelope
    def mock_post(url, json=None, **kwargs):
        if "sessions" in url:
            from kin.storage.db import get_connection

            bob_conn = get_connection(bob_dir / "kin.db")
            def get_bob_pubkey(un: str):
                if un == "alice":
                    return alice_ed_pub
                return None
            ack = ingest_envelope(bob_conn, b"01234567890123456789012345678901", json, get_public_key_fn=get_bob_pubkey)
            bob_conn.close()
            mock_resp = httpx.Response(200, json={"status": ack.status})
            return mock_resp
        return httpx.Response(404)

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    ok, res, err = send_human_message_to_session_action(
        profile_name="alice",
        session_id="sess-comp-1",
        message_text="Need review on Section 4",
        profile_dir=alice_dir,
        http_client=client,
    )

    assert err is None, f"send_human_message_to_session_action failed: {err}"
    assert ok is True
    assert res["status"] == "delivered"

    # Assert Bob's local SQLite database received, decrypted, and stored the message end-to-end
    from kin.tui.local_state import get_session_events

    bob_events = get_session_events(bob_dir, "sess-comp-1")
    assert len(bob_events) == 1
    assert bob_events[0].kind == MessageKind.QUESTION.value


def test_compose_human_message_unreachable_peer_failure_path(dual_profile_setup, monkeypatch):
    """Assert failure path returns clear RecoverableError when peer endpoint is unreachable and relay fails (§14.8 Line 227)."""
    import httpx

    alice_dir = dual_profile_setup["alice_dir"]

    client = httpx.Client()
    def failing_post(*args, **kwargs):
        raise httpx.RequestError("Connection refused")
    monkeypatch.setattr(client, "post", failing_post)

    ok, res, err = send_human_message_to_session_action(
        profile_name="alice",
        session_id="sess-comp-1",
        message_text="Hello Bob",
        profile_dir=alice_dir,
        http_client=client,
    )

    assert ok is False
    assert err is not None
    assert "Failed to deliver message to peer" in err.what_happened


@pytest.mark.asyncio
async def test_compose_modal_keyboard_trigger_and_review_flow(dual_profile_setup, monkeypatch):
    """Assert pressing 'm' in SessionArenaWidget opens ComposeMessageModal with review-before-send flow (§14.8 Line 232)."""
    from textual.app import App
    from kin.tui.state import SessionSummary

    alice_dir = dual_profile_setup["alice_dir"]
    dummy_summary = SessionSummary(
        session_id="sess-comp-1",
        status="active",
        type="research",
        initiator_username="alice",
        receiver_username="bob",
        objective="Test compose modal",
        turn_limit=12,
        created_at="2026-08-01T12:00:00Z",
        updated_at="2026-08-01T12:00:00Z",
    )

    class TestApp(App):
        def compose(self):
            yield SessionArenaWidget(session_id="sess-comp-1", session_summary=dummy_summary, profile_name="alice", profile_dir=alice_dir)

    app = TestApp()
    async with app.run_test() as pilot:
        arena = pilot.app.query_one(SessionArenaWidget)

        # Press 'm' to launch modal
        await pilot.press("m")
        await pilot.pause()

        modal = pilot.app.screen
        assert isinstance(modal, ComposeMessageModal)

        # Type message
        from textual.widgets import Input
        inp = pilot.app.screen.query_one("#compose-input", Input)
        inp.value = "Draft message"
        await pilot.pause()

        # Step 1: Click Review & Send
        await pilot.click("#btn-review")
        await pilot.pause()

        assert modal.review_step is True

        # Cancel modal
        await pilot.click("#btn-cancel")
        await pilot.pause()
