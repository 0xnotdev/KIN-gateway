"""Encryption at rest helper using AES-256-GCM with versioned nonce formatting."""

from __future__ import annotations

import base64
import binascii
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION_PREFIX = b"v1:"


def encrypt_field(key: bytes, plaintext: str | None) -> str | None:
    """Encrypt a string field with AES-256-GCM. Returns a base64 encoded token."""
    if plaintext is None:
        return None
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    raw_token = VERSION_PREFIX + nonce + ciphertext
    return base64.b64encode(raw_token).decode("utf-8")


def decrypt_field(key: bytes, token: str | None) -> str | None:
    """Decrypt a base64 encoded AES-256-GCM token into a string field."""
    if token is None:
        return None
    raw_token = base64.b64decode(token.encode("utf-8"))
    if not raw_token.startswith(VERSION_PREFIX):
        raise ValueError("Unsupported vault token version prefix")
    payload = raw_token[len(VERSION_PREFIX):]
    nonce = payload[:12]
    ciphertext = payload[12:]
    aesgcm = AESGCM(key)
    plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext_bytes.decode("utf-8")


def decrypt_field_or_plaintext(key: bytes, value: str | None) -> str | None:
    """Decrypt a vault field, while accepting an unmistakably legacy plaintext value.

    A value carrying the versioned vault prefix is always decrypted and authentication
    failures propagate. This prevents a wrong key or damaged ciphertext from being
    mistaken for legacy plaintext during V1-to-V1.1 compatibility reads.
    """
    if value is None:
        return None
    try:
        raw_token = base64.b64decode(value.encode("utf-8"), validate=True)
    except (ValueError, binascii.Error):
        return value
    if not raw_token.startswith(VERSION_PREFIX):
        return value
    return decrypt_field(key, value)


def encrypt_bytes(key: bytes, data: bytes | None) -> bytes | None:
    """Encrypt raw bytes with AES-256-GCM. Returns versioned binary payload."""
    if data is None:
        return None
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return VERSION_PREFIX + nonce + ciphertext


def decrypt_bytes(key: bytes, token: bytes | None) -> bytes | None:
    """Decrypt a versioned binary payload into raw bytes."""
    if token is None:
        return None
    if not token.startswith(VERSION_PREFIX):
        raise ValueError("Unsupported vault token version prefix")
    payload = token[len(VERSION_PREFIX):]
    nonce = payload[:12]
    ciphertext = payload[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)
