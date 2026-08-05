"""M7 Slice 3 classified Context Pantry and no-local-path proofs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.context_pantry import (
    MAX_CONTEXT_ITEM_BYTES,
    PantryValidationError,
    attach_context_pack,
    build_reviewed_context_pack,
    create_context_pack,
    register_local_reference,
)
from kin.schemas import verify_envelope_signature
from kin.storage.migrations import run_migrations
from kin.storage.vault import decrypt_field
from kin.transport.v11 import dispatch_session
from kin.tui.state import ContextPantryItem


VAULT_KEY = b"\x29" * 32
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    return conn


def test_classification_review_and_expiry_are_enforced() -> None:
    conn = _db()
    excluded = [
        ContextPantryItem(
            kind="pasted_text",
            size_bytes=12,
            classification="local_only",
            content="owner scratch",
        ),
        ContextPantryItem(
            kind="message",
            size_bytes=12,
            classification="private",
            content="private draft",
        ),
    ]
    assert build_reviewed_context_pack(conn, VAULT_KEY, excluded, now=NOW) == []

    unreviewed = ContextPantryItem(
        kind="message",
        size_bytes=8,
        classification="share_with_peer",
        content="sendable",
        item_id="ctx_unreviewed",
        reviewed=False,
    )
    with pytest.raises(PantryValidationError, match="must be reviewed"):
        build_reviewed_context_pack(conn, VAULT_KEY, [unreviewed], now=NOW)

    expired = ContextPantryItem(
        kind="message",
        size_bytes=7,
        classification="share_with_peer",
        content="expired",
        item_id="ctx_expired",
        reviewed=True,
        expiry="2026-08-05T11:59:59Z",
    )
    with pytest.raises(PantryValidationError, match="expired"):
        build_reviewed_context_pack(conn, VAULT_KEY, [expired], now=NOW)

    oversized = ContextPantryItem(
        kind="approved_artifact",
        size_bytes=MAX_CONTEXT_ITEM_BYTES + 1,
        classification="share_with_peer",
        content="x" * (MAX_CONTEXT_ITEM_BYTES + 1),
        item_id="ctx_oversized",
        reviewed=True,
    )
    with pytest.raises(PantryValidationError, match="size limit"):
        build_reviewed_context_pack(conn, VAULT_KEY, [oversized], now=NOW)
    conn.close()


def test_context_pack_is_local_until_explicit_attachment_and_requires_fresh_review() -> None:
    conn = _db()
    item = ContextPantryItem(
        kind="pasted_text",
        size_bytes=17,
        classification="share_with_peer",
        content="team constraints",
        item_id="ctx_constraints",
        reviewed=True,
    )
    stored = create_context_pack(conn, VAULT_KEY, name="Team constraints", items=[item])
    assert conn.execute("SELECT COUNT(*) FROM outbound_envelope_queue").fetchone()[0] == 0

    attached = attach_context_pack(conn, VAULT_KEY, stored.pack_id)
    assert attached[0].reviewed is False
    with pytest.raises(PantryValidationError, match="must be reviewed"):
        build_reviewed_context_pack(conn, VAULT_KEY, attached, now=NOW)
    attached[0].reviewed = True
    assert build_reviewed_context_pack(conn, VAULT_KEY, attached, now=NOW)[0]["content"] == "team constraints"
    conn.close()


def test_opaque_local_reference_resolves_only_selected_file_without_path_leak(tmp_path: Path) -> None:
    conn = _db()
    selected = tmp_path / "selected-private-name.txt"
    sibling = tmp_path / "never-list-this-secret.txt"
    selected.write_text("reviewed selected content", encoding="utf-8")
    sibling.write_text("unapproved sibling content", encoding="utf-8")
    missing_path = tmp_path / "do-not-leak-missing-name.txt"
    with pytest.raises(PantryValidationError) as registration_error:
        register_local_reference(conn, VAULT_KEY, missing_path)
    assert str(tmp_path) not in str(registration_error.value)
    assert missing_path.name not in str(registration_error.value)
    ref_id = register_local_reference(
        conn,
        VAULT_KEY,
        selected,
        expires_at="2026-08-06T12:00:00Z",
    )
    item = ContextPantryItem(
        kind="local_reference",
        size_bytes=selected.stat().st_size,
        classification="share_with_peer",
        item_id="ctx_selected",
        local_ref_id=ref_id,
        reviewed=True,
    )
    pack = build_reviewed_context_pack(conn, VAULT_KEY, [item], now=NOW)
    wire = json.dumps(pack, sort_keys=True)

    assert pack[0]["content"] == "reviewed selected content"
    assert set(pack[0]) == {
        "schema_version",
        "item_id",
        "kind",
        "classification",
        "content",
        "size_bytes",
        "expires_at",
    }
    assert str(tmp_path) not in wire
    assert selected.name not in wire
    assert sibling.name not in wire
    assert "unapproved sibling content" not in wire
    assert ref_id not in wire

    missing = ContextPantryItem(
        kind="local_reference",
        size_bytes=0,
        classification="share_with_peer",
        item_id="ctx_missing",
        local_ref_id="ctxref_does_not_exist",
        reviewed=True,
    )
    with pytest.raises(PantryValidationError) as caught:
        build_reviewed_context_pack(conn, VAULT_KEY, [missing], now=NOW)
    assert str(tmp_path) not in str(caught.value)
    assert sibling.name not in str(caught.value)
    conn.close()


def test_reviewed_pack_is_inside_real_signed_task_request_without_local_metadata(tmp_path: Path) -> None:
    conn = _db()
    selected = tmp_path / "release-input.txt"
    selected.write_text("approved release input", encoding="utf-8")
    ref_id = register_local_reference(conn, VAULT_KEY, selected)
    item = ContextPantryItem(
        kind="local_reference",
        size_bytes=selected.stat().st_size,
        classification="share_with_peer",
        item_id="ctx_release",
        local_ref_id=ref_id,
        reviewed=True,
    )
    pack = build_reviewed_context_pack(conn, VAULT_KEY, [item], now=NOW)
    signing_key = ed25519.Ed25519PrivateKey.generate()

    result = dispatch_session(
        conn,
        VAULT_KEY,
        sender_identity_key=signing_key,
        sender_x25519_privkey=b"\x31" * 32,
        sender_username="alice",
        peer_username="bob",
        sender_agent_id="ag_alice",
        receiver_agent_id="ag_bob",
        collaboration_mode="ask",
        goal="Review release input",
        context_pack=pack,
        now=NOW,
    )
    encrypted = conn.execute(
        "SELECT envelope_json_enc FROM outbound_envelope_queue WHERE session_id = ?",
        (result["session_id"],),
    ).fetchone()[0]
    envelope = json.loads(decrypt_field(VAULT_KEY, encrypted))

    assert verify_envelope_signature(envelope, signing_key.public_key()) is True
    assert envelope["payload"]["context_pack"] == pack
    serialized = json.dumps(envelope, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert selected.name not in serialized
    assert ref_id not in serialized
    conn.close()
