"""Dual-profile cross-node integration tests for human message composition (§14.8 Step 5/6, Line 227)."""

import io
import json
import pytest
from rich.console import Console
from kin.schemas import MessageKind
from kin.tui.local_state import (
    create_private_note,
    get_private_notes,
    promote_private_note_to_peer_visible,
    send_human_message_to_session_action,
)
from kin.tui.state import UiEvent
from kin.tui.widgets.compose_modal import ComposeMessageModal
from kin.tui.widgets.private_note_modal import PrivateNoteAuthoringModal
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

    from kin.identity.storage import get_or_create_vault_key
    return {
        "alice_dir": alice_dir,
        "bob_dir": bob_dir,
        "alice_ed_pub": alice_ed_pub,
        "bob_vault_key": get_or_create_vault_key("bob"),
    }


def test_compose_human_message_end_to_end_transmission(dual_profile_setup, monkeypatch):
    """Assert Alice composes a message, signs envelope, self-ingests, and delivers to Bob's node end-to-end (§14.8 Line 227)."""
    import httpx
    from kin.transport.v11 import ingest_envelope

    alice_dir = dual_profile_setup["alice_dir"]
    bob_dir = dual_profile_setup["bob_dir"]
    alice_ed_pub = dual_profile_setup["alice_ed_pub"]
    bob_vault_key = dual_profile_setup["bob_vault_key"]

    # Mock HTTP client to route direct transport post from Alice to Bob's ingest_envelope
    def mock_post(url, json=None, **kwargs):
        if "sessions" in url:
            from kin.storage.db import get_connection

            bob_conn = get_connection(bob_dir / "kin.db")
            def get_bob_pubkey(un: str):
                if un == "alice":
                    return alice_ed_pub
                return None
            ack = ingest_envelope(bob_conn, bob_vault_key, json, get_public_key_fn=get_bob_pubkey)
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

    bob_events = get_session_events(bob_dir, "sess-comp-1", profile_name="bob")
    assert len(bob_events) == 1
    assert bob_events[0].kind == MessageKind.QUESTION.value
    assert bob_events[0].content == "Need review on Section 4"


def test_compose_human_message_redaction_on_recipient_side(dual_profile_setup, monkeypatch):
    """Assert free-form human message containing sensitive patterns is redacted on recipient side (§14.8 Step 5/6)."""
    import httpx
    from kin.transport.v11 import ingest_envelope
    from kin.tui.widgets.inspector import InspectorWidget
    from kin.tui.local_state import get_session_events

    alice_dir = dual_profile_setup["alice_dir"]
    bob_dir = dual_profile_setup["bob_dir"]
    alice_ed_pub = dual_profile_setup["alice_ed_pub"]
    bob_vault_key = dual_profile_setup["bob_vault_key"]

    def mock_post(url, json=None, **kwargs):
        if "sessions" in url:
            from kin.storage.db import get_connection

            bob_conn = get_connection(bob_dir / "kin.db")
            def get_bob_pubkey(un: str):
                if un == "alice":
                    return alice_ed_pub
                return None
            ack = ingest_envelope(bob_conn, bob_vault_key, json, get_public_key_fn=get_bob_pubkey)
            bob_conn.close()
            return httpx.Response(200, json={"status": ack.status})
        return httpx.Response(404)

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    secret_msg = "Please check key: sk-live-abcdef1234567890123456789012"
    ok, res, err = send_human_message_to_session_action(
        profile_name="alice",
        session_id="sess-comp-1",
        message_text=secret_msg,
        profile_dir=alice_dir,
        http_client=client,
    )

    assert ok is True

    # Retrieve Bob's events
    bob_events = get_session_events(bob_dir, "sess-comp-1", profile_name="bob")
    assert len(bob_events) == 1
    assert "sk-live-abcdef1234567890123456789012" not in bob_events[0].content
    assert "REDACTED" in bob_events[0].content

    # Inspect rendered output in InspectorWidget
    insp = InspectorWidget(selected_event=bob_events[0])
    rendered = insp.render()
    assert "sk-live-abcdef1234567890123456789012" not in rendered
    assert "REDACTED" in rendered


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


@pytest.mark.asyncio
async def test_private_note_exclusion_from_peer_views_and_plain_export(
    dual_profile_setup,
    build_tui_app,
    monkeypatch,
):
    """Ctrl+S creates one owner-only note visible solely in the Notes lane."""
    from kin.storage.db import get_connection
    from kin.tui.local_state import get_session_events
    from kin.tui.shell import ConfirmationModal
    from textual.widgets import Input

    alice_dir = dual_profile_setup["alice_dir"]
    note_text = 'Keep the API [draft] and fallback concern private for now.'
    promoted_calls: list[str] = []

    def fake_promote(_profile_dir, _profile_name, _session_id, note_event_id):
        promoted_calls.append(note_event_id)
        return True, None

    monkeypatch.setattr(
        "kin.tui.widgets.session_arena.promote_private_note_to_peer_visible",
        fake_promote,
    )

    app = build_tui_app(profile_name="alice", profile_dir=alice_dir)
    async with app.run_test(size=(120, 36)) as pilot:
        app.tab_manager.open_tab(
            "tab:sess-comp-1",
            "Private note session",
            "session",
        )
        app.sync_tab_bar()
        await app.canvas.recompose()
        await pilot.pause()
        arena = app.canvas.get_session_arena_widget()
        assert arena is not None
        arena.focus()

        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, PrivateNoteAuthoringModal)
        app.screen.query_one("#private-note-input", Input).value = note_text
        await pilot.press("enter")
        await pilot.pause()

        assert len(app.screen_stack) == 1
        assert arena.active_lane == "notes"
        assert [note.note_text for note in arena.private_notes] == [note_text]
        assert get_session_events(alice_dir, "sess-comp-1", "alice") == []
        assert arena.events == []
        assert arena.exchange_timeline_widget.events == []
        assert arena.activity_feed_widget.raw_events == []

        for lane in ("transcript", "activity", "outputs", "decisions", "needs_you"):
            arena.switch_lane(lane)
            output = io.StringIO()
            Console(file=output, width=120, color_system=None).print(arena.render())
            assert note_text not in output.getvalue(), lane

        arena.switch_lane("notes")
        output = io.StringIO()
        Console(file=output, width=120, color_system=None).print(arena.render())
        assert note_text in output.getvalue()

        # Even with Notes active, export uses the peer-visible audit exporter.
        await pilot.press("ctrl+e")
        export_path = alice_dir / "exports" / "latest-view.txt"
        assert export_path.exists()
        assert note_text not in export_path.read_text(encoding="utf-8")

        # Promotion is Arena-specific and shows the exact boundary-crossing text.
        app.set_focus(arena)
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmationModal)
        confirmation_body = app.screen.query_one("#modal-body")
        assert confirmation_body.size.height >= 2
        visible_confirmation = "\n".join(
            confirmation_body.render_line(line).text
            for line in range(confirmation_body.size.height)
        )
        assert note_text in " ".join(visible_confirmation.split())
        await pilot.press("n")
        await pilot.pause()
        assert promoted_calls == []

        arena.action_promote_private_note()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmationModal)
        await pilot.press("y")
        await pilot.pause()
        assert promoted_calls == [arena.private_notes[0].event_id]

    notes = get_private_notes(alice_dir, "sess-comp-1", "alice")
    assert len(notes) == 1
    conn = get_connection(alice_dir / "kin.db")
    row = conn.execute(
        "SELECT kind, visibility, signature FROM session_events WHERE event_id = ?",
        (notes[0].event_id,),
    ).fetchone()
    conn.close()
    assert row == ("private_note", "local_only", None)


@pytest.mark.asyncio
async def test_deliberate_private_note_promotion_uses_real_ed25519_signature(
    dual_profile_setup,
    build_tui_app,
    monkeypatch,
):
    """Promotion reuses the real signed envelope and Bob decrypts its content."""
    import httpx
    from kin.audit.export import export_session
    from kin.identity.storage import get_or_create_vault_key
    from kin.schemas import verify_envelope_signature
    from kin.storage.db import get_connection
    from kin.transport.v11 import ingest_envelope
    from kin.tui.local_state import get_session_events

    alice_dir = dual_profile_setup["alice_dir"]
    bob_dir = dual_profile_setup["bob_dir"]
    alice_ed_pub = dual_profile_setup["alice_ed_pub"]
    bob_vault_key = dual_profile_setup["bob_vault_key"]
    note_text = "Promote this exact architecture concern to Bob."

    created, create_error = create_private_note(
        alice_dir,
        "alice",
        "sess-comp-1",
        "alice",
        note_text,
    )
    assert created is True
    assert create_error is None
    note = get_private_notes(alice_dir, "sess-comp-1", "alice")[0]

    captured_envelopes: list[dict] = []

    def mock_post(url, json=None, **kwargs):
        if "sessions" not in url:
            return httpx.Response(404)
        captured_envelopes.append(dict(json))
        bob_conn = get_connection(bob_dir / "kin.db")

        def get_bob_pubkey(username: str):
            return alice_ed_pub if username == "alice" else None

        ack = ingest_envelope(
            bob_conn,
            bob_vault_key,
            json,
            get_public_key_fn=get_bob_pubkey,
        )
        bob_conn.close()
        return httpx.Response(200, json={"status": ack.status})

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    promoted, promotion_error = promote_private_note_to_peer_visible(
        alice_dir,
        "alice",
        "sess-comp-1",
        note.event_id,
        http_client=client,
    )
    assert promoted is True
    assert promotion_error is None
    assert len(captured_envelopes) == 1
    envelope = captured_envelopes[0]
    assert envelope["kind"] == MessageKind.QUESTION.value
    assert envelope["payload"]["message"] == note_text
    assert envelope["signature"]
    assert verify_envelope_signature(envelope, alice_ed_pub) is True

    bob_events = get_session_events(bob_dir, "sess-comp-1", "bob")
    assert len(bob_events) == 1
    assert bob_events[0].kind == MessageKind.QUESTION.value
    assert bob_events[0].content == note_text

    bob_conn = get_connection(bob_dir / "kin.db")
    bob_signature = bob_conn.execute(
        "SELECT signature FROM session_events WHERE event_id = ?",
        (bob_events[0].event_id,),
    ).fetchone()[0]
    bob_conn.close()
    assert bob_signature == envelope["signature"]

    alice_conn = get_connection(alice_dir / "kin.db")
    exported = export_session(
        alice_conn,
        get_or_create_vault_key("alice"),
        "sess-comp-1",
        format="json",
    )
    alice_conn.close()
    exported_data = json.loads(exported)
    assert [event["kind"] for event in exported_data["events"]] == [
        MessageKind.QUESTION.value
    ]
    assert exported_data["events"][0]["payload"]["message"] == note_text
    assert exported_data["events"][0]["signature"] == envelope["signature"]

    # The same public event must be present in the actual Ctrl+E plain-text
    # session export, while the original private_note row remains excluded.
    app = build_tui_app(profile_name="alice", profile_dir=alice_dir)
    async with app.run_test(size=(120, 36)) as pilot:
        app.tab_manager.open_tab(
            "tab:sess-comp-1",
            "Promoted note session",
            "session",
        )
        app.sync_tab_bar()
        await app.canvas.recompose()
        await pilot.pause()
        await pilot.press("ctrl+e")
        plain_export = (alice_dir / "exports" / "latest-view.txt").read_text(
            encoding="utf-8"
        )
        assert note_text in plain_export
        assert "private_note" not in plain_export
