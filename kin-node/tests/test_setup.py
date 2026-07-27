"""Tests for first-run identity setup flow."""

import pytest
import keyring
import keyring.backend
from kin.identity.setup import setup_new_identity, verify_phrase_confirmation
from kin.identity.storage import load_private_key


from kin.testing.insecure_memory_keyring import InMemoryTestKeyring


@pytest.fixture(autouse=True)
def mock_keyring():
    """Fixture that intercepts keyring operations and routes them to InMemoryTestKeyring."""
    mem_keyring = InMemoryTestKeyring()
    keyring.set_keyring(mem_keyring)
    yield mem_keyring


def test_setup_new_identity() -> None:
    """Test setup_new_identity generates a phrase and stores the private key."""
    profile = "setup-test-profile"
    
    phrase = setup_new_identity(profile)
    
    # 1. Verification of the returned recovery phrase
    words = phrase.split()
    assert len(words) == 12
    
    # 2. Verification that the private key was successfully stored in the keychain
    stored_pkey = load_private_key(profile)
    assert len(stored_pkey) == 32


def test_verify_phrase_confirmation_success() -> None:
    """Test verify_phrase_confirmation returns True for correct input."""
    phrase = "apple banana cherry date elderberry fig grape honeydew melon nectarine orange peach"
    
    # Correct case-sensitive matching
    assert verify_phrase_confirmation(phrase, [0, 2], ["apple", "cherry"]) is True
    # Case insensitivity check
    assert verify_phrase_confirmation(phrase, [1, 3], ["BANANA", "daTe"]) is True
    # Extra whitespace tolerance
    assert verify_phrase_confirmation(phrase, [0, 4], ["  apple  ", "elderberry "]) is True


def test_verify_phrase_confirmation_failures() -> None:
    """Test verify_phrase_confirmation returns False for incorrect/invalid inputs."""
    phrase = "apple banana cherry date elderberry fig grape honeydew melon nectarine orange peach"
    
    # Wrong words
    assert verify_phrase_confirmation(phrase, [0, 2], ["apple", "banana"]) is False
    # Length mismatch
    assert verify_phrase_confirmation(phrase, [0, 2], ["apple"]) is False
    assert verify_phrase_confirmation(phrase, [0], ["apple", "cherry"]) is False
    # Index out of bounds
    assert verify_phrase_confirmation(phrase, [-1, 2], ["apple", "cherry"]) is False
    assert verify_phrase_confirmation(phrase, [12, 1], ["peach", "banana"]) is False
