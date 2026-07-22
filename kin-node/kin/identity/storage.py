"""Keychain-backed secret storage using the keyring library with safety assertions."""

from __future__ import annotations

import keyring


class SecretNotFoundError(Exception):
    """Raised when a requested secret is not found in the keychain."""
    pass


class InsecureBackendError(Exception):
    """Raised when the active keyring backend is determined to be insecure."""
    pass


def _assert_secure_backend() -> None:
    """Inspect the active keyring backend and raise InsecureBackendError if it is insecure.

    Only explicitly allowlisted secure OS-level credential managers or backends marked
    with the `KIN_TEST_BACKEND = True` class attribute are allowed.
    """
    kr = keyring.get_keyring()

    # Bypassed if it's an explicitly marked test double
    if getattr(kr, "KIN_TEST_BACKEND", False) is True:
        return

    cls = kr.__class__
    fqcn = f"{cls.__module__}.{cls.__name__}"

    # Explicit allowlist of secure OS credential managers
    allowlist = {
        "keyring.backends.Windows.WinVaultKeyring",
        "keyring.backends.macOS.Keychain",
        "keyring.backends.SecretService.Keyring",
        "keyring.backends.kwallet.DBusKeyring",
    }

    if fqcn not in allowlist:
        raise InsecureBackendError(
            f"Insecure or unrecognized keyring backend: {fqcn}. "
            "KIN requires a secure OS-level credential store (such as Windows Credential Manager, "
            "macOS Keychain, or Linux Secret Service/KWallet) to protect secrets. "
            "Unrecognized backends are rejected by default."
        )


def get_private_key_service(profile: str) -> str:
    """Return the service name for storing the private key of a profile."""
    return f"kin-{profile}-private-key"


def get_x25519_private_key_service(profile: str) -> str:
    """Return the service name for storing the X25519 private key of a profile."""
    return f"kin-{profile}-x25519-private-key"


def get_vault_key_service(profile: str) -> str:
    """Return the service name for storing the vault key of a profile."""
    return f"kin-{profile}-vault-key"


def get_or_create_vault_key(profile: str) -> bytes:
    """Load or generate the 32-byte vault key from the keychain for the given profile.

    Asserts that the active backend is secure.
    """
    import os
    _assert_secure_backend()
    service = get_vault_key_service(profile)
    hex_key = keyring.get_password(service, "vault_key")
    if hex_key is None:
        key_bytes = os.urandom(32)
        keyring.set_password(service, "vault_key", key_bytes.hex())
        return key_bytes
    try:
        return bytes.fromhex(hex_key)
    except ValueError as e:
        raise SecretNotFoundError(f"Stored vault key is invalid/malformed: {e}")


def get_llm_api_key_service(profile: str, provider: str) -> str:
    """Return the service name for storing the LLM API key of a profile and provider."""
    # Ensure provider is lowercase for consistency
    return f"kin-{profile}-llm-{provider.lower()}"


def save_private_key(profile: str, private_key: bytes) -> None:
    """Save the private key bytes to the keychain for the given profile.

    Asserts that the active backend is secure. The private key is hex-encoded before storing.
    """
    _assert_secure_backend()
    service = get_private_key_service(profile)
    hex_key = private_key.hex()
    keyring.set_password(service, "private_key", hex_key)


def load_private_key(profile: str) -> bytes:
    """Load the private key bytes from the keychain for the given profile.

    Raises SecretNotFoundError if the private key is not found in the keychain.
    """
    service = get_private_key_service(profile)
    hex_key = keyring.get_password(service, "private_key")
    if hex_key is None:
        raise SecretNotFoundError(f"Private key not found for profile: {profile}")
    try:
        return bytes.fromhex(hex_key)
    except ValueError as e:
        raise SecretNotFoundError(f"Stored private key is invalid/malformed: {e}")


def save_x25519_private_key(profile: str, private_key: bytes) -> None:
    """Save the X25519 private key bytes to the keychain for the given profile.

    Asserts that the active backend is secure. The private key is hex-encoded before storing.
    """
    _assert_secure_backend()
    service = get_x25519_private_key_service(profile)
    hex_key = private_key.hex()
    keyring.set_password(service, "x25519_private_key", hex_key)


def load_x25519_private_key(profile: str) -> bytes:
    """Load the X25519 private key bytes from the keychain for the given profile.

    Raises SecretNotFoundError if the X25519 private key is not found in the keychain.
    """
    service = get_x25519_private_key_service(profile)
    hex_key = keyring.get_password(service, "x25519_private_key")
    if hex_key is None:
        raise SecretNotFoundError(f"X25519 private key not found for profile: {profile}")
    try:
        return bytes.fromhex(hex_key)
    except ValueError as e:
        raise SecretNotFoundError(f"Stored X25519 private key is invalid/malformed: {e}")


def save_llm_api_key(profile: str, provider: str, api_key: str) -> None:
    """Save the LLM API key to the keychain for the given profile and provider.

    Asserts that the active backend is secure.
    """
    _assert_secure_backend()
    service = get_llm_api_key_service(profile, provider)
    keyring.set_password(service, "api_key", api_key)


def load_llm_api_key(profile: str, provider: str) -> str:
    """Load the LLM API key from the keychain for the given profile and provider.

    Raises SecretNotFoundError if the LLM API key is not found in the keychain.
    """
    service = get_llm_api_key_service(profile, provider)
    api_key = keyring.get_password(service, "api_key")
    if api_key is None:
        raise SecretNotFoundError(
            f"LLM API key not found for profile: {profile}, provider: {provider}"
        )
    return api_key
