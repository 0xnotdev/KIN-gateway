"""Identity key generation and derivation using BIP39 (mnemonic) and Ed25519 (cryptography)."""

from mnemonic import Mnemonic
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305


def generate_recovery_phrase() -> str:
    """Generate a BIP39-style 12-word recovery phrase (English)."""
    mnemo = Mnemonic("english")
    return mnemo.generate(strength=128)  # 128 bits of entropy = 12 words


def derive_key_pair(phrase: str) -> tuple[bytes, bytes]:
    """Deterministically derive an Ed25519 key pair from a recovery phrase.

    Uses HKDF with SHA-256 to derive a 32-byte seed from the BIP39 seed bytes,
    then constructs the Ed25519 key pair.

    Returns (private_key_bytes, public_key_bytes).
    """
    mnemo = Mnemonic("english")
    # Validate the mnemonic phrase first
    if not mnemo.check(phrase):
        raise ValueError("Invalid mnemonic phrase")

    # Generate the 64-byte seed from the mnemonic phrase
    # (using empty passphrase as per standard BIP39 when not specified)
    bip39_seed = mnemo.to_seed(phrase, passphrase="")

    # Deterministically derive 32 bytes for the Ed25519 private key seed using HKDF
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"kin-ed25519-key-derivation",
    )
    private_seed = hkdf.derive(bip39_seed)

    # Generate keys
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_seed)
    public_key = private_key.public_key()

    return private_key.private_bytes_raw(), public_key.public_bytes_raw()


def sign_message(private_key: bytes, message: bytes) -> bytes:
    """Sign a message with the given Ed25519 private key."""
    priv_key_obj = ed25519.Ed25519PrivateKey.from_private_bytes(private_key)
    return priv_key_obj.sign(message)


def verify_signature(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature against a public key and message.

    Returns False if verification fails (e.g. invalid signature, wrong key),
    rather than raising an exception.
    """
    try:
        pub_key_obj = ed25519.Ed25519PublicKey.from_public_bytes(public_key)
        pub_key_obj.verify(signature, message)
        return True
    except (InvalidSignature, ValueError):
        return False


def derive_x25519_key_pair(phrase: str) -> tuple[bytes, bytes]:
    """Deterministically derive an X25519 key pair from a recovery phrase.

    Uses HKDF with SHA-256 to derive a 32-byte seed from the BIP39 seed bytes,
    then constructs the X25519 key pair.

    Returns (private_key_bytes, public_key_bytes).
    """
    mnemo = Mnemonic("english")
    # Validate the mnemonic phrase first
    if not mnemo.check(phrase):
        raise ValueError("Invalid mnemonic phrase")

    bip39_seed = mnemo.to_seed(phrase, passphrase="")

    # Deterministically derive 32 bytes for the X25519 private key seed using HKDF
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"kin-x25519-key-derivation",
    )
    private_seed = hkdf.derive(bip39_seed)

    private_key = x25519.X25519PrivateKey.from_private_bytes(private_seed)
    public_key = private_key.public_key()

    return private_key.private_bytes_raw(), public_key.public_bytes_raw()


def encrypt_for_recipient(
    sender_x25519_priv: bytes, recipient_x25519_pub: bytes, plaintext: bytes
) -> bytes:
    """Perform X25519 ECDH key exchange and encrypt plaintext using ChaCha20Poly1305.

    Shared secret is derived through X25519 and ran through HKDF-SHA256
    to generate a 32-byte symmetric key. Prepend a random 12-byte nonce to
    the ciphertext (nonce || ciphertext).
    """
    import os

    priv_key = x25519.X25519PrivateKey.from_private_bytes(sender_x25519_priv)
    pub_key = x25519.X25519PublicKey.from_public_bytes(recipient_x25519_pub)

    # Key exchange
    shared_secret = priv_key.exchange(pub_key)

    # Derive symmetric key
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"kin-message-encryption",
    )
    symmetric_key = hkdf.derive(shared_secret)

    # AEAD encryption
    cipher = ChaCha20Poly1305(symmetric_key)
    nonce = os.urandom(12)
    ciphertext = cipher.encrypt(nonce, plaintext, None)

    return nonce + ciphertext


def decrypt_from_sender(
    recipient_x25519_priv: bytes, sender_x25519_pub: bytes, ciphertext: bytes
) -> bytes:
    """Perform X25519 ECDH key exchange and decrypt ciphertext using ChaCha20Poly1305.

    Splits the 12-byte nonce prepended to the ciphertext and decrypts. Raises
    an error if decryption fails.
    """
    if len(ciphertext) < 12:
        raise ValueError("Ciphertext too short to contain nonce")

    nonce = ciphertext[:12]
    raw_ciphertext = ciphertext[12:]

    priv_key = x25519.X25519PrivateKey.from_private_bytes(recipient_x25519_priv)
    pub_key = x25519.X25519PublicKey.from_public_bytes(sender_x25519_pub)

    # Key exchange
    shared_secret = priv_key.exchange(pub_key)

    # Derive symmetric key
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"kin-message-encryption",
    )
    symmetric_key = hkdf.derive(shared_secret)

    # AEAD decryption
    cipher = ChaCha20Poly1305(symmetric_key)
    return cipher.decrypt(nonce, raw_ciphertext, None)

