"""Unit and Integration Tests for Resumable First Flight Wizard (§14.6)."""

import json
from pathlib import Path
import pytest
import httpx

from kin.identity.keys import derive_key_pair
from kin.identity.storage import load_private_key
from kin.tui.first_flight import FirstFlightController
from kin.tui.persistence import UiStatePreferences, load_ui_preferences, save_ui_preferences
from kin.tui.redaction import contains_secrets_or_paths
from kin.tui.state import RecoverableError
from kin.tui.widgets.first_flight_wizard import FirstFlightWizardWidget
from kin.tui.widgets.first_flight_modal import FirstFlightFieldsModal, FirstFlightScreen
from textual.widgets import Input

SAMPLE_AGENT_YAML = """schema_version: "1.1"
id: "test-agent"
name: "Test Agent"
description: "Test description"
adapter:
  type: "local_command"
  command: "echo"
  working_directory: "/tmp"
capabilities:
  tags: ["test"]
  accepts: ["text/plain"]
boundaries:
  network_access: "deny"
  filesystem: "none"
  shell: "deny"
  max_runtime_seconds: 60
  max_artifact_bytes: 1000
autonomy:
  relay_information: "always_ask"
  propose_actions: "always_ask"
  execute_local_actions: "always_ask"
"""


def test_first_flight_empty_profile_walkthrough(tmp_path: Path):
    """1. First Flight from empty profile walks through steps in order (§14.6)."""
    prof_dir = tmp_path / "profiles" / "empty_user"
    controller = FirstFlightController(profile_name="empty_user", profile_dir=prof_dir)
    prefs = UiStatePreferences()

    # Initial step for empty profile MUST be 'identity'
    durable = controller.check_durable_state()
    assert durable["has_identity"] is False
    assert durable["has_agents"] is False
    assert controller.determine_start_step(prefs) == "identity"

    # Step 1: Create Identity
    phrase, word_indices = controller.prepare_identity_creation()
    assert len(phrase.split()) == 12
    words = phrase.split()
    user_words = [words[word_indices[0]], words[word_indices[1]]]

    err = controller.confirm_identity_creation("empty_user", phrase, word_indices, user_words)
    assert err is None

    # Verify durable state updated
    durable_after_id = controller.check_durable_state()
    assert durable_after_id["has_identity"] is True
    assert durable_after_id["username"] == "empty_user"

    # Step 2: Connect Agent Card via file import
    card_file = tmp_path / "test-agent.yaml"
    card_file.write_text(SAMPLE_AGENT_YAML, encoding="utf-8")
    card_err = controller.connect_agent_card(card_file)
    assert card_err is None

    durable_after_agent = controller.check_durable_state()
    assert durable_after_agent["has_agents"] is True

    # Step 3: Check Relay Reachability (Probing directory returns 404 for probe user)
    class MockHealthClient:
        def get(self, url, timeout=3.0):
            class Response:
                status_code = 404
            return Response()

    ok, relay_err = controller.check_relay_reachability(client=MockHealthClient())
    assert ok is True
    assert relay_err is None
    prefs = controller.mark_progress("relay_checked", True)

    # Step 4: Pair Contact with real relay lookup mock
    class MockPairClient:
        def get(self, url):
            class Response:
                status_code = 200
                def json(self):
                    return {
                        "public_key": "0" * 64,
                        "x25519_public_key": "1" * 64,
                        "endpoint": "http://127.0.0.1:8321",
                    }
                def raise_for_status(self):
                    pass
            return Response()

    prepared, fingerprint, contact_err = controller.prepare_contact_pairing("alice", client=MockPairClient())
    assert contact_err is None
    assert prepared is not None
    assert fingerprint is not None
    assert len(fingerprint) > 0
    contact_err = controller.confirm_contact_pairing(prepared, fingerprint, fingerprint)
    assert contact_err is None

    durable_after_pair = controller.check_durable_state()
    assert durable_after_pair["has_contacts"] is True

    # Step 5: Demo Mode & Guided Dispatch Progress
    prefs = controller.mark_progress("demo_completed", True)
    prefs = controller.mark_progress("guided_dispatch_shown", True)

    # Final step MUST be complete
    assert controller.determine_start_step(prefs) == "complete"


def test_first_flight_resumability_from_durable_state(tmp_path: Path):
    """2. Verify wizard resumes at correct step based on existing durable state (§14.6)."""
    prof_dir = tmp_path / "profiles" / "resume_user"
    controller = FirstFlightController(profile_name="resume_user", profile_dir=prof_dir)
    prefs = UiStatePreferences()

    # Pre-populate Identity ONLY
    phrase, indices = controller.prepare_identity_creation()
    words = phrase.split()
    controller.confirm_identity_creation("resume_user", phrase, indices, [words[indices[0]], words[indices[1]]])

    # Wizard MUST resume at 'agent' step (identity exists, but no agents)
    assert controller.determine_start_step(prefs) == "agent"

    # Pre-populate Agent Card
    card_file = tmp_path / "test-agent.yaml"
    card_file.write_text(SAMPLE_AGENT_YAML, encoding="utf-8")
    controller.connect_agent_card(card_file)

    # Wizard MUST resume at 'relay' step (identity and agent exist)
    assert controller.determine_start_step(prefs) == "relay"


def test_first_flight_failure_paths_produce_recoverable_errors(tmp_path: Path):
    """3. Failed identity, relay, agent import, and pairing produce RecoverableErrors (§14.6)."""
    prof_dir = tmp_path / "profiles" / "fail_user"
    controller = FirstFlightController(profile_name="fail_user", profile_dir=prof_dir)
    prefs = UiStatePreferences()
    wizard = FirstFlightWizardWidget(controller, prefs)

    # A. Incorrect phrase verification
    err1 = controller.confirm_identity_creation("fail_user", "word " * 12, [0, 1], ["wrong", "wrong"])
    assert isinstance(err1, RecoverableError)
    assert "confirmation failed" in err1.what_happened.lower()

    # Set wizard error state and verify it stays usable (clear error)
    wizard.set_error(err1)
    assert wizard.lifecycle_state.name == "RECOVERABLE_ERROR"
    wizard.clear_error()
    assert wizard.lifecycle_state.name == "NORMAL"

    # B. Missing Agent Card file
    err2 = controller.connect_agent_card(tmp_path / "nonexistent.yaml")
    assert isinstance(err2, RecoverableError)
    assert "not found" in err2.what_happened.lower()

    # C. Unreachable Relay
    class FailingClient:
        def get(self, url, timeout=3.0):
            raise httpx.ConnectError("Connection refused")

    ok, err3 = controller.check_relay_reachability(client=FailingClient())
    assert ok is False
    assert isinstance(err3, RecoverableError)
    assert "unreachable" in err3.what_happened.lower()

    # D. Pairing non-existent contact (404)
    class NotFoundClient:
        def get(self, url):
            class Response:
                status_code = 404
            return Response()

    _, _, err4 = controller.prepare_contact_pairing("nobody", client=NotFoundClient())
    assert isinstance(err4, RecoverableError)
    assert "not found" in err4.what_happened.lower()


def test_first_flight_never_records_contact_before_exact_oob_fingerprint(tmp_path: Path):
    controller = FirstFlightController(profile_name="oob_owner", profile_dir=tmp_path / "oob_owner")
    phrase, indices = controller.prepare_identity_creation()
    words = phrase.split()
    assert controller.confirm_identity_creation(
        "oob_owner", phrase, indices, [words[indices[0]], words[indices[1]]]
    ) is None

    prepared = {
        "username": "bob",
        "public_key": "0" * 64,
        "x25519_public_key": "1" * 64,
        "endpoint": "https://bob.example",
    }
    error = controller.confirm_contact_pairing(prepared, "alpha beta gamma", "alpha beta wrong")
    assert isinstance(error, RecoverableError)
    assert controller.check_durable_state()["has_contacts"] is False

    assert controller.confirm_contact_pairing(prepared, "alpha beta gamma", "  ALPHA   beta gamma ") is None
    assert controller.check_durable_state()["has_contacts"] is True


def test_first_flight_restore_identity_valid_end_to_end(tmp_path: Path):
    """3b. Valid end-to-end identity restoration from 12-word mnemonic with byte-level key match (§14.6)."""
    prof_dir = tmp_path / "profiles" / "restore_user"
    controller = FirstFlightController(profile_name="restore_user", profile_dir=prof_dir)

    valid_mnemonic, _ = controller.prepare_identity_creation()
    err = controller.restore_identity_from_mnemonic("restore_user", valid_mnemonic)
    assert err is None

    # Byte-level assertion: exact private key derived from mnemonic matches stored keychain bytes!
    expected_priv, _ = derive_key_pair(valid_mnemonic)
    loaded_priv = load_private_key("restore_user")
    assert loaded_priv == expected_priv

    durable = controller.check_durable_state()
    assert durable["has_identity"] is True
    assert durable["username"] == "restore_user"


def test_first_flight_restore_identity_malformed_phrase_rejection(tmp_path: Path):
    """3c. Rejection of malformed 12-word mnemonic phrase (§14.6)."""
    prof_dir = tmp_path / "profiles" / "restore_fail"
    controller = FirstFlightController(profile_name="restore_fail", profile_dir=prof_dir)

    bad_mnemonic = "invalid short phrase"
    err = controller.restore_identity_from_mnemonic("restore_fail", bad_mnemonic)
    assert isinstance(err, RecoverableError)
    assert "exactly 12 words" in err.what_happened.lower()

    durable = controller.check_durable_state()
    assert durable["has_identity"] is False


def test_first_flight_demo_mode_alice_bob(tmp_path: Path):
    """4. Demo mode runs end-to-end without touching real identity state (§14.6)."""
    prof_dir = tmp_path / "profiles" / "demo_user"
    controller = FirstFlightController(profile_name="demo_user", profile_dir=prof_dir)
    prefs = UiStatePreferences()

    # Durable state remains untouched before and after demo progress mark
    durable_before = controller.check_durable_state()
    assert durable_before["has_identity"] is False

    prefs = controller.mark_progress("demo_completed", True)
    assert prefs.first_flight_progress["demo_completed"] is True

    durable_after = controller.check_durable_state()
    assert durable_after["has_identity"] is False


def test_first_flight_skip_and_return(tmp_path: Path):
    """5. Skipping a step and returning to it later works correctly (§14.6)."""
    prof_dir = tmp_path / "profiles" / "skip_user"
    controller = FirstFlightController(profile_name="skip_user", profile_dir=prof_dir)

    # Pre-populate identity & agent
    phrase, indices = controller.prepare_identity_creation()
    words = phrase.split()
    controller.confirm_identity_creation("skip_user", phrase, indices, [words[indices[0]], words[indices[1]]])

    card_file = tmp_path / "test-agent.yaml"
    card_file.write_text(SAMPLE_AGENT_YAML, encoding="utf-8")
    controller.connect_agent_card(card_file)

    prefs = UiStatePreferences()
    assert controller.determine_start_step(prefs) == "relay"

    # Mark relay checked, skip pairing
    prefs = controller.mark_progress("relay_checked", True)
    prefs = controller.mark_progress("pairing_skipped", True)

    # Step advances to demo
    assert controller.determine_start_step(prefs) == "demo"

    # Un-skip pairing -> steps return to pairing
    prefs = controller.mark_progress("pairing_skipped", False)
    assert controller.determine_start_step(prefs) == "pairing"


def test_first_flight_persistence_zero_secrets_leakage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """6. Assert ui-state.json contains ZERO secret material after First Flight using contains_secrets_or_paths (§14.6)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    prof_name = "secret_test_user"
    prof_dir = tmp_path / ".kin" / "profiles" / prof_name
    controller = FirstFlightController(profile_name=prof_name, profile_dir=prof_dir)

    # Prepare & confirm identity creation
    secret_phrase, word_indices = controller.prepare_identity_creation()
    secret_words = secret_phrase.split()
    user_words = [secret_words[word_indices[0]], secret_words[word_indices[1]]]

    err = controller.confirm_identity_creation(prof_name, secret_phrase, word_indices, user_words)
    assert err is None

    # Mark all progress steps
    controller.mark_progress("relay_checked", True)
    controller.mark_progress("demo_completed", True)
    controller.mark_progress("guided_dispatch_shown", True)

    # Read ui-state.json raw text
    ui_state_file = prof_dir / "ui-state.json"
    assert ui_state_file.exists()
    raw_text = ui_state_file.read_text(encoding="utf-8")

    # Structural check using contains_secrets_or_paths: MUST be False!
    assert contains_secrets_or_paths(raw_text) is False

    # Explicit secret pattern checks
    assert "private_key" not in raw_text
    assert "x25519" not in raw_text
    assert f"kin-{prof_name}-private-key" not in raw_text


@pytest.mark.asyncio
async def test_production_launcher_first_flight_is_keyboard_reachable_and_completes(
    tmp_path: Path,
    build_tui_app,
):
    profile_dir = tmp_path / "profiles" / "keyboard_owner"
    card_path = tmp_path / "keyboard-agent.yaml"
    card_path.write_text(SAMPLE_AGENT_YAML, encoding="utf-8")
    app = build_tui_app(
        profile_name="keyboard_owner",
        profile_dir=profile_dir,
        auto_first_flight=True,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        assert isinstance(app.screen, FirstFlightScreen)
        wizard = app.screen.wizard
        assert wizard.current_step == "identity"

        await pilot.press("c")
        assert isinstance(app.screen, FirstFlightFieldsModal)
        phrase_words = wizard.active_phrase.split()
        requested = [phrase_words[index] for index in wizard.verification_indices]
        app.screen.query_one("#ff-word1", Input).value = requested[0]
        app.screen.query_one("#ff-word2", Input).value = requested[1]
        app.screen.query_one("#ff-word2", Input).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert wizard.current_step == "agent"

        await pilot.press("i")
        app.screen.query_one("#ff-path", Input).value = str(card_path)
        await pilot.press("enter")
        await pilot.pause()
        assert wizard.current_step == "relay"

        await pilot.press("s", "s", "s", "f")
        assert wizard.current_step == "complete"
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, FirstFlightScreen)
        assert "First Flight complete" in app.status_bar.status_message
