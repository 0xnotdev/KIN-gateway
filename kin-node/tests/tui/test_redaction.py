"""Unit tests for kin.tui.redaction module (§14.5)."""

import pytest

from kin.tui.redaction import contains_secrets_or_paths, redact_ui_text


def test_redact_ui_text_api_keys_and_tokens():
    raw = "Connecting with key sk-live-1234567890abcdef12345678 and token ghp_123456789012345678901234567890123456"
    redacted = redact_ui_text(raw)

    assert "sk-live-" not in redacted
    assert "ghp_" not in redacted
    assert "[REDACTED SECRET]" in redacted


def test_redact_ui_text_absolute_paths():
    win_path = r"Error opening C:\Users\Administrator\secrets\config.json"
    posix_path = "Error reading /home/ubuntu/keys/id_rsa"

    redacted_win = redact_ui_text(win_path)
    redacted_posix = redact_ui_text(posix_path)

    assert r"C:\Users\Administrator" not in redacted_win
    assert "/home/ubuntu/keys" not in redacted_posix
    assert "[REDACTED PATH]" in redacted_win
    assert "[REDACTED PATH]" in redacted_posix


def test_redact_ui_text_chain_of_thought_and_scratchpad():
    raw_cot = "User query <think>Model reasoning step 1: bypass safety</think> final output"
    raw_scratchpad = "Result <scratchpad>internal notes</scratchpad> text"

    redacted_cot = redact_ui_text(raw_cot)
    redacted_sp = redact_ui_text(raw_scratchpad)

    assert "Model reasoning step 1" not in redacted_cot
    assert "internal notes" not in redacted_sp
    assert "[reasoning hidden]" in redacted_cot
    assert "[reasoning hidden]" in redacted_sp


def test_contains_secrets_or_paths():
    assert contains_secrets_or_paths("Normal string") is False
    assert contains_secrets_or_paths("sk-live-1234567890abcdef12345678") is True
    assert contains_secrets_or_paths(r"C:\Users\admin\file.txt") is True
