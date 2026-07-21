"""Fingerprint verification algorithm per system-design-v1.md section 4.2."""

from __future__ import annotations

import hashlib
from mnemonic import Mnemonic


def compute_fingerprint(public_key_a: bytes, public_key_b: bytes) -> str:
    """Compute a symmetric, deterministic 4-word fingerprint from two public keys.

    1. Sort the public keys by raw bytes value to ensure symmetry.
    2. Compute SHA-256 over the concatenation of the sorted keys.
    3. Take the first 8 bytes of the hash, split into four 2-byte chunks.
    4. Map each chunk (big-endian int) modulo 2048 to the English BIP39 wordlist.
    5. Return the 4 words joined with hyphens.
    """
    # Sort keys by raw byte value to guarantee symmetry
    sorted_keys = sorted([public_key_a, public_key_b])

    # Concatenate and compute SHA-256
    concatenated = sorted_keys[0] + sorted_keys[1]
    hasher = hashlib.sha256(concatenated)
    digest = hasher.digest()

    # Extract first 8 bytes
    hash_bytes = digest[:8]

    # Load BIP39 English wordlist
    wordlist = Mnemonic("english").wordlist

    # Extract four 2-byte chunks and map to words
    words = []
    for i in range(4):
        chunk = hash_bytes[i * 2 : (i + 1) * 2]
        chunk_val = int.from_bytes(chunk, byteorder="big")
        word_idx = chunk_val % 2048
        words.append(wordlist[word_idx])

    return "-".join(words)
