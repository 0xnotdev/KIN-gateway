"""First-run identity setup flow per system-design-v1.md section 4.2."""

from __future__ import annotations

from kin.identity.keys import generate_recovery_phrase, derive_key_pair
from kin.identity.storage import save_private_key


def setup_new_identity(profile: str) -> str:
    """Run the first-run identity setup flow.

    Generates a recovery phrase, derives the Ed25519 key pair, saves the
    private key to the profile's keychain, and returns the generated
    recovery phrase.
    """
    phrase = generate_recovery_phrase()
    private_key, _public_key = derive_key_pair(phrase)
    save_private_key(profile, private_key)
    return phrase


def verify_phrase_confirmation(
    phrase: str, word_indices: list[int], user_input: list[str]
) -> bool:
    """Confirm that the user correctly entered the words at the specified indices.

    Performs case-insensitive validation and strips extra whitespace.
    """
    words = phrase.strip().split()
    if len(word_indices) != len(user_input):
        return False

    for idx, input_word in zip(word_indices, user_input):
        if idx < 0 or idx >= len(words):
            return False
        if words[idx].lower().strip() != input_word.lower().strip():
            return False

    return True
