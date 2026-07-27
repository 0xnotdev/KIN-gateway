"""Tests for keychain-backed secret storage with profile isolation."""

import pytest
import keyring
import keyring.backend
from kin.identity.storage import (
    save_private_key,
    load_private_key,
    save_x25519_private_key,
    load_x25519_private_key,
    save_llm_api_key,
    load_llm_api_key,
    SecretNotFoundError,
)


from kin.testing.insecure_memory_keyring import InMemoryTestKeyring


@pytest.fixture(autouse=True)
def mock_keyring():
    """Fixture that intercepts keyring operations and routes them to InMemoryTestKeyring."""
    mem_keyring = InMemoryTestKeyring()
    keyring.set_keyring(mem_keyring)
    yield mem_keyring


def test_private_key_storage_roundtrip() -> None:
    """Test saving and loading private keys works."""
    profile = "test-profile-1"
    pkey = b"\x01" * 32

    save_private_key(profile, pkey)
    loaded = load_private_key(profile)
    assert loaded == pkey


def test_private_key_missing_raises_error() -> None:
    """Test loading missing private key raises SecretNotFoundError."""
    with pytest.raises(SecretNotFoundError, match="Private key not found for profile"):
        load_private_key("non-existent-profile")


def test_private_key_malformed_raises_error() -> None:
    """Test that a malformed (non-hex) private key raises SecretNotFoundError."""
    profile = "malformed-profile"
    # Save a non-hex value directly to the mocked keyring under this profile's namespace
    keyring.set_password(f"kin-{profile}-private-key", "private_key", "not-a-hex-value")
    
    with pytest.raises(SecretNotFoundError, match="Stored private key is invalid/malformed"):
        load_private_key(profile)


def test_llm_api_key_storage_roundtrip() -> None:
    """Test saving and loading LLM API keys works."""
    profile = "test-profile-2"
    provider = "anthropic"
    api_key = "sk-ant-12345"

    save_llm_api_key(profile, provider, api_key)
    loaded = load_llm_api_key(profile, provider)
    assert loaded == api_key


def test_llm_api_key_provider_case_insensitivity() -> None:
    """Test that provider name lookup is case insensitive."""
    profile = "test-profile-3"
    api_key = "sk-openai-123"

    save_llm_api_key(profile, "OpenAI", api_key)
    
    # Load using lowercase
    assert load_llm_api_key(profile, "openai") == api_key
    # Load using uppercase
    assert load_llm_api_key(profile, "OPENAI") == api_key


def test_llm_api_key_missing_raises_error() -> None:
    """Test loading missing LLM API key raises SecretNotFoundError."""
    with pytest.raises(SecretNotFoundError, match="LLM API key not found for profile"):
        load_llm_api_key("test-profile", "non-existent-provider")


def test_profile_isolation() -> None:
    """Test that two different profiles do not collide or read each other's secrets."""
    profile_a = "alice"
    profile_b = "bob"
    
    key_a = b"a" * 32
    key_b = b"b" * 32
    
    save_private_key(profile_a, key_a)
    save_private_key(profile_b, key_b)
    
    assert load_private_key(profile_a) == key_a
    assert load_private_key(profile_b) == key_b
    
    llm_key_a = "api-key-alice"
    llm_key_b = "api-key-bob"
    
    save_llm_api_key(profile_a, "anthropic", llm_key_a)
    save_llm_api_key(profile_b, "anthropic", llm_key_b)
    
    assert load_llm_api_key(profile_a, "anthropic") == llm_key_a
    assert load_llm_api_key(profile_b, "anthropic") == llm_key_b


class UnrecognizedMockKeyring(keyring.backend.KeyringBackend):
    """An unrecognized mock keyring to test the safety checks."""
    priority = 1

    def set_password(self, servicename, username, password):
        pass

    def get_password(self, servicename, username):
        return None

    def delete_password(self, servicename, username):
        return 0


def test_unrecognized_backend_raises_error() -> None:
    """Test that saving fails with InsecureBackendError when the active backend is unrecognized/not allowlisted."""
    from kin.identity.storage import InsecureBackendError

    original_keyring = keyring.get_keyring()
    unrecognized_keyring = UnrecognizedMockKeyring()
    keyring.set_keyring(unrecognized_keyring)

    try:
        with pytest.raises(InsecureBackendError, match="Insecure or unrecognized keyring backend"):
            save_private_key("test-profile", b"some-key-bytes")

        with pytest.raises(InsecureBackendError, match="Insecure or unrecognized keyring backend"):
            save_llm_api_key("test-profile", "openai", "some-api-key")
    finally:
        keyring.set_keyring(original_keyring)


class MockWinVaultKeyring(keyring.backend.KeyringBackend):
    """A mock keyring class that simulates the Windows WinVaultKeyring path."""
    priority = 1

    def set_password(self, servicename, username, password):
        pass

    def get_password(self, servicename, username):
        return None

    def delete_password(self, servicename, username):
        return 0


# Set the module path and class name to simulate the allowlisted Windows backend
MockWinVaultKeyring.__module__ = "keyring.backends.Windows"
MockWinVaultKeyring.__name__ = "WinVaultKeyring"


def test_allowlisted_backend_accepted() -> None:
    """Test that an allowlisted backend is accepted without raising InsecureBackendError."""
    original_keyring = keyring.get_keyring()
    allowlisted_keyring = MockWinVaultKeyring()
    keyring.set_keyring(allowlisted_keyring)

    try:
        # Should not raise any exception
        save_private_key("test-profile", b"some-key-bytes")
        save_llm_api_key("test-profile", "openai", "some-api-key")
    finally:
        keyring.set_keyring(original_keyring)


def test_x25519_private_key_storage_roundtrip() -> None:
    """Test saving and loading X25519 private keys works."""
    profile = "test-profile-x"
    xkey = b"\x09" * 32

    save_x25519_private_key(profile, xkey)
    loaded = load_x25519_private_key(profile)
    assert loaded == xkey


def test_x25519_private_key_missing_raises_error() -> None:
    """Test loading missing X25519 private key raises SecretNotFoundError."""
    with pytest.raises(SecretNotFoundError, match="X25519 private key not found for profile"):
        load_x25519_private_key("non-existent-profile-x")


def test_x25519_private_key_malformed_raises_error() -> None:
    """Test that a malformed (non-hex) X25519 private key raises SecretNotFoundError."""
    profile = "malformed-profile-x"
    keyring.set_password(f"kin-{profile}-x25519-private-key", "x25519_private_key", "not-a-hex-value")
    
    with pytest.raises(SecretNotFoundError, match="Stored X25519 private key is invalid/malformed"):
        load_x25519_private_key(profile)

