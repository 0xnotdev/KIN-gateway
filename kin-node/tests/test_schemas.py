"""Unit and contract tests for V1.1 Pydantic models, RFC 8785 JCS canonicalization, and Ed25519 signing."""

import json
import math
from pathlib import Path

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric import ed25519
from pydantic import ValidationError

from kin.schemas import (
    ActionClass,
    AgentAvailability,
    AgentCard,
    ApprovalDecision,
    ApprovalRequest,
    ArtifactOffer,
    CapabilityAdvertisement,
    DecisionKind,
    MessageKind,
    PublishedAgentCard,
    RiskLabel,
    SessionEnvelope,
    SessionEvent,
    TransportAcknowledgement,
    canonical_jcs,
    compute_content_hash,
    sign_envelope,
    verify_and_build_envelope,
    verify_envelope_signature,
)


def test_v11_golden_fixture_corpus():
    """Verify that canonical JCS bytes, content hash, and Ed25519 signature match the golden fixture corpus."""
    fixture_path = Path(__file__).parent / "fixtures" / "v11_canonical_envelopes.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    envelope_dict = data["envelope"]
    pub_key_bytes = bytes.fromhex(data["public_key_hex"])
    pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_key_bytes)

    # Validate structural schema
    envelope = SessionEnvelope.model_validate(envelope_dict)
    assert envelope.session_id == "sess-test-12345"
    assert envelope.sequence == 1
    assert envelope.kind == MessageKind.TASK_REQUEST

    # Check payload hash computation
    computed_hash = compute_content_hash(envelope.payload)
    assert computed_hash == data["content_hash"]

    # Check signature verification against golden public key
    assert verify_envelope_signature(envelope_dict, pub_key) is True


def test_rfc8785_non_bmp_key_sorting():
    """Verify RFC 8785 JCS UTF-16 code-unit key sorting for non-BMP characters (e.g. emojis)."""
    # 😀 (\U0001F600) UTF-16 surrogates: 0xD83D 0xDE00. \uFFFF: 0xFFFF.
    # UTF-16 code-unit order: 0xD83D < 0xFFFF, so 😀 comes BEFORE \uFFFF.
    data = {
        "\uFFFF": 2,
        "\U0001F600": 1,
    }
    jcs_bytes = canonical_jcs(data)
    assert jcs_bytes == b'{"\xf0\x9f\x98\x80":1,"\xef\xbf\xbf":2}'


def test_rfc8785_ecmascript_number_formatting():
    """Verify ECMAScript number formatting compliance per RFC 8785 section 3.2.3."""
    data = {
        "int_as_float": 1.0,
        "exp_large": 1e21,
        "exp_small": 1e-7,
    }
    jcs_bytes = canonical_jcs(data)
    assert b'"int_as_float":1' in jcs_bytes
    assert b'"exp_large":1e+21' in jcs_bytes
    assert b'"exp_small":1e-7' in jcs_bytes


def test_schema_rejection_missing_required_version():
    """Verify missing required schema_version or protocol_version fails validation."""
    raw = {
        "session_id": "sess-1",
        "sequence": 1,
        "actor_username": "alice",
        "actor_agent_id": "scout",
        "timestamp": "2026-07-22T12:00:00.000Z",
        "kind": "task_request",
        "content_hash": "GAaPZonhugqbksiBER6fUh-BO14JN_qQatR-2s9kXP0",
        "payload": {},
    }
    with pytest.raises(ValidationError):
        SessionEnvelope.model_validate(raw)


def test_schema_rejection_string_sequence_strict_type():
    """Verify string sequence '1' is rejected by strict validation."""
    raw = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "sess-1",
        "sequence": "1",
        "actor_username": "alice",
        "actor_agent_id": "scout",
        "timestamp": "2026-07-22T12:00:00.000Z",
        "kind": "task_request",
        "content_hash": "GAaPZonhugqbksiBER6fUh-BO14JN_qQatR-2s9kXP0",
        "payload": {},
    }
    with pytest.raises(ValidationError):
        SessionEnvelope.model_validate(raw)


def test_schema_rejection_non_json_payload():
    """Verify non-JSON payload items (NaN, sets, functions) are rejected."""
    raw = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "sess-1",
        "sequence": 1,
        "actor_username": "alice",
        "actor_agent_id": "scout",
        "timestamp": "2026-07-22T12:00:00.000Z",
        "kind": "task_request",
        "content_hash": "GAaPZonhugqbksiBER6fUh-BO14JN_qQatR-2s9kXP0",
        "payload": {"invalid_float": math.nan},
    }
    with pytest.raises(ValidationError):
        SessionEnvelope.model_validate(raw)


def test_schema_rejection_malformed_content_hash():
    """Verify content_hash with invalid length or non-base64url characters is rejected."""
    raw = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "sess-1",
        "sequence": 1,
        "actor_username": "alice",
        "actor_agent_id": "scout",
        "timestamp": "2026-07-22T12:00:00.000Z",
        "kind": "task_request",
        "content_hash": "short_invalid_hash",
        "payload": {},
    }
    with pytest.raises(ValidationError):
        SessionEnvelope.model_validate(raw)


def test_verify_and_build_envelope_pipeline(alice_keys, frozen_clock):
    """Test full 6-stage verification pipeline for building a VerifiedEnvelope using conftest fixtures."""
    priv_key = alice_keys["private_key"]
    pub_key = alice_keys["public_key"]

    payload = {"goal": "Test goal"}
    hash_str = compute_content_hash(payload)

    envelope_dict = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "session_id": "sess-pipeline",
        "sequence": 1,
        "actor_username": "alice",
        "actor_agent_id": "code-scout",
        "timestamp": frozen_clock,
        "kind": "task_request",
        "content_hash": hash_str,
        "payload": payload,
    }
    sig = sign_envelope(envelope_dict, priv_key)
    envelope_dict["signature"] = sig

    participant_map = {"alice": "code-scout"}
    get_pub_key = lambda user: pub_key if user == "alice" else None

    # 1. Valid Pipeline Execution
    res = verify_and_build_envelope(envelope_dict, get_pub_key, "sess-pipeline", participant_map)
    assert res.success is True
    assert res.verified_envelope is not None

    # 2. Session ID mismatch
    res_bad_session = verify_and_build_envelope(envelope_dict, get_pub_key, "sess-wrong", participant_map)
    assert res_bad_session.success is False

    # 3. Content hash mismatch
    bad_hash_dict = dict(envelope_dict)
    bad_hash_dict["content_hash"] = compute_content_hash({"goal": "Tampered goal"})
    res_bad_hash = verify_and_build_envelope(bad_hash_dict, get_pub_key, "sess-pipeline", participant_map)
    assert res_bad_hash.success is False

    # 4. Agent ID substitution
    bad_agent_dict = dict(envelope_dict)
    bad_agent_dict["actor_agent_id"] = "wrong-agent"
    bad_agent_dict["signature"] = sign_envelope(bad_agent_dict, priv_key)
    res_bad_agent = verify_and_build_envelope(bad_agent_dict, get_pub_key, "sess-pipeline", participant_map)
    assert res_bad_agent.success is False
    assert res_bad_agent.error_code == "UNAUTHORIZED_AGENT"

    # 5. Forged signature
    bad_sig_dict = dict(envelope_dict)
    bad_sig_dict["signature"] = "invalid_signature_string_here_12345678901234567890123"
    res_bad_sig = verify_and_build_envelope(bad_sig_dict, get_pub_key, "sess-pipeline", participant_map)
    assert res_bad_sig.success is False


def test_conftest_agent_card_fixtures(sample_agent_card, sample_published_card):
    """Verify validation of AgentCard and PublishedAgentCard fixtures from conftest.py."""
    assert sample_agent_card.id == "code-scout"
    assert sample_agent_card.schema_version == "1.1"

    assert sample_published_card.agent_id == "data-cleaner"
    assert sample_published_card.availability == AgentAvailability.READY
    assert sample_published_card.protocol_version == "1.1"


def test_session_event_valid_construction():
    """Verify valid construction of a SessionEvent schema model with schema_version and protocol_version."""
    event = SessionEvent(
        schema_version="1.1",
        protocol_version="1.1",
        event_id="ev-100",
        session_id="sess-100",
        event_order=0,
        sequence=1,
        actor_username="alice",
        actor_agent_id="code-scout",
        kind=MessageKind.TASK_REQUEST,
        visibility="peer_visible",
        payload={"goal": "Write tests"},
        signature="sig123",
        created_at="2026-07-22T12:00:00.000Z",
    )
    assert event.schema_version == "1.1"
    assert event.protocol_version == "1.1"
    assert event.event_id == "ev-100"
    assert event.event_order == 0
    assert event.kind == MessageKind.TASK_REQUEST
    assert event.visibility == "peer_visible"


def test_session_event_missing_required_field():
    """Verify rejection of SessionEvent when a required field is missing."""
    raw = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "event_id": "ev-100",
        # session_id is missing
        "event_order": 0,
        "actor_username": "alice",
        "kind": "task_request",
        "visibility": "peer_visible",
        "payload": {},
        "created_at": "2026-07-22T12:00:00.000Z",
    }
    with pytest.raises(ValidationError):
        SessionEvent.model_validate(raw)


def test_session_event_invalid_kind():
    """Verify rejection of SessionEvent when kind is an unrecognized string or non-string type."""
    # 1. Unrecognized arbitrary string kind -> REJECTED
    raw_str = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "event_id": "ev-100",
        "session_id": "sess-100",
        "event_order": 0,
        "actor_username": "alice",
        "kind": "hacked_kind",  # Arbitrary unrecognized string
        "visibility": "peer_visible",
        "payload": {},
        "created_at": "2026-07-22T12:00:00.000Z",
    }
    with pytest.raises(ValidationError):
        SessionEvent.model_validate(raw_str)

    # 2. Invalid non-string type -> REJECTED
    raw_num = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "event_id": "ev-100",
        "session_id": "sess-100",
        "event_order": 0,
        "actor_username": "alice",
        "kind": 12345,
        "visibility": "peer_visible",
        "payload": {},
        "created_at": "2026-07-22T12:00:00.000Z",
    }
    with pytest.raises(ValidationError):
        SessionEvent.model_validate(raw_num)


def test_session_event_invalid_visibility():
    """Verify rejection of SessionEvent when visibility is not peer_visible or local_only."""
    raw = {
        "schema_version": "1.1",
        "protocol_version": "1.1",
        "event_id": "ev-100",
        "session_id": "sess-100",
        "event_order": 0,
        "actor_username": "alice",
        "kind": "task_request",
        "visibility": "broadcast_public",  # Invalid visibility
        "payload": {},
        "created_at": "2026-07-22T12:00:00.000Z",
    }
    with pytest.raises(ValidationError):
        SessionEvent.model_validate(raw)


def test_session_event_rejection_missing_schema_or_protocol_version():
    """Verify rejection of SessionEvent when schema_version or protocol_version is omitted (no defaults)."""
    raw_missing_schema = {
        # schema_version is missing
        "protocol_version": "1.1",
        "event_id": "ev-100",
        "session_id": "sess-100",
        "event_order": 0,
        "actor_username": "alice",
        "kind": "task_request",
        "visibility": "peer_visible",
        "payload": {},
        "created_at": "2026-07-22T12:00:00.000Z",
    }
    with pytest.raises(ValidationError):
        SessionEvent.model_validate(raw_missing_schema)

    raw_missing_protocol = {
        "schema_version": "1.1",
        # protocol_version is missing
        "event_id": "ev-100",
        "session_id": "sess-100",
        "event_order": 0,
        "actor_username": "alice",
        "kind": "task_request",
        "visibility": "peer_visible",
        "payload": {},
        "created_at": "2026-07-22T12:00:00.000Z",
    }
    with pytest.raises(ValidationError):
        SessionEvent.model_validate(raw_missing_protocol)


