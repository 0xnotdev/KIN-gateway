"""Tests for symmetric key fingerprint computation."""

from kin.identity.fingerprint import compute_fingerprint


def test_fingerprint_symmetry() -> None:
    """Test that fingerprint is symmetric regardless of argument order."""
    key_a = b"a" * 32
    key_b = b"b" * 32

    fp1 = compute_fingerprint(key_a, key_b)
    fp2 = compute_fingerprint(key_b, key_a)

    assert fp1 == fp2


def test_fingerprint_determinism() -> None:
    """Test that fingerprint computation is deterministic."""
    key_a = b"\x01" * 32
    key_b = b"\x02" * 32

    fp1 = compute_fingerprint(key_a, key_b)
    fp2 = compute_fingerprint(key_a, key_b)

    assert fp1 == fp2
    assert len(fp1.split("-")) == 4


def test_fingerprint_uniqueness() -> None:
    """Test that different key pairs produce different fingerprints."""
    key_a = b"\x01" * 32
    key_b = b"\x02" * 32
    key_c = b"\x03" * 32

    fp_ab = compute_fingerprint(key_a, key_b)
    fp_ac = compute_fingerprint(key_a, key_c)

    assert fp_ab != fp_ac
