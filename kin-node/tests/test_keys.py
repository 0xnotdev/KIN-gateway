"""Tests for key generation, derivation, signing, and verification."""

import pytest
from kin.identity.keys import (
    generate_recovery_phrase,
    derive_key_pair,
    sign_message,
    verify_signature,
    derive_x25519_key_pair,
    encrypt_for_recipient,
    decrypt_from_sender,
)


def test_generate_recovery_phrase() -> None:
    """Test that generated recovery phrases are valid 12-word phrases."""
    phrase = generate_recovery_phrase()
    words = phrase.split()
    assert len(words) == 12
    # Check that generating a second phrase returns a different one
    phrase_2 = generate_recovery_phrase()
    assert phrase != phrase_2


def test_derive_key_pair_determinism() -> None:
    """Test that key derivation is deterministic (same phrase -> same keys twice)."""
    phrase = generate_recovery_phrase()

    # Call it first time
    priv_1, pub_1 = derive_key_pair(phrase)
    # Call it second time
    priv_2, pub_2 = derive_key_pair(phrase)

    # Ensure both keys are identical
    assert priv_1 == priv_2
    assert pub_1 == pub_2

    # Check length (Ed25519 keys are 32 bytes raw)
    assert len(priv_1) == 32
    assert len(pub_1) == 32


def test_derive_key_pair_uniqueness() -> None:
    """Test that two different phrases produce different public keys."""
    phrase_1 = generate_recovery_phrase()
    phrase_2 = generate_recovery_phrase()
    assert phrase_1 != phrase_2

    _priv_1, pub_1 = derive_key_pair(phrase_1)
    _priv_2, pub_2 = derive_key_pair(phrase_2)

    assert pub_1 != pub_2


def test_derive_key_pair_invalid_phrase() -> None:
    """Test that an invalid phrase raises ValueError."""
    with pytest.raises(ValueError, match="Invalid mnemonic phrase"):
        derive_key_pair("invalid phrase here")


def test_sign_verify_roundtrip() -> None:
    """Test that signing a message and verifying it succeeds."""
    phrase = generate_recovery_phrase()
    priv, pub = derive_key_pair(phrase)

    message = b"hello from kin personal agent network"
    sig = sign_message(priv, message)

    assert len(sig) == 64  # Ed25519 signature is 64 bytes
    assert verify_signature(pub, message, sig) is True


def test_verify_fails_on_tampered_message() -> None:
    """Test that verification fails if the message has been tampered with."""
    phrase = generate_recovery_phrase()
    priv, pub = derive_key_pair(phrase)

    message = b"original message"
    sig = sign_message(priv, message)

    tampered_message = b"tampered message"
    assert verify_signature(pub, tampered_message, sig) is False


def test_verify_fails_on_wrong_key() -> None:
    """Test that verification fails if verified against a different public key."""
    phrase_1 = generate_recovery_phrase()
    priv_1, pub_1 = derive_key_pair(phrase_1)

    phrase_2 = generate_recovery_phrase()
    _priv_2, pub_2 = derive_key_pair(phrase_2)

    message = b"secure message"
    sig = sign_message(priv_1, message)

    # Verifying signature with the correct public key should work
    assert verify_signature(pub_1, message, sig) is True
    # Verifying signature with a different public key should fail
    assert verify_signature(pub_2, message, sig) is False


def test_verify_fails_on_invalid_signature_bytes() -> None:
    """Test that verification fails and does not raise for malformed/tampered signature bytes."""
    phrase = generate_recovery_phrase()
    _priv, pub = derive_key_pair(phrase)

    message = b"hello"
    # Provide a completely wrong/malformed signature of different length or format
    bad_sig_short = b"short_sig"
    bad_sig_wrong_len = b"x" * 64

    assert verify_signature(pub, message, bad_sig_short) is False
    assert verify_signature(pub, message, bad_sig_wrong_len) is False


def test_derive_x25519_key_pair_determinism() -> None:
    """Test that X25519 key derivation is deterministic."""
    phrase = generate_recovery_phrase()
    priv1, pub1 = derive_x25519_key_pair(phrase)
    priv2, pub2 = derive_x25519_key_pair(phrase)
    assert priv1 == priv2
    assert pub1 == pub2
    assert len(priv1) == 32
    assert len(pub1) == 32


def test_derive_x25519_key_pair_uniqueness() -> None:
    """Test that different phrases yield different public keys."""
    p1 = generate_recovery_phrase()
    p2 = generate_recovery_phrase()
    _, pub1 = derive_x25519_key_pair(p1)
    _, pub2 = derive_x25519_key_pair(p2)
    assert pub1 != pub2


def test_encrypt_decrypt_roundtrip() -> None:
    """Test X25519 + ChaCha20Poly1305 encrypt/decrypt roundtrip succeeds."""
    p_sender = generate_recovery_phrase()
    p_recip = generate_recovery_phrase()

    sender_priv, sender_pub = derive_x25519_key_pair(p_sender)
    recip_priv, recip_pub = derive_x25519_key_pair(p_recip)

    plaintext = b"top secret agent message"
    ciphertext = encrypt_for_recipient(sender_priv, recip_pub, plaintext)

    # Must contain 12-byte nonce + encrypted data
    assert len(ciphertext) > 12

    decrypted = decrypt_from_sender(recip_priv, sender_pub, ciphertext)
    assert decrypted == plaintext


def test_decrypt_fails_with_wrong_key() -> None:
    """Test that decrypt fails when the wrong private/public key is used."""
    p_sender = generate_recovery_phrase()
    p_recip = generate_recovery_phrase()
    p_third = generate_recovery_phrase()

    sender_priv, sender_pub = derive_x25519_key_pair(p_sender)
    recip_priv, recip_pub = derive_x25519_key_pair(p_recip)
    third_priv, _ = derive_x25519_key_pair(p_third)

    plaintext = b"another secret"
    ciphertext = encrypt_for_recipient(sender_priv, recip_pub, plaintext)

    # Decrypting with wrong recipient private key must fail
    with pytest.raises(Exception):
        decrypt_from_sender(third_priv, sender_pub, ciphertext)


def test_decrypt_fails_on_tampered_ciphertext() -> None:
    """Test that decryption fails if the ciphertext bytes are tampered with."""
    p_sender = generate_recovery_phrase()
    p_recip = generate_recovery_phrase()

    sender_priv, sender_pub = derive_x25519_key_pair(p_sender)
    recip_priv, recip_pub = derive_x25519_key_pair(p_recip)

    plaintext = b"original data"
    ciphertext = encrypt_for_recipient(sender_priv, recip_pub, plaintext)

    # Tamper with one byte in the ciphertext portion (after the 12-byte nonce)
    tampered = bytearray(ciphertext)
    tampered[-1] ^= 0xFF

    with pytest.raises(Exception):
        decrypt_from_sender(recip_priv, sender_pub, bytes(tampered))

