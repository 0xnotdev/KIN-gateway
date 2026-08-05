"""M6 non-TTY parity contracts for V1.1 dispatch, approval, export, and recovery."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter

from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
import httpx
import pytest
from typer.testing import CliRunner

from kin.cli import app
from kin.identity.keys import derive_key_pair, derive_x25519_key_pair, generate_recovery_phrase
from kin.identity.fingerprint import compute_fingerprint
from kin.identity.storage import (
    get_or_create_vault_key,
    save_private_key,
    save_x25519_private_key,
)
from kin.policy.persistence import create_pending_approval
from kin.schemas import ActionClass, ApprovalRequest, RiskLabel
from kin.storage.db import create_schema, get_connection


def _profile_with_real_identity_and_contact(
    profile_dir: Path,
    profile_name: str = "cli-alice",
) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    alice_ed = ed25519.Ed25519PrivateKey.from_private_bytes(b"a" * 32)
    alice_x = x25519.X25519PrivateKey.from_private_bytes(b"x" * 32)
    bob_ed = ed25519.Ed25519PrivateKey.from_private_bytes(b"b" * 32)
    bob_x = x25519.X25519PrivateKey.from_private_bytes(b"y" * 32)
    save_private_key(profile_name, alice_ed.private_bytes_raw())
    save_x25519_private_key(profile_name, alice_x.private_bytes_raw())
    get_or_create_vault_key(profile_name)

    conn = get_connection(profile_dir / "kin.db")
    create_schema(conn)
    conn.execute(
        "INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, ?, ?)",
        ("alice", alice_ed.public_key().public_bytes_raw().hex(), "keychain-ref", "1.1"),
    )
    conn.execute(
        """INSERT INTO contacts
           (username, display_name, public_key, x25519_public_key, endpoint,
            autonomy_level, fingerprint_verified_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "bob",
            "Bob",
            bob_ed.public_key().public_bytes_raw().hex(),
            bob_x.public_key().public_bytes_raw().hex(),
            "",
            "always_ask",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def _runner_for_profile(monkeypatch: pytest.MonkeyPatch, profile_dir: Path) -> CliRunner:
    monkeypatch.setattr("kin.cli.get_profile_dir", lambda _profile: profile_dir)
    return CliRunner()


def test_non_tty_dispatch_uses_real_signed_v11_persistence_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_name = "cli-alice"
    profile_dir = tmp_path / profile_name
    _profile_with_real_identity_and_contact(profile_dir, profile_name)
    runner = _runner_for_profile(monkeypatch, profile_dir)

    result = runner.invoke(
        app,
        [
            "--profile",
            profile_name,
            "dispatch",
            "--peer",
            "bob",
            "--sender-agent",
            "alice-agent",
            "--receiver-agent",
            "bob-agent",
            "--type",
            "ask",
            "--goal",
            "Review the release evidence",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    session_id = payload["result"]["session_id"]
    conn = get_connection(profile_dir / "kin.db")
    event = conn.execute(
        "SELECT kind, visibility, signature FROM session_events WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    queued = conn.execute(
        "SELECT delivery_state FROM outbound_envelope_queue WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    assert event[0:2] == ("task_request", "peer_visible")
    assert event[2]
    assert queued == ("pending",)


def test_non_tty_approval_decision_uses_real_owner_persistence_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_name = "cli-alice"
    profile_dir = tmp_path / profile_name
    _profile_with_real_identity_and_contact(profile_dir, profile_name)
    runner = _runner_for_profile(monkeypatch, profile_dir)
    conn = get_connection(profile_dir / "kin.db")
    session_id = "sess-cli-approval"
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO sessions
           (session_id, type, initiator_username, receiver_username, status,
            turn_limit, created_at, updated_at)
           VALUES (?, 'ask', 'alice', 'bob', 'awaiting_owner_approval', 12, ?, ?)""",
        (session_id, now, now),
    )
    request = ApprovalRequest(
        schema_version="1.1",
        approval_id="approval-cli-1",
        session_id=session_id,
        agent_id="alice-agent",
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Apply reviewed patch",
        reason="Owner approval is required",
        risk_label=RiskLabel.HIGH,
        requested_scope={"path": "reviewed.patch"},
        expires_at="2099-01-01T00:00:00Z",
    )
    create_pending_approval(
        conn,
        get_or_create_vault_key(profile_name),
        request,
        agent_id="alice-agent",
        action_class=ActionClass.WORKSPACE_WRITE,
        expires_at=request.expires_at,
    )
    conn.close()

    result = runner.invoke(
        app,
        [
            "--profile",
            profile_name,
            "approval",
            "decide",
            "approval-cli-1",
            "--session",
            session_id,
            "--decision",
            "approve_once",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["ok"] is True
    conn = get_connection(profile_dir / "kin.db")
    row = conn.execute(
        "SELECT decision FROM approvals WHERE approval_id = 'approval-cli-1'"
    ).fetchone()
    status = conn.execute(
        "SELECT status FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    assert row == ("approve_once",)
    assert status == ("active",)


def test_non_tty_export_and_recovery_use_real_durable_session_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_name = "cli-alice"
    profile_dir = tmp_path / profile_name
    _profile_with_real_identity_and_contact(profile_dir, profile_name)
    runner = _runner_for_profile(monkeypatch, profile_dir)
    dispatch = runner.invoke(
        app,
        [
            "--profile", profile_name, "dispatch",
            "--peer", "bob", "--sender-agent", "alice-agent",
            "--receiver-agent", "bob-agent", "--goal", "Durable CLI session", "--json",
        ],
    )
    session_id = json.loads(dispatch.stdout)["result"]["session_id"]
    export_path = tmp_path / "exports" / "session.md"

    exported = runner.invoke(
        app,
        [
            "--profile", profile_name, "session", "export", session_id,
            "--format", "markdown", "--output", str(export_path), "--json",
        ],
    )
    recovered = runner.invoke(
        app,
        ["--profile", profile_name, "session", "recover", session_id, "--json"],
    )

    assert exported.exit_code == 0, exported.stdout
    assert json.loads(exported.stdout)["written"] is True
    assert "Durable CLI session" in export_path.read_text(encoding="utf-8")
    assert recovered.exit_code == 0, recovered.stdout
    recovery = json.loads(recovered.stdout)
    assert recovery["recovered_from_persistence"] is True
    assert recovery["events"][0]["kind"] == "task_request"
    assert recovery["current_turn"] == 1


def test_non_tty_init_and_restore_accept_protected_phrase_file_without_echo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phrase = generate_recovery_phrase()
    phrase_file = tmp_path / "recovery.txt"
    phrase_file.write_text(phrase, encoding="utf-8")
    public_key = derive_key_pair(phrase)[1]
    x_public = derive_x25519_key_pair(phrase)[1]
    profile_dirs = {
        "cli-init": tmp_path / "cli-init",
        "cli-restore": tmp_path / "cli-restore",
    }
    monkeypatch.setattr("kin.cli.get_profile_dir", lambda profile: profile_dirs[profile])
    directory_state = {"registered": False}

    def directory_get(url: str, **kwargs):
        del kwargs
        if url.endswith("/alice") and directory_state["registered"]:
            return httpx.Response(
                200,
                json={
                    "public_key": public_key.hex(),
                    "x25519_public_key": x_public.hex(),
                    "endpoint": "https://alice.example",
                },
                request=httpx.Request("GET", url),
            )
        return httpx.Response(404, request=httpx.Request("GET", url))

    def directory_post(*args, **kwargs):
        del args, kwargs
        directory_state["registered"] = True
        return httpx.Response(
            200,
            json={"ok": True},
            request=httpx.Request("POST", "http://localhost:8000/directory/register"),
        )

    monkeypatch.setattr("kin.cli.httpx.get", directory_get)
    monkeypatch.setattr("kin.cli.httpx.post", directory_post)
    runner = CliRunner()

    initialized = runner.invoke(
        app,
        [
            "--profile", "cli-init", "init", "--username", "alice",
            "--recovery-phrase-file", str(phrase_file), "--json",
        ],
    )
    restored = runner.invoke(
        app,
        [
            "--profile", "cli-restore", "restore", "--username", "alice",
            "--recovery-phrase-file", str(phrase_file), "--json",
        ],
    )

    assert initialized.exit_code == 0, initialized.stdout
    assert restored.exit_code == 0, restored.stdout
    assert json.loads(initialized.stdout)["recovery_phrase_exposed"] is False
    assert json.loads(restored.stdout)["identity_restored"] is True
    assert phrase not in initialized.stdout
    assert phrase not in restored.stdout


def test_cli_session_list_100_sessions_20_agents_under_two_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_dir = tmp_path / "scale-profile"
    profile_dir.mkdir(parents=True)
    conn = get_connection(profile_dir / "kin.db")
    create_schema(conn)
    now = datetime.now(timezone.utc).isoformat()
    for index in range(100):
        conn.execute(
            """INSERT INTO sessions
               (session_id, type, initiator_username, receiver_username, status,
                objective, turn_limit, created_at, updated_at)
               VALUES (?, 'ask', 'alice', 'bob', 'active', ?, 12, ?, ?)""",
            (f"sess-scale-{index:03d}", f"Objective {index}", now, now),
        )
    for index in range(20):
        conn.execute(
            """INSERT INTO agents
               (agent_id, name, adapter_type, enabled, availability, created_at,
                updated_at, card_version, published_card_json)
               VALUES (?, ?, 'embedded', 1, 'ready', ?, ?, 1, '{}')""",
            (f"agent-{index:02d}", f"Agent {index}", now, now),
        )
    conn.commit()
    conn.close()
    runner = _runner_for_profile(monkeypatch, profile_dir)

    started = perf_counter()
    result = runner.invoke(app, ["--profile", "scale-profile", "session", "list", "--json"])
    elapsed = perf_counter() - started

    assert result.exit_code == 0, result.stdout
    assert len(json.loads(result.stdout)["sessions"]) == 100
    assert elapsed < 2.0, f"CLI session list took {elapsed:.3f}s"


@pytest.mark.parametrize(
    "command",
    [
        ["init"],
        ["pair"],
        ["restore"],
        ["serve"],
        ["doctor"],
        ["contacts"],
        ["contact-policy"],
        ["configure"],
        ["migrate"],
        ["inbox"],
        ["dispatch"],
        ["session", "list"],
        ["session", "open"],
        ["session", "export"],
        ["session", "recover"],
        ["approval", "list"],
        ["approval", "decide"],
        ["agent", "list"],
        ["agent", "inspect"],
        ["agent", "validate"],
        ["agent", "enable"],
        ["agent", "disable"],
        ["agent", "import"],
        ["agent", "publish"],
    ],
)
def test_m6_named_scriptable_commands_expose_json_and_plain_contracts(
    command: list[str],
) -> None:
    result = CliRunner().invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.stdout
    assert "--json" in result.stdout
    assert "--plain" in result.stdout


def test_non_tty_pair_requires_and_records_exact_out_of_band_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_name = "cli-alice"
    profile_dir = tmp_path / profile_name
    _profile_with_real_identity_and_contact(profile_dir, profile_name)
    conn = get_connection(profile_dir / "kin.db")
    conn.execute("DELETE FROM contacts WHERE username = 'bob'")
    alice_public = bytes.fromhex(conn.execute("SELECT public_key FROM identity").fetchone()[0])
    conn.commit()
    conn.close()
    bob_private = ed25519.Ed25519PrivateKey.from_private_bytes(b"b" * 32)
    bob_public = bob_private.public_key().public_bytes_raw()
    bob_x_public = x25519.X25519PrivateKey.from_private_bytes(b"y" * 32).public_key().public_bytes_raw()
    fingerprint = compute_fingerprint(alice_public, bob_public)
    monkeypatch.setattr("kin.cli.get_profile_dir", lambda _profile: profile_dir)
    monkeypatch.setattr(
        "kin.cli.httpx.get",
        lambda _url: httpx.Response(
            200,
            json={
                "public_key": bob_public.hex(),
                "x25519_public_key": bob_x_public.hex(),
                "endpoint": "https://bob.example",
            },
            request=httpx.Request("GET", _url),
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "--profile", profile_name, "pair", "bob",
            "--verified-fingerprint", fingerprint, "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["fingerprint_verified"] is True
    conn = get_connection(profile_dir / "kin.db")
    verified = conn.execute(
        "SELECT fingerprint_verified_at FROM contacts WHERE username = 'bob'"
    ).fetchone()[0]
    conn.close()
    assert verified


def test_non_tty_configure_reads_credential_file_and_never_echoes_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_dir = tmp_path / "configure-profile"
    secret = "sk-proj-configure-secret-never-print"
    secret_file = tmp_path / "provider.key"
    secret_file.write_text(secret, encoding="utf-8")
    monkeypatch.setattr("kin.cli.get_profile_dir", lambda _profile: profile_dir)

    result = CliRunner().invoke(
        app,
        [
            "--profile", "configure-profile", "configure",
            "--provider", "openrouter", "--api-key-file", str(secret_file), "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["credential_present"] is True
    assert secret not in result.stdout


def test_serve_json_emits_machine_readable_startup_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_dir = tmp_path / "serve-profile"
    monkeypatch.setattr("kin.cli.get_profile_dir", lambda _profile: profile_dir)
    captured: dict[str, object] = {}

    def fake_run(app_arg, *, host, port):
        captured.update({"app": app_arg, "host": host, "port": port})

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "--profile", "serve-profile", "serve", "--port", "9077",
            "--no-fetch", "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "starting"
    assert payload["profile"] == "serve-profile"
    assert payload["port"] == 9077
    assert captured["port"] == 9077
